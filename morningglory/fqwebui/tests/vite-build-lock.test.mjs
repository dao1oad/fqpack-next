import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  appendViteOutDirArgs,
  createIsolatedViteArtifactsContext,
  runLockedBuild
} from './vite-build-lock.mjs'

const projectDir = fileURLToPath(new URL('..', import.meta.url))

test('createIsolatedViteArtifactsContext returns a stable isolated outDir per spec file', () => {
  const ghostingSpecUrl = new URL('./kline-slim-ghosting.browser.spec.mjs', import.meta.url).href
  const ghostingContextA = createIsolatedViteArtifactsContext(ghostingSpecUrl, projectDir)
  const ghostingContextB = createIsolatedViteArtifactsContext(ghostingSpecUrl, projectDir)
  const ganttContext = createIsolatedViteArtifactsContext(
    new URL('./gantt-sidebar-hover-alignment.browser.spec.mjs', import.meta.url).href,
    projectDir
  )

  assert.equal(ghostingContextA.outDir, ghostingContextB.outDir)
  assert.equal(ghostingContextA.outDirRelative, ghostingContextB.outDirRelative)
  assert.notEqual(ghostingContextA.outDir, ganttContext.outDir)
  assert.match(
    ghostingContextA.outDirRelative.replaceAll(path.sep, '/'),
    /^\.playwright-vite\/kline-slim-ghosting-browser-spec-[a-f0-9]{8}$/
  )
  assert.equal(
    ghostingContextA.outDir,
    path.join(projectDir, ghostingContextA.outDirRelative)
  )
})

test('appendViteOutDirArgs appends a preview/build outDir without mutating the base args', () => {
  const baseArgs = ['preview', '--host', '127.0.0.1', '--port', '18087', '--strictPort']
  const nextArgs = appendViteOutDirArgs(baseArgs, '.playwright-vite/ghosting-12345678')

  assert.deepEqual(baseArgs, [
    'preview',
    '--host',
    '127.0.0.1',
    '--port',
    '18087',
    '--strictPort'
  ])
  assert.deepEqual(nextArgs, [
    'preview',
    '--host',
    '127.0.0.1',
    '--port',
    '18087',
    '--strictPort',
    '--outDir',
    '.playwright-vite/ghosting-12345678'
  ])
})

test('runLockedBuild executes the build command once with the isolated outDir appended', async () => {
  const tempDir = await mkdtemp(path.join(os.tmpdir(), 'vite-build-lock-'))
  const captureFile = path.join(tempDir, 'args.json')

  try {
    await runLockedBuild(
      () => ({
        command: process.execPath,
        args: [
          '-e',
          "const fs = require('node:fs'); const output = process.argv[1]; const records = fs.existsSync(output) ? JSON.parse(fs.readFileSync(output, 'utf8')) : []; records.push(process.argv.slice(2)); fs.writeFileSync(output, JSON.stringify(records));",
          captureFile
        ]
      }),
      projectDir,
      {
        outDir: '.playwright-vite/ghosting-12345678'
      }
    )

    const records = JSON.parse(await readFile(captureFile, 'utf8'))
    assert.equal(records.length, 1)
    assert.deepEqual(records[0], ['--outDir', '.playwright-vite/ghosting-12345678'])
  } finally {
    await rm(tempDir, {
      recursive: true,
      force: true
    })
  }
})
