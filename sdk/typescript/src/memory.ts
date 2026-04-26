/**
 * Memory Graph — PostgreSQL + pgvector 封装（TypeScript）
 */

import { Pool, type PoolClient } from 'pg'

let pool: Pool | null = null

export async function connectMemory(postgresUrl: string): Promise<void> {
  pool = new Pool({ connectionString: postgresUrl, max: 10, idleTimeoutMillis: 30000 })
  await pool.query('SELECT 1')
  console.log(`Memory Graph 已连接: ${postgresUrl}`)
}

export async function disconnectMemory(): Promise<void> {
  if (pool) { await pool.end(); pool = null }
}

export class MemoryGraph {
  static async writeLifeEvent(params: {
    type: string
    title: string
    timestamp: Date
    sourceApp: string
    description?: string
    metadata?: Record<string, unknown>
    embedding?: number[]
  }): Promise<string> {
    if (!pool) throw new Error('Memory Graph 未连接')
    const { type, title, timestamp, sourceApp, description = '', metadata = {}, embedding } = params
    const id = crypto.randomUUID()
    const embStr = embedding ? `[${embedding.join(',')}]` : null

    await pool.query(
      `INSERT INTO life_events (id, type, title, description, timestamp, source_app, metadata, embedding)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector)`,
      [id, type, title, description, timestamp, sourceApp, JSON.stringify(metadata), embStr]
    )
    return id
  }

  static async writeKnowledgeItem(params: {
    type: string
    title: string
    timestamp: Date
    sourceApp: string
    content?: string
    summary?: string
    sourceUrl?: string
    tags?: string[]
    embedding?: number[]
  }): Promise<string> {
    if (!pool) throw new Error('Memory Graph 未连接')
    const { type, title, timestamp, sourceApp, content = '', summary = '', sourceUrl = '', tags = [], embedding } = params
    const id = crypto.randomUUID()
    const embStr = embedding ? `[${embedding.join(',')}]` : null

    await pool.query(
      `INSERT INTO knowledge_items (id, type, title, content, summary, source_url, source_app, tags, timestamp, embedding)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::vector)`,
      [id, type, title, content, summary, sourceUrl, sourceApp, tags, timestamp, embStr]
    )
    return id
  }

  static async semanticSearch(params: {
    queryEmbedding: number[]
    table?: string
    limit?: number
    typeFilter?: string
  }): Promise<Record<string, unknown>[]> {
    if (!pool) throw new Error('Memory Graph 未连接')
    const { queryEmbedding, table = 'life_events', limit = 10, typeFilter } = params
    const embStr = `[${queryEmbedding.join(',')}]`

    const typeClause = typeFilter ? 'AND type = $3' : ''
    const query = `
      SELECT id, type, title, description, timestamp, source_app, metadata,
             1 - (embedding <=> $1::vector) AS similarity
      FROM ${table}
      WHERE embedding IS NOT NULL ${typeClause}
      ORDER BY embedding <=> $1::vector
      LIMIT $2
    `

    const values: unknown[] = typeFilter ? [embStr, limit, typeFilter] : [embStr, limit]
    const result = await pool.query(query, values)
    return result.rows
  }

  static async queryRecent(params: {
    sourceApp?: string
    typeFilter?: string
    limit?: number
    table?: string
  }): Promise<Record<string, unknown>[]> {
    if (!pool) throw new Error('Memory Graph 未连接')
    const { sourceApp, typeFilter, limit = 20, table = 'life_events' } = params

    const conditions: string[] = []
    const values: unknown[] = []

    if (sourceApp) { values.push(sourceApp); conditions.push(`source_app = $${values.length}`) }
    if (typeFilter) { values.push(typeFilter); conditions.push(`type = $${values.length}`) }
    values.push(limit)

    const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''
    const result = await pool.query(
      `SELECT id, type, title, description, timestamp, source_app, metadata, created_at
       FROM ${table} ${where} ORDER BY timestamp DESC LIMIT $${values.length}`,
      values
    )
    return result.rows
  }
}
