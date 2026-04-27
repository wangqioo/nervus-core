# Nervus v1

> 一个运行在本地 AI 主机上的个人操作系统，以五方向空间导航为交互核心，通过 iOS 原生壳子安装到手机上。本地大模型（Qwen3.5）+ 云端 API 双通道，所有数据自托管，零隐私泄露。

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
- **Chat**（左划）— 本地 / 云端 LLM 对话（走 Model Platform 代理）
- **Files**（右划）— 文件传输助手
- **应用中心**（下划）— 从 `/api/apps` 动态读取已注册 App

---

## 当前版本：v1.0

| 功能 | 状态 |
|------|------|
| 五方向空间导航 SPA | ✅ |
| iOS Capacitor 壳子 | ✅ |
| Files 文件传输面板 | ✅ |
| 深色 / 浅色自动跟随系统 | ✅ |
| 全屏 + 安全区适配 | ✅ |
| **Arbor Core Platform（基座）** | ✅ |
| App Platform（注册/发现/心跳） | ✅ |
| Model Platform（本地 + 云端 Chat 网关） | ✅ |
| Event Platform（事件持久化/分页/过滤） | ✅ |
| Knowledge Platform（pgvector 语义搜索） | ✅ |
| 三级路由引擎（Fast/Semantic/Dynamic） | ✅ |
| Flow 配置驱动的跨 App 自动化 | ✅ |
| Embedding Pipeline（异步向量化） | ✅ |
| App 心跳 / 离线检测 | ✅ |
| 应用中心动态读取 /api/apps | ✅ |
| **GPU 推理（Jetson Orin Nano CUDA）** | ✅ |
| 本地模型 Qwen3.5（thinking 模式正确关闭） | ✅ |
| 云端模型接入（DeepSeek / GLM / Anthropic） | ✅ |
| 各 App 前端面板联通 | 🔧 进行中 |

---

## 目录

