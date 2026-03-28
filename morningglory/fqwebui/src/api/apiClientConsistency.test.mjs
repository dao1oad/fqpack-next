import test from 'node:test'
import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'

const apiDirectory = new URL('./', import.meta.url)
const apiFiles = readdirSync(apiDirectory)
  .filter((name) => name.endsWith('.js'))
  .sort()

test('api modules use the shared http client instead of importing axios directly', () => {
  assert.ok(apiFiles.length > 0)

  for (const fileName of apiFiles) {
    const source = readFileSync(new URL(fileName, apiDirectory), 'utf8').replace(/\r/g, '')

    assert.doesNotMatch(
      source,
      /import axios from 'axios'/,
      `${fileName} should not import axios directly`,
    )
    assert.match(
      source,
      /from ['"]@\/http['"]/,
      `${fileName} should import the shared http client`,
    )
  }
})
