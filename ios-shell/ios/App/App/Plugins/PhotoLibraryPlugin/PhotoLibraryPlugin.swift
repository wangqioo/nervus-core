import Foundation
import Capacitor
import Photos
import UIKit

/**
 PhotoLibraryPlugin
 监听 PHPhotoLibrary 相册变化，自动上传新照片到 Nervus photo-scanner。
 权限：NSPhotoLibraryUsageDescription（Info.plist）
 */
@objc(PhotoLibraryPlugin)
public class PhotoLibraryPlugin: CAPPlugin, PHPhotoLibraryChangeObserver {

    private var isWatching = false
    private var lastFetchDate: Date = Date()

    // MARK: - 权限

    @objc func requestPermission(_ call: CAPPluginCall) {
        PHPhotoLibrary.requestAuthorization(for: .readWrite) { status in
            switch status {
            case .authorized:
                call.resolve(["granted": true, "limited": false])
            case .limited:
                call.resolve(["granted": true, "limited": true])
            default:
                call.resolve(["granted": false, "limited": false])
            }
        }
    }

    // MARK: - 监听控制

    @objc func startWatching(_ call: CAPPluginCall) {
        guard !isWatching else {
            call.resolve(["status": "already_watching"])
            return
        }
        PHPhotoLibrary.shared().register(self)
        isWatching = true
        lastFetchDate = Date()
        call.resolve(["status": "watching"])
    }

    @objc func stopWatching(_ call: CAPPluginCall) {
        if isWatching {
            PHPhotoLibrary.shared().unregisterChangeObserver(self)
            isWatching = false
        }
        call.resolve(["status": "stopped"])
    }

    // MARK: - 获取最近照片

    @objc func getRecentPhotos(_ call: CAPPluginCall) {
        let limit = call.getInt("limit") ?? 20
        let fetchOptions = PHFetchOptions()
        fetchOptions.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: false)]
        fetchOptions.fetchLimit = limit

        let assets = PHAsset.fetchAssets(with: .image, options: fetchOptions)
        var photos: [[String: Any]] = []

        assets.enumerateObjects { asset, _, _ in
            photos.append([
                "localIdentifier": asset.localIdentifier,
                "creationDate": asset.creationDate?.ISO8601Format() ?? "",
                "width": asset.pixelWidth,
                "height": asset.pixelHeight,
            ])
        }
        call.resolve(["photos": photos])
    }

    // MARK: - PHPhotoLibraryChangeObserver

    public func photoLibraryDidChange(_ changeInstance: PHChange) {
        // 只处理新增照片
        let fetchOptions = PHFetchOptions()
        fetchOptions.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: false)]
        fetchOptions.predicate = NSPredicate(
            format: "creationDate > %@", lastFetchDate as CVarArg
        )
        fetchOptions.fetchLimit = 20

        let newAssets = PHAsset.fetchAssets(with: .image, options: fetchOptions)
        guard newAssets.count > 0 else { return }

        lastFetchDate = Date()

        let manager = PHImageManager.default()
        let reqOpts = PHImageRequestOptions()
        reqOpts.isSynchronous = false
        reqOpts.deliveryMode = .highQualityFormat
        reqOpts.isNetworkAccessAllowed = true

        newAssets.enumerateObjects { [weak self] asset, _, _ in
            manager.requestImageDataAndOrientation(for: asset, options: reqOpts) { data, uti, _, _ in
                guard let data = data else { return }
                let base64 = data.base64EncodedString()
                let filename = "photo_\(Int(Date().timeIntervalSince1970)).jpg"

                self?.notifyListeners("newPhoto", data: [
                    "base64": base64,
                    "mimeType": "image/jpeg",
                    "filename": filename,
                    "localIdentifier": asset.localIdentifier,
                    "creationDate": asset.creationDate?.ISO8601Format() ?? "",
                    "width": asset.pixelWidth,
                    "height": asset.pixelHeight,
                ])
            }
        }
    }
}
