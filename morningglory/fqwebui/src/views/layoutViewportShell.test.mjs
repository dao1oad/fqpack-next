import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const readSource = (relativePath) => (
  readFileSync(new URL(relativePath, import.meta.url), 'utf8').replace(/\r/g, '')
)

const appSource = readSource('../App.vue')
const workbenchDensitySource = readSource('../style/workbench-density.css')
const runtimeSource = readSource('./RuntimeObservability.vue')

test('app shell locks browser scrolling and delegates height to the viewport shell', () => {
  assert.match(appSource, /body\s*\{[\s\S]*overflow:\s*hidden;/)
  assert.doesNotMatch(appSource, /body\s*\{[\s\S]*overflow-y:\s*auto;/)
  assert.doesNotMatch(appSource, /body\s*\{[\s\S]*overflow-x:\s*auto;/)
  assert.match(appSource, /\.app-shell\s*\{[\s\S]*display:\s*flex;[\s\S]*flex-direction:\s*column;[\s\S]*height:\s*100vh;[\s\S]*height:\s*100dvh;[\s\S]*overflow:\s*hidden;/)
})

test('shared workbench shell uses viewport height and dedicated internal scroll helpers', () => {
  assert.match(workbenchDensitySource, /\.workbench-page \{[\s\S]*height:\s*100vh;[\s\S]*height:\s*100dvh;[\s\S]*overflow:\s*hidden;/)
  assert.doesNotMatch(workbenchDensitySource, /\.workbench-page \{[\s\S]*\n\s+min-height:\s*100vh;/)
  assert.match(workbenchDensitySource, /\.workbench-body \{[\s\S]*overflow:\s*hidden;/)
  assert.match(workbenchDensitySource, /\.workbench-body--scroll \{[\s\S]*overflow:\s*auto;/)
  assert.match(workbenchDensitySource, /\.workbench-scroll-panel \{[\s\S]*overflow:\s*auto;/)
  assert.match(workbenchDensitySource, /\.workbench-table-wrap \{[\s\S]*overflow:\s*hidden;/)
})

test('RuntimeObservability keeps the viewport fixed and delegates scrolling to sidebar, feed, and detail panes', () => {
  assert.match(runtimeSource, /\.runtime-shell \{[^}]*overflow:\s*hidden;/)
  assert.match(runtimeSource, /\.runtime-browse-layout \{[\s\S]*grid-template-columns:\s*minmax\(200px,\s*0\.58fr\) minmax\(820px,\s*2\.42fr\) minmax\(400px,\s*1\.08fr\);[\s\S]*overflow:\s*hidden;/)
  assert.match(runtimeSource, /\.runtime-browser-panel \{[\s\S]*overflow:\s*hidden;/)
  assert.match(runtimeSource, /\.runtime-browser-panel--feed \{[\s\S]*overflow-y:\s*auto;[\s\S]*overflow-x:\s*hidden;/)
  assert.match(runtimeSource, /\.component-symbol-list \{[\s\S]*overflow:\s*auto;/)
  assert.match(runtimeSource, /\.runtime-detail-panel--fill \{[\s\S]*overflow:\s*auto;/)
  assert.match(runtimeSource, /\.runtime-detail-panel--steps \{[\s\S]*overflow-y:\s*auto;[\s\S]*overflow-x:\s*hidden;/)
  assert.doesNotMatch(runtimeSource, /\.runtime-shell \{[^}]*overflow-y:\s*auto;/)
  assert.doesNotMatch(runtimeSource, /\.runtime-browse-layout \{[^}]*overflow-y:\s*auto;/)
})
