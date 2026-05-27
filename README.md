# Nervus

Nervus 是一个通用的个人 Agent OS 运行时。它不绑定某一台设备，也不内置某个硬件项目的专用逻辑。

当前主线是单进程架构：Arbor Core 直接用 Python 启动，数据落在本地 SQLite，不再依赖 Docker、PostgreSQL、Redis 或 NATS。交互层以终端和 API 为主，后续可以接入其他界面。

## 核心定位

Nervus 不是一个聊天应用，而是一个 Agent 运行时：

- 接收自然语言意图或 API 调用
- 通过 Fast / Semantic / Dynamic 三层路由分发任务
- 调用 Widget、Flow、模型网关和知识系统
- 把事件、知识、上下文和 Widget 数据保存到本地 SQLite
- 以低资源占用方式运行在普通 Linux 机器上

## 快速开始

```bash
git clone https://github.com/wangqioo/nervus-v1.git
cd nervus-v1/core/arbor

cp .env.example .env
# 按需填写模型 API Key

pip install -r requirements.txt
python main.py
```

启动后检查：

```bash
curl http://localhost:8090/health
```

可选启动终端界面：

```bash
cd nervus-v1/nervus-cli
pip install -r requirements.txt
python app.py
```

## 架构概览

```text
nervus-v1/
  core/arbor/              Arbor Core，单进程主服务，默认端口 8090
    main.py                启动入口
    router/                三层路由：Fast / Semantic / Dynamic
    executor/              Flow 执行与嵌入管线
    nervus_platform/       Apps / Models / Events / Knowledge / Config
    widgets/               内置卡片：reminders、calendar、notes、alarms
    infra/                 SQLite 封装的事件、KV、关系数据接口
    api/                   HTTP API
  config/                  模型配置与 Flow 配置
  nervus-cli/              Textual TUI，终端交互层
  sdk/                     Python / TypeScript SDK
  docs/                    设计文档
  tests/                   测试
```

## 设计原则

### 单进程优先

Nervus 现在默认使用：

- SQLite 作为主存储
- 进程内事件总线替代 NATS
- SQLite KV 替代 Redis
- SQLite 表替代 PostgreSQL
- `python main.py` 直接启动

这让它更适合低功耗设备、开发板、旧电脑、Crostini 和远程终端环境。

### Terminal-first

Nervus 优先服务于终端环境。Web UI 或移动端壳可以作为外部交互层，但运行时本身不依赖浏览器。

### Runtime 与设备解耦

设备专用逻辑不直接放进本仓库。例如 ChromeOS / Chromebox 专用集成由 `chromebox-boxy-rev3-lab` 维护，再按需安装到本地 Nervus checkout。

## Widget 系统

Widget 是 Nervus 的功能单元。每个 Widget 可以拥有自己的 SQLite 数据、HTTP 路由和 AI 调度入口。

当前内置 Widget：

| Widget | 文件 | 说明 |
| --- | --- | --- |
| reminders | `core/arbor/widgets/reminders.py` | 提醒事项 |
| calendar | `core/arbor/widgets/calendar.py` | 日历事件 |
| notes | `core/arbor/widgets/notes.py` | 文本笔记 |
| alarms | `core/arbor/widgets/alarms.py` | 闹钟 |

Widget 统一通过以下入口暴露：

```text
GET  /api/widgets
POST /api/widgets/dispatch
```

## 模型配置

在 `core/arbor/.env` 中填写 API Key：

```bash
DEEPSEEK_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

模型列表在 `config/models.json` 中维护。可选接入本地 llama.cpp 服务：

```bash
LLM_URL=http://localhost:8080
```

## 常用命令

```bash
# 启动 Arbor Core
make run

# 测试
make test

# 测试 API
make test-api

# 热加载 Flow
make reload-flows
```

## 和 ChromeOS 项目的关系

`nervus-v1` 保持通用运行时，不保存 Chromebox 专用代码。

ChromeOS / Chromebox 相关内容放在：

```text
chromebox-boxy-rev3-lab/
  integrations/nervus/
  scripts/chromeboxctl
  scripts/install-nervus-integration.sh
```

如果要让 Nervus 控制那台 ChromeOS 设备，请在 `chromebox-boxy-rev3-lab` 中安装对应集成。

## 路线

- 当前：单进程 Arbor Core、SQLite、本地 Widget、终端优先
- 近期：完善 metabolism 机制、知识衰减、上下文巩固
- 中期：增强 TUI、语音输入、硬件终端适配
- 长期：允许不同设备项目以外部集成方式接入 Nervus
