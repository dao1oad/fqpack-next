<template>
  <WorkbenchPage class="clx-screening-page">
    <MyHeader />
    <div class="workbench-body clx-screening-body">
      <header class="clx-screening-header">
        <div class="clx-screening-title-row">
          <div class="workbench-title-group">
            <div class="workbench-page-title">CLX日线选股</div>
            <div class="workbench-page-meta">
              <span>{{ activeScope?.tradeDate || '暂无交易日' }}</span>
              <span>{{ activeScope?.profileId || 'profile 未知' }}</span>
              <span>{{ activeScope?.algorithmVersion || 'algorithm 未知' }}</span>
              <span>{{ activeScope?.dataVersion || 'data 未知' }}</span>
            </div>
          </div>
          <div class="clx-screening-actions">
            <el-select
              v-model="selectedScopeId"
              class="clx-scope-select"
              placeholder="选择批次"
              @change="handleScopeChange"
            >
              <el-option
                v-for="scope in scopes"
                :key="scope.scopeId"
                :label="formatScopeOption(scope)"
                :value="scope.scopeId"
              />
            </el-select>
            <el-button :loading="loading.bootstrap || loading.scope" @click="refreshAll">刷新</el-button>
            <el-button type="primary" :disabled="!selectedRow" @click="openSelectedInKline">
              Kline Slim
            </el-button>
          </div>
        </div>

        <div v-if="activeScope" class="clx-scope-state-row">
          <StatusChip :variant="activeScopeStatus.variant">
            {{ activeScopeStatus.label }}
          </StatusChip>
          <StatusChip :variant="stockPartitionStatus.variant">{{ stockPartitionStatus.label }}</StatusChip>
          <StatusChip :variant="etfPartitionStatus.variant">{{ etfPartitionStatus.label }}</StatusChip>
          <StatusChip variant="muted">switch_opt <strong>{{ activeScope.switchOpt ?? '-' }}</strong></StatusChip>
          <StatusChip variant="muted">数据截至 <strong>{{ activeScope.dataAsOf || '-' }}</strong></StatusChip>
        </div>

        <el-alert
          v-if="activeScope?.isPartial"
          class="clx-partial-alert"
          :type="activeScope.isFailed ? 'error' : 'warning'"
          :closable="false"
          show-icon
          :title="activeScope.isFailed ? activeScopeStatus.detail : '当前是部分结果，仅包含已完成分区，不代表股票与 ETF 的正式完整发布。'"
        />
        <el-alert
          v-if="pageError"
          class="clx-partial-alert"
          type="error"
          :closable="false"
          show-icon
          :title="pageError"
        />

        <div
          v-if="latestObservedScope?.isPartial && latestObservedScope.scopeId !== activeScope?.scopeId"
          class="clx-latest-progress"
        >
          <span>最新运行 {{ latestObservedScope.tradeDate }}</span>
          <StatusChip :variant="latestStockStatus.variant">{{ latestStockStatus.label }}</StatusChip>
          <StatusChip :variant="latestEtfStatus.variant">{{ latestEtfStatus.label }}</StatusChip>
          <el-button size="small" @click="selectObservedPartial">查看部分结果</el-button>
        </div>

        <div class="clx-kpi-row">
          <button type="button" class="clx-kpi" @click="resetFilters">
            <span>候选</span><strong>{{ summary.candidateCount }}</strong>
          </button>
          <button type="button" class="clx-kpi" @click="filters.assetTypes = ['stock']">
            <span>股票命中</span><strong>{{ summary.stockHitCount }}</strong>
          </button>
          <button type="button" class="clx-kpi" @click="filters.assetTypes = ['etf']">
            <span>ETF命中</span><strong>{{ summary.etfHitCount }}</strong>
          </button>
          <div class="clx-kpi"><span>全量</span><strong>{{ summary.universeCount }}</strong></div>
          <div class="clx-kpi"><span>已评估</span><strong>{{ summary.evaluatedCount }}</strong></div>
          <div class="clx-kpi"><span>错误</span><strong>{{ summary.errorCount }}</strong></div>
          <div class="clx-kpi"><span>平均模型数</span><strong>{{ formatDecimal(summary.averageModelCount) }}</strong></div>
          <div class="clx-kpi"><span>最高共振</span><strong>{{ summary.maxModelCount }}</strong></div>
          <button type="button" class="clx-kpi" @click="filters.lineFlags.above_ma250 = 'yes'">
            <span>站上MA250</span><strong>{{ summary.aboveMa250Count }}</strong>
          </button>
        </div>
      </header>

      <div class="clx-screening-layout">
        <aside class="clx-filter-panel">
          <div class="clx-panel-heading">
            <strong>筛选</strong>
            <el-button link type="primary" @click="resetFilters">重置</el-button>
          </div>
          <el-input v-model="filters.q" clearable placeholder="代码或名称" />

          <section class="clx-filter-section">
            <span class="clx-filter-label">资产</span>
            <el-checkbox-group v-model="filters.assetTypes">
              <el-checkbox value="stock">股票</el-checkbox>
              <el-checkbox value="etf">ETF</el-checkbox>
            </el-checkbox-group>
          </section>

          <section class="clx-filter-section">
            <span class="clx-filter-label">最少模型数</span>
            <el-input-number v-model="filters.minModelCount" :min="1" :max="18" controls-position="right" />
          </section>

          <section class="clx-filter-section">
            <span class="clx-filter-label">模型</span>
            <el-input v-model="modelSearch" clearable size="small" placeholder="搜索 S0000-S0017" />
            <el-checkbox-group v-model="filters.modelKeys" class="clx-model-filter-list">
              <el-checkbox
                v-for="model in filteredCatalogModels"
                :key="model.key"
                :value="model.key"
                :title="model.description"
              >
                {{ model.key }} {{ model.label !== model.key ? model.label : '' }}
              </el-checkbox>
            </el-checkbox-group>
          </section>

          <section class="clx-filter-section">
            <span class="clx-filter-label">条件</span>
            <el-select v-model="filters.conditionKeys" multiple collapse-tags clearable placeholder="全部条件">
              <el-option
                v-for="condition in catalog.conditions"
                :key="condition.key"
                :label="condition.label"
                :value="condition.key"
              />
            </el-select>
          </section>

          <section class="clx-filter-section">
            <span class="clx-filter-label">方向</span>
            <el-checkbox-group v-model="filters.directions">
              <el-checkbox value="buy">买入</el-checkbox>
              <el-checkbox value="sell">卖出</el-checkbox>
            </el-checkbox-group>
          </section>

          <section class="clx-filter-section clx-line-filters">
            <span class="clx-filter-label">线关系</span>
            <label>缠论连线</label>
            <el-select v-model="filters.lineFlags.above_chanlun_line" clearable placeholder="全部">
              <el-option label="站上" value="yes" />
              <el-option label="下方" value="no" />
              <el-option label="未知" value="unknown" />
            </el-select>
            <label>MA250</label>
            <el-select v-model="filters.lineFlags.above_ma250" clearable placeholder="全部">
              <el-option label="站上" value="yes" />
              <el-option label="下方" value="no" />
              <el-option label="未知" value="unknown" />
            </el-select>
            <label>模型参考线</label>
            <el-select v-model="filters.lineFlags.above_reference_line" clearable placeholder="全部">
              <el-option label="站上" value="yes" />
              <el-option label="下方" value="no" />
              <el-option label="未知" value="unknown" />
            </el-select>
          </section>
        </aside>

        <main class="clx-results-panel">
          <el-tabs v-model="activeTab" class="clx-main-tabs">
            <el-tab-pane label="结果" name="results">
              <div class="clx-results-toolbar">
                <div>
                  <strong>{{ queryResult.total }}</strong>
                  <span> 条服务端结果</span>
                </div>
                <StatusChip variant="muted">模型数 ↓ / 条件数 ↓ / symbol ↑</StatusChip>
              </div>
              <div class="clx-results-table-wrap" v-loading="loading.results">
                <el-table
                  :data="queryResult.rows"
                  row-key="symbol"
                  height="100%"
                  size="small"
                  highlight-current-row
                  :current-row-key="selectedRow?.symbol"
                  @row-click="selectRow"
                >
                  <el-table-column label="标的" width="132" fixed="left">
                    <template #default="{ row }">
                      <div class="clx-symbol-cell">
                        <strong>{{ row.code || row.symbol }}</strong>
                        <span>{{ row.name || '-' }}</span>
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column label="资产" width="64">
                    <template #default="{ row }">{{ formatAssetType(row.assetType) }}</template>
                  </el-table-column>
                  <el-table-column label="最新价" width="82" align="right">
                    <template #default="{ row }">{{ formatPrice(row.latestPrice) }}</template>
                  </el-table-column>
                  <el-table-column label="涨跌" width="78" align="right">
                    <template #default="{ row }">
                      <span :class="getChangeClass(row.changePct)">{{ formatPercent(row.changePct) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="模型" width="72" align="center" prop="distinctModelCount" />
                  <el-table-column label="条件" width="72" align="center" prop="distinctConditionCount" />
                  <el-table-column label="命中模型" min-width="210">
                    <template #default="{ row }">
                      <div class="clx-model-chips">
                        <span v-for="key in row.modelKeys.slice(0, 5)" :key="key" class="clx-model-chip">{{ key }}</span>
                        <span v-if="row.modelKeys.length > 5" class="clx-model-chip clx-model-chip--more">+{{ row.modelKeys.length - 5 }}</span>
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column label="缠论" width="70">
                    <template #default="{ row }">{{ formatLineState(row.aboveChanlunLine.state) }}</template>
                  </el-table-column>
                  <el-table-column label="MA250" width="70">
                    <template #default="{ row }">{{ formatLineState(row.aboveMa250.state) }}</template>
                  </el-table-column>
                  <el-table-column label="最近触发" min-width="112" prop="latestTrigger" />
                  <el-table-column label="数据" width="74">
                    <template #default="{ row }">{{ row.dataQuality || '-' }}</template>
                  </el-table-column>
                </el-table>
              </div>
              <div class="clx-pagination-row">
                <el-button :disabled="cursorStack.length === 0" @click="previousPage">上一页</el-button>
                <span>第 {{ cursorStack.length + 1 }} 页</span>
                <el-button :disabled="!queryResult.nextCursor" @click="nextPage">下一页</el-button>
              </div>
            </el-tab-pane>

            <el-tab-pane v-if="activeScope?.isFinal" label="统计" name="statistics">
              <div class="clx-statistics-grid" v-loading="loading.statistics">
                <section class="clx-stat-section">
                  <h3>资产分组</h3>
                  <div class="clx-stat-list">
                    <div v-for="(value, key) in statistics.byAssetType" :key="key" class="clx-stat-row">
                      <strong>{{ formatAssetType(key) }}</strong>
                      <span>{{ formatStatValue(value) }}</span>
                    </div>
                  </div>
                </section>
                <section class="clx-stat-section">
                  <h3>模型命中</h3>
                  <div class="clx-stat-list clx-stat-list--scroll">
                    <div v-for="item in statistics.byModel" :key="statKey(item)" class="clx-stat-row">
                      <strong>{{ statLabel(item) }}</strong>
                      <span>{{ statCount(item) }}</span>
                    </div>
                  </div>
                </section>
                <section class="clx-stat-section">
                  <h3>条件分布</h3>
                  <div class="clx-stat-list clx-stat-list--scroll">
                    <div v-for="item in statistics.byCondition" :key="statKey(item)" class="clx-stat-row">
                      <strong>{{ statLabel(item) }}</strong>
                      <span>{{ statCount(item) }}</span>
                    </div>
                  </div>
                </section>
                <section class="clx-stat-section">
                  <h3>模型共振</h3>
                  <div class="clx-stat-list clx-stat-list--scroll">
                    <div v-for="item in statistics.resonance" :key="statKey(item)" class="clx-stat-row">
                      <strong>{{ statLabel(item) }}</strong>
                      <span>{{ statCount(item) }}</span>
                    </div>
                  </div>
                </section>
                <section class="clx-stat-section">
                  <h3>模型共现</h3>
                  <div class="clx-stat-list clx-stat-list--scroll">
                    <div v-for="item in statistics.modelCooccurrence" :key="item.modelKeys.join(':')" class="clx-stat-row">
                      <strong>{{ item.modelKeys.join(' + ') || '-' }}</strong>
                      <span>{{ item.symbolCount }}</span>
                    </div>
                  </div>
                </section>
                <section class="clx-stat-section">
                  <h3>线关系</h3>
                  <div class="clx-stat-list clx-stat-list--scroll">
                    <div v-for="item in statistics.lineRelations" :key="item.key" class="clx-stat-row">
                      <strong>{{ formatLineRelationLabel(item.key) }}</strong>
                      <span>上 {{ item.yesCount }} / 下 {{ item.noCount }} / 未知 {{ item.unknownCount }}</span>
                    </div>
                  </div>
                </section>
              </div>
            </el-tab-pane>

            <el-tab-pane label="批次" name="batch">
              <div v-if="activeScope" class="clx-batch-grid">
                <section v-for="assetType in ['stock', 'etf']" :key="assetType" class="clx-partition-section">
                  <div class="clx-partition-head">
                    <strong>{{ formatAssetType(assetType) }}</strong>
                    <StatusChip :variant="getPartitionMeta(assetType).variant">
                      {{ getPartitionMeta(assetType).label }}
                    </StatusChip>
                  </div>
                  <dl>
                    <dt>selection_key</dt><dd>{{ activeScope.partitions[assetType].selectionKey || '-' }}</dd>
                    <dt>attempt</dt><dd>{{ activeScope.partitions[assetType].attemptNo || '-' }}</dd>
                    <dt>partition_id</dt><dd>{{ activeScope.partitions[assetType].partitionId || '-' }}</dd>
                    <dt>universe</dt><dd>{{ activeScope.partitions[assetType].universeCount }}</dd>
                    <dt>evaluated</dt><dd>{{ activeScope.partitions[assetType].processedCount }}</dd>
                    <dt>hits</dt><dd>{{ activeScope.partitions[assetType].hitCount }}</dd>
                    <dt>errors</dt><dd>{{ activeScope.partitions[assetType].errorCount }}</dd>
                    <dt>snapshot</dt><dd>{{ shortHash(activeScope.partitions[assetType].snapshotHash) }}</dd>
                    <dt>content</dt><dd>{{ shortHash(activeScope.partitions[assetType].contentHash) }}</dd>
                  </dl>
                  <p v-if="activeScope.partitions[assetType].message" class="clx-partition-error">
                    {{ activeScope.partitions[assetType].message }}
                  </p>
                </section>
              </div>
            </el-tab-pane>
          </el-tabs>
        </main>

        <aside class="clx-detail-panel" v-loading="loading.detail">
          <div class="clx-panel-heading">
            <strong>信号详情</strong>
            <el-button v-if="selectedRow" link type="primary" @click="openSelectedInKline">Kline</el-button>
          </div>
          <div v-if="detail" class="clx-detail-content">
            <div class="clx-detail-symbol">
              <strong>{{ detail.snapshot.code || detail.snapshot.symbol }}</strong>
              <span>{{ detail.snapshot.name || '-' }}</span>
            </div>
            <div class="clx-detail-summary">
              <StatusChip variant="info">{{ detail.snapshot.distinctModelCount }} 模型</StatusChip>
              <StatusChip variant="muted">{{ detail.snapshot.distinctConditionCount }} 条件</StatusChip>
            </div>
            <div class="clx-membership-list">
              <article v-for="membership in detail.memberships" :key="membershipKey(membership)" class="clx-membership">
                <header>
                  <strong>{{ membership.modelKey }}</strong>
                  <span>{{ membership.triggerDate || '-' }}</span>
                </header>
                <div class="clx-membership-condition">
                  {{ membership.conditionLabel || membership.conditionKey || '条件未标注' }}
                </div>
                <dl>
                  <dt>方向</dt><dd>{{ membership.direction || '-' }}</dd>
                  <dt>raw</dt><dd>{{ membership.signalValueRaw ?? '-' }}</dd>
                  <dt>entrypoint</dt><dd>{{ formatEntrypoint(membership.primaryEntrypoint) }}</dd>
                </dl>
                <StatusChip v-if="membership.ambiguous" variant="warning">双义 / 待判定</StatusChip>
                <div v-if="membership.conditionEvidence.length" class="clx-evidence-list">
                  <div v-for="(evidence, index) in membership.conditionEvidence" :key="index">
                    <strong>{{ evidenceLabel(evidence) }}</strong>
                    <span>{{ evidenceValue(evidence) }}</span>
                  </div>
                </div>
              </article>
            </div>
          </div>
          <div v-else class="clx-detail-empty">从结果中选择标的</div>
        </aside>
      </div>
    </div>
  </WorkbenchPage>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { clxDailySelectionApi } from '@/api/clxDailySelectionApi.js'
import MyHeader from '@/views/MyHeader.vue'
import StatusChip from '@/components/workbench/StatusChip.vue'
import WorkbenchPage from '@/components/workbench/WorkbenchPage.vue'
import {
  buildClxSelectionQueryPayload,
  buildClxSelectionRouteQuery,
  createClxRequestChannel,
  formatClxNumber,
  getClxPartitionStatusMeta,
  getClxScopeStatusMeta,
  normalizeClxCatalog,
  normalizeClxDetail,
  normalizeClxScope,
  normalizeClxScopes,
  normalizeClxSelectionQuery,
  normalizeClxStatistics,
  normalizeClxSummary,
  parseClxSelectionRouteQuery,
  pickDefaultClxScope,
} from './clxDailySelection.mjs'

const route = useRoute()
const router = useRouter()

const emptySummary = () => normalizeClxSummary({})
const emptyQueryResult = () => normalizeClxSelectionQuery({})
const emptyStatistics = () => normalizeClxStatistics({})

const scopes = ref([])
const selectedScopeId = ref('')
const catalog = ref(normalizeClxCatalog({}))
const summary = ref(emptySummary())
const statistics = ref(emptyStatistics())
const queryResult = ref(emptyQueryResult())
const detail = ref(null)
const selectedRow = ref(null)
const activeTab = ref('results')
const modelSearch = ref('')
const cursorStack = ref([])
const currentCursor = ref('')
const pageError = ref('')
const loading = reactive({ bootstrap: false, scope: false, results: false, statistics: false, detail: false })
const filters = reactive({
  q: '',
  assetTypes: [],
  modelKeys: [],
  conditionKeys: [],
  directions: [],
  minModelCount: 1,
  lineFlags: {
    above_chanlun_line: '',
    above_ma250: '',
    above_reference_line: '',
  },
})

let queryTimer = 0
let routeSyncing = false
const bootstrapRequests = createClxRequestChannel()
const scopeRequests = createClxRequestChannel()
const resultRequests = createClxRequestChannel()
const detailRequests = createClxRequestChannel()

const activeScope = computed(() => scopes.value.find((item) => item.scopeId === selectedScopeId.value) || null)
const latestObservedScope = computed(() => scopes.value[0] || null)
const activeScopeStatus = computed(() => getClxScopeStatusMeta(activeScope.value || {}))
const stockPartitionStatus = computed(() => getClxPartitionStatusMeta(activeScope.value?.partitions?.stock, 'stock'))
const etfPartitionStatus = computed(() => getClxPartitionStatusMeta(activeScope.value?.partitions?.etf, 'etf'))
const latestStockStatus = computed(() => getClxPartitionStatusMeta(latestObservedScope.value?.partitions?.stock, 'stock'))
const latestEtfStatus = computed(() => getClxPartitionStatusMeta(latestObservedScope.value?.partitions?.etf, 'etf'))
const filteredCatalogModels = computed(() => {
  const keyword = modelSearch.value.trim().toLowerCase()
  if (!keyword) return catalog.value.models
  return catalog.value.models.filter((item) => `${item.key} ${item.label}`.toLowerCase().includes(keyword))
})

const formatScopeOption = (scope) => `${scope.tradeDate || '-'} · ${scope.isFinal ? '完整' : scope.isFailed ? '失败' : '部分'} · ${scope.scopeId}`
const formatAssetType = (value) => String(value || '').toLowerCase() === 'etf' ? 'ETF' : '股票'
const formatDecimal = (value) => formatClxNumber(value, { digits: 2 })
const formatPrice = (value) => formatClxNumber(value, { digits: 3 })
const formatPercent = (value) => formatClxNumber(value, { digits: 2, suffix: '%' })
const getChangeClass = (value) => Number(value) > 0 ? 'clx-change-up' : Number(value) < 0 ? 'clx-change-down' : ''
const formatLineState = (value) => value === 'yes' ? '站上' : value === 'no' ? '下方' : '未知'
const shortHash = (value) => String(value || '-').length > 16 ? `${String(value).slice(0, 12)}...` : String(value || '-')
const membershipKey = (item) => [item.modelKey, item.conditionKey, item.triggerDate, item.signalValueRaw].join(':')
const formatEntrypoint = (value) => value && typeof value === 'object' ? value.label || value.code || '-' : value || '-'
const evidenceLabel = (value) => value && typeof value === 'object' ? value.label || value.key || value.code || 'evidence' : 'evidence'
const evidenceValue = (value) => {
  if (!value || typeof value !== 'object') return String(value ?? '-')
  const resolved = value.value ?? value.actual ?? value.result ?? value.reference_value
  return resolved && typeof resolved === 'object' ? JSON.stringify(resolved) : String(resolved ?? '-')
}
const statKey = (item) => [item?.asset_type, item?.model_key, item?.condition_key, item?.key, item?.label].filter(Boolean).join(':') || JSON.stringify(item)
const statLabel = (item) => [item?.asset_type ? formatAssetType(item.asset_type) : '', item?.label || item?.model_key || item?.condition_key || item?.key || '-'].filter(Boolean).join(' ')
const statCount = (item) => Number(item?.hit_count ?? item?.count ?? item?.value ?? 0)
const formatStatValue = (value) => {
  if (value === null || value === undefined) return '-'
  if (typeof value !== 'object') return String(value)
  const hits = value.hit_symbol_count ?? value.hit_count ?? value.count ?? '-'
  const evaluated = value.evaluated_count ?? value.total ?? '-'
  return `${hits} / ${evaluated}`
}
const formatLineRelationLabel = (value) => ({
  above_chanlun_line: '缠论连线',
  above_ma250: 'MA250',
  above_reference_line: '模型参考线',
})[value] || value || '-'
const getPartitionMeta = (assetType) => getClxPartitionStatusMeta(activeScope.value?.partitions?.[assetType], assetType)

const applyRouteState = () => {
  const state = parseClxSelectionRouteQuery(route.query)
  filters.q = state.q
  filters.assetTypes = state.assetTypes
  filters.modelKeys = state.modelKeys
  filters.conditionKeys = state.conditionKeys
  filters.directions = state.directions
  filters.minModelCount = state.minModelCount
  return state
}

const syncRoute = async () => {
  routeSyncing = true
  try {
    await router.replace({
      path: '/clx-daily-screening',
      query: buildClxSelectionRouteQuery({
        scopeId: selectedScopeId.value,
        q: filters.q,
        assetTypes: filters.assetTypes,
        modelKeys: filters.modelKeys,
        conditionKeys: filters.conditionKeys,
        directions: filters.directions,
        minModelCount: filters.minModelCount,
        symbol: selectedRow.value?.symbol || '',
      }),
    })
  } finally {
    routeSyncing = false
  }
}

const buildQueryPayload = (scopeId = selectedScopeId.value) => buildClxSelectionQueryPayload({
  scopeId,
  q: filters.q,
  assetTypes: filters.assetTypes,
  modelKeys: filters.modelKeys,
  conditionKeys: filters.conditionKeys,
  directions: filters.directions,
  minModelCount: filters.minModelCount,
  lineFlags: Object.fromEntries(Object.entries(filters.lineFlags).filter(([, value]) => value)),
  cursor: currentCursor.value,
})

const loadResults = async ({ syncUrl = true, scopeId = selectedScopeId.value, clearError = true } = {}) => {
  if (!scopeId) return
  const requestPayload = buildQueryPayload(scopeId)
  const requestKey = `${scopeId}|${JSON.stringify(requestPayload)}`
  const token = resultRequests.begin(requestKey)
  const isCurrent = () => resultRequests.isCurrent(token, requestKey) && selectedScopeId.value === scopeId
  loading.results = true
  if (clearError) pageError.value = ''
  try {
    const payload = await clxDailySelectionApi.queryBatchResults(
      scopeId,
      requestPayload,
      { signal: token.signal },
    )
    if (!isCurrent()) return
    queryResult.value = normalizeClxSelectionQuery(payload)
    if (selectedRow.value) {
      selectedRow.value = queryResult.value.rows.find((row) => (
        row.symbol === selectedRow.value.symbol && row.assetType === selectedRow.value.assetType
      )) || null
      if (!selectedRow.value) detail.value = null
    }
    if (syncUrl) await syncRoute()
  } catch (error) {
    if (!isCurrent()) return
    queryResult.value = emptyQueryResult()
    pageError.value = error?.response?.data?.message || 'CLX 结果加载失败'
  } finally {
    if (isCurrent()) loading.results = false
  }
}

const loadScopeData = async () => {
  const scopeId = selectedScopeId.value
  if (!scopeId) return
  const token = scopeRequests.begin(scopeId)
  const isCurrent = () => scopeRequests.isCurrent(token, scopeId) && selectedScopeId.value === scopeId
  resultRequests.abort()
  detailRequests.abort()
  loading.scope = true
  loading.results = false
  loading.detail = false
  pageError.value = ''
  selectedRow.value = null
  detail.value = null
  summary.value = emptySummary()
  statistics.value = emptyStatistics()
  queryResult.value = emptyQueryResult()
  currentCursor.value = ''
  cursorStack.value = []
  const scope = scopes.value.find((item) => item.scopeId === scopeId)
  const scopeIsFinal = Boolean(scope?.isFinal)
  if (!scopeIsFinal && activeTab.value === 'statistics') activeTab.value = 'results'
  loading.statistics = scopeIsFinal

  const summaryTask = clxDailySelectionApi.getBatchSummary(scopeId, { signal: token.signal })
    .then((payload) => {
      if (isCurrent()) summary.value = normalizeClxSummary(payload)
    })
    .catch((error) => {
      if (!isCurrent()) return
      summary.value = emptySummary()
      pageError.value = error?.response?.data?.message || 'CLX 批次摘要加载失败'
    })

  const statisticsTask = scopeIsFinal
    ? clxDailySelectionApi.getBatchStatistics(scopeId, { signal: token.signal })
      .then((payload) => {
        if (isCurrent()) statistics.value = normalizeClxStatistics(payload)
      })
      .catch((error) => {
        if (!isCurrent()) return
        statistics.value = emptyStatistics()
        pageError.value = error?.response?.data?.message || 'CLX 统计加载失败'
      })
      .finally(() => {
        if (isCurrent()) loading.statistics = false
      })
    : Promise.resolve()

  try {
    await Promise.allSettled([
      summaryTask,
      statisticsTask,
      loadResults({ scopeId, clearError: false }),
    ])
  } finally {
    if (isCurrent()) loading.scope = false
  }
}

const loadBootstrap = async () => {
  const token = bootstrapRequests.begin('bootstrap')
  const isCurrent = () => bootstrapRequests.isCurrent(token, 'bootstrap')
  scopeRequests.abort()
  resultRequests.abort()
  detailRequests.abort()
  loading.bootstrap = true
  loading.scope = false
  loading.results = false
  loading.detail = false
  pageError.value = ''
  const initialRoute = applyRouteState()
  try {
    const [catalogPayload, batchesPayload, latestFinalPayload] = await Promise.all([
      clxDailySelectionApi.getModelCatalog({ signal: token.signal }),
      clxDailySelectionApi.getBatches({ includePartial: true }, { signal: token.signal }),
      clxDailySelectionApi.getLatestBatch({ includePartial: false }, { signal: token.signal }).catch(() => null),
    ])
    if (!isCurrent()) return
    catalog.value = normalizeClxCatalog(catalogPayload)
    scopes.value = normalizeClxScopes(batchesPayload)
    const requested = scopes.value.find((item) => item.scopeId === initialRoute.scopeId)
    const finalScope = latestFinalPayload ? pickDefaultClxScope(latestFinalPayload) : null
    selectedScopeId.value = requested?.scopeId || finalScope?.scopeId || scopes.value.find((item) => item.isFinal)?.scopeId || ''
    await loadScopeData()
    if (!isCurrent()) return
    if (initialRoute.symbol) {
      const row = queryResult.value.rows.find((item) => item.symbol === initialRoute.symbol || item.code === initialRoute.symbol)
      if (row) await selectRow(row)
    }
  } catch (error) {
    if (!isCurrent()) return
    pageError.value = error?.response?.data?.message || 'CLX 工作台初始化失败'
  } finally {
    if (isCurrent()) loading.bootstrap = false
  }
}

const refreshAll = () => loadBootstrap()
const handleScopeChange = () => loadScopeData()
const selectObservedPartial = async () => {
  if (!latestObservedScope.value) return
  selectedScopeId.value = latestObservedScope.value.scopeId
  await loadScopeData()
}
const resetFilters = () => {
  filters.q = ''
  filters.assetTypes = []
  filters.modelKeys = []
  filters.conditionKeys = []
  filters.directions = []
  filters.minModelCount = 1
  Object.keys(filters.lineFlags).forEach((key) => { filters.lineFlags[key] = '' })
}
const selectRow = async (row) => {
  const scopeId = selectedScopeId.value
  const assetType = row.assetType || 'stock'
  const symbol = row.symbol
  const detailKey = [scopeId, assetType, symbol].join('|')
  const token = detailRequests.begin(detailKey)
  const isCurrent = () => (
    detailRequests.isCurrent(token, detailKey) &&
    selectedScopeId.value === scopeId &&
    selectedRow.value?.symbol === symbol &&
    (selectedRow.value?.assetType || 'stock') === assetType
  )
  selectedRow.value = row
  detail.value = null
  loading.detail = true
  try {
    const payload = await clxDailySelectionApi.getBatchResultDetail(
      scopeId,
      assetType,
      symbol,
      { signal: token.signal },
    )
    if (!isCurrent()) return
    detail.value = normalizeClxDetail(payload)
    await syncRoute()
  } catch (error) {
    if (!isCurrent()) return
    pageError.value = error?.response?.data?.message || 'CLX 标的详情加载失败'
  } finally {
    if (isCurrent()) loading.detail = false
  }
}
const openSelectedInKline = () => {
  if (!selectedRow.value) return
  router.push({
    path: '/kline-slim',
    query: {
      symbol: selectedRow.value.symbol,
      period: '1d',
      clxScope: selectedScopeId.value,
      clxAssetType: selectedRow.value.assetType,
      clxModels: filters.modelKeys.join(','),
      clxConditions: filters.conditionKeys.join(','),
      clxWorkbench: '1',
    },
  })
}
const nextPage = async () => {
  if (!queryResult.value.nextCursor) return
  cursorStack.value.push(currentCursor.value)
  currentCursor.value = queryResult.value.nextCursor
  await loadResults({ syncUrl: false })
}
const previousPage = async () => {
  if (!cursorStack.value.length) return
  currentCursor.value = cursorStack.value.pop() || ''
  await loadResults({ syncUrl: false })
}

watch(
  () => [
    filters.q,
    filters.assetTypes.join(','),
    filters.modelKeys.join(','),
    filters.conditionKeys.join(','),
    filters.directions.join(','),
    filters.minModelCount,
    ...Object.values(filters.lineFlags),
  ],
  () => {
    if (loading.bootstrap || loading.scope || !selectedScopeId.value) return
    window.clearTimeout(queryTimer)
    queryTimer = window.setTimeout(() => {
      currentCursor.value = ''
      cursorStack.value = []
      loadResults()
    }, 220)
  },
)

watch(() => route.fullPath, () => {
  if (routeSyncing || route.path !== '/clx-daily-screening') return
  const routeState = applyRouteState()
  if (routeState.scopeId && routeState.scopeId !== selectedScopeId.value) {
    selectedScopeId.value = routeState.scopeId
    loadScopeData()
  }
})

onMounted(loadBootstrap)
onBeforeUnmount(() => {
  window.clearTimeout(queryTimer)
  bootstrapRequests.abort()
  scopeRequests.abort()
  resultRequests.abort()
  detailRequests.abort()
})
</script>

<style scoped>
.clx-screening-page {
  background: #eef1f5;
  color: #172033;
}

.clx-screening-body {
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 0;
}

.clx-screening-header {
  flex: 0 0 auto;
  padding: 12px 16px 10px;
  border-bottom: 1px solid #cfd6df;
  background: #fff;
}

.clx-screening-title-row,
.clx-scope-state-row,
.clx-latest-progress,
.clx-kpi-row,
.clx-screening-actions,
.clx-results-toolbar,
.clx-pagination-row,
.clx-panel-heading,
.clx-partition-head,
.clx-detail-summary {
  display: flex;
  align-items: center;
}

.clx-screening-title-row {
  justify-content: space-between;
  gap: 16px;
}

.clx-screening-actions,
.clx-scope-state-row,
.clx-latest-progress,
.clx-detail-summary {
  gap: 8px;
}

.clx-scope-select {
  width: 320px;
}

.clx-scope-state-row {
  flex-wrap: wrap;
  margin-top: 10px;
}

.clx-partial-alert {
  margin-top: 8px;
}

.clx-latest-progress {
  margin-top: 8px;
  padding: 6px 10px;
  border-left: 3px solid #d97706;
  background: #fff7ed;
  font-size: 12px;
}

.clx-kpi-row {
  display: grid;
  grid-template-columns: repeat(8, minmax(92px, 1fr));
  gap: 1px;
  margin-top: 10px;
  border: 1px solid #d7dde6;
  background: #d7dde6;
}

.clx-kpi {
  min-width: 0;
  padding: 8px 10px;
  border: 0;
  border-radius: 0;
  background: #fff;
  color: #4b5563;
  text-align: left;
}

button.clx-kpi {
  cursor: pointer;
}

button.clx-kpi:hover {
  background: #eff6ff;
}

.clx-kpi span,
.clx-kpi strong {
  display: block;
}

.clx-kpi span {
  font-size: 11px;
}

.clx-kpi strong {
  margin-top: 3px;
  color: #111827;
  font-size: 18px;
}

.clx-screening-layout {
  display: grid;
  grid-template-columns: 252px minmax(560px, 1fr) 352px;
  flex: 1;
  min-height: 0;
}

.clx-filter-panel,
.clx-results-panel,
.clx-detail-panel {
  min-width: 0;
  min-height: 0;
  background: #fff;
}

.clx-filter-panel,
.clx-detail-panel {
  overflow-y: auto;
  padding: 12px;
}

.clx-filter-panel {
  border-right: 1px solid #d7dde6;
}

.clx-detail-panel {
  border-left: 1px solid #d7dde6;
}

.clx-panel-heading {
  justify-content: space-between;
  min-height: 32px;
  margin-bottom: 10px;
}

.clx-filter-section {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid #e5e7eb;
}

.clx-filter-label {
  color: #374151;
  font-size: 12px;
  font-weight: 700;
}

.clx-model-filter-list {
  display: flex;
  flex-direction: column;
  max-height: 226px;
  overflow-y: auto;
}

.clx-model-filter-list :deep(.el-checkbox) {
  height: 28px;
  margin-right: 0;
}

.clx-line-filters label {
  color: #6b7280;
  font-size: 11px;
}

.clx-results-panel {
  overflow: hidden;
}

.clx-main-tabs {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.clx-main-tabs :deep(.el-tabs__header) {
  flex: 0 0 auto;
  margin: 0;
  padding: 0 14px;
  border-bottom: 1px solid #d7dde6;
}

.clx-main-tabs :deep(.el-tabs__content),
.clx-main-tabs :deep(.el-tab-pane) {
  flex: 1;
  min-height: 0;
  height: 100%;
}

.clx-main-tabs :deep(.el-tab-pane) {
  display: flex;
  flex-direction: column;
}

.clx-results-toolbar,
.clx-pagination-row {
  flex: 0 0 auto;
  justify-content: space-between;
  min-height: 44px;
  padding: 0 14px;
  border-bottom: 1px solid #e5e7eb;
}

.clx-results-table-wrap {
  flex: 1;
  min-height: 0;
}

.clx-pagination-row {
  justify-content: flex-end;
  gap: 12px;
  border-top: 1px solid #e5e7eb;
  border-bottom: 0;
  font-size: 12px;
}

.clx-symbol-cell {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.clx-symbol-cell span {
  overflow: hidden;
  color: #6b7280;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.clx-model-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.clx-model-chip {
  padding: 1px 5px;
  border: 1px solid #bfdbfe;
  background: #eff6ff;
  color: #1d4ed8;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 10px;
}

.clx-model-chip--more {
  border-color: #d1d5db;
  background: #f3f4f6;
  color: #4b5563;
}

.clx-change-up { color: #b91c1c; }
.clx-change-down { color: #047857; }

.clx-statistics-grid,
.clx-batch-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0;
  height: 100%;
  overflow: auto;
}

.clx-stat-section,
.clx-partition-section {
  min-height: 0;
  padding: 16px;
  border-right: 1px solid #e5e7eb;
  border-bottom: 1px solid #e5e7eb;
}

.clx-stat-section h3 {
  margin: 0 0 12px;
  font-size: 14px;
}

.clx-stat-list--scroll {
  max-height: 260px;
  overflow-y: auto;
}

.clx-stat-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 7px 0;
  border-bottom: 1px solid #f0f2f5;
  font-size: 12px;
}

.clx-partition-head {
  justify-content: space-between;
}

.clx-partition-section dl,
.clx-membership dl {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 7px 10px;
  margin: 14px 0 0;
  font-size: 12px;
}

.clx-partition-section dt,
.clx-membership dt {
  color: #6b7280;
}

.clx-partition-section dd,
.clx-membership dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.clx-partition-error {
  color: #b91c1c;
  font-size: 12px;
}

.clx-detail-symbol {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 8px;
}

.clx-detail-symbol strong {
  font-size: 18px;
}

.clx-detail-symbol span {
  color: #6b7280;
}

.clx-membership-list {
  margin-top: 12px;
}

.clx-membership {
  padding: 12px 0;
  border-top: 1px solid #d7dde6;
}

.clx-membership header {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
}

.clx-membership-condition {
  margin-top: 6px;
  color: #1f2937;
  font-size: 13px;
  font-weight: 600;
}

.clx-evidence-list {
  margin-top: 8px;
  padding-left: 9px;
  border-left: 2px solid #0d9488;
}

.clx-evidence-list > div {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 3px 0;
  font-size: 11px;
}

.clx-detail-empty {
  padding: 24px 0;
  color: #6b7280;
  text-align: center;
}

@media (max-width: 1280px) {
  .clx-screening-layout {
    grid-template-columns: 226px minmax(520px, 1fr) 310px;
  }

  .clx-kpi-row {
    grid-template-columns: repeat(4, minmax(92px, 1fr));
  }
}
</style>
