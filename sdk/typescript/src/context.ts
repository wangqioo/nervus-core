/**
 * Context Graph — Redis 工作记忆封装（TypeScript）
 */

import Redis from 'ioredis'

const TTL_MAP: Record<string, number> = {
  'temporal.': 6 * 3600,
  'physical.': 24 * 3600,
  'cognitive.': 12 * 3600,
  'social.': 12 * 3600,
  'travel.': 7 * 24 * 3600,
}
const DEFAULT_TTL = 24 * 3600
const KEY_PREFIX = 'context:user:'

let redis: Redis | null = null

export async function connectContext(redisUrl: string): Promise<void> {
  redis = new Redis(redisUrl, {
    lazyConnect: false,
    maxRetriesPerRequest: 3,
    retryStrategy: (times) => Math.min(times * 100, 3000),
  })
  await redis.ping()
  console.log(`Context Graph 已连接: ${redisUrl}`)
}

export async function disconnectContext(): Promise<void> {
  if (redis) {
    redis.disconnect()
    redis = null
  }
}

function fullKey(field: string): string {
  return `${KEY_PREFIX}${field}`
}

function getTtl(field: string): number | null {
  for (const [prefix, ttl] of Object.entries(TTL_MAP)) {
    if (field.startsWith(prefix)) return ttl
  }
  return DEFAULT_TTL
}

export class Context {
  static async get<T = unknown>(field: string, defaultValue?: T): Promise<T | undefined> {
    if (!redis) throw new Error('Context Graph 未连接')
    const raw = await redis.get(fullKey(field))
    if (raw === null) return defaultValue
    try { return JSON.parse(raw) as T } catch { return raw as unknown as T }
  }

  static async set(field: string, value: unknown, ttl?: number): Promise<void> {
    if (!redis) throw new Error('Context Graph 未连接')
    const serialized = JSON.stringify(value)
    const effectiveTtl = ttl ?? getTtl(field)
    if (effectiveTtl) {
      await redis.setex(fullKey(field), effectiveTtl, serialized)
    } else {
      await redis.set(fullKey(field), serialized)
    }
  }

  static async delete(field: string): Promise<void> {
    if (!redis) throw new Error('Context Graph 未连接')
    await redis.del(fullKey(field))
  }

  static async getNamespace(namespace: string): Promise<Record<string, unknown>> {
    if (!redis) throw new Error('Context Graph 未连接')
    const pattern = fullKey(`${namespace}.*`)
    const keys = await redis.keys(pattern)
    if (!keys.length) return {}
    const values = await redis.mget(...keys)
    const prefixLen = fullKey(`${namespace}.`).length
    const result: Record<string, unknown> = {}
    keys.forEach((key, i) => {
      const shortKey = key.slice(prefixLen)
      const val = values[i]
      if (val !== null) {
        try { result[shortKey] = JSON.parse(val) } catch { result[shortKey] = val }
      }
    })
    return result
  }

  static async increment(field: string, delta = 1): Promise<number> {
    if (!redis) throw new Error('Context Graph 未连接')
    const result = await redis.incrbyfloat(fullKey(field), delta)
    const ttl = getTtl(field)
    if (ttl) await redis.expire(fullKey(field), ttl)
    return parseFloat(result)
  }

  static async getAllUserState(): Promise<Record<string, unknown>> {
    if (!redis) throw new Error('Context Graph 未连接')
    const pattern = `${KEY_PREFIX}*`
    const keys = await redis.keys(pattern)
    if (!keys.length) return {}
    const values = await redis.mget(...keys)
    const result: Record<string, unknown> = {}
    keys.forEach((key, i) => {
      const shortKey = key.slice(KEY_PREFIX.length)
      const val = values[i]
      if (val !== null) {
        try { result[shortKey] = JSON.parse(val) } catch { result[shortKey] = val }
      }
    })
    return result
  }
}
