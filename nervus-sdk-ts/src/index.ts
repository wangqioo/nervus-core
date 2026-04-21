/**
 * @nervus/sdk — Nervus 生态系统 TypeScript SDK
 *
 * 用法示例：
 *   import { NervusApp, Context, emit } from '@nervus/sdk'
 *
 *   const app = new NervusApp('calorie-tracker')
 *
 *   app.on('media.photo.classified', { filter: { tags_contains: ['food'] } }, async (event) => {
 *     const result = await app.llm.vision(event.payload.photoPath, '识别食物热量')
 *     await Context.set('physical.last_meal', event.timestamp)
 *     await emit('health.calorie.meal_logged', result)
 *   })
 *
 *   app.action('analyze_meal', async ({ photoPath }) => {
 *     return await app.llm.visionJson(photoPath, '识别食物并返回热量 JSON')
 *   })
 *
 *   app.run({ port: 8001 })
 */

export { NervusApp } from './app'
export { Context } from './context'
export { emit, subscribe } from './bus'
export { LLMClient } from './llm'
export { MemoryGraph } from './memory'
export type { Event, Manifest, AppConfig, EventHandler, SubscribeConfig } from './models'
