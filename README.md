# Nervus

> 一个运行在本地 AI 主机上的个人操作系统，以五方向空间导航为交互核心，通过 iOS 原生壳子安装到手机上。

```
          ↑ 上滑
          感知面板
← 左滑    ← 主页 →    右滑 →
  Chat          Files
          ↓ 下滑
          应用中心
```

- **主页** — AI 摘要卡片 + 快捷入口
- **感知面板**（上划）— 健康 / 系统状态
- **Chat**（左划）— 接本地 LLM 对话
- **Files**（右划）— 文件传输助手
- **应用中心**（下划）— 可自定义的 App 网格，支持添加 / 删除

---

## 当前版本：v1.2

| 功能 | 状态 |
|------|------|
| 五方向空间导航 SPA | ✅ |
| iOS Capacitor 壳子 | ✅ |
| Files 文件传输面板 | ✅ |
| 应用中心（动态，localStorage） | ✅ |
| 深色 / 浅色自动跟随系统 | ✅ |
| 全屏 + 灵动岛安全区适配 | ✅ |
| 各 App 后端联通 | 🔧 进行中 |

---

## 目录

1. [硬件要求](#1-硬件要求)
2. [服务端部署（Linux 主机）](#2-服务端部署linux-主机)
3. [网络穿透（外网访问）](#3-网络穿透外网访问)
4. [iOS 壳子安装](#4-ios-壳子安装)
5. [日常更新前端](#5-日常更新前端)
6. [项目结构](#6-项目结构)

---

## 1. 硬件要求

| 角色 | 推荐配置 | 说明 |
|------|---------|------|
| AI 主机 | NVIDIA Jetson Orin Nano 8GB | 运行 LLM + 所有后端服务 |
| 手机 | iPhone（iOS 16+） | 安装 Nervus 壳子 |
| 开发电脑 | Mac（macOS 13+，Xcode 15+） | 编译 iOS 壳子 |

> 没有 Jetson 也可以用任意 Linux 机器（x86 / ARM），只要有 Docker 和足够内存跑 LLM 即可。

---

## 2. 服务端部署（Linux 主机）

### 前置条件

```bash
# 安装 Docker + Docker Compose
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # 免 sudo 运行 docker（需重新登录）
```

### 拉取代码并启动

```bash
git clone https://github.com/wangqioo/nervus-v1.git nervus
cd nervus
docker compose up -d
```

启动后各服务端口：

| 服务 | 端口 | 说明 |
|------|------|------|
| Caddy（HTTPS） | 443 | 主入口，自签名证书 |
| Caddy（HTTP） | 8900 | 局域网备用 |
| Files 后端 | 8015 | 文件传输助手 |

访问 `https://<主机IP>` 即可在局域网内打开 Nervus 前端。

---

## 3. 网络穿透（外网访问）

如果需要在外网用手机访问（不在同一局域网），需要配置穿透隧道，否则跳过此节。

推荐工具：**frp**（免费，自建）或 **cpolar / ngrok**（托管，有免费套餐）。

以 frp 为例，在有公网 IP 的服务器上运行 frps，在 Jetson 上运行 frpc，将本地 443 端口映射到公网某端口即可。

配置完成后将公网地址填入 `ios-shell/capacitor.config.json` 的 `server.url`（见下节）。

---

## 4. iOS 壳子安装

### 前置条件

- Mac 电脑，已安装 **Xcode 15+**
- **Apple ID**（免费即可，无需付费开发者账号）
- 手机通过数据线连接 Mac

### 步骤

**① 修改服务器地址**

打开 `ios-shell/capacitor.config.json`，将 `server.url` 改为你自己的 Nervus 地址：

```json
{
  "appId": "com.yourname.nervus",
  "appName": "Nervus",
  "webDir": "www",
  "server": {
    "url": "https://<你的主机IP或域名>",
    "cleartext": true
  }
}
```

**② 安装依赖**

```bash
cd ios-shell
npm install
npx cap sync ios
```

**③ 用 Xcode 编译安装**

```bash
open ios/App/App.xcodeproj
```

在 Xcode 里：
1. 左侧选中 `App` 项目
2. `Signing & Capabilities` → Team 选你的 Apple ID
3. Bundle Identifier 改成你自己的（如 `com.yourname.nervus`）
4. 顶部设备选你的 iPhone → 点 ▶ Run

**④ 信任开发者证书**

首次安装后，在手机上：
> **设置 → 通用 → VPN 与设备管理 → 找到你的 Apple ID → 信任**

之后每次打开 App 即可正常使用。

> **注意**：免费 Apple ID 签名的 App 有效期 7 天，到期后需重新用 Xcode Run 一次。付费开发者账号有效期 1 年。

---

## 5. 日常更新前端

前端是单文件 `mobile/index.html`，修改后直接 scp 到主机，**无需重启 Docker，无需重新编译 Xcode**。

```bash
# 局域网直连
scp mobile/index.html <用户名>@<主机IP>:/home/<用户名>/nervus/mobile/index.html

# 或通过 SSH 隧道
scp -P <端口> mobile/index.html <用户名>@<公网IP>:/home/<用户名>/nervus/mobile/index.html
```

上传后刷新手机 App（完全关闭再重开）即可看到最新版本。

---

## 6. 项目结构

```
nervus/
├── mobile/
│   └── index.html              # 全部前端 UI（单文件 SPA）
│
├── ios-shell/                  # iOS 原生壳子（Capacitor）
│   ├── capacitor.config.json   # ← 改这里配置服务器地址
│   └── ios/App/App/
│       ├── MainViewController.swift   # SSL 自签名证书绕过 + 状态栏主题
│       ├── AppDelegate.swift
│       └── Info.plist
│
├── apps/                       # 各功能后端（独立 Docker 服务）
│   ├── file-manager/           # ✅ Files 面板（端口 8015）
│   ├── meeting-notes/
│   ├── pdf-extractor/
│   ├── video-transcriber/
│   ├── calorie-tracker/
│   ├── photo-scanner/
│   ├── reminder/
│   ├── personal-notes/
│   ├── knowledge-base/
│   ├── rss-reader/
│   ├── sense/
│   ├── status-sense/
│   ├── workflow-viewer/
│   └── calendar/
│
├── caddy/Caddyfile              # 反向代理（HTTPS 443 + HTTP 8900）
├── docker-compose.yml           # 一键启动所有服务
├── postgres/                    # 数据库初始化
├── redis/                       # 缓存配置
├── nats/                        # 消息队列
├── whisper/                     # 本地语音转文字
├── nervus-sdk/                  # Python SDK
├── nervus-sdk-ts/               # TypeScript SDK
└── docs/
    └── porting-guide.md         # 新 App 接入手册
```

---

## 内存参考（Jetson Orin Nano 8GB）

| 组件 | 占用 |
|------|------|
| 系统底层 | ~1.5 GB |
| LLM（Qwen 4B INT4） | ~2.8 GB |
| Redis + PostgreSQL + NATS | ~550 MB |
| Caddy + 各 App 服务 | ~1.5 GB |
| **合计** | **~6.4 GB** |
