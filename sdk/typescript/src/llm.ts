/**
 * LLM Client — llama.cpp server 封装（TypeScript）
 */

import axios, { type AxiosInstance } from 'axios'
import { readFileSync } from 'fs'
import { extname } from 'path'

export class LLMClient {
  private client: AxiosInstance

  constructor(baseUrl: string, timeout = 30000) {
    this.client = axios.create({
      baseURL: baseUrl.replace(/\/$/, ''),
      timeout,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  async chat(
    prompt: string,
    options: {
      system?: string
      temperature?: number
      maxTokens?: number
      jsonMode?: boolean
    } = {}
  ): Promise<string> {
    const {
      system = '你是 Nervus 的 AI 助手，运行在边缘设备上，简洁准确地回答问题。',
      temperature = 0.3,
      maxTokens = 1024,
      jsonMode = false,
    } = options

    const messages = []
    if (system) messages.push({ role: 'system', content: system })
    messages.push({ role: 'user', content: prompt })

    const body: Record<string, unknown> = {
      model: 'qwen3.5',
      messages,
      temperature,
      max_tokens: maxTokens,
      stream: false,
    }
    if (jsonMode) body.response_format = { type: 'json_object' }

    const res = await this.client.post('/v1/chat/completions', body)
    return res.data.choices[0].message.content as string
  }

  async chatJson<T = Record<string, unknown>>(
    prompt: string,
    options: { system?: string; temperature?: number } = {}
  ): Promise<T> {
    const text = await this.chat(prompt, {
      ...options,
      system: options.system ?? '你是 Nervus 的 AI 助手。请以 JSON 格式返回结果。',
      jsonMode: true,
    })
    try {
      return JSON.parse(text) as T
    } catch {
      const match = text.match(/\{[\s\S]*\}/)
      if (match) return JSON.parse(match[0]) as T
      throw new Error(`模型返回的不是有效 JSON: ${text.slice(0, 200)}`)
    }
  }

  async vision(imagePath: string, prompt: string, options: { temperature?: number; maxTokens?: number } = {}): Promise<string> {
    const { temperature = 0.2, maxTokens = 512 } = options

    let imageContent: unknown
    if (imagePath.startsWith('http://') || imagePath.startsWith('https://')) {
      imageContent = { type: 'image_url', image_url: { url: imagePath } }
    } else {
      const ext = extname(imagePath).toLowerCase()
      const mimeMap: Record<string, string> = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.webp': 'image/webp',
      }
      const mime = mimeMap[ext] ?? 'image/jpeg'
      const b64 = readFileSync(imagePath).toString('base64')
      imageContent = { type: 'image_url', image_url: { url: `data:${mime};base64,${b64}` } }
    }

    const body = {
      model: 'qwen3.5',
      messages: [{ role: 'user', content: [imageContent, { type: 'text', text: prompt }] }],
      temperature,
      max_tokens: maxTokens,
      stream: false,
    }

    const res = await this.client.post('/v1/chat/completions', body)
    return res.data.choices[0].message.content as string
  }

  async visionJson<T = Record<string, unknown>>(
    imagePath: string,
    prompt: string,
    options: { temperature?: number } = {}
  ): Promise<T> {
    const text = await this.vision(imagePath, `${prompt}\n\n请以 JSON 格式返回结果。`, options)
    try {
      return JSON.parse(text) as T
    } catch {
      const match = text.match(/\{[\s\S]*\}/)
      if (match) return JSON.parse(match[0]) as T
      throw new Error(`模型返回的不是有效 JSON: ${text.slice(0, 200)}`)
    }
  }

  async embed(text: string): Promise<number[]> {
    const res = await this.client.post('/v1/embeddings', {
      model: 'qwen3.5',
      input: text,
    })
    return res.data.data[0].embedding as number[]
  }
}
