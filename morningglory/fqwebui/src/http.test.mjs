import test from 'node:test'
import assert from 'node:assert/strict'
import axios from 'axios'
import './http.js'

test('http response interceptor accepts 202 Accepted payloads', async () => {
  const interceptor = axios.interceptors.response.handlers.at(-1)

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

test('http response interceptor still rejects non-2xx responses', async () => {
  const interceptor = axios.interceptors.response.handlers.at(-1)

  await assert.rejects(
    () => interceptor.fulfilled({
      status: 400,
      data: { error: 'bad request' },
    }),
  )
})
