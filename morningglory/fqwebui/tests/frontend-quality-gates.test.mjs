import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const readSource = (relativePath) => (
  readFileSync(new URL(relativePath, import.meta.url), 'utf8').replace(/\r/g, '')
)

const collectSourceFiles = (relativeDir) => {
  const rootDir = fileURLToPath(new URL(relativeDir, import.meta.url))
  const files = []

  const walk = (currentDir) => {
    for (const entry of readdirSync(currentDir, { withFileTypes: true })) {
      const nextPath = path.join(currentDir, entry.name)

      if (entry.isDirectory()) {
        walk(nextPath)
        continue
      }

      if (/\.(js|mjs|vue)$/.test(entry.name)) {
        files.push({
          path: nextPath,
          content: readFileSync(nextPath, 'utf8').replace(/\r/g, '')
        })
      }
    }
  }

  walk(rootDir)
  return files
}

const packageJson = readSource('../package.json')
const eslintConfig = readSource('../eslint.config.mjs')
const browserSmokeRunner = readSource('../scripts/run-browser-smoke.mjs')
const nodeTestRunner = readSource('../scripts/run-node-tests.mjs')
const ciYaml = readSource('../../../.github/workflows/ci.yml')
const preflightScript = readSource('../../../script/fq_local_preflight.ps1')
const mainSource = readSource('../src/main.js')
const globalSource = readSource('../src/global.js')
const sourceFiles = collectSourceFiles('../src/')

test('fqwebui exposes frontend quality gate entrypoints', () => {
  assert.match(packageJson, /"lint"/)
  assert.match(packageJson, /"build"/)
  assert.match(packageJson, /scripts\/run-node-tests\.mjs/)
  assert.match(packageJson, /scripts\/run-browser-smoke\.mjs/)
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
  assert.match(ciYaml, /playwright install --with-deps chromium/)
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

test('known-red frontend Node tests do not grow beyond the current 7-file ceiling', () => {
  const knownRedMatch = nodeTestRunner.match(/KNOWN_RED_TEST_FILES = new Set\(\[([\s\S]*?)\]\)/)

  assert.ok(knownRedMatch, 'KNOWN_RED_TEST_FILES definition should exist')

  const knownRedEntries = [...knownRedMatch[1].matchAll(/'([^']+\.test\.mjs)'/g)].map((match) => match[1])

  assert.ok(knownRedEntries.length > 0, 'KNOWN_RED_TEST_FILES should stay explicit')
  assert.ok(knownRedEntries.length <= 7, `KNOWN_RED_TEST_FILES grew to ${knownRedEntries.length}`)
})

test('empty Vuex wiring is removed once fqwebui no longer has real store consumers', () => {
  const vuexConsumerPattern = /\$store\b|useStore\(|mapState\b|mapGetters\b|mapActions\b|mapMutations\b|store\.(commit|dispatch)\(/
  const storeDirFragment = `${path.sep}src${path.sep}store${path.sep}`
  const storeFileUrl = new URL('../src/store/index.js', import.meta.url)
  const storeDirPath = fileURLToPath(new URL('../src/store/', import.meta.url))
  const consumerFiles = sourceFiles.filter(
    ({ path: filePath, content }) => !filePath.includes(storeDirFragment) && vuexConsumerPattern.test(content)
  )
  const vuexImportFiles = sourceFiles.filter(({ content }) => /\bfrom ['"]vuex['"]|\brequire\(['"]vuex['"]\)/.test(content))
  const lingeringStoreFiles = existsSync(storeDirPath)
    ? readdirSync(storeDirPath).filter((entry) => /\.(js|mjs|ts|vue)$/.test(entry))
    : []

  assert.equal(
    consumerFiles.length,
    0,
    `unexpected Vuex consumer(s): ${consumerFiles.map(({ path: filePath }) => path.relative(fileURLToPath(new URL('../src/', import.meta.url)), filePath)).join(', ')}`
  )
  assert.doesNotMatch(mainSource, /import store from '\.\/store'/)
  assert.doesNotMatch(mainSource, /\.use\(store\)/)
  assert.equal(
    existsSync(storeFileUrl),
    false,
    'src/store/index.js should be removed once fqwebui no longer has real Vuex consumers'
  )
  assert.equal(
    lingeringStoreFiles.length,
    0,
    `src/store should not retain Vuex source files: ${lingeringStoreFiles.join(', ')}`
  )
  assert.equal(
    vuexImportFiles.length,
    0,
    `unexpected vuex import(s): ${vuexImportFiles.map(({ path: filePath }) => path.relative(fileURLToPath(new URL('../src/', import.meta.url)), filePath)).join(', ')}`
  )
  assert.doesNotMatch(packageJson, /"vuex"\s*:/)
})

test('legacy futures pages import trading constants explicitly instead of relying on globalProperties injections', () => {
  const tradingConstantsSource = readSource('../src/config/tradingConstants.mjs')
  const tradingConstantNames = [
    'futureAccount',
    'stockAccount',
    'digitCoinAccount',
    'globalFutureAccount',
    'digitCoinLevel',
    'globalFutureSymbol',
    'maxAccountUseRate',
    'stopRate'
  ]
  const legacyTradingGlobalPattern = /(this|that)\.\$(futureAccount|stockAccount|digitCoinAccount|globalFutureAccount|digitCoinLevel|globalFutureSymbol|maxAccountUseRate|stopRate)\b/
  const remainingTradingFiles = [
    '../src/views/js/kline-mixin.js',
    '../src/views/StatisticsChat.vue'
  ]
  const retiredTradingFiles = [
    new URL('../src/views/js/future-control.js', import.meta.url),
    new URL('../src/views/FuturePositionList.vue', import.meta.url),
  ]

  for (const constantName of tradingConstantNames) {
    assert.match(tradingConstantsSource, new RegExp(`export const ${constantName} =`))
  }

  for (const fileUrl of retiredTradingFiles) {
    assert.equal(existsSync(fileUrl), false, `${fileUrl} should be removed`)
  }

  for (const relativePath of remainingTradingFiles) {
    const content = readSource(relativePath)
    assert.match(content, /tradingConstants\.mjs/)
    assert.doesNotMatch(content, legacyTradingGlobalPattern)
  }

  assert.doesNotMatch(
    globalSource,
    /app\.config\.globalProperties\.\$(futureAccount|stockAccount|digitCoinAccount|globalFutureAccount|digitCoinLevel|globalFutureSymbol|maxAccountUseRate|stopRate)\b/
  )
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

test('browser smoke gate executes a real Playwright chromium spec instead of config-only assertions', () => {
  assert.match(browserSmokeRunner, /FQ_PLAYWRIGHT_EXECUTABLE_PATH/)
  assert.match(browserSmokeRunner, /Program Files\\\\Google\\\\Chrome/)
  assert.match(browserSmokeRunner, /install', 'chromium/)
  assert.match(browserSmokeRunner, /tests\/daily-screening\.browser\.spec\.mjs/)
  assert.match(browserSmokeRunner, /'test', \.\.\.smokeSpecs, '--project=chromium'/)
  assert.match(readSource('../playwright.config.mjs'), /launchOptions:/)
})
