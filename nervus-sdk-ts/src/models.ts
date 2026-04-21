import { z } from 'zod'

// ── 事件模型 ──────────────────────────────────────────────

export const EventSchema = z.object({
  id: z.string().default(() => crypto.randomUUID()),
  subject: z.string(),
  payload: z.record(z.unknown()).default({}),
  source_app: z.string().default(''),
  timestamp: z.string().default(() => new Date().toISOString()),
  correlation_id: z.string().nullable().default(null),
})

export type Event = z.infer<typeof EventSchema>

// ── Manifest 模型 ─────────────────────────────────────────

export interface SubscribeConfig {
  subject: string
  filter?: Record<string, unknown>
  handler?: string
}

export interface ActionSpec {
  name: string
  description?: string
  input?: Record<string, string>
  output?: Record<string, string>
}

export interface Manifest {
  id: string
  name: string
  version?: string
  description?: string
  subscribes?: SubscribeConfig[]
  publishes?: string[]
  actions?: ActionSpec[]
  context_reads?: string[]
  context_writes?: string[]
  memory_writes?: string[]
}

// ── App 配置 ──────────────────────────────────────────────

export interface AppConfig {
  appId: string
  port: number
  natsUrl: string
  redisUrl: string
  postgresUrl: string
  llamaUrl: string
  whisperUrl: string
  arborUrl: string
}

export function getAppConfig(appId: string): AppConfig {
  return {
    appId,
    port: parseInt(process.env.APP_PORT ?? '8000'),
    natsUrl: process.env.NATS_URL ?? 'nats://localhost:4222',
    redisUrl: process.env.REDIS_URL ?? 'redis://localhost:6379',
    postgresUrl: process.env.POSTGRES_URL ?? 'postgresql://nervus:nervus_secret@localhost:5432/nervus',
    llamaUrl: process.env.LLAMA_URL ?? 'http://localhost:8080',
    whisperUrl: process.env.WHISPER_URL ?? 'http://localhost:8081',
    arborUrl: process.env.ARBOR_URL ?? 'http://localhost:8090',
  }
}

// ── 类型别名 ──────────────────────────────────────────────

export type EventHandler = (event: Event) => Promise<unknown>
export type FilterConfig = Record<string, unknown>
