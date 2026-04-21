# Nervus iOS Shell

Capacitor 6 原生壳，包装 Nervus 感知页并提供 4 个原生插件。

## 项目结构

```
ios-shell/
├── capacitor.config.ts       # Capacitor 配置
├── package.json
├── src/
│   ├── index.html            # 移动端 UI（感知/录音/笔记/知识库四标签）
│   └── js/
│       └── nervus-bridge.js  # JS 桥接层，封装所有原生插件调用
└── ios/App/App/Plugins/
    ├── PhotoLibraryPlugin/   # 相册监听，自动上传新照片
    ├── AudioRecorderPlugin/  # 会议录音（16kHz 单声道）
    ├── NervusDiscoveryPlugin/ # Bonjour/mDNS 局域网服务发现
    └── BackgroundSyncPlugin/ # 后台拉取 + 本地通知
```

## 快速开始

### 前置条件

- macOS + Xcode 15+
- Node.js 20+
- Nervus 边缘设备（Jetson Orin Nano）在同一 Wi-Fi 网络

### 安装

```bash
cd nervus/ios-shell
npm install
npx cap sync ios
npx cap open ios
```

### Xcode 配置

1. **Info.plist**：将 `ios/App/App/Plugins/Info.plist.additions.xml` 中的所有 key 合并到 `ios/App/App/Info.plist`

2. **Capabilities** — 在 Signing & Capabilities 标签页开启：
   - Background Modes:
     - [x] Background fetch
     - [x] Background processing
     - [x] Audio, AirPlay, and Picture in Picture
     - [x] Remote notifications

3. **Bundle ID**：改为你的 Apple Developer Team 下的 ID（默认 `ai.nervus.app`）

4. **签名**：选择你的 Development Team

### 构建 & 运行

```bash
# 同步 Web 资产到 iOS 项目
npx cap sync ios

# 用 Xcode 打开并运行到设备
npx cap open ios
```

## 原生插件说明

### PhotoLibraryPlugin

监听 `PHPhotoLibrary` 变化，有新照片时自动：
1. 编码为 base64
2. 通过 `nervus-bridge.js` 的 `Nervus.Photos._uploadPhoto()` 上传到 `photo-scanner:8006/upload`
3. photo-scanner 分类后发布 `media.photo.classified` 事件到 NATS 总线

### AudioRecorderPlugin

- 使用 `AVAudioRecorder` 录制 16kHz 单声道 M4A
- 录音结束后自动上传到 `meeting-notes:8002/record`
- meeting-notes 调用 Whisper 转写，自动生成会议纪要

### NervusDiscoveryPlugin

- 优先直连 `nervus.local`（Caddy mDNS 配置）
- 回退到 `_nervus._tcp` Bonjour 服务浏览
- 发现后通过 `serviceChange` 事件持续通知 JS 层

### BackgroundSyncPlugin

- 注册 `BGAppRefreshTask`（Task ID: `ai.nervus.background-sync`）
- 系统唤醒时调用 `pollAndNotify()` 拉取 Arbor Core 未读通知
- 使用 `UNUserNotificationCenter` 推送本地通知

## Nervus Bridge JS API

```js
// 初始化（自动发现服务器 + 开始监听相册）
await Nervus.init({ watchPhotos: true });

// 手动调用 API
await Nervus.api('/notify/notifications');

// 录音
await Nervus.Recorder.start();
const result = await Nervus.Recorder.stop(); // 自动上传

// 相册
const perm = await Nervus.Photos.requestPermission();
await Nervus.Photos.startWatching(photo => console.log(photo));

// 通知
await Nervus.Background.scheduleNotification({
  title: '提醒', body: '内容', delayMs: 0
});
```
