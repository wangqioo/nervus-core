import Foundation
import Photos
import UIKit
import CryptoKit
import CoreLocation

// MARK: - PhotoSync 配置
private let kServerURL  = "http://150.158.146.192:6143"
private let kUsername   = "admin"
private let kPassword   = "152535"
private let kDeviceID   = "iphone_" + (UIDevice.current.identifierForVendor?.uuidString ?? "unknown")
private let kTokenKey   = "photosync_token"
private let kLastSyncKey = "photosync_last_sync"

// MARK: - PhotoSyncManager
class PhotoSyncManager: NSObject {

    static let shared = PhotoSyncManager()
    private override init() {}

    private var isSyncing = false  // 防止并发重复同步

    var onStatusUpdate: ((String) -> Void)?

    func syncIfNeeded() {
        guard !isSyncing else {
            NSLog("[PhotoSync] already syncing, skip")
            return
        }
        let status = PHPhotoLibrary.authorizationStatus(for: .readWrite)
        notify("权限状态: \(statusText(status))")

        switch status {
        case .authorized, .limited:
            Task { await self.sync() }
        case .notDetermined:
            PHPhotoLibrary.requestAuthorization(for: .readWrite) { newStatus in
                self.notify("授权结果: \(self.statusText(newStatus))")
                if newStatus == .authorized || newStatus == .limited {
                    Task { await self.sync() }
                }
            }
        default:
            notify("相册权限被拒绝，请到设置里开启")
        }
    }

    private func statusText(_ s: PHAuthorizationStatus) -> String {
        switch s {
        case .authorized: return "完全授权"
        case .limited: return "有限授权"
        case .denied: return "拒绝"
        case .restricted: return "受限"
        case .notDetermined: return "未决定"
        @unknown default: return "未知(\(s.rawValue))"
        }
    }

    private func notify(_ msg: String) {
        NSLog("[PhotoSync] \(msg)")
        DispatchQueue.main.async {
            self.onStatusUpdate?(msg)
        }
    }

    // MARK: - 主同步流程
    private func sync() async {
        isSyncing = true
        defer { isSyncing = false }

        // 同步期间保持屏幕常亮，防止熄屏后被系统暂停
        await MainActor.run { UIApplication.shared.isIdleTimerDisabled = true }
        defer { Task { @MainActor in UIApplication.shared.isIdleTimerDisabled = false } }

        notify("开始同步...")

        // 1. 获取 token
        notify("正在登录服务器...")
        guard let token = await getToken() else {
            // getToken 内部已输出具体错误，这里不再重复 notify
            return
        }
        notify("✓ 登录成功")

        // 2. 取今天拍摄的照片
        let todayPhotos = fetchTodayPhotos()
        notify("近2天相册共 \(todayPhotos.count) 张照片")
        guard !todayPhotos.isEmpty else {
            notify("近2天没有照片")
            return
        }

        // 3. 导出图片数据并计算哈希，用于去重
        notify("正在计算照片哈希...")
        var assetDataList: [(asset: PHAsset, data: Data, hash: String)] = []
        for asset in todayPhotos {
            guard let data = await exportAsset(asset) else { continue }
            let hash = SHA256.hash(data: data).compactMap { String(format: "%02x", $0) }.joined()
            assetDataList.append((asset: asset, data: data, hash: hash))
        }

        // 4. 去重：问服务器哪些哈希已存在
        let hashes = assetDataList.map { $0.hash }
        let existing = await checkExisting(token: token, hashes: hashes)

        // 5. 过滤出未上传的
        let toUpload = assetDataList.filter { !existing.contains($0.hash) }

        guard !toUpload.isEmpty else {
            notify("✓ 近2天照片已全部上传过")
            return
        }
        notify("正在上传 \(toUpload.count) 张照片...")

        // 按 25MB 自动分批，避免单次请求过大
        let maxBatchBytes = 25 * 1024 * 1024
        var batches: [[(asset: PHAsset, data: Data, hash: String)]] = []
        var current: [(asset: PHAsset, data: Data, hash: String)] = []
        var currentSize = 0
        for item in toUpload {
            if currentSize + item.data.count > maxBatchBytes && !current.isEmpty {
                batches.append(current)
                current = []
                currentSize = 0
            }
            current.append(item)
            currentSize += item.data.count
        }
        if !current.isEmpty { batches.append(current) }

        for (i, batch) in batches.enumerated() {
            if batches.count > 1 { notify("上传第 \(i+1)/\(batches.count) 批...") }
            await uploadBatch(items: batch, token: token)
        }

        UserDefaults.standard.set(Date(), forKey: kLastSyncKey)
        notify("✓ 同步完成，共上传 \(toUpload.count) 张")
    }

