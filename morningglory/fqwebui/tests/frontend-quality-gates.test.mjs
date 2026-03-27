import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const readSource = (relativePath) => (
  readFileSync(new URL(relativePath, import.meta.url), 'utf8').replace(/\r/g, '')
)

const packageJson = readSource('../package.json')
const eslintConfig = readSource('../eslint.config.mjs')
const nodeTestRunner = readSource('../scripts/run-node-tests.mjs')
const ciYaml = readSource('../../../.github/workflows/ci.yml')
const preflightScript = readSource('../../../script/fq_local_preflight.ps1')

test('fqwebui exposes frontend quality gate entrypoints', () => {
  assert.match(packageJson, /"lint"/)
  assert.match(packageJson, /"build"/)
  assert.match(packageJson, /scripts\/run-node-tests\.mjs/)
  assert.match(packageJson, /\.vue/)
  assert.match(eslintConfig, /src\/\*\*\/\*\.vue/)
  assert.match(eslintConfig, /tests\/\*\*\/\*\.vue/)
  assert.match(preflightScript, /frontendChanged/)
  assert.match(preflightScript, /Test-FrontendChanges/)
  assert.match(preflightScript, /frontend/)
  assert.match(preflightScript, /frontendLintExitCode/)
  assert.match(preflightScript, /frontendBrowserSmokeExitCode/)
  assert.match(preflightScript, /frontendUnitExitCode/)
  assert.match(preflightScript, /frontendBuildExitCode/)
  assert.match(preflightScript, /frontend = \[ordered\]@{/)
  assert.match(ciYaml, /npm run test:browser-smoke/)
  assert.match(ciYaml, /npm run build/)
  assert.match(preflightScript, /fqwebui/)
})

test('test:unit discovers src and tests suites through a shared runner with explicit known-red exclusions', () => {
  assert.match(nodeTestRunner, /KNOWN_RED_TEST_FILES/)
  assert.match(nodeTestRunner, /new URL\('\.\.\/src\/', import\.meta\.url\)/)
  assert.match(nodeTestRunner, /new URL\('\.\.\/tests\/', import\.meta\.url\)/)
  assert.match(nodeTestRunner, /kline-slim-subject-panel\.test\.mjs/)
  assert.match(nodeTestRunner, /stock-control-signal-lists\.test\.mjs/)
})

test('preflight computes frontendChanged after the base ref is fetched and resolved', () => {
  const fetchBaseRefIndex = preflightScript.indexOf('Fetch-BaseRef -RepoRoot $repoRoot -ResolvedBaseRef $resolvedBaseRef')
  const frontendChangedIndex = preflightScript.indexOf('$frontendChanged = Test-FrontendChanges -RepoRoot $repoRoot -ResolvedBaseRef $resolvedBaseRef')

  assert.notEqual(fetchBaseRefIndex, -1)
  assert.notEqual(frontendChangedIndex, -1)
  assert.ok(fetchBaseRefIndex < frontendChangedIndex)
})

test('frontend gate orchestration changes also trigger the frontend checks', () => {
  assert.match(ciYaml, /script\/fq_local_preflight\.ps1/)
  assert.match(ciYaml, /\.github\/workflows\/ci\.yml/)
  assert.match(preflightScript, /\.github\/workflows\/ci\.yml/)
  assert.match(preflightScript, /script\/fq_local_preflight\.ps1/)
})

test('preflight detects frontend changes from the full working tree and bypasses cache on dirty state', () => {
  assert.match(preflightScript, /git -C \$RepoRoot diff --name-only \$ResolvedBaseRef -- @triggerPaths/)
  assert.match(preflightScript, /git -C \$RepoRoot ls-files --others --exclude-standard -- @triggerPaths/)
  assert.match(preflightScript, /Test-HasUncommittedChanges/)
  assert.match(preflightScript, /HasUncommittedChanges/)
  assert.match(preflightScript, /if \(\$HasUncommittedChanges\) {\s*return \$false/)
})
