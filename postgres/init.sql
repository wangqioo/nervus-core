-- Nervus Memory Graph 初始化 SQL
-- PostgreSQL 16 + pgvector
-- 执行时机：容器首次启动

-- ── 扩展 ──────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- 全文检索支持

-- ── 人生事件表 ────────────────────────────────
-- 存储用户生活中的所有重要事件
-- type: photo / meeting / meal / travel / note / article / video
CREATE TABLE IF NOT EXISTS life_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type        TEXT NOT NULL,
    title       TEXT,
    description TEXT,
    timestamp   TIMESTAMPTZ NOT NULL,
    source_app  TEXT NOT NULL,
    metadata    JSONB DEFAULT '{}',
    embedding   vector(1536),           -- 用于语义召回
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_life_events_type      ON life_events (type);
CREATE INDEX IF NOT EXISTS idx_life_events_timestamp ON life_events (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_life_events_source    ON life_events (source_app);
CREATE INDEX IF NOT EXISTS idx_life_events_metadata  ON life_events USING gin (metadata);
-- 向量相似度索引（IVFFlat，适合 Jetson 内存预算）
-- 需要先有足够数据才能创建，初始时注释掉，数据量 >1000 后执行
-- CREATE INDEX ON life_events USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ── 知识条目表 ────────────────────────────────
-- 存储所有知识来源：文章、PDF、视频、笔记、会议纪要
CREATE TABLE IF NOT EXISTS knowledge_items (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type        TEXT NOT NULL,          -- article / pdf / video / note / meeting / rss
    title       TEXT NOT NULL,
    content     TEXT,
    summary     TEXT,
    source_url  TEXT,
    source_app  TEXT NOT NULL,
    tags        TEXT[] DEFAULT '{}',
    timestamp   TIMESTAMPTZ NOT NULL,
    embedding   vector(1536),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_type      ON knowledge_items (type);
CREATE INDEX IF NOT EXISTS idx_knowledge_timestamp ON knowledge_items (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_tags      ON knowledge_items USING gin (tags);
CREATE INDEX IF NOT EXISTS idx_knowledge_title_trgm ON knowledge_items USING gin (title gin_trgm_ops);

-- ── 关系图谱表 ────────────────────────────────
-- 连接不同事件/知识条目之间的语义关联
-- relation: related_to / part_of / generated_from / references / contradicts
CREATE TABLE IF NOT EXISTS item_relations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id   UUID NOT NULL,
    target_id   UUID NOT NULL,
    relation    TEXT NOT NULL,
    weight      FLOAT DEFAULT 1.0,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_relations_source ON item_relations (source_id);
CREATE INDEX IF NOT EXISTS idx_relations_target ON item_relations (target_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_relations_pair ON item_relations (source_id, target_id, relation);

-- ── App 注册表 ────────────────────────────────
-- 记录所有已接入 Nervus 生态的 App
CREATE TABLE IF NOT EXISTS app_registry (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    app_id          TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    version         TEXT NOT NULL,
    description     TEXT,
    manifest        JSONB NOT NULL,     -- 完整 manifest.json 内容
    endpoint_url    TEXT NOT NULL,      -- App 的 HTTP 服务地址
    status          TEXT DEFAULT 'online', -- online / offline / error
    last_heartbeat  TIMESTAMPTZ DEFAULT NOW(),
    registered_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_app_registry_status ON app_registry (status);

-- ── 执行日志表 ────────────────────────────────
-- 记录 Arbor Core 的每次路由决策和 Flow 执行
CREATE TABLE IF NOT EXISTS execution_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    flow_id         TEXT,
    trigger_subject TEXT NOT NULL,
    trigger_payload JSONB,
    routing_mode    TEXT NOT NULL,      -- fast / semantic / dynamic
    steps_executed  JSONB DEFAULT '[]',
    status          TEXT NOT NULL,      -- success / failed / partial
    duration_ms     INTEGER,
    error           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exec_logs_flow       ON execution_logs (flow_id);
CREATE INDEX IF NOT EXISTS idx_exec_logs_subject    ON execution_logs (trigger_subject);
CREATE INDEX IF NOT EXISTS idx_exec_logs_created    ON execution_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_exec_logs_status     ON execution_logs (status);

-- ── 通知历史表 ────────────────────────────────
CREATE TABLE IF NOT EXISTS notifications (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type        TEXT NOT NULL,          -- global_popup / push / silent
    title       TEXT NOT NULL,
    body        TEXT,
    metadata    JSONB DEFAULT '{}',
    is_read     BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notifications_read    ON notifications (is_read);
CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications (created_at DESC);

-- ── 自动更新 updated_at ───────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_life_events_updated
    BEFORE UPDATE ON life_events
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_knowledge_items_updated
    BEFORE UPDATE ON knowledge_items
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ── 初始化完成标记 ────────────────────────────
INSERT INTO app_registry (app_id, name, version, description, manifest, endpoint_url, status)
VALUES (
    'nervus-system',
    'Nervus System',
    '1.0.0',
    '系统保留条目，Nervus 核心服务',
    '{"id": "nervus-system", "subscribes": [], "publishes": ["system.*"]}',
    'http://nervus-arbor:8090',
    'online'
) ON CONFLICT (app_id) DO NOTHING;
