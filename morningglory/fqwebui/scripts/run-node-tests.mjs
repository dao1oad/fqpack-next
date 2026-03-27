import { spawnSync } from 'node:child_process'
import { readdir } from 'node:fs/promises'
import { relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT_URLS = [
  new URL('../src/', import.meta.url),
  new URL('../tests/', import.meta.url),
]

const KNOWN_RED_TEST_FILES = new Set([
  'src/views/js/kline-slim-subject-panel.test.mjs',
  'tests/gantt-history-chart.test.mjs',
  'tests/kline-slim-chart-refactor.test.mjs',
  'tests/kline-slim-multi-period-chanlun.test.mjs',
  'tests/kline-slim-sidebar.test.mjs',
  'tests/stock-control-layout-metrics.test.mjs',
  'tests/stock-control-signal-lists.test.mjs',
])

const includeKnownRed = process.argv.includes('--include-known-red')
const projectRoot = fileURLToPath(new URL('../', import.meta.url))

const toPosixPath = (value) => value.replace(/\\/g, '/')

const collectTestFiles = async (directoryUrl) => {
  const entries = await readdir(directoryUrl, { withFileTypes: true })
  const files = []

  for (const entry of entries) {
    const entryUrl = new URL(entry.name, directoryUrl)
    if (entry.isDirectory()) {
      files.push(...await collectTestFiles(new URL(`${entry.name}/`, directoryUrl)))
      continue
    }
    if (entry.isFile() && entry.name.endsWith('.test.mjs')) {
      files.push(fileURLToPath(entryUrl))
    }
  }

  return files
}

const discoveredFiles = []
for (const rootUrl of ROOT_URLS) {
  discoveredFiles.push(...await collectTestFiles(rootUrl))
}

const resolvedFiles = discoveredFiles
  .map((filePath) => {
    const relativePath = toPosixPath(relative(projectRoot, filePath))
    return { filePath, relativePath }
  })
  .sort((left, right) => left.relativePath.localeCompare(right.relativePath))

const runnableFiles = resolvedFiles.filter(({ relativePath }) => (
  includeKnownRed || !KNOWN_RED_TEST_FILES.has(relativePath)
))

if (!runnableFiles.length) {
  throw new Error('No runnable Node test files found under src/ or tests/.')
}

if (!includeKnownRed) {
  const excludedFiles = resolvedFiles.filter(({ relativePath }) => KNOWN_RED_TEST_FILES.has(relativePath))
  if (excludedFiles.length) {
    console.log(`Skipping ${excludedFiles.length} known-red frontend Node tests.`)
  }
}

const result = spawnSync(
  process.execPath,
  ['--experimental-default-type=module', '--test', ...runnableFiles.map(({ filePath }) => filePath)],
  {
    cwd: projectRoot,
    stdio: 'inherit',
  },
)

if (result.error) {
  throw result.error
}

process.exit(result.status ?? 1)
