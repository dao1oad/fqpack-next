import { test, expect } from '@playwright/test'
import path from 'node:path'

import { createIsolatedViteArtifactsContext, runLockedBuild } from './vite-build-lock.mjs'
import {
  cleanupServerPort,
  startPreviewServer,
  stopDevServer,
  waitForServer,
} from './kline-slim-browser-helpers.mjs'

const DEV_SERVER_PORT = 18093
const DEV_SERVER_URL = `http://127.0.0.1:${DEV_SERVER_PORT}`
const TARGET_URL = `${DEV_SERVER_URL}/system-settings?tabTitle=%E8%AE%BE%E7%BD%AE`
const PREVIEW_ARTIFACTS = createIsolatedViteArtifactsContext(import.meta.url)
const VIEWPORTS = [
  { name: 'desktop-3col', width: 1600, height: 900 },
  { name: 'desktop-2col', width: 1200, height: 900 },
  { name: 'narrow-1col', width: 860, height: 900 },
]

let devServerProcess = null

function buildDashboardPayload() {
  return {
    bootstrap: {
      file_path: 'D:/fqpack/config/freshquant_bootstrap.yaml',
      sections: [
        {
          key: 'mongodb',
          title: 'MongoDB',
          description: '主业务库与只读模型依赖的 Mongo 启动配置。',
          restart_required: true,
          source: 'bootstrap_file',
          items: [
            { key: 'mongodb.host', field: 'host', label: '主机', editable: true, restart_required: true, source: 'bootstrap_file', value: 'fq_mongodb' },
            { key: 'mongodb.port', field: 'port', label: '端口', editable: true, restart_required: true, source: 'bootstrap_file', value: 27017 },
          ],
        },
        {
          key: 'redis',
          title: 'Redis',
          description: '运行队列与实时缓存依赖的 Redis 启动配置。',
          restart_required: true,
          source: 'bootstrap_file',
          items: [
            { key: 'redis.host', field: 'host', label: '主机', editable: true, restart_required: true, source: 'bootstrap_file', value: 'fq_redis' },
            { key: 'redis.port', field: 'port', label: '端口', editable: true, restart_required: true, source: 'bootstrap_file', value: 6379 },
            { key: 'redis.db', field: 'db', label: 'DB', editable: true, restart_required: true, source: 'bootstrap_file', value: 1 },
          ],
        },
        {
          key: 'memory',
          title: 'Memory',
          description: 'Memory 服务冷数据和 artifact 根路径。',
          restart_required: true,
          source: 'bootstrap_file',
          items: [
            { key: 'memory.mongodb.host', field: 'mongodb.host', label: 'Mongo 主机', editable: true, restart_required: true, source: 'bootstrap_file', value: '127.0.0.1' },
            { key: 'memory.mongodb.port', field: 'mongodb.port', label: 'Mongo 端口', editable: true, restart_required: true, source: 'bootstrap_file', value: 27027 },
            { key: 'memory.mongodb.db', field: 'mongodb.db', label: 'Mongo 库', editable: true, restart_required: true, source: 'bootstrap_file', value: 'fq_memory' },
          ],
        },
        {
          key: 'order_management',
          title: '订单管理',
          description: '订单管理写库与 projection 库配置。',
          restart_required: true,
          source: 'bootstrap_file',
          items: [
            { key: 'order_management.mongo_database', field: 'mongo_database', label: 'Mongo 库', editable: true, restart_required: true, source: 'bootstrap_file', value: 'freshquant_order_management' },
            { key: 'order_management.projection_database', field: 'projection_database', label: 'Projection 库', editable: true, restart_required: true, source: 'bootstrap_file', value: 'freshquant' },
          ],
        },
        {
          key: 'position_management',
          title: '仓位管理库',
          description: '仓位管理单独 Mongo 库配置。',
          restart_required: true,
          source: 'bootstrap_file',
          items: [
            { key: 'position_management.mongo_database', field: 'mongo_database', label: 'Mongo 库', editable: true, restart_required: true, source: 'bootstrap_file', value: 'freshquant_position_management' },
          ],
        },
        {
          key: 'api',
          title: 'API',
          description: '前后端内部 API 基础地址。',
          restart_required: true,
          source: 'bootstrap_file',
          items: [
            { key: 'api.base_url', field: 'base_url', label: '基础地址', editable: true, restart_required: true, source: 'bootstrap_file', value: 'http://127.0.0.1:15000' },
          ],
        },
        {
          key: 'xtdata',
          title: 'XTData',
          description: 'XTData 端口配置。',
          restart_required: true,
          source: 'bootstrap_file',
          items: [
            { key: 'xtdata.port', field: 'port', label: '端口', editable: true, restart_required: true, source: 'bootstrap_file', value: 58610 },
          ],
        },
      ],
      values: {
        mongodb: { host: 'fq_mongodb', port: 27017, db: 'freshquant', gantt_db: 'freshquant_gantt' },
        redis: { host: 'fq_redis', port: 6379, db: 1, password: '' },
        memory: { mongodb: { host: '127.0.0.1', port: 27027, db: 'fq_memory' }, cold_root: '.codex/memory', artifact_root: 'D:/fqpack/runtime/artifacts/memory' },
        order_management: { mongo_database: 'freshquant_order_management', projection_database: 'freshquant' },
        position_management: { mongo_database: 'freshquant_position_management' },
        api: { base_url: 'http://127.0.0.1:15000' },
        xtdata: { port: 58610 },
      },
    },
    settings: {
      sections: [
        {
          key: 'xtquant',
          title: 'XTQuant',
          description: '交易连接、账户和 broker submit mode。',
          restart_required: false,
          source: 'params.xtquant',
          items: [
            { key: 'xtquant.account', field: 'account', label: '账户', editable: true, restart_required: false, source: 'params.xtquant', value: '068000076370' },
            { key: 'xtquant.account_type', field: 'account_type', label: '账户类型', editable: true, restart_required: false, source: 'params.xtquant', value: 'CREDIT' },
            { key: 'xtquant.broker_submit_mode', field: 'broker_submit_mode', label: 'Broker Submit Mode', editable: true, restart_required: false, source: 'params.xtquant', value: 'observe_only' },
            { key: 'xtquant.auto_repay.enabled', field: 'auto_repay.enabled', label: '自动还款', editable: true, restart_required: false, source: 'params.xtquant', value: true },
            { key: 'xtquant.auto_repay.reserve_cash', field: 'auto_repay.reserve_cash', label: '留底现金', editable: true, restart_required: false, source: 'params.xtquant', value: 5000 },
          ],
        },
        {
          key: 'guardian',
          title: 'Guardian',
          description: 'Guardian 股票阈值、网格间距和下单金额配置。',
          restart_required: false,
          source: 'params.guardian',
          items: [
            { key: 'guardian.stock.lot_amount', field: 'stock.lot_amount', label: '单次买入金额', editable: true, restart_required: false, source: 'params.guardian', value: 50000 },
            { key: 'guardian.stock.threshold.mode', field: 'stock.threshold.mode', label: '阈值模式', editable: true, restart_required: false, source: 'params.guardian', value: 'percent' },
            { key: 'guardian.stock.threshold.percent', field: 'stock.threshold.percent', label: '阈值百分比', editable: true, restart_required: false, source: 'params.guardian', value: 1 },
            { key: 'guardian.stock.grid_interval.mode', field: 'stock.grid_interval.mode', label: '网格模式', editable: true, restart_required: false, source: 'params.guardian', value: 'percent' },
            { key: 'guardian.stock.grid_interval.percent', field: 'stock.grid_interval.percent', label: '网格百分比', editable: true, restart_required: false, source: 'params.guardian', value: 3 },
          ],
        },
        {
          key: 'position_management',
          title: '仓位门禁',
          description: '仓位管理阈值真值，保存在 pm_configs。',
          restart_required: false,
          source: 'pm_configs.thresholds',
          items: [
            { key: 'position_management.allow_open_min_bail', field: 'allow_open_min_bail', label: '允许开新仓最低保证金', editable: true, restart_required: false, source: 'pm_configs.thresholds', value: 800000 },
            { key: 'position_management.holding_only_min_bail', field: 'holding_only_min_bail', label: '仅允许持仓内买入最低保证金', editable: true, restart_required: false, source: 'pm_configs.thresholds', value: 100000 },
          ],
        },
      ],
      strategies: [
        { code: 'Guardian', name: '守护者策略', desc: '这是一个高抛低吸的超级网格策略', b62_uid: 'gWyxlpDMPglnysji' },
        { code: 'Manual', name: '手动策略', desc: '这是手动挡交易策略', b62_uid: 'gWyxlpDMPglnysjj' },
      ],
      values: {
        xtquant: {
          account: '068000076370',
          account_type: 'CREDIT',
          broker_submit_mode: 'observe_only',
          path: 'D:/mock/path',
          auto_repay: { enabled: true, reserve_cash: 5000 },
        },
        guardian: { stock: { lot_amount: 50000, threshold: { mode: 'percent', percent: 1, atr: { period: null, multiplier: null } }, grid_interval: { mode: 'percent', percent: 3, atr: { period: null, multiplier: null } } } },
        position_management: { allow_open_min_bail: 800000, holding_only_min_bail: 100000 },
      },
    },
  }
}

