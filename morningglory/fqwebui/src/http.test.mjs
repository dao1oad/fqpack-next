import test from 'node:test'
import assert from 'node:assert/strict'
import * as httpModule from './http.js'

const { default: http, HTTP_CONFIG } = httpModule

test('http client exposes the shared base config', () => {
  assert.equal(typeof HTTP_CONFIG, 'object')
  assert.equal(HTTP_CONFIG.baseURL, '')
  assert.equal(Number.isFinite(HTTP_CONFIG.timeout), true)
  assert.ok(HTTP_CONFIG.timeout > 0)
  assert.equal(http.defaults.baseURL, HTTP_CONFIG.baseURL)
  assert.equal(http.defaults.timeout, HTTP_CONFIG.timeout)
})

test('http response interceptor unwraps payloads', async () => {
  const interceptor = http.interceptors.response.handlers.at(-1)

  assert.equal(typeof interceptor?.fulfilled, 'function')
  await assert.doesNotReject(async () => {
    const payload = await interceptor.fulfilled({
      status: 202,
      data: {
        run: { id: 'run-202' },
      },
    })
    assert.deepEqual(payload, {
      run: { id: 'run-202' },
    })
  })
})
