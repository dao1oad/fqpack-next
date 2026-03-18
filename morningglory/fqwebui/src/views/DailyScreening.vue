<template>
  <div class="workbench-page daily-screening-page">
    <MyHeader />

    <div class="workbench-body daily-screening-body" v-loading="pageLoading">
      <section class="workbench-toolbar">
        <div class="workbench-toolbar__header">
          <div class="workbench-title-group">
            <div class="workbench-page-title">每日选股</div>
            <div class="workbench-page-meta">
              <span>Dagster 预计算</span>
              <span>/</span>
              <span>统一条件池交集</span>
              <span>/</span>
              <span>基础池固定锚定 A ∪ B</span>
            </div>
          </div>
          <div class="workbench-toolbar__actions">
            <el-button @click="loadScopes">刷新 scopes</el-button>
            <el-button @click="refreshCurrentScope">刷新结果</el-button>
          </div>
        </div>

        <div class="workbench-summary-row">
          <span class="workbench-summary-chip workbench-summary-chip--muted">
            当前 scope <strong>{{ selectedScopeLabel }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--success">
            基础池 <strong>{{ scopeSummary?.stock_count ?? 0 }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--warning">
            当前结果 <strong>{{ resultRows.length }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--muted">
            已选条件 <strong>{{ activeConditionCount }}</strong>
          </span>
        </div>
      </section>

      <el-alert
        v-if="pageError"
        class="workbench-alert"
        type="error"
        :title="pageError"
        :closable="false"
        show-icon
      />

      <div class="daily-screening-grid">
        <section class="workbench-panel daily-filter-panel" v-loading="loadingFilters">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">筛选工作台</div>
              <p class="workbench-panel__desc">前端只做组合查询，不再触发运行，不再展示 SSE。</p>
            </div>
          </div>

          <article class="workbench-block">
            <div class="workbench-panel__title">Scope</div>
            <el-select
              v-model="selectedScopeId"
              class="daily-field-control"
              filterable
              clearable
              placeholder="请选择 scope"
            >
              <el-option
                v-for="item in scopeItems"
                :key="item.scopeId"
                :label="item.isLatest ? `${item.label}（latest）` : item.label"
                :value="item.scopeId"
              />
            </el-select>
          </article>

          <article class="workbench-block">
            <div class="workbench-panel__title">CLS 模型</div>
            <div class="daily-chip-grid">
              <el-button
                v-for="item in filterGroups.clsModels"
                :key="item.key"
                size="small"
                :type="conditionKeys.includes(item.key) ? 'primary' : 'default'"
                :plain="!conditionKeys.includes(item.key)"
                @click="toggleCondition(item.key)"
              >
                {{ item.label }} · {{ item.count }}
              </el-button>
            </div>
          </article>

          <article class="workbench-block">
            <div class="workbench-panel__title">热门窗口</div>
            <div class="daily-chip-grid">
              <el-button
                v-for="item in filterGroups.hotWindows"
                :key="item.key"
                size="small"
                :type="conditionKeys.includes(item.key) ? 'primary' : 'default'"
                :plain="!conditionKeys.includes(item.key)"
                @click="toggleCondition(item.key)"
              >
                {{ item.label }} · {{ item.count }}
              </el-button>
            </div>
          </article>

          <article class="workbench-block">
            <div class="workbench-panel__title">市场属性</div>
            <div class="daily-chip-grid">
              <el-button
                v-for="item in filterGroups.marketFlags"
                :key="item.key"
                size="small"
                :type="conditionKeys.includes(item.key) ? 'primary' : 'default'"
                :plain="!conditionKeys.includes(item.key)"
                @click="toggleCondition(item.key)"
              >
                {{ item.label }} · {{ item.count }}
              </el-button>
            </div>
          </article>

          <article class="workbench-block">
            <div class="workbench-panel__title">chanlun 周期</div>
            <div class="daily-chip-grid">
              <el-button
                v-for="item in filterGroups.chanlunPeriods"
                :key="item.key"
                size="small"
                :type="conditionKeys.includes(item.key) ? 'primary' : 'default'"
                :plain="!conditionKeys.includes(item.key)"
                @click="toggleCondition(item.key)"
              >
                {{ item.label }} · {{ item.count }}
              </el-button>
            </div>
          </article>

          <article class="workbench-block">
            <div class="workbench-panel__title">chanlun 信号</div>
            <div class="daily-chip-grid">
              <el-button
                v-for="item in filterGroups.chanlunSignals"
                :key="item.key"
                size="small"
                :type="conditionKeys.includes(item.key) ? 'primary' : 'default'"
                :plain="!conditionKeys.includes(item.key)"
                @click="toggleCondition(item.key)"
              >
                {{ item.label }} · {{ item.count }}
              </el-button>
            </div>
          </article>

          <article class="workbench-block">
            <div class="workbench-panel__title">Shouban30 缠论指标</div>
            <div class="daily-metric-grid">
              <el-form-item label="高级段倍数 ≤">
                <el-input-number
                  v-model="metricFilters.higherMultipleLte"
                  controls-position="right"
                  :min="0"
                  :step="0.1"
                  class="daily-field-control"
                />
              </el-form-item>
              <el-form-item label="段倍数 ≤">
                <el-input-number
                  v-model="metricFilters.segmentMultipleLte"
                  controls-position="right"
                  :min="0"
                  :step="0.1"
                  class="daily-field-control"
                />
              </el-form-item>
              <el-form-item label="笔涨幅% ≤">
                <el-input-number
                  v-model="metricFilters.biGainPercentLte"
                  controls-position="right"
                  :min="0"
                  :step="0.1"
                  class="daily-field-control"
                />
              </el-form-item>
            </div>
          </article>

          <div class="daily-filter-actions">
            <span class="daily-expression">{{ currentExpression }}</span>
            <div class="daily-action-buttons">
              <el-button type="primary" @click="queryRows">查询结果</el-button>
              <el-button @click="resetFilters">重置筛选</el-button>
            </div>
          </div>
        </section>

        <section class="workbench-panel daily-results-panel" v-loading="queryLoading">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">交集列表</div>
              <p class="workbench-panel__desc">无条件时默认显示基础池，勾选后统一取交集。</p>
            </div>
            <div class="workbench-panel__meta">
              <span>{{ resultRows.length }} 条</span>
            </div>
          </div>

          <el-table
            :data="resultRows"
            size="small"
            border
            height="640"
            @row-click="handleRowClick"
          >
            <el-table-column prop="code" label="代码" width="92" />
            <el-table-column prop="name" label="名称" min-width="120" show-overflow-tooltip />
            <el-table-column label="高级段倍数" width="116">
              <template #default="{ row }">
                {{ formatNumber(row.higherMultiple) }}
              </template>
            </el-table-column>
            <el-table-column label="段倍数" width="96">
              <template #default="{ row }">
                {{ formatNumber(row.segmentMultiple) }}
              </template>
            </el-table-column>
            <el-table-column label="笔涨幅%" width="96">
              <template #default="{ row }">
                {{ formatNumber(row.biGainPercent) }}
              </template>
            </el-table-column>
            <el-table-column prop="chanlunReason" label="缠论原因" min-width="150" show-overflow-tooltip />
          </el-table>
        </section>

        <aside class="daily-detail-stack" v-loading="detailLoading">
          <section class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">标的详情</div>
                <p class="workbench-panel__desc">展示命中条件画像和 Shouban30 缠论指标。</p>
              </div>
            </div>

            <div v-if="detailSnapshot" class="daily-detail-summary">
              <div class="daily-detail-title">{{ detailSnapshot.name || detailSnapshot.code }}</div>
              <div class="daily-detail-meta">
                <span class="workbench-code">{{ detailSnapshot.code }}</span>
                <span>/</span>
                <span>{{ selectedScopeLabel }}</span>
              </div>
            </div>
            <div v-else class="daily-empty">请先选择一只股票。</div>
          </section>

          <section class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">命中条件</div>
              </div>
            </div>

            <div v-if="detailSnapshot" class="daily-condition-stack">
              <article class="workbench-block">
                <div class="workbench-panel__title">CLS 模型</div>
                <div class="daily-chip-grid">
                  <span
                    v-for="item in detail.clsMemberships"
                    :key="item.conditionKey"
                    class="workbench-summary-chip workbench-summary-chip--muted"
                  >
                    {{ formatDailyScreeningConditionLabel(item.conditionKey) }}
                  </span>
                  <span v-if="detail.clsMemberships.length === 0" class="daily-empty-inline">暂无</span>
                </div>
              </article>

              <article class="workbench-block">
                <div class="workbench-panel__title">热门窗口</div>
                <div class="daily-chip-grid">
                  <span
                    v-for="item in detail.hotMemberships"
                    :key="item.conditionKey"
                    class="workbench-summary-chip workbench-summary-chip--warning"
                  >
                    {{ formatDailyScreeningConditionLabel(item.conditionKey) }}
                  </span>
                  <span v-if="detail.hotMemberships.length === 0" class="daily-empty-inline">暂无</span>
                </div>
              </article>

              <article class="workbench-block">
                <div class="workbench-panel__title">市场属性</div>
                <div class="daily-chip-grid">
                  <span
                    v-for="item in detail.marketFlagMemberships"
                    :key="item.conditionKey"
                    class="workbench-summary-chip workbench-summary-chip--success"
                  >
                    {{ formatDailyScreeningConditionLabel(item.conditionKey) }}
                  </span>
                  <span v-if="detail.marketFlagMemberships.length === 0" class="daily-empty-inline">暂无</span>
                </div>
              </article>

              <article class="workbench-block">
                <div class="workbench-panel__title">chanlun 周期</div>
                <div class="daily-chip-grid">
                  <span
                    v-for="item in detail.chanlunPeriodMemberships"
                    :key="item.conditionKey"
                    class="workbench-summary-chip workbench-summary-chip--muted"
                  >
                    {{ formatDailyScreeningConditionLabel(item.conditionKey) }}
                  </span>
                  <span v-if="detail.chanlunPeriodMemberships.length === 0" class="daily-empty-inline">暂无</span>
                </div>
              </article>

              <article class="workbench-block">
                <div class="workbench-panel__title">chanlun 信号</div>
                <div class="daily-chip-grid">
                  <span
                    v-for="item in detail.chanlunSignalMemberships"
                    :key="item.conditionKey"
                    class="workbench-summary-chip workbench-summary-chip--muted"
                  >
                    {{ formatDailyScreeningConditionLabel(item.conditionKey) }}
                  </span>
                  <span v-if="detail.chanlunSignalMemberships.length === 0" class="daily-empty-inline">暂无</span>
                </div>
              </article>
            </div>
          </section>

          <section class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">Shouban30 缠论指标</div>
              </div>
            </div>

            <el-descriptions v-if="detailSnapshot" :column="1" border size="small">
              <el-descriptions-item label="高级段倍数">
                {{ formatNumber(detailSnapshot.higherMultiple) }}
              </el-descriptions-item>
              <el-descriptions-item label="段倍数">
                {{ formatNumber(detailSnapshot.segmentMultiple) }}
              </el-descriptions-item>
              <el-descriptions-item label="笔涨幅%">
                {{ formatNumber(detailSnapshot.biGainPercent) }}
              </el-descriptions-item>
              <el-descriptions-item label="缠论原因">
                {{ detailSnapshot.chanlunReason || '-' }}
              </el-descriptions-item>
            </el-descriptions>
          </section>

          <section class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">历史热门理由</div>
              </div>
            </div>

            <el-table
              :data="detail.hot_reasons"
              size="small"
              border
              height="280"
              empty-text="暂无热门理由"
            >
              <el-table-column prop="date" label="日期" width="108" />
              <el-table-column prop="time" label="时间" width="72" />
              <el-table-column prop="provider" label="来源" width="80" />
              <el-table-column prop="plate_name" label="板块" width="120" show-overflow-tooltip />
              <el-table-column prop="stock_reason" label="标的理由" min-width="180" show-overflow-tooltip />
              <el-table-column prop="plate_reason" label="板块理由" min-width="180" show-overflow-tooltip />
            </el-table>
          </section>
        </aside>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'

import MyHeader from './MyHeader.vue'
import { dailyScreeningApi } from '@/api/dailyScreeningApi.js'
import {
  buildDailyScreeningQueryPayload,
  buildDailyScreeningWorkbenchState,
  formatDailyScreeningConditionLabel,
  normalizeDailyScreeningDetail,
  normalizeDailyScreeningFilterCatalog,
  normalizeDailyScreeningResultRows,
  normalizeDailyScreeningScopeItems,
  readDailyScreeningPayload,
  toggleDailyScreeningSelection,
} from './dailyScreeningPage.mjs'

const loadingScopes = ref(false)
const loadingFilters = ref(false)
const queryLoading = ref(false)
const detailLoading = ref(false)
const pageError = ref('')

const scopeItems = ref([])
const selectedScopeId = ref('')
const scopeSummary = ref({})
const filterCatalog = ref(normalizeDailyScreeningFilterCatalog({}))
const resultRows = ref([])
const selectedCode = ref('')
const detail = ref(normalizeDailyScreeningDetail({}))

const conditionKeys = ref([])
const metricFilters = reactive({
  higherMultipleLte: null,
  segmentMultipleLte: null,
  biGainPercentLte: null,
})

const pageLoading = computed(() => loadingScopes.value || loadingFilters.value)
const detailSnapshot = computed(() => detail.value?.snapshot || null)
const filterGroups = computed(() => filterCatalog.value.groups || {})
const selectedScopeLabel = computed(() => {
  const matched = scopeItems.value.find((item) => item.scopeId === selectedScopeId.value)
  return matched?.label || selectedScopeId.value || '-'
})
const activeConditionCount = computed(() => {
  const metricCount = Object.values(metricFilters).filter((value) => value != null).length
  return conditionKeys.value.length + metricCount
})
const currentExpression = computed(() => {
  if (!conditionKeys.value.length && activeConditionCount.value === 0) {
    return '默认展示基础池 A ∪ B'
  }
  const labels = conditionKeys.value.map((item) => formatDailyScreeningConditionLabel(item))
  const metricLabels = []
  if (metricFilters.higherMultipleLte != null) metricLabels.push(`高级段倍数 <= ${metricFilters.higherMultipleLte}`)
  if (metricFilters.segmentMultipleLte != null) metricLabels.push(`段倍数 <= ${metricFilters.segmentMultipleLte}`)
  if (metricFilters.biGainPercentLte != null) metricLabels.push(`笔涨幅% <= ${metricFilters.biGainPercentLte}`)
  return [...labels, ...metricLabels].join(' ∩ ') || '默认展示基础池 A ∪ B'
})

const formatNumber = (value) => {
  if (value == null || value === '') return '-'
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric.toFixed(2) : '-'
}

const resetMetricFilters = () => {
  metricFilters.higherMultipleLte = null
  metricFilters.segmentMultipleLte = null
  metricFilters.biGainPercentLte = null
}

const applyStateDefaults = (latestScope = null) => {
  const state = buildDailyScreeningWorkbenchState(latestScope)
  if (!selectedScopeId.value) {
    selectedScopeId.value = state.scopeId
  }
  conditionKeys.value = [...state.conditionKeys]
  resetMetricFilters()
}

const loadScopes = async () => {
  loadingScopes.value = true
  try {
    const [scopesResponse, latestResponse] = await Promise.all([
      dailyScreeningApi.getScopes(),
      dailyScreeningApi.getLatestScope(),
    ])
    scopeItems.value = normalizeDailyScreeningScopeItems(
      readDailyScreeningPayload(scopesResponse),
    )
    const latestScope = readDailyScreeningPayload(latestResponse)
    if (!selectedScopeId.value) {
      selectedScopeId.value = String(
        latestScope?.scope || latestScope?.run_id || '',
      ).trim()
    }
    if (!conditionKeys.value.length) {
      applyStateDefaults(latestScope)
    }
    pageError.value = ''
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '加载 scopes 失败'
  } finally {
    loadingScopes.value = false
  }
}

const loadScopeSummary = async () => {
  if (!selectedScopeId.value) {
    scopeSummary.value = {}
    return
  }
  const payload = readDailyScreeningPayload(
    await dailyScreeningApi.getScopeSummary(selectedScopeId.value),
  )
  scopeSummary.value = payload || {}
}

const loadFilterCatalog = async () => {
  if (!selectedScopeId.value) {
    filterCatalog.value = normalizeDailyScreeningFilterCatalog({})
    return
  }
  loadingFilters.value = true
  try {
    const payload = readDailyScreeningPayload(
      await dailyScreeningApi.getFilters(selectedScopeId.value),
    )
    filterCatalog.value = normalizeDailyScreeningFilterCatalog(payload)
  } finally {
    loadingFilters.value = false
  }
}

const queryRows = async () => {
  if (!selectedScopeId.value) {
    resultRows.value = []
    return
  }
  queryLoading.value = true
  try {
    const payload = readDailyScreeningPayload(
      await dailyScreeningApi.queryStocks(
        buildDailyScreeningQueryPayload({
          scopeId: selectedScopeId.value,
          conditionKeys: conditionKeys.value,
          metricFilters,
        }),
      ),
    )
    resultRows.value = normalizeDailyScreeningResultRows(payload?.rows)
    pageError.value = ''
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '查询交集结果失败'
  } finally {
    queryLoading.value = false
  }
}

const loadDetail = async (code) => {
  if (!selectedScopeId.value || !code) {
    detail.value = normalizeDailyScreeningDetail({})
    return
  }
  detailLoading.value = true
  try {
    const payload = readDailyScreeningPayload(
      await dailyScreeningApi.getStockDetail(selectedScopeId.value, code),
    )
    detail.value = normalizeDailyScreeningDetail(payload)
    pageError.value = ''
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '加载标的详情失败'
  } finally {
    detailLoading.value = false
  }
}

const refreshCurrentScope = async () => {
  if (!selectedScopeId.value) return
  try {
    await Promise.all([loadScopeSummary(), loadFilterCatalog()])
    await queryRows()
    if (selectedCode.value) {
      await loadDetail(selectedCode.value)
    }
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '刷新 scope 失败'
  }
}

const toggleCondition = (key) => {
  conditionKeys.value = toggleDailyScreeningSelection(conditionKeys.value, key)
}

const resetFilters = async () => {
  conditionKeys.value = []
  resetMetricFilters()
  await queryRows()
}

const handleRowClick = async (row) => {
  selectedCode.value = row.code
  await loadDetail(row.code)
}

watch(selectedScopeId, async (scopeId) => {
  if (!scopeId) return
  selectedCode.value = ''
  detail.value = normalizeDailyScreeningDetail({})
  conditionKeys.value = []
  resetMetricFilters()
  await refreshCurrentScope()
})

onMounted(async () => {
  await loadScopes()
  if (selectedScopeId.value) {
    await refreshCurrentScope()
  }
})
</script>

<style scoped>
.daily-screening-body {
  padding: 24px;
}

.daily-screening-grid {
  display: grid;
  grid-template-columns: 360px minmax(520px, 1fr) 420px;
  gap: 16px;
  align-items: start;
}

.daily-filter-panel,
.daily-results-panel,
.daily-detail-stack {
  min-height: 240px;
}

.daily-detail-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.daily-chip-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.daily-metric-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
}

.daily-field-control {
  width: 100%;
}

.daily-filter-actions {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 16px;
}

.daily-action-buttons {
  display: flex;
  gap: 8px;
}

.daily-expression {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.daily-detail-summary {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.daily-detail-title {
  font-size: 20px;
  font-weight: 600;
}

.daily-detail-meta {
  display: flex;
  gap: 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.daily-condition-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.daily-empty,
.daily-empty-inline {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

@media (max-width: 1480px) {
  .daily-screening-grid {
    grid-template-columns: 320px minmax(420px, 1fr);
  }

  .daily-detail-stack {
    grid-column: 1 / -1;
  }
}

@media (max-width: 960px) {
  .daily-screening-body {
    padding: 16px;
  }

  .daily-screening-grid {
    grid-template-columns: 1fr;
  }
}
</style>