async function runBuild() {
  await runLockedBuild(
    () => ({
      command: process.execPath,
      args: [path.join(process.cwd(), 'node_modules', 'vite', 'bin', 'vite.js'), 'build'],
    }),
    process.cwd(),
    { outDir: PREVIEW_ARTIFACTS.outDirRelative },
  )
}

test.beforeAll(async () => {
  test.setTimeout(120000)
  cleanupServerPort(DEV_SERVER_PORT)
  await runBuild()
  devServerProcess = startPreviewServer({
    port: DEV_SERVER_PORT,
    cwd: process.cwd(),
    outDir: PREVIEW_ARTIFACTS.outDirRelative,
  })
  await waitForServer(DEV_SERVER_URL)
})

test.afterAll(async () => {
  await stopDevServer(devServerProcess)
  devServerProcess = null
})

test('system settings scroll keeps every section header clear of the first row', async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/system-config/dashboard') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildDashboardPayload()),
      })
      return
    }

    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ error: `${url.pathname} not mocked` }),
    })
  })

  for (const viewport of VIEWPORTS) {
    await test.step(`viewport ${viewport.name}`, async () => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      await page.goto(TARGET_URL)

      await expect(page.getByRole('heading', { name: '系统设置' })).toBeVisible()
      await expect(page.locator('.settings-dense-column')).toHaveCount(3)
      await expect(page.getByText('自动还款', { exact: true })).toBeVisible()
      await expect(page.getByText('留底现金', { exact: true })).toBeVisible()

      const overlapMetrics = await page.evaluate(async () => {
        const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
        const columns = [...document.querySelectorAll('.settings-dense-column__body')]
        columns.forEach((column, index) => {
          column.scrollTop = Math.min([180, 220, 180][index] ?? 0, column.scrollHeight)
        })
        await wait(150)

        return [...document.querySelectorAll('.settings-dense-section')]
          .map((section) => {
            const title = section.querySelector('h2')?.textContent?.trim()
            const header = section.querySelector('.settings-dense-section__header')
            const firstRow = section.querySelector('.settings-ledger__row')
            if (!title || !header || !firstRow) {
              return null
            }

            const headerRect = header.getBoundingClientRect()
            const rowRect = firstRow.getBoundingClientRect()
            return {
              title,
              overlap: Number((headerRect.bottom - rowRect.top).toFixed(2)),
            }
          })
          .filter(Boolean)
      })

      expect(overlapMetrics.length).toBeGreaterThan(0)
      for (const section of overlapMetrics) {
        expect(section.overlap, `${viewport.name}: ${section.title} first row is covered by section header`).toBeLessThanOrEqual(1)
      }
    })
  }
})
