import test from 'node:test'
import assert from 'node:assert/strict'
import http from './http.js'

test('http client exposes the shared base config', () => {
  assert.equal(http.defaults.baseURL, '')
  assert.equal(http.defaults.timeout, 0)
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
