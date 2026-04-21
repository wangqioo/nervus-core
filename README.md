# Nervus

> 连接所有 App 的神经系统

**它从未停止存在过。**

---

## 项目结构

```
nervus/
├── docker-compose.yml          # 一键启动所有服务
├── nats/                       # NATS 突触总线配置
├── redis/                      # Redis Context Graph 配置
├── postgres/                   # PostgreSQL Memory Graph 初始化 SQL
├── caddy/                      # 反向代理配置（局域网 HTTPS）
├── whisper/                    # faster-whisper 语音转写服务
├── arbor-core/                 # Nervus 神经路由中枢
│   ├── router/                 # 快速/语义/动态三种路由引擎
│   ├── executor/               # Flow 执行引擎 + 流程加载器
│   ├── flows/                  # JSON 流程配置
│   └── api/                    # App 注册、通知、状态 API
├── nervus-sdk/                 # Python SDK
└── nervus-sdk-ts/              # TypeScript SDK
apps/
├── calorie-tracker/            # 热量管理（拍照自动记录）
├── meeting-notes/              # 会议纪要（录音+白板自动整合）
├── photo-scanner/              # 相册扫描器（感知层）
├── knowledge-base/             # 知识库（语义检索+问答）
├── life-memory/                # 人生记忆库（旅行日志+时间线）
└── sense/                      # 感知页数据服务
```

---

## 快速开始

### 1. 启动基础设施

```bash
docker compose up -d nats redis postgres caddy
```

### 2. 准备 AI 模型

```bash
# 下载 Qwen3.5-4B 多模态模型到 models/ 目录
mkdir -p models
# 从 HuggingFace 下载 qwen3.5-4b-multimodal-q4_k_m.gguf 和 mmproj 文件
```

### 3. 启动 AI 服务（Jetson 上）

```bash
# 带 CUDA 加速
docker compose up -d llama-cpp whisper

# x86 开发机（无 CUDA）
docker compose --profile dev up -d llama-cpp-dev whisper
```

### 4. 启动 Arbor Core 和所有 App

```bash
docker compose up -d arbor-core app-calorie-tracker app-meeting-notes app-photo-scanner app-knowledge-base app-life-memory app-sense
```

### 5. 验收测试

```bash
# AI 服务
curl http://localhost:8080/health

# NATS 消息总线
curl http://localhost:8222

# 系统状态
curl http://localhost:8090/status

# 发布测试事件
curl -X POST http://localhost:4222 -d '...'
```

---

## 核心概念

### Synapse Bus（突触总线）

所有数据通过 NATS 事件总线流动。主题命名规范：

```
{domain}.{entity}.{verb}

media.photo.classified
meeting.recording.processed
health.calorie.meal_logged
context.user_state.updated
knowledge.document.indexed
```

### NSI（Nervus Standard Interface）

每个 App 必须实现：

```
GET  /manifest    能力声明
POST /intake/:id  接收事件
POST /action/:id  执行能力
GET  /state       当前状态
GET  /health      健康检查
```

### Context Graph

用户当下状态，存储在 Redis，所有 App 共享：

```
physical.last_meal / calorie_remaining
cognitive.load (low/medium/high)
temporal.day_type / time_of_day
travel.is_traveling / current_trip
social.recent_meeting
```

### Memory Graph

长期记忆，存储在 PostgreSQL + pgvector：

- `life_events` — 人生事件（照片、会议、旅行）
- `knowledge_items` — 知识条目（文章、PDF、笔记）
- `item_relations` — 条目间的语义关联

---

## 开发新 App（Python）

```python
from nervus_sdk import NervusApp, Context, emit
from nervus_sdk.models import Event

app = NervusApp("my-app")

@app.on("media.photo.classified", filter={"tags_contains": ["food"]})
async def handle_food(event: Event):
    result = await app.llm.vision(event.payload["photo_path"], "识别食物")
    await Context.set("physical.last_meal", event.timestamp)
    await emit("health.calorie.meal_logged", result)

@app.action("my_action")
async def my_action(param: str = "") -> dict:
    return {"result": param}

@app.state
async def get_state() -> dict:
    return {"status": "ok"}

app.run(port=8001)
```

---

## 硬件要求

- **推荐：** NVIDIA Jetson Orin Nano 8GB（JetPack 6.x）
- **开发调试：** 任意 x86/ARM Linux（禁用 CUDA，使用 CPU 推理）

### 内存预算（Jetson）

| 组件 | 内存 |
|---|---|
| 系统底层 | ~1.5GB |
| Qwen3.5-4B 多模态 INT4 | ~2.8GB |
| Redis + PostgreSQL + NATS | ~550MB |
| Arbor Core + 6 个 App | ~1.2GB |
| faster-whisper（按需） | ~500MB |
| **常驻合计** | **~6.3GB** |
| **峰值（转写中）** | **~6.8GB** |

