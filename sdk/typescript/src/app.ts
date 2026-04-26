/**
 * NervusApp — TypeScript SDK 主入口类
 */

import Fastify, { type FastifyInstance } from 'fastify'
import axios from 'axios'
import { connectBus, disconnectBus, subscribe, emit, makeFilter } from './bus'
import { connectContext, disconnectContext, Context } from './context'
import { LLMClient } from './llm'
import { MemoryGraph } from './memory'
import { getAppConfig, type AppConfig, type Event, type EventHandler, type Manifest, type FilterConfig } from './models'

interface HandlerEntry {
  subject: string
  filter: FilterConfig
  handler: EventHandler
}

interface ActionEntry {
  name: string
  handler: (params: Record<string, unknown>) => Promise<unknown>
}

export class NervusApp {
  readonly appId: string
  readonly config: AppConfig
  readonly llm: LLMClient
  readonly memory: typeof MemoryGraph
  readonly ctx: typeof Context

  private handlers: HandlerEntry[] = []
  private actions: ActionEntry[] = []
  private stateFn: (() => Promise<Record<string, unknown>>) | null = null
  private manifest: Manifest | null = null
  private server: FastifyInstance

  constructor(appId: string) {
    this.appId = appId
    this.config = getAppConfig(appId)
    this.llm = new LLMClient(this.config.llamaUrl)
    this.memory = MemoryGraph
    this.ctx = Context

    this.server = Fastify({ logger: { level: 'info' } })
    this._setupNsiRoutes()
  }

  // ── 装饰器风格 API ────────────────────────────────────

  on(subject: string, filterOrHandler: FilterConfig | EventHandler, handler?: EventHandler): this {
    let filter: FilterConfig = {}
    let fn: EventHandler

    if (typeof filterOrHandler === 'function') {
      fn = filterOrHandler
    } else {
      filter = filterOrHandler
      fn = handler!
    }

    this.handlers.push({ subject, filter, handler: fn })
    return this
  }

  action(name: string, handler: (params: Record<string, unknown>) => Promise<unknown>): this {
    this.actions.push({ name, handler })
    return this
  }

  state(fn: () => Promise<Record<string, unknown>>): this {
    this.stateFn = fn
    return this
  }

  setManifest(manifest: Manifest): this {
    this.manifest = manifest
    return this
  }

  // ── 便捷方法 ──────────────────────────────────────────

  async emit(subject: string, payload: Record<string, unknown>, correlationId?: string): Promise<void> {
    await emit(subject, payload, correlationId)
  }

  // ── NSI 标准接口 ──────────────────────────────────────

  private _setupNsiRoutes(): void {
    const app = this

    this.server.get('/manifest', async () => {
      return app.manifest ?? { id: app.appId, name: app.appId, version: '1.0.0' }
    })

    this.server.get('/health', async () => ({ status: 'ok', app_id: app.appId }))

    this.server.post<{ Params: { name: string }; Body: Record<string, unknown> }>(
      '/intake/:name',
      async (req, reply) => {
        const { name } = req.params
        const body = req.body
        const event: Event = 'subject' in body
          ? (body as unknown as Event)
          : { id: crypto.randomUUID(), subject: `intake.${name}`, payload: body, source_app: 'arbor-core', timestamp: new Date().toISOString(), correlation_id: null }

        for (const entry of app.handlers) {
          if (entry.subject.includes(name)) {
            const filterFn = makeFilter(entry.filter)
            if (!filterFn || filterFn(event)) {
              const result = await entry.handler(event)
              return { status: 'ok', result }
            }
          }
        }
        reply.code(404)
        return { error: `处理器 ${name} 未注册` }
      }
    )

    this.server.post<{ Params: { name: string }; Body: Record<string, unknown> }>(
      '/action/:name',
      async (req, reply) => {
        const { name } = req.params
        const entry = app.actions.find(a => a.name === name)
        if (!entry) {
          reply.code(404)
          return { error: `Action ${name} 未注册` }
        }
        const result = await entry.handler(req.body)
        return { status: 'ok', result }
      }
    )

    this.server.get('/state', async () => {
      const state = app.stateFn ? await app.stateFn() : {}
      return { status: 'ok', state }
    })

    this.server.get<{ Params: { type: string } }>('/query/:type', async (req) => {
      return { status: 'ok', type: req.params.type, data: [] }
    })
  }

  // ── 生命周期 ──────────────────────────────────────────

  private async startup(): Promise<void> {
    console.log(`[${this.appId}] 正在启动...`)
    await connectBus(this.config.natsUrl, this.appId)
    await connectContext(this.config.redisUrl)

    for (const entry of this.handlers) {
      const filterFn = makeFilter(entry.filter)
      await subscribe(entry.subject, entry.handler, filterFn, this.appId)
    }

    await this.registerWithArbor()
    console.log(`[${this.appId}] 启动完成，端口 ${this.config.port}`)
  }

  private async shutdown(): Promise<void> {
    console.log(`[${this.appId}] 正在关闭...`)
    await disconnectBus()
    await disconnectContext()
  }

  private async registerWithArbor(): Promise<void> {
    try {
      await axios.post(`${this.config.arborUrl}/apps/register`, {
        manifest: this.manifest ?? { id: this.appId, name: this.appId, version: '1.0.0' },
        endpoint_url: `http://${this.appId}:${this.config.port}`,
      }, { timeout: 5000 })
      console.log(`[${this.appId}] 已向 Arbor Core 注册`)
    } catch (err) {
      console.warn(`[${this.appId}] 向 Arbor 注册失败:`, (err as Error).message)
    }
  }

  async run(options: { port?: number; host?: string } = {}): Promise<void> {
    const port = options.port ?? this.config.port
    const host = options.host ?? '0.0.0.0'

    await this.startup()

    await this.server.listen({ port, host })

    // 优雅关闭
    const shutdown = async () => {
      await this.server.close()
      await this.shutdown()
      process.exit(0)
    }
    process.on('SIGTERM', shutdown)
    process.on('SIGINT', shutdown)
  }
}