    // MARK: - 获取最近 2 天的照片
    private func fetchTodayPhotos() -> [PHAsset] {
        let since = Calendar.current.date(byAdding: .day, value: -2, to: Date())!

        let fetchOptions = PHFetchOptions()
        fetchOptions.predicate = NSPredicate(
            format: "creationDate >= %@ AND mediaType == %d",
            since as NSDate,
            PHAssetMediaType.image.rawValue
        )
        fetchOptions.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: true)]

        let result = PHAsset.fetchAssets(with: fetchOptions)
        var assets: [PHAsset] = []
        result.enumerateObjects { asset, _, _ in assets.append(asset) }
        return assets
    }

    // MARK: - 登录获取 token
    private func getToken() async -> String? {
        // 先用缓存的 token 验证
        if let cached = UserDefaults.standard.string(forKey: kTokenKey) {
            if await verifyToken(cached) { return cached }
        }
        // 重新登录
        guard let url = URL(string: "\(kServerURL)/api/auth/login") else { return nil }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONEncoder().encode(["username": kUsername, "password": kPassword])
        req.timeoutInterval = 15

        let data: Data
        do {
            let (d, resp) = try await URLSession.shared.data(for: req)
            if let http = resp as? HTTPURLResponse {
                NSLog("[PhotoSync] login HTTP status: \(http.statusCode)")
            }
            data = d
        } catch {
            NSLog("[PhotoSync] login request failed: \(error.localizedDescription)")
            notify("❌ 登录失败: \(error.localizedDescription)")
            return nil
        }

        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let token = json["token"] as? String else {
            let body = String(data: data, encoding: .utf8) ?? "nil"
            NSLog("[PhotoSync] login JSON parse failed, body: \(body)")
            notify("❌ 登录响应解析失败")
            return nil
        }

        UserDefaults.standard.set(token, forKey: kTokenKey)
        return token
    }

    private func verifyToken(_ token: String) async -> Bool {
        guard let url = URL(string: "\(kServerURL)/api/photos?limit=1") else { return false }
        var req = URLRequest(url: url)
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.timeoutInterval = 10
        do {
            let (_, resp) = try await URLSession.shared.data(for: req)
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            NSLog("[PhotoSync] verifyToken status: \(code)")
            return code == 200
        } catch {
            NSLog("[PhotoSync] verifyToken failed: \(error.localizedDescription)")
            notify("❌ 网络错误: \(error.localizedDescription)")
            return false
        }
    }

    // MARK: - 去重检查（按文件哈希）
    private func checkExisting(token: String, hashes: [String]) async -> Set<String> {
        guard let url = URL(string: "\(kServerURL)/api/photos/check") else { return [] }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.httpBody = try? JSONSerialization.data(withJSONObject: [
            "device_id": kDeviceID,
            "hashes": hashes
        ])
        guard let (data, _) = try? await URLSession.shared.data(for: req),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let existing = json["existing"] as? [String] else { return [] }
        return Set(existing)
    }

    // MARK: - 反地理编码（坐标 → 地名）
    private func reverseGeocode(_ location: CLLocation) async -> String {
        await withCheckedContinuation { continuation in
            CLGeocoder().reverseGeocodeLocation(location) { placemarks, _ in
                let p = placemarks?.first
                // 组合：国家/省/市/区/街道
                let parts = [p?.country, p?.administrativeArea, p?.locality,
                             p?.subLocality, p?.thoroughfare].compactMap { $0 }
                continuation.resume(returning: parts.joined(separator: " "))
            }
        }
    }

    // MARK: - 批量上传
    private func uploadBatch(items: [(asset: PHAsset, data: Data, hash: String)], token: String) async {
        guard let url = URL(string: "\(kServerURL)/api/photos/upload") else { return }

        let boundary = "Boundary-\(UUID().uuidString)"
        var body = Data()

        func field(_ name: String, _ value: String) {
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n".data(using: .utf8)!)
            body.append("\(value)\r\n".data(using: .utf8)!)
        }

        for item in items {
            let asset = item.asset
            let shotAt = asset.creationDate.map { ISO8601DateFormatter().string(from: $0) } ?? ISO8601DateFormatter().string(from: Date())
            let filename = "photo_\(Int(asset.creationDate?.timeIntervalSince1970 ?? 0)).jpg"

            // 照片文件
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"photos\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
            body.append("Content-Type: image/jpeg\r\n\r\n".data(using: .utf8)!)
            body.append(item.data)
            body.append("\r\n".data(using: .utf8)!)

            field("shot_at", shotAt)
            field("file_hash", item.hash)

            // 尺寸
            field("width", "\(asset.pixelWidth)")
            field("height", "\(asset.pixelHeight)")

            // 媒体类型（照片 / 慢动作 / 全景等）
            var mediaSubtype = "photo"
            if asset.mediaSubtypes.contains(.photoLive)      { mediaSubtype = "live_photo" }
            if asset.mediaSubtypes.contains(.photoPanorama)  { mediaSubtype = "panorama" }
            if asset.mediaSubtypes.contains(.photoHDR)       { mediaSubtype = "hdr" }
            if asset.mediaSubtypes.contains(.photoScreenshot){ mediaSubtype = "screenshot" }
            field("media_subtype", mediaSubtype)

            // 是否收藏
            field("is_favorite", asset.isFavorite ? "1" : "0")

            // 地理位置
            if let loc = asset.location {
                field("latitude",  String(format: "%.6f", loc.coordinate.latitude))
                field("longitude", String(format: "%.6f", loc.coordinate.longitude))
                let placeName = await reverseGeocode(loc)
                if !placeName.isEmpty { field("location_name", placeName) }
            }
        }

        // device_id
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"device_id\"\r\n\r\n".data(using: .utf8)!)
        body.append("\(kDeviceID)\r\n".data(using: .utf8)!)
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)

        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.httpBody = body
        req.timeoutInterval = 600

        do {
            let (data, resp) = try await URLSession.shared.data(for: req)
            if let http = resp as? HTTPURLResponse {
                let result = String(data: data, encoding: .utf8) ?? ""
                print("[PhotoSync] 上传响应 \(http.statusCode): \(result.prefix(100))")
            }
        } catch {
            print("[PhotoSync] 上传失败: \(error.localizedDescription)")
        }
    }

    // MARK: - 导出 PHAsset 为 JPEG Data
    private func exportAsset(_ asset: PHAsset) async -> Data? {
        await withCheckedContinuation { continuation in
            let options = PHImageRequestOptions()
            options.deliveryMode = .highQualityFormat
            options.isNetworkAccessAllowed = true
            options.isSynchronous = false

            PHImageManager.default().requestImageDataAndOrientation(for: asset, options: options) { data, _, _, _ in
                guard let data else {
                    continuation.resume(returning: Optional<Data>.none)
                    return
                }
                // 压缩到最大 1MB
                if data.count > 1_000_000,
                   let img = UIImage(data: data),
                   let compressed = img.jpegData(compressionQuality: 0.7) {
                    continuation.resume(returning: compressed)
                } else {
                    continuation.resume(returning: data)
                }
            }
        }
    }
}
