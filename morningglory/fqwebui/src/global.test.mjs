import test from 'node:test'
import assert from 'node:assert/strict'
import { setTimeout as delay } from 'node:timers/promises'

import { SimpleCache } from './global.js'

test('SimpleCache expires entries using the default ttl when no per-key ttl is provided', async () => {
  const cache = new SimpleCache(0.02)

  cache.set('default', 'value')
  assert.equal(cache.get('default'), 'value')

  await delay(40)

  assert.equal(cache.get('default'), undefined)
})

test('SimpleCache supports a per-key ttl override without changing the default ttl behavior', async () => {
  const cache = new SimpleCache(1)

  cache.set('short', 'expires-fast', 0.02)
  cache.set('default', 'still-here')

  await delay(40)

  assert.equal(cache.get('short'), undefined)
  assert.equal(cache.get('default'), 'still-here')
})
