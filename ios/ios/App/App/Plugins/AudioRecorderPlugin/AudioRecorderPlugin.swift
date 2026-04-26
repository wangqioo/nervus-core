import Foundation
import Capacitor
import AVFoundation

/**
 AudioRecorderPlugin
 封装 AVAudioRecorder，录制会议音频（16kHz 单声道，适配 Whisper）。
 权限：NSMicrophoneUsageDescription（Info.plist）
 后台录音：需在 Xcode Capabilities 开启 "Audio, AirPlay, and Picture in Picture"
 */
@objc(AudioRecorderPlugin)
public class AudioRecorderPlugin: CAPPlugin, AVAudioRecorderDelegate {

    private var recorder: AVAudioRecorder?
    private var recordingURL: URL?
    private var startTime: Date?

    // MARK: - 权限

    @objc func requestPermission(_ call: CAPPluginCall) {
        AVAudioApplication.requestRecordPermission { granted in
            call.resolve(["granted": granted])
        }
    }

    // MARK: - 开始录音

    @objc func start(_ call: CAPPluginCall) {
        guard recorder == nil else {
            call.reject("已有录音进行中")
            return
        }

        let format  = call.getString("format") ?? "m4a"
        let quality = call.getString("quality") ?? "high"

        // 配置 AVAudioSession
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playAndRecord,
                                    mode: .default,
                                    options: [.defaultToSpeaker, .allowBluetooth])
            try session.setActive(true)
        } catch {
            call.reject("AVAudioSession 配置失败: \(error.localizedDescription)")
            return
        }

        // 输出文件路径
        let tmpDir = FileManager.default.temporaryDirectory
        let filename = "nervus_recording_\(Int(Date().timeIntervalSince1970)).\(format)"
        let url = tmpDir.appendingPathComponent(filename)
        recordingURL = url

        // 录音参数 — 16kHz 单声道，Whisper 最佳格式
        let settings: [String: Any] = {
            switch format {
            case "wav":
                return [
                    AVFormatIDKey: kAudioFormatLinearPCM,
                    AVSampleRateKey: 16000.0,
                    AVNumberOfChannelsKey: 1,
                    AVLinearPCMBitDepthKey: 16,
                    AVLinearPCMIsFloatKey: false,
                ]
            default: // m4a
                let q: AVAudioQuality = quality == "high" ? .high : .medium
                return [
                    AVFormatIDKey: kAudioFormatMPEG4AAC,
                    AVSampleRateKey: 16000.0,
                    AVNumberOfChannelsKey: 1,
                    AVEncoderAudioQualityKey: q.rawValue,
                    AVEncoderBitRateKey: 32000,
                ]
            }
        }()

        do {
            recorder = try AVAudioRecorder(url: url, settings: settings)
            recorder?.delegate = self
            recorder?.isMeteringEnabled = true
            recorder?.record()
            startTime = Date()
            call.resolve(["status": "recording", "filename": filename])
        } catch {
            call.reject("录音器创建失败: \(error.localizedDescription)")
        }
    }

    // MARK: - 停止录音

    @objc func stop(_ call: CAPPluginCall) {
        guard let rec = recorder, let url = recordingURL, let start = startTime else {
            call.reject("没有进行中的录音")
            return
        }

        rec.stop()
        let durationSec = Date().timeIntervalSince(start)
        recorder = nil

        do {
            let audioData = try Data(contentsOf: url)
            let base64 = audioData.base64EncodedString()
            try? FileManager.default.removeItem(at: url)  // 清理临时文件
            recordingURL = nil
            startTime = nil

            call.resolve([
                "base64": base64,
                "filename": url.lastPathComponent,
                "durationSec": durationSec,
                "format": url.pathExtension,
            ])
        } catch {
            call.reject("读取录音文件失败: \(error.localizedDescription)")
        }

        // 释放 Audio Session
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    // MARK: - 获取当前时长

    @objc func getDuration(_ call: CAPPluginCall) {
        let seconds = startTime.map { Date().timeIntervalSince($0) } ?? 0
        call.resolve(["seconds": seconds])
    }

    // MARK: - 音量计量（供 UI 波形显示用）

    @objc func getMetering(_ call: CAPPluginCall) {
        guard let rec = recorder, rec.isRecording else {
            call.resolve(["averagePower": -160, "peakPower": -160])
            return
        }
        rec.updateMeters()
        call.resolve([
            "averagePower": rec.averagePower(forChannel: 0),
            "peakPower":    rec.peakPower(forChannel: 0),
        ])
    }

    // MARK: - AVAudioRecorderDelegate

    public func audioRecorderDidFinishRecording(_ recorder: AVAudioRecorder, successfully flag: Bool) {
        notifyListeners("recordingFinished", data: ["success": flag])
    }

    public func audioRecorderEncodeErrorDidOccur(_ recorder: AVAudioRecorder, error: Error?) {
        notifyListeners("recordingError", data: ["message": error?.localizedDescription ?? "未知错误"])
    }
}
