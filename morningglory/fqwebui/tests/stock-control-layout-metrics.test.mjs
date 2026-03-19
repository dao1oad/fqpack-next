import test from 'node:test'
import assert from 'node:assert/strict'
import { chromium } from '@playwright/test'

const BASE_URL = process.env.FQ_WEBUI_BASE_URL || 'http://127.0.0.1:18080'

test('stock-control tables fit at 100% browser zoom without horizontal overflow', async () => {
  const browser = await chromium.launch({ headless: true })

  try {
    const page = await browser.newPage({
      viewport: { width: 1920, height: 1080 },
      deviceScaleFactor: 1
    })
    await page.goto(`${BASE_URL}/#/stock-control`, { waitUntil: 'networkidle' })

    const metrics = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('.panel-card')).map((card) => {
        const title = card.querySelector('.panel-card-header span')?.textContent?.trim() || ''
        const ledger = card.querySelector('.stock-control-ledger')
        const header = card.querySelector('.stock-control-ledger__header')
        const priceCells = Array.from(card.querySelectorAll('.stock-control-ledger__cell--price'))
        const timeCells = Array.from(card.querySelectorAll('.stock-control-ledger__cell--time'))
        const maxPriceOverflow = priceCells.reduce((maxOverflow, cell) => {
          return Math.max(maxOverflow, cell.scrollWidth - cell.clientWidth)
        }, 0)
        const maxTimeOverflow = timeCells.reduce((maxOverflow, cell) => {
          return Math.max(maxOverflow, cell.scrollWidth - cell.clientWidth)
        }, 0)

        return {
          title,
          ledgerClientWidth: ledger?.clientWidth || 0,
          ledgerScrollWidth: ledger?.scrollWidth || 0,
          headerClientWidth: header?.clientWidth || 0,
          headerScrollWidth: header?.scrollWidth || 0,
          maxPriceOverflow,
          maxTimeOverflow
        }
      })
    })

    assert.equal(metrics.length, 3)
    for (const item of metrics) {
      assert.ok(
        item.ledgerScrollWidth <= item.ledgerClientWidth + 1,
        `${item.title} ledger overflow: ${item.ledgerScrollWidth} > ${item.ledgerClientWidth}`
      )
      assert.ok(
        item.headerScrollWidth <= item.headerClientWidth + 1,
        `${item.title} header overflow: ${item.headerScrollWidth} > ${item.headerClientWidth}`
      )
      assert.ok(item.maxPriceOverflow <= 1, `${item.title} price overflow: ${item.maxPriceOverflow}`)
      assert.ok(item.maxTimeOverflow <= 1, `${item.title} time overflow: ${item.maxTimeOverflow}`)
    }
  } finally {
    await browser.close()
  }
})
