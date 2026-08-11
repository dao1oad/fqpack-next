<script setup>
import { computed, ref, watch } from 'vue'

import {
  ACCORDION_SECTIONS,
  buildAccordionSections,
  buildDecisionCard,
  fetchDetail,
  formatMetric,
} from './clxFundamentalDetailLogic.mjs'
import { DIMENSION_META, GRADE_META } from './clxFundamentalRankingLogic.mjs'

const props = defineProps({
  row: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['close'])

const loading = ref(false)
const error = ref('')
const detail = ref(null)
const openSections = ref(new Set())

const decisionCard = computed(() =>
  detail.value ? buildDecisionCard(detail.value, props.row) : null,
)

const accordionSections = computed(() =>
  detail.value ? buildAccordionSections(detail.value, props.row) : [],
)

const isDeep = computed(() => props.row?.tier === 'deep')

const evidenceWeak = computed(() =>
  detail.value ? detail.value.evidenceGrade === 'D' : false,
)

const toggleSection = (key) => {
  const next = new Set(openSections.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  openSections.value = next
}

const isOpen = (key) => openSections.value.has(key)

const loadDetail = async () => {
  const row = props.row
  if (!row) {
    detail.value = null
    error.value = ''
    return
  }
  loading.value = true
  error.value = ''
  try {
    const result = await fetchDetail({ row })
    detail.value = result.detail
  } catch (err) {
    detail.value = null
    error.value = err?.message || '详情加载失败'
  } finally {
    loading.value = false
  }
}

watch(
  () => props.row?.symbol,
  () => loadDetail(),
)

defineExpose({ refresh: loadDetail })
</script>

<template>
  <section class="clx-workbench-panel clx-fund-detail-panel">
    <header class="clx-panel-head">
      <div>
        <h2>标的基本面详情</h2>
        <p class="clx-panel-time">
          <template v-if="row">
            <strong>{{ row.symbol }} {{ row.name }}</strong>
            · {{ isDeep ? '深析' : '本期初评' }}
            · 快排 #{{ row.quickRank }}
          </template>
          <template v-else>未选择标的</template>
        </p>
      </div>
      <div class="clx-panel-actions">
        <el-button size="small" :disabled="!row" @click="emit('close')">返回列表 (Esc)</el-button>
      </div>
    </header>

    <div v-if="!row" class="clx-panel-empty">点击左侧列表行查看标的基本面详情</div>
    <div v-else-if="error" class="clx-panel-error">
      {{ error }}
      <el-button size="small" @click="loadDetail">重试</el-button>
    </div>
    <div v-else-if="loading && !detail" class="clx-panel-empty">加载中...</div>
    <template v-else-if="detail && decisionCard">
      <div v-if="evidenceWeak" class="clx-fund-detail__d-banner">
        ⚠ 证据等级 D：仅初步观察，估值暂停
      </div>
      <div class="clx-fund-detail__scroll">
        <div class="clx-fund-decision">
          <div class="clx-fund-decision__strip">
            <span>as-of {{ detail.asOf || '—' }}</span>
            <span>报告期 {{ detail.financialReportDate || '—' }}</span>
            <span>行情 {{ detail.quoteDate || '—' }}</span>
            <span>证据 {{ detail.evidenceGrade }}</span>
            <span>生成 {{ detail.generatedAt || '—' }}</span>
          </div>
          <p class="clx-fund-decision__positioning">
            {{ decisionCard.oneLinePositioning || '—' }}
          </p>
          <div class="clx-fund-decision__six">
            <div
              v-for="item in decisionCard.sixDimensions"
              :key="item.key"
              class="clx-fund-decision__six-item"
              :class="`clx-fund-decision__six-item--${item.grade}`"
              :title="item.rationale"
            >
              <span class="clx-fund-decision__six-label">
                {{ DIMENSION_META[item.key]?.label }}
              </span>
              <strong>{{ GRADE_META[item.grade]?.label }}</strong>
              <span class="clx-fund-decision__six-grade">{{ item.grade }}</span>
            </div>
          </div>
          <div class="clx-fund-decision__metrics">
            <div v-for="item in decisionCard.metricItems" :key="item.label">
              <span>{{ item.label }}</span>
              <strong>{{ formatMetric(item.value, { suffix: item.suffix || '' }) }}</strong>
            </div>
          </div>
          <div v-if="decisionCard.risks.length" class="clx-fund-decision__risks">
            <strong>风险清单</strong>
            <span
              v-for="(risk, index) in decisionCard.risks"
              :key="index"
              :class="`clx-fund-decision__risk--${risk.level}`"
            >
              {{ risk.level === 'high' ? '高' : risk.level === 'medium' ? '中' : '低' }} · {{ risk.text }}
            </span>
          </div>
          <div class="clx-fund-decision__cols">
            <div>
              <strong>三项优势</strong>
              <ul>
                <li v-for="(item, index) in decisionCard.advantages" :key="index">{{ item }}</li>
                <li v-if="!decisionCard.advantages.length" class="clx-fund-decision__muted">—</li>
              </ul>
            </div>
            <div>
              <strong>三项问题</strong>
              <ul>
                <li v-for="(item, index) in decisionCard.problems" :key="index">{{ item }}</li>
                <li v-if="!decisionCard.problems.length" class="clx-fund-decision__muted">—</li>
              </ul>
            </div>
          </div>
        </div>

        <div class="clx-fund-accordion">
          <div
            v-for="section in accordionSections"
            :key="section.key"
            class="clx-fund-accordion__item"
          >
            <button
              type="button"
              class="clx-fund-accordion__head"
              :aria-expanded="isOpen(section.key)"
              @click="toggleSection(section.key)"
            >
              <span>{{ isOpen(section.key) ? '▾' : '▸' }}</span>
              <strong>{{ section.label }}</strong>
            </button>
            <div v-if="isOpen(section.key)" class="clx-fund-accordion__body">
              <template v-if="section.key === 'evidenceTrace'">
                <div class="clx-fund-accordion__rows">
                  <div v-for="entry in section.entries" :key="entry.label">
                    <span>{{ entry.label }}</span>
                    <strong>{{ entry.value }}</strong>
                  </div>
                </div>
                <details class="clx-fund-accordion__ids">
                  <summary>evidence_ids（{{ section.evidenceIds.length }} 条，展开下钻来源）</summary>
                  <ul>
                    <li v-for="id in section.evidenceIds" :key="id">{{ id }}</li>
                  </ul>
                </details>
              </template>
              <template v-else-if="section.content">
                <pre class="clx-fund-accordion__json">{{ JSON.stringify(section.content, null, 2) }}</pre>
              </template>
              <template v-else-if="section.rows">
                <div class="clx-fund-accordion__rows">
                  <div v-for="entry in section.rows" :key="entry.label">
                    <span>{{ entry.label }}</span>
                    <strong>{{ formatMetric(entry.value, { suffix: entry.suffix || '' }) }}</strong>
                  </div>
                </div>
              </template>
              <div v-else class="clx-fund-decision__muted">
                {{ isDeep ? '本期深析未提供该分节内容' : '本期初评仅提供规则化指标，详见决策卡' }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.clx-workbench-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--fq-border-soft, #ebeef5);
  border-radius: var(--fq-radius-md, 8px);
  background: var(--fq-panel-bg, #fff);
  box-shadow: var(--fq-shadow-sm, 0 1px 2px rgba(15, 23, 42, 0.04));
}

.clx-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--fq-border-soft, #ebeef5);
}

.clx-panel-head h2 {
  margin: 0;
  font-size: 15px;
}

.clx-panel-time {
  margin: 6px 0 0;
  color: var(--fq-text-muted, #909399);
  font-size: 12px;
}

.clx-panel-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.clx-fund-detail__d-banner {
  flex: 0 0 auto;
  padding: 6px 14px;
  background: var(--fq-chip-bg-warning, #fef3c7);
  color: var(--fq-status-warning, #d97706);
  font-size: 12px;
}

.clx-fund-detail__scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 10px 14px 16px;
}

.clx-fund-decision {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--fq-border-soft, #ebeef5);
  border-radius: 8px;
  background: var(--fq-panel-bg-muted, #f8fafc);
}

.clx-fund-decision__strip {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  color: var(--fq-text-muted, #909399);
  font-size: 11px;
}

.clx-fund-decision__positioning {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  line-height: 1.5;
}

.clx-fund-decision__six {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}

.clx-fund-decision__six-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-radius: 6px;
  background: #fff;
  font-size: 12px;
}

.clx-fund-decision__six-label {
  flex: 1 1 auto;
  color: var(--fq-text-secondary, #606266);
}

.clx-fund-decision__six-item strong {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  color: #fff;
  font-size: 11px;
}

.clx-fund-decision__six-item--strong strong { background: #16a34a; }
.clx-fund-decision__six-item--good strong { background: #2563eb; }
.clx-fund-decision__six-item--neutral strong { background: #9ca3af; }
.clx-fund-decision__six-item--watch strong { background: #d97706; }
.clx-fund-decision__six-item--weak strong { background: #dc2626; }
.clx-fund-decision__six-item--evidence_gap strong { background: #b8b8c0; }

.clx-fund-decision__six-grade {
  color: var(--fq-text-muted, #909399);
  font-size: 10px;
}

.clx-fund-decision__metrics {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 6px;
}

.clx-fund-decision__metrics div {
  padding: 6px 8px;
  border-radius: 6px;
  background: #fff;
  text-align: center;
}

.clx-fund-decision__metrics span {
  display: block;
  color: var(--fq-text-muted, #909399);
  font-size: 11px;
}

.clx-fund-decision__metrics strong {
  display: block;
  margin-top: 2px;
  font-size: 13px;
}

.clx-fund-decision__risks {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
}

.clx-fund-decision__risk--high { color: var(--fq-status-danger, #dc2626); }
.clx-fund-decision__risk--medium { color: var(--fq-status-warning, #d97706); }
.clx-fund-decision__risk--low { color: var(--fq-text-secondary, #606266); }

.clx-fund-decision__cols {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  font-size: 12px;
}

.clx-fund-decision__cols ul {
  margin: 4px 0 0;
  padding-left: 16px;
}

.clx-fund-decision__muted {
  color: var(--fq-text-muted, #909399);
  font-size: 12px;
}

.clx-fund-accordion {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 10px;
}

.clx-fund-accordion__item {
  border: 1px solid var(--fq-border-soft, #ebeef5);
  border-radius: 6px;
  overflow: hidden;
}

.clx-fund-accordion__head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 12px;
  border: 0;
  background: var(--fq-panel-bg-muted, #f8fafc);
  color: var(--fq-text-primary, #303133);
  text-align: left;
  cursor: pointer;
}

.clx-fund-accordion__body {
  padding: 10px 12px;
  font-size: 12px;
}

.clx-fund-accordion__rows {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.clx-fund-accordion__rows div {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 8px;
  background: var(--fq-panel-bg-muted, #f8fafc);
  border-radius: 4px;
}

.clx-fund-accordion__rows span {
  color: var(--fq-text-muted, #909399);
}

.clx-fund-accordion__json {
  margin: 0;
  max-height: 240px;
  overflow: auto;
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-all;
}

.clx-fund-accordion__ids summary {
  cursor: pointer;
  color: var(--fq-text-secondary, #606266);
}

.clx-fund-accordion__ids ul {
  margin: 6px 0 0;
  padding-left: 16px;
}

.clx-panel-empty,
.clx-panel-error {
  padding: 16px 12px;
  color: var(--fq-text-muted, #909399);
  font-size: 12px;
  text-align: center;
}

.clx-panel-error {
  color: var(--fq-status-danger, #dc2626);
}
</style>
