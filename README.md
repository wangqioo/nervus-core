# Nervus

> 一个部署在 Jetson Orin Nano 上的个人 AI 操作系统，以五方向空间导航为交互核心，通过 iOS 原生壳子运行在手机上。

---

## 当前版本：v1.2

| 里程碑 | 状态 |
|--------|------|
| 五方向空间导航 SPA | ✅ 完成 |
| iOS Capacitor 壳子 | ✅ 完成 |
| Files 面板（文件传输助手） | ✅ 完成 |
| 应用中心（动态 localStorage） | ✅ 完成 |
| 全屏化 / 去模拟手机壳 | ✅ 完成 |
| 其余 App 后端联通 | 🔧 进行中 |

---

## 项目结构

```
nervus/
├── mobile/
│   └── index.html              # Nervus 前端，全部 UI（单文件 SPA）
│
├── ios-shell/                  # iOS 原生壳子（Capacitor）
│   ├── capacitor.config.json   # server.url → Orin 地址
│   └── ios/App/App/
│       ├── MainViewController.swift   # SSL 自签名证书绕过
│       ├── AppDelegate.swift
│       └── Info.plist
│
├── apps/                       # 各功能后端（独立 Docker 服务）
│   ├── file-manager/           # ✅ Files 面板后端（端口 8015）
│   ├── meeting-notes/          # 会议纪要
│   ├── pdf-extractor/          # PDF 提取
│   ├── video-transcriber/      # 视频转录
│   ├── calorie-tracker/        # 热量管理
│   ├── photo-scanner/          # 相册扫描
│   ├── reminder/               # 待办提醒
│   ├── personal-notes/         # 个人笔记
│   ├── knowledge-base/         # 知识库
│   ├── rss-reader/             # RSS 订阅
│   ├── sense/                  # 感知面板数据
│   ├── status-sense/           # 系统状态
│   ├── workflow-viewer/        # 工作流
│   └── calendar/               # 日历
│
├── caddy/
│   └── Caddyfile               # 反向代理（HTTPS 443 + HTTP 8900）
├── docker-compose.yml          # 一键启动所有服务
├── arbor-core/                 # 跨 App 消息路由中枢（规划中）
├── nats/                       # 消息队列配置
├── postgres/                   # 数据库初始化
├── redis/                      # 缓存配置
├── whisper/                    # 本地语音转文字
├── nervus-sdk/                 # Python SDK
├── nervus-sdk-ts/              # TypeScript SDK
└── docs/
    └── porting-guide.md        # App 接入手册
```

---

## 交互设计

```
          ↑ 上滑
          感知面板
← 左滑    ← 主页 →    右滑 →
  Chat          Files（文件传输助手）
          ↓ 下滑
          应用中心
```

- **主页**：AI 对话卡片 + 快捷入口
- **感知面板**（上划）：健康/系统状态感知
- **Chat**（右划）：接本地 LLM 对话
- **Files**（左划）：文件传输助手，支持文件/链接/文字/图片
- **应用中心**（下划）：动态 App 网格，localStorage 持久化，支持添加/删除

---

## 部署

### 硬件

- **运行设备**：NVIDIA Jetson Orin Nano 8GB（JetPack 6.x）
- **当前地址**：`ssh -p 6000 nvidia@150.158.146.192`

### 服务启动（在 Orin 上）

```bash
git clone https://github.com/wangqioo/nervus-v1.git nervus
cd nervus
docker compose up -d
```

### 访问地址

| 方式 | 地址 |
|------|------|
| HTTPS（frp 穿透） | `https://150.158.146.192:6205` |
| 局域网 HTTPS | `https://nervus.local` |
| 局域网 HTTP | `http://<orin-ip>:8900` |

### 更新前端（不需要重启 Docker）

```bash
# 在 Mac 本地执行
scp -P 6000 mobile/index.html nvidia@150.158.146.192:/home/nvidia/nervus/mobile/index.html
```

---

## iOS 安装

```bash
cd ios-shell

# 1. 同步配置
npx cap sync ios

# 2. 打开 Xcode
open ios/App/App.xcodeproj
```

Xcode 里选择 iPhone → **Signing & Capabilities** 选 Apple ID → ▶ Run。

首次安装需在手机 **设置 → 通用 → VPN 与设备管理** 里信任开发者证书。

> 日常改前端只需 scp 更新 `mobile/index.html`，**不需要重新编译 Xcode**。

---

## 硬件内存预算（Jetson Orin Nano 8GB）

| 组件 | 内存 |
|------|------|
| 系统底层 | ~1.5 GB |
| LLM（Qwen 4B INT4） | ~2.8 GB |
| Redis + PostgreSQL + NATS | ~550 MB |
| Caddy + 各 App 服务 | ~1.5 GB |
| **常驻合计** | **~6.4 GB** |
