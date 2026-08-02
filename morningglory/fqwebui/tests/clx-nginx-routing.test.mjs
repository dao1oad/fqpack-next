import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const nginxSource = await readFile(new URL('../nginx.conf', import.meta.url), 'utf8')

test('CLX API uses the primary FreshQuant API upstream', () => {
  assert.match(
    nginxSource,
    /location \/api\/ \{[\s\S]*?proxy_pass \$fq_apiserver;/,
  )
  assert.doesNotMatch(nginxSource, /CLX_API_UPSTREAM/)
  assert.doesNotMatch(nginxSource, /\$clx_apiserver/)
  assert.doesNotMatch(nginxSource, /location \/api\/clx-daily-selection\//)
})
