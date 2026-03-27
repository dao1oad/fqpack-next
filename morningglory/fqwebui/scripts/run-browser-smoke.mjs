import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'

const projectRoot = process.cwd()
const playwrightCli = path.join(projectRoot, 'node_modules', 'playwright', 'cli.js')
const smokeSpecs = (
  process.env.FQ_BROWSER_SMOKE_SPECS
    ? process.env.FQ_BROWSER_SMOKE_SPECS.split(',').map((item) => item.trim()).filter(Boolean)
    : [
        'tests/daily-screening.browser.spec.mjs',
        'tests/system-settings.browser.spec.mjs',
        'tests/workbench-overlap.browser.spec.mjs',
      ]
)
const localBrowserCandidates = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
]
const localBrowserPath = localBrowserCandidates.find((candidate) => existsSync(candidate))

const runCommand = (args, extraEnv = {}) => {
  const result = spawnSync(process.execPath, [playwrightCli, ...args], {
    cwd: projectRoot,
    env: {
      ...process.env,
      ...extraEnv,
    },
    stdio: 'inherit',
  })

  if (result.error) {
    throw result.error
  }

  if (result.status !== 0) {
    process.exit(result.status ?? 1)
  }
}

if (!localBrowserPath) {
  runCommand(['install', 'chromium'])
}

runCommand(
  ['test', ...smokeSpecs, '--project=chromium'],
  localBrowserPath
    ? { FQ_PLAYWRIGHT_EXECUTABLE_PATH: localBrowserPath }
    : {},
)
