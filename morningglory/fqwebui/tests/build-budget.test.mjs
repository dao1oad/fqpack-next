import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const viteConfig = readFileSync(new URL('../vite.config.js', import.meta.url), 'utf8').replace(/\r/g, '')

test('vite config exposes bundle budget controls for fqwebui heavy chunks', () => {
  assert.match(viteConfig, /manualChunks/)
  assert.match(viteConfig, /chunkSizeWarningLimit/)
  assert.match(viteConfig, /element-plus/)
  assert.match(viteConfig, /echarts/)
})
