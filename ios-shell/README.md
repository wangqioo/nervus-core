# WebShell

一个 iOS 原生壳应用，让你把任意 HTML/Web 应用打包进手机，像原生 App 一样使用。

基于 [Capacitor](https://capacitorjs.com/) 构建，Web 层可通过 Bridge 调用相机、定位、文件系统、推送通知等原生能力。

## 功能

- **应用管理**：卡片式主页，支持添加、删除任意 Web 应用
- **本地应用**：本地 HTML 文件直接内嵌运行（无跨域限制）
- **外部 URL**：远程网址用独立 WKWebView 打开
- **相册同步**：自动读取本地相册，状态实时显示
- **原生 Bridge**：Web 页面可调用以下原生能力：
  - 相机拍照 / 相册选图
  - GPS 定位（单次 + 持续监听）
  - 推送通知
  - 文件读写（Documents 目录）
  - 触感反馈（Haptics）
  - 麦克风

## 项目结构

```
webshell-app/
├── www/                        # Web 层（打包进 App 的页面）
│   ├── index.html              # 主页（应用卡片列表）
│   ├── bridge.js               # Native ↔ Web 通信桥
│   ├── webshell-client.js      # 客户端工具库
│   └── apps/
│       └── demo/index.html     # 内置 Demo 应用
├── ios/                        # Xcode / Capacitor iOS 工程
│   └── App/
│       └── App/
│           ├── AppDelegate.swift       # 原生入口
│           └── PhotoSyncManager.swift  # 相册同步模块
├── capacitor.config.json       # Capacitor 配置
├── deploy.sh                   # 构建部署脚本
└── package.json
```

## 开发

**环境要求**

- Node.js 18+
- Xcode 15+
- CocoaPods

**安装依赖**

```bash
npm install
```

**同步 Web 资源到 iOS 工程**

```bash
npx cap sync ios
```

**用 Xcode 打开**

```bash
npx cap open ios
```

然后连接真机或选择模拟器，点击运行即可。

## 添加自己的 Web 应用

**方式一：本地 HTML**

将 HTML 文件放入 `www/apps/<你的应用>/index.html`，在主页点击"添加应用"填写路径 `apps/<你的应用>/index.html`。

**方式二：远程 URL**

在主页点击"添加应用"，直接填写 `https://` 开头的网址即可。

## Bridge API

在嵌入的 Web 应用中，可直接调用 `window.Bridge` 访问原生能力：

```js
// 从相册选图，返回图片 URL
const url = await Bridge.pickPhoto();

// 拍照
const url = await Bridge.takePhoto();

// 获取当前位置
const { lat, lng, accuracy } = await Bridge.getLocation();

// 保存 / 读取文件
await Bridge.saveFile('data.json', JSON.stringify(data));
const raw = await Bridge.readFile('data.json');

// 触感反馈
Bridge.vibrate();

// 判断是否运行在原生容器中
if (Bridge.isNative()) { ... }
```

跨域远程页面也可通过 `postMessage` 调用 Bridge：

```js
// 在远程页面中
const id = Math.random().toString();
window.parent.postMessage({ id, method: 'getLocation', args: [] }, '*');
window.addEventListener('message', (e) => {
  if (e.data.id === id) console.log(e.data.result);
});
```