1. [硬件要求](#1-硬件要求)
2. [服务端部署](#2-服务端部署linux-主机)
3. [本地模型（GPU 推理）](#3-本地模型gpu-推理)
4. [云端模型接入](#4-云端模型接入)
5. [网络穿透](#5-网络穿透外网访问)
6. [iOS 壳子安装](#6-ios-壳子安装)
7. [日常更新前端](#7-日常更新前端)
8. [平台 API 速查](#8-平台-api-速查)
9. [项目结构](#9-项目结构)

---

## 1. 硬件要求

| 角色 | 推荐配置 | 说明 |
|------|---------|------|
| AI 主机 | NVIDIA Jetson Orin Nano 8GB | 运行 LLM + 所有后端服务 |
| 手机 | iPhone（iOS 16+） | 安装 Nervus 壳子 |
| 开发电脑 | Mac（macOS 13+，Xcode 15+） | 编译 iOS 壳子 |

> 没有 Jetson 也可以用任意 Linux 机器（x86 / ARM），只要有 Docker 和足够内存跑 LLM 即可。GPU 推理需要 CUDA 12.x（x86 或 Jetson JetPack 6+）。

---

## 2. 服务端部署（Linux 主机）

### 前置条件

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

### 拉取代码并启动

```bash
git clone https://github.com/wangqioo/nervus-v1.git nervus
cd nervus
cp .env.example .env          # 按需填入云端 API Key
docker compose up -d
```

启动后各服务端口：

| 服务 | 端口 | 说明 |
|------|------|------|
| Caddy（HTTPS） | 443 | 主入口，自签名证书 |
| Caddy（HTTP） | 8900 | 局域网备用 |
| Arbor Core | 8090 | 平台基座（内部） |
| llama.cpp | 8080 | 本地 LLM（默认宿主机直跑，见下节） |

访问 `https://<主机IP>` 即可在局域网内打开 Nervus 前端。

---

## 3. 本地模型（GPU 推理）

Nervus 使用 llama.cpp 运行本地模型。**推荐直接在宿主机启动**以获得 GPU 加速，而非通过 Docker 容器（Docker 镜像为通用 ARM CPU 构建，无 CUDA 支持）。

### Jetson Orin Nano（JetPack 6+）

```bash
# 克隆并编译 llama.cpp（含 CUDA）
git clone https://github.com/ggml-org/llama.cpp ~/llama.cpp
cd ~/llama.cpp
cmake -B build -DGGML_CUDA=ON
cmake --build build --config Release -j$(nproc)

# 下载模型（Qwen3.5-4B-Q4_K_M 推荐）
mkdir -p ~/models/qwen3.5-4b
# 将 .gguf 文件放入 ~/models/qwen3.5-4b/

# 创建系统服务（开机自动启动）
sudo tee /etc/systemd/system/llama-gpu.service > /dev/null << 'EOF'
[Unit]
Description=llama.cpp GPU server
After=network.target

[Service]
Type=simple
User=nvidia
Environment=GGML_CUDA_DISABLE_GRAPHS=1
ExecStartPre=-/usr/bin/pkill -f llama-server
ExecStart=/home/nvidia/llama.cpp/build/bin/llama-server \
  --model /home/nvidia/models/qwen3.5-4b/Qwen3.5-4B-Q4_K_M.gguf \
  --mmproj /home/nvidia/models/qwen3.5-4b/mmproj-F16.gguf \
  --port 8080 --ctx-size 4096 --n-gpu-layers 36 --parallel 2 \
  --host 0.0.0.0 --log-disable
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now llama-gpu
```

> **注意**：Jetson 的 Tegra GPU 存在 CUDA graph 分配器问题，必须设置 `GGML_CUDA_DISABLE_GRAPHS=1`，否则加载模型时会崩溃。

**实测性能（Orin Nano 8GB）：**

| 模式 | 速度 |
|------|------|
| CPU（Docker 通用镜像） | ~5 tok/s |
| GPU（宿主机 CUDA 构建，36 层） | **~11 tok/s** |

docker-compose.yml 中的 Arbor 通过 `LLAMA_URL=http://172.20.0.1:8080`（Docker 网桥 IP）访问宿主机上的 llama-server。

### x86 Linux（独立显卡）

步骤相同，编译时加 `-DGGML_CUDA=ON`，`--n-gpu-layers` 可设为 99（全 GPU）。

---

## 4. 云端模型接入

在 `.env` 文件中填写 API Key，重启 Arbor 即可：

```bash
# .env
DEEPSEEK_API_KEY=sk-...        # DeepSeek（openai_compat 协议）
ZHIPUAI_API_KEY=...            # 智谱 GLM-4（openai_compat 协议）
ANTHROPIC_API_KEY=sk-ant-...   # Claude（anthropic 协议）
```

支持的模型在 `config/models.json` 中配置，前端模型管理页可一键测试连通性。

---

## 5. 网络穿透（外网访问）

推荐工具：**frp**（免费，自建）或 **cpolar / ngrok**（托管）。

在有公网 IP 的服务器上运行 frps，在主机上运行 frpc，将本地 443 端口映射到公网某端口。配置完成后将公网地址填入 `ios/capacitor.config.json` 的 `server.url`。

---

## 6. iOS 壳子安装

**① 修改服务器地址**

```json
// ios/capacitor.config.json
{
  "server": {
    "url": "https://<你的主机IP或域名>",
    "cleartext": true
  }
}
```

**② 安装依赖并同步**

```bash
cd ios
npm install
npx cap sync ios
open ios/App/App.xcodeproj
```

**③ 用 Xcode 编译安装**

在 Xcode 里：Signing & Capabilities → 选 Apple ID → Bundle Identifier 改成你自己的 → ▶ Run

**④ 信任证书**

设置 → 通用 → VPN 与设备管理 → 找到你的 Apple ID → 信任

> 免费 Apple ID 签名有效期 7 天，到期后重新 Run 一次。

---

## 7. 日常更新前端

前端是单文件 `frontend/index.html`，修改后直接 scp，**无需重启 Docker**。

```bash
scp frontend/index.html <用户名>@<主机IP>:/home/<用户名>/nervus/frontend/index.html
```

更新 Flow 配置同理，scp 后调用热更新接口：

```bash
curl -X POST http://<主机IP>:8900/api/flows/reload
```

---

## 8. 平台 API 速查

所有接口经 Caddy `/api/*` → Arbor Core（`:8090`）。

| 接口 | 说明 |
|------|------|
| `GET /api/health` | 基础健康检查 |
| `GET /api/status` | 全局状态（App 数、Flow 数、embedding 统计） |
| `GET /api/apps` | 已注册 App 列表 |
| `POST /api/apps/register` | App 注册（SDK 自动调用） |
| `POST /api/apps/{id}/heartbeat` | 心跳上报（SDK 自动调用） |
| `GET /api/models` | 模型列表 |
| `GET /api/models/status` | 模型在线状态 |
| `POST /api/models/{id}/test` | 测试指定模型连通性 |
| `POST /api/models/chat` | Chat 统一网关（本地/云端自动路由） |
| `GET /api/events/recent` | 最近事件（`?limit=50&subject=meeting&since=2025-01-01`） |
| `GET /api/events/count` | 事件统计数量 |
| `POST /api/platform/knowledge` | 写入知识库 |
| `POST /api/platform/knowledge/search` | 搜索知识库（`semantic:true` 启用向量搜索） |
| `GET /api/flows` | 已加载 Flow 列表 |
| `POST /api/flows/reload` | 热更新 Flow 配置 |
| `GET /api/logs` | Flow 执行日志 |
| `GET /api/config/public` | 前端公共配置 |

---

## 9. 项目结构

```
nervus/
├── frontend/
│   └── index.html              # 全屏 SPA，五方向导航，单文件
│
├── ios/                        # iOS Capacitor 壳子
│   ├── capacitor.config.json   # ← 部署时改这里：填服务器地址
│   └── ios/App/                # Xcode 工程
│
├── apps/                       # 各功能 App，每个是独立 Docker 服务
│   ├── file-manager/           # 文件传输（:8015）
│   ├── meeting-notes/          # 会议纪要（:8002）
│   ├── calorie-tracker/        # 热量管理（:8001）
│   ├── photo-scanner/          # 相册扫描（:8006）
│   ├── personal-notes/         # 个人笔记（:8007）
│   ├── knowledge-base/         # 知识库（:8003）
│   ├── pdf-extractor/          # PDF 提取（:8008）
│   ├── video-transcriber/      # 视频转录（:8009）
│   ├── rss-reader/             # RSS 订阅（:8010）
│   ├── reminder/               # 提醒（:8012）
│   ├── calendar/               # 日历（:8011）
│   ├── life-memory/            # 生活记忆（:8004）
│   ├── status-sense/           # 系统状态（:8013）
│   ├── sense/                  # 感知数据（:8005）
│   └── workflow-viewer/        # 工作流可视化（:8014）
│
├── core/
│   ├── arbor/                  # 平台基座（:8090）
│   │   ├── main.py             # 启动入口
│   │   ├── nervus_platform/
│   │   │   ├── apps/           # App 注册/发现/心跳
│   │   │   ├── models/         # Chat 网关（本地 + 云端）
│   │   │   ├── events/         # 事件持久化/查询/统计
│   │   │   ├── knowledge/      # 知识写入/pgvector 语义搜索
│   │   │   └── config/         # 公共配置
│   │   ├── router/             # 三级路由引擎
│   │   │   ├── fast_router.py      # Flow 模式匹配，< 100ms
│   │   │   ├── semantic_router.py  # LLM 语义推理，< 2s
│   │   │   └── dynamic_router.py  # 多事件关联规划，< 5s
│   │   ├── executor/           # Flow 执行器 + Embedding Pipeline
│   │   └── infra/              # NATS / Redis / Postgres / Settings
│   ├── caddy/                  # 反向代理，统一入口（:443/:8900）
│   ├── nats/                   # 消息总线（:4222）
│   ├── postgres/               # PostgreSQL + pgvector（:5432）
│   ├── redis/                  # 上下文缓存（:6379）
│   └── whisper/                # 本地语音识别（:8081）
│
├── sdk/
│   └── python/                 # Nervus Python SDK，所有 App 基于此构建
│
├── config/
│   ├── models.json             # 模型配置（本地 + 云端，热更新）
│   ├── public.json             # 前端公共配置
│   └── flows/                  # Flow 配置文件（热更新，无需重启）
│       ├── media-flows.json    # 相片 → 热量/生活记忆
│       ├── meeting-flows.json  # 录音 → 纪要 → 知识库
│       └── health-flows.json   # 热量 → 上下文/提醒
│
├── tests/                      # 测试套件
│   ├── run_tests.sh            # 统一测试入口（自动跳过未运行的服务）
│   ├── test_model_service.py   # Model Platform 单元测试
│   └── test_sdk_llm.py         # SDK LLM 集成测试
│
├── dev-server.py               # 本地开发服务器（/apps/* 静态 + /api/* 代理）
├── .env.example                # 环境变量示例
├── docker-compose.yml          # 一键启动全部服务
└── docs/
    ├── porting-guide.md        # 新 App 接入手册
    ├── platform-v0.1-plan.md   # 平台规划文档
    └── Nervus_完整开发文档.md  # 完整架构设计文档
```

---

## 内存参考（Jetson Orin Nano 8GB 统一内存）

| 组件 | 占用 |
|------|------|
| 系统底层 | ~1.0 GB |
| llama-server（Qwen3.5-4B Q4_K_M，GPU） | ~4.6 GB |
| PostgreSQL + Redis + NATS | ~50 MB |
| Caddy + Arbor + 全部 App 容器 | ~430 MB |
| **合计** | **~6.1 GB** |

> Jetson 采用统一内存架构，CPU 与 GPU 共享同一块 RAM。模型加载后大部分内存由 llama-server 占用，这是正常现象。
