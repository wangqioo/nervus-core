/**
 * Synapse Bus — NATS JetStream 封装（TypeScript）
 */

import { connect as natsConnect, NatsConnection, JetStreamClient, StringCodec } from 'nats'
import type { Event, EventHandler, FilterConfig } from './models'
import { EventSchema } from './models'

let nc: NatsConnection | null = null
let js: JetStreamClient | null = null
let appId = ''
const sc = StringCodec()

export async function connectBus(natsUrl: string, id: string): Promise<void> {
  appId = id
  nc = await natsConnect({
    servers: natsUrl,
    name: `nervus-${id}`,
    reconnect: true,
    maxReconnectAttempts: -1,
    reconnectTimeWait: 2000,
  })
  js = nc.jetstream()
  console.log(`[${id}] 已连接 NATS: ${natsUrl}`)
}

export async function disconnectBus(): Promise<void> {
  if (nc) {
    await nc.drain()
    nc = null
    js = null
  }
}

export async function emit(
  subject: string,
  payload: Record<string, unknown>,
  correlationId?: string
): Promise<void> {
  if (!nc) throw new Error('Bus 未连接')

  const event: Event = {
    id: crypto.randomUUID(),
    subject,
    payload,
    source_app: appId,
    timestamp: new Date().toISOString(),
    correlation_id: correlationId ?? null,
  }

  const data = sc.encode(JSON.stringify(event))

  if (js) {
    await js.publish(subject, data)
  } else {
    nc.publish(subject, data)
  }
}

export async function subscribe(
  subject: string,
  handler: EventHandler,
  filterFn?: ((event: Event) => boolean) | null,
  queueGroup?: string
): Promise<void> {
  if (!nc) throw new Error('Bus 未连接')

  const messageHandler = async (msg: { data: Uint8Array; ack?: () => void; nak?: () => void }) => {
    try {
      const raw = sc.decode(msg.data)
      const event = EventSchema.parse(JSON.parse(raw))

      if (filterFn && !filterFn(event)) return

      await handler(event)
      msg.ack?.()
    } catch (err) {
      console.error(`[${appId}] 处理事件失败 ${subject}:`, err)
      msg.nak?.()
    }
  }

  // 尝试 JetStream 持久化订阅
  if (js) {
    try {
      const consumerName = `${appId}-${subject.replace(/\./g, '-').replace(/\*/g, 'wc').replace(/>/g, 'all')}`
      const sub = await js.subscribe(subject, {
        durable: consumerName,
        queue: queueGroup,
        mack: true,
      })
      ;(async () => {
        for await (const msg of sub) {
          await messageHandler(msg as any)
        }
      })().catch(console.error)
      console.log(`[${appId}] JetStream 订阅: ${subject}`)
      return
    } catch {
      // 降级到普通订阅
    }
  }

  const sub = nc.subscribe(subject, { queue: queueGroup })
  ;(async () => {
    for await (const msg of sub) {
      await messageHandler(msg as any)
    }
  })().catch(console.error)
  console.log(`[${appId}] 普通订阅: ${subject}`)
}

export function makeFilter(conditions: FilterConfig): ((event: Event) => boolean) | null {
  if (!conditions || Object.keys(conditions).length === 0) return null

  return (event: Event): boolean => {
    const payload = event.payload as Record<string, unknown>

    if ('tags_contains' in conditions) {
      const tags = (payload['tags'] as string[]) ?? []
      const required = conditions['tags_contains'] as string[]
      if (!required.some(t => tags.includes(t))) return false
    }

    if ('field_eq' in conditions) {
      const checks = conditions['field_eq'] as Record<string, unknown>
      for (const [field, value] of Object.entries(checks)) {
        if (payload[field] !== value) return false
      }
    }

    return true
  }
}
