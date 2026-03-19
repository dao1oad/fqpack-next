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
              <span>基础池由 CLS 各模型结果和热门 30/45/60/90 天结果先取并集形成</span>
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

          <article class="workbench-block daily-guide-block">
            <div class="workbench-panel__title">工作台说明</div>
            <ul class="daily-guide-list">
              <li v-for="line in workbenchGuideLines" :key="line">{{ line }}</li>
            </ul>
          </article>

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

          <article
            v-for="section in conditionSections"
            :key="section.key"
            class="workbench-block"
          >
            <div class="daily-section-header">
              <div class="workbench-panel__title">{{ section.title }}</div>
              <el-popover
                trigger="hover"
                placement="right"
                :width="360"
              >
                <template #reference>
                  <button
                    type="button"
                    class="daily-info-trigger"
                    :aria-label="`查看${section.title}说明`"
                  >
                    i
                  </button>
                </template>
                <div class="daily-help-card">
                  <div class="daily-help-card__title">{{ section.title }}</div>
                  <div class="daily-help-card__section">
                    <div class="daily-help-card__label">上游数据来源</div>
                    <p>{{ section.help?.source || '-' }}</p>
                  </div>
                  <div class="daily-help-card__section">
                    <div class="daily-help-card__label">筛选规则</div>
                    <p>{{ section.help?.rule || '-' }}</p>
                  </div>
                  <div class="daily-help-card__section">
                    <div class="daily-help-card__label">结果作用范围</div>
                    <p>{{ section.help?.scopeNote || '-' }}</p>
                  </div>
                </div>
              </el-popover>
            </div>
            <div class="daily-chip-grid">
              <div
                v-for="item in section.items"
                :key="item.key"
                class="daily-condition-chip"
              >
                <el-button
                  size="small"
                  :type="isSectionItemSelected(section, item) ? 'primary' : 'default'"
                  :plain="!isSectionItemSelected(section, item)"
                  @click="toggleSectionItem(section, item)"
                >
                  {{ formatSectionItemLabel(section, item) }}
                </el-button>
              </div>
            </div>
          </article>

          <article class="workbench-block">
            <div class="daily-section-header">
              <div class="workbench-panel__title">日线缠论涨幅</div>
              <el-popover
                trigger="hover"
                placement="right"
                :width="360"
              >
                <template #reference>
                  <button
                    type="button"
                    class="daily-info-trigger"
                    aria-label="查看日线缠论涨幅说明"
                  >
                    i
                  </button>
                </template>
                <div class="daily-help-card">
                  <div class="daily-help-card__title">日线缠论涨幅</div>
                  <div class="daily-help-card__section">
                    <div class="daily-help-card__label">上游数据来源</div>
                    <p>{{ dailyChanlunHelp?.source || '-' }}</p>
                  </div>
                  <div class="daily-help-card__section">
                    <div class="daily-help-card__label">筛选规则</div>
                    <p>{{ dailyChanlunHelp?.rule || '-' }}</p>
                  </div>
                  <div class="daily-help-card__section">
                    <div class="daily-help-card__label">结果作用范围</div>
                    <p>{{ dailyChanlunHelp?.scopeNote || '-' }}</p>
                  </div>
                </div>
              </el-popover>
            </div>
            <div class="daily-metric-toggle-row">
              <el-button
                size="small"
                :type="dayChanlunEnabled ? 'primary' : 'default'"
                :plain="!dayChanlunEnabled"
                @click="toggleDayChanlunFilter"
              >
                {{ dayChanlunEnabled ? '已参与筛选' : '参与筛选' }}
              </el-button>
              <span class="daily-metric-toggle-note">默认值：高级段倍数 3 / 段倍数 2 / 笔涨幅% 20</span>
            </div>
            <div class="daily-metric-grid">
              <el-form-item
                v-for="item in metricFieldConfigs"
                :key="item.key"
              >
                <template #label>
                  <span class="daily-form-label">{{ item.label }}</span>
                </template>
                <el-input-number
                  v-model="metricFilters[item.key]"
                  controls-position="right"
                  :min="0"
                  :step="item.step"
                  class="daily-field-control"
                />
              </el-form-item>
            </div>
          </article>

          <div class="daily-filter-actions">
            <span class="daily-expression">{{ currentExpression }}</span>
            <div class="daily-action-buttons">
              <el-button @click="resetFilters">重置筛选</el-button>
            </div>
          </div>
        </section>

        <div class="daily-center-stack">
          <section class="workbench-panel daily-results-panel" v-loading="queryLoading">
            <div class="workbench-panel__header daily-results-header">
              <div class="daily-results-header__action">
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :disabled="!resultRows.length"
                  :loading="isWorkspaceActionRunning('workspace:append-intersection')"
                  @click="handleAppendIntersectionToPrePool"
                >
                  全部加入pre_pools
                </el-button>
              </div>
              <div class="workbench-title-group">
                <div class="workbench-panel__title">交集列表</div>
                <p class="workbench-panel__desc">无条件时默认显示基础池，勾选后统一取交集。</p>
              </div>
              <div class="workbench-panel__meta daily-results-meta">
                <span>{{ resultRows.length }} 条</span>
              </div>
            </div>

            <el-table
              :data="resultRows"
              size="small"
              border
              height="380"
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

          <section class="workbench-panel daily-workspace-panel" v-loading="workspaceLoading">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">工作区</div>
                <p class="workbench-panel__desc">和 /gantt/shouban30 共用同一套 pre_pools / stock_pools / must_pools。</p>
              </div>
              <div class="workbench-panel__meta">
                <span>pre_pools {{ prePoolItems.length }}</span>
                <span>/</span>
                <span>stock_pools {{ stockPoolItems.length }}</span>
              </div>
            </div>

            <el-alert
              v-if="workspaceError"
              class="workbench-alert"
              type="error"
              :title="workspaceError"
              :closable="false"
              show-icon
            />

            <el-tabs v-model="activeWorkspaceTab" class="daily-workspace-tabs">
              <el-tab-pane
                v-for="tab in workspaceTabs"
                :key="tab.key"
                :name="tab.key"
              >
                <template #label>
                  <div class="daily-workspace-tab-label">
                    <span>{{ tab.label }}</span>
                    <span>{{ tab.rows.length }}</span>
                  </div>
                </template>

                <div class="daily-workspace-actions">
                  <template v-if="tab.key === 'pre_pool'">
                    <el-button
                      size="small"
                      type="primary"
                      plain
                      :loading="isWorkspaceActionRunning('workspace:pre:sync-stock')"
                      @click="handleSyncPrePoolToStockPool"
                    >
                      {{ tab.batch_action_label }}
                    </el-button>
                    <el-button
                      size="small"
                      type="primary"
                      plain
                      :loading="isWorkspaceActionRunning('workspace:pre:sync-tdx')"
                      @click="handleSyncPrePoolToTdx"
                    >
                      {{ tab.sync_action_label }}
                    </el-button>
                    <el-button
                      size="small"
                      type="danger"
                      plain
                      :loading="isWorkspaceActionRunning('workspace:pre:clear')"
                      @click="handleClearPrePool"
                    >
                      {{ tab.clear_action_label }}
                    </el-button>
                  </template>

                  <template v-else>
                    <el-button
                      size="small"
                      type="primary"
                      plain
                      :loading="isWorkspaceActionRunning('workspace:stock:sync-must')"
                      @click="handleSyncStockPoolToMustPool"
                    >
                      {{ tab.batch_action_label }}
                    </el-button>
                    <el-button
                      size="small"
                      type="primary"
                      plain
                      :loading="isWorkspaceActionRunning('workspace:stock:sync-tdx')"
                      @click="handleSyncStockPoolToTdx"
                    >
                      {{ tab.sync_action_label }}
                    </el-button>
                    <el-button
                      size="small"
                      type="danger"
                      plain
                      :loading="isWorkspaceActionRunning('workspace:stock:clear')"
                      @click="handleClearStockPool"
                    >
                      {{ tab.clear_action_label }}
                    </el-button>
                  </template>
                </div>

                <el-table
                  :data="tab.rows"
                  size="small"
                  border
                  height="260"
                >
                  <el-table-column prop="code6" label="代码" width="92" />
                  <el-table-column prop="name" label="名称" min-width="120" show-overflow-tooltip />
                  <el-table-column prop="provider" label="来源" width="120" show-overflow-tooltip />
                  <el-table-column prop="plate_name" label="上下文" min-width="140" show-overflow-tooltip />
                  <el-table-column label="操作" min-width="180">
                    <template #default="{ row }">
                      <div class="daily-workspace-row-actions">
                        <template v-if="tab.key === 'pre_pool'">
                          <el-button
                            size="small"
                            type="primary"
                            link
                            :loading="isWorkspaceActionRunning(`workspace:pre:add:${row.code6}`)"
                            @click.stop="handleAddPrePoolToStockPools(row)"
                          >
                            {{ row.primary_action_label }}
                          </el-button>
                          <el-button
                            size="small"
                            type="danger"
                            link
                            :loading="isWorkspaceActionRunning(`workspace:pre:delete:${row.code6}`)"
                            @click.stop="handleDeletePrePoolRow(row)"
                          >
                            {{ row.secondary_action_label }}
                          </el-button>
                        </template>
                        <template v-else>
                          <el-button
                            size="small"
                            type="primary"
                            link
                            :loading="isWorkspaceActionRunning(`workspace:stock:add-must:${row.code6}`)"
                            @click.stop="handleAddStockPoolToMustPools(row)"
                          >
                            {{ row.primary_action_label }}
                          </el-button>
                          <el-button
                            size="small"
                            type="danger"
                            link
                            :loading="isWorkspaceActionRunning(`workspace:stock:delete:${row.code6}`)"
                            @click.stop="handleDeleteStockPoolRow(row)"
                          >
                            {{ row.secondary_action_label }}
                          </el-button>
                        </template>
                      </div>
                    </template>
                  </el-table-column>
                </el-table>
              </el-tab-pane>
            </el-tabs>
          </section>
        </div>

        <aside class="daily-detail-stack" v-loading="detailLoading">
          <section class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">标的详情</div>
                <p class="workbench-panel__desc">展示命中条件画像和日线缠论涨幅。</p>
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
                <div class="workbench-panel__title">日线缠论涨幅</div>
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
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import MyHeader from './MyHeader.vue'
import { dailyScreeningApi } from '@/api/dailyScreeningApi.js'
import {
  addShouban30PrePoolToStockPool,
  addShouban30StockPoolToMustPool,
  appendShouban30PrePool,
  clearShouban30PrePool,
  clearShouban30StockPool,
  deleteShouban30PrePoolItem,
  deleteShouban30StockPoolItem,
  getShouban30PrePool,
  getShouban30StockPool,
  syncShouban30PrePoolToStockPool,
  syncShouban30PrePoolToTdx,
  syncShouban30StockPoolToMustPool,
  syncShouban30StockPoolToTdx,
} from '@/api/ganttShouban30.js'
import {
  DEFAULT_DAILY_CHANLUN_METRIC_FILTERS,
  buildDailyScreeningAppendPrePoolPayload,
  buildDailyScreeningQueryPayload,
  buildDailyScreeningWorkspaceTabs,
  buildDailyScreeningWorkbenchState,
  formatDailyScreeningConditionLabel,
  normalizeDailyScreeningDetail,
  normalizeDailyScreeningFilterCatalog,
  normalizeDailyScreeningResultRows,
  normalizeDailyScreeningScopeItems,
  readDailyScreeningPayload,
  resolveDailyScreeningClsGroupLabels,
  resolveDailyScreeningClsGroupModels,
  toggleDailyScreeningSelection,
} from './dailyScreeningPage.mjs'

const loadingScopes = ref(false)
const loadingFilters = ref(false)
const queryLoading = ref(false)
const detailLoading = ref(false)
const workspaceLoading = ref(false)
const pageError = ref('')
const workspaceError = ref('')

const scopeItems = ref([])
const selectedScopeId = ref('')
const scopeSummary = ref({})
const filterCatalog = ref(normalizeDailyScreeningFilterCatalog({}))
const resultRows = ref([])
const selectedCode = ref('')
const detail = ref(normalizeDailyScreeningDetail({}))
const prePoolItems = ref([])
const stockPoolItems = ref([])
const activeWorkspaceTab = ref('pre_pool')
const workspaceActionKey = ref('')

const conditionKeys = ref([])
const clsGroupKeys = ref([])
const dayChanlunEnabled = ref(false)
const metricFilters = reactive({
  ...DEFAULT_DAILY_CHANLUN_METRIC_FILTERS,
})

let metricFilterDebounceTimer = null
let suppressMetricFilterAutoQuery = false

const pageLoading = computed(() => loadingScopes.value || loadingFilters.value)
const detailSnapshot = computed(() => detail.value?.snapshot || null)
const filterGroups = computed(() => filterCatalog.value.groups || {})
const sectionHelp = computed(() => filterCatalog.value.sectionHelp || {})
const conditionSections = computed(() => ([
  {
    key: 'clsGroups',
    title: 'CLS 模型分组',
    items: filterGroups.value.clsGroups || [],
    help: sectionHelp.value.clsGroups,
  },
  {
    key: 'hotWindows',
    title: '热门窗口',
    items: filterGroups.value.hotWindows || [],
    help: sectionHelp.value.hotWindows,
  },
  {
    key: 'marketFlags',
    title: '市场属性',
    items: filterGroups.value.marketFlags || [],
    help: sectionHelp.value.marketFlags,
  },
  {
    key: 'chanlunPeriods',
    title: 'chanlun 周期',
    items: filterGroups.value.chanlunPeriods || [],
    help: sectionHelp.value.chanlunPeriods,
  },
  {
    key: 'chanlunSignals',
    title: 'chanlun 信号',
    items: filterGroups.value.chanlunSignals || [],
    help: sectionHelp.value.chanlunSignals,
  },
]))
const dailyChanlunHelp = computed(() => sectionHelp.value.dailyChanlun || {})
const metricFieldConfigs = computed(() => ([
  {
    key: 'higherMultipleLte',
    label: '高级段倍数 ≤',
    step: 0.1,
  },
  {
    key: 'segmentMultipleLte',
    label: '段倍数 ≤',
    step: 0.1,
  },
  {
    key: 'biGainPercentLte',
    label: '笔涨幅% ≤',
    step: 0.1,
  },
]))
const workbenchGuideLines = [
  '上游范围：全市场股票，排除 ST 和北交所',
  '基础池：CLS 各模型结果和热门 30/45/60/90 天结果先取并集形成',
  '交集规则：用户勾选的条件会在当前结果上继续取交集',
  '工作区用途：交集结果可加入 pre_pools，再同步到 stock_pools / must_pools',
]
const selectedScopeLabel = computed(() => {
  const matched = scopeItems.value.find((item) => item.scopeId === selectedScopeId.value)
  return matched?.label || selectedScopeId.value || '-'
})
const activeConditionCount = computed(() => {
  return conditionKeys.value.length + clsGroupKeys.value.length + (dayChanlunEnabled.value ? 1 : 0)
})
const currentExpression = computed(() => {
  if (!conditionKeys.value.length && activeConditionCount.value === 0) {
    return '默认展示“CLS 各模型结果和热门 30/45/60/90 天结果先取并集形成的基础池”'
  }
  const labels = [
    ...resolveDailyScreeningClsGroupLabels(clsGroupKeys.value),
    ...conditionKeys.value.map((item) => formatDailyScreeningConditionLabel(item)),
  ]
  if (dayChanlunEnabled.value) {
    labels.push(
      `日线缠论涨幅（高级段倍数 <= ${metricFilters.higherMultipleLte} / 段倍数 <= ${metricFilters.segmentMultipleLte} / 笔涨幅% <= ${metricFilters.biGainPercentLte}）`,
    )
  }
  return labels.join(' ∩ ') || '默认展示“CLS 各模型结果和热门 30/45/60/90 天结果先取并集形成的基础池”'
})
const workspaceTabs = computed(() => {
  return buildDailyScreeningWorkspaceTabs({
    prePoolItems: prePoolItems.value,
    stockPoolItems: stockPoolItems.value,
  })
})

const formatNumber = (value) => {
  if (value == null || value === '') return '-'
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric.toFixed(2) : '-'
}

const resetMetricFilters = () => {
  metricFilters.higherMultipleLte = DEFAULT_DAILY_CHANLUN_METRIC_FILTERS.higherMultipleLte
  metricFilters.segmentMultipleLte = DEFAULT_DAILY_CHANLUN_METRIC_FILTERS.segmentMultipleLte
  metricFilters.biGainPercentLte = DEFAULT_DAILY_CHANLUN_METRIC_FILTERS.biGainPercentLte
}

const readSharedWorkspacePayload = (response) => {
  if (response && typeof response === 'object') {
    if (response.data && typeof response.data === 'object') {
      return response.data
    }
    return response
  }
  return {}
}

const isWorkspaceActionRunning = (key) => workspaceActionKey.value === key

const buildSelectedFilterKeys = () => {
  const keys = [
    ...clsGroupKeys.value,
    ...conditionKeys.value,
  ]
  if (dayChanlunEnabled.value) {
    keys.push('metric:daily_chanlun')
  }
  return keys
}

const isSectionItemSelected = (section, item) => {
  if (section?.key === 'clsGroups') {
    return clsGroupKeys.value.includes(item?.key)
  }
  return conditionKeys.value.includes(item?.key)
}

const formatSectionItemLabel = (section, item) => {
  if (section?.key === 'clsGroups') {
    return item?.label || ''
  }
  return `${item?.label || ''} · ${Number(item?.count || 0)}`
}

const scheduleMetricFilterQuery = () => {
  if (metricFilterDebounceTimer) {
    clearTimeout(metricFilterDebounceTimer)
  }
  metricFilterDebounceTimer = setTimeout(() => {
    metricFilterDebounceTimer = null
    void queryRows()
  }, 250)
}

const applyStateDefaults = (latestScope = null) => {
  const state = buildDailyScreeningWorkbenchState(latestScope)
  if (!selectedScopeId.value) {
    selectedScopeId.value = state.scopeId
  }
  suppressMetricFilterAutoQuery = true
  conditionKeys.value = [...state.conditionKeys]
  clsGroupKeys.value = [...state.clsGroupKeys]
  dayChanlunEnabled.value = Boolean(state.dayChanlunEnabled)
  resetMetricFilters()
  suppressMetricFilterAutoQuery = false
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
    if (!conditionKeys.value.length && !clsGroupKeys.value.length && !dayChanlunEnabled.value) {
      applyStateDefaults(latestScope)
    }
    pageError.value = ''
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '加载 scopes 失败'
  } finally {
    loadingScopes.value = false
  }
}

const loadWorkspace = async () => {
  workspaceLoading.value = true
  workspaceError.value = ''
  try {
    const [prePoolResponse, stockPoolResponse] = await Promise.all([
      getShouban30PrePool(),
      getShouban30StockPool(),
    ])
    prePoolItems.value = readSharedWorkspacePayload(prePoolResponse)?.items || []
    stockPoolItems.value = readSharedWorkspacePayload(stockPoolResponse)?.items || []
  } catch (error) {
    workspaceError.value = error?.response?.data?.error || error?.message || '加载工作区失败'
  } finally {
    workspaceLoading.value = false
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
          clxsModels: resolveDailyScreeningClsGroupModels(clsGroupKeys.value),
          metricFiltersEnabled: dayChanlunEnabled.value,
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

const toggleCondition = async (key) => {
  conditionKeys.value = toggleDailyScreeningSelection(conditionKeys.value, key)
  await queryRows()
}

const resetFilters = async () => {
  suppressMetricFilterAutoQuery = true
  conditionKeys.value = []
  clsGroupKeys.value = []
  dayChanlunEnabled.value = false
  resetMetricFilters()
  suppressMetricFilterAutoQuery = false
  await queryRows()
}

const toggleClsGroup = async (key) => {
  clsGroupKeys.value = toggleDailyScreeningSelection(clsGroupKeys.value, key)
  await queryRows()
}

const toggleSectionItem = async (section, item) => {
  if (section?.key === 'clsGroups') {
    await toggleClsGroup(item?.key)
    return
  }
  await toggleCondition(item?.key)
}

const toggleDayChanlunFilter = async () => {
  dayChanlunEnabled.value = !dayChanlunEnabled.value
  await queryRows()
}

const handleRowClick = async (row) => {
  selectedCode.value = row.code
  await loadDetail(row.code)
}

const runWorkspaceAction = async ({
  actionKey,
  action,
  successMessage,
  refreshWorkspace = true,
} = {}) => {
  workspaceActionKey.value = actionKey || ''
  workspaceError.value = ''
  try {
    const response = await action()
    if (refreshWorkspace) {
      await loadWorkspace()
    }
    const resolvedMessage = typeof successMessage === 'function'
      ? successMessage(readSharedWorkspacePayload(response))
      : successMessage
    if (resolvedMessage) {
      ElMessage.success(resolvedMessage)
    }
    return response
  } catch (error) {
    const message = error?.response?.data?.error || error?.message || '工作区操作失败'
    workspaceError.value = message
    ElMessage.error(message)
    return null
  } finally {
    workspaceActionKey.value = ''
  }
}

const handleAppendIntersectionToPrePool = async () => {
  const payload = buildDailyScreeningAppendPrePoolPayload({
    scopeId: selectedScopeId.value,
    rows: resultRows.value,
    conditionKeys: buildSelectedFilterKeys(),
    expression: currentExpression.value,
  })
  if (!payload.items.length) {
    ElMessage.warning('当前交集结果没有可加入的标的')
    return
  }
  await runWorkspaceAction({
    actionKey: 'workspace:append-intersection',
    action: () => appendShouban30PrePool(payload),
    successMessage: `已将当前交集结果 ${payload.items.length} 条加入 pre_pools`,
  })
}

const handleAddPrePoolToStockPools = async (row) => {
  await runWorkspaceAction({
    actionKey: `workspace:pre:add:${String(row?.code6 || '').trim()}`,
    action: () => addShouban30PrePoolToStockPool({ code6: row?.code6 }),
    successMessage: `${String(row?.code6 || '').trim()} 已加入 stock_pools`,
  })
}

const handleDeletePrePoolRow = async (row) => {
  await runWorkspaceAction({
    actionKey: `workspace:pre:delete:${String(row?.code6 || '').trim()}`,
    action: () => deleteShouban30PrePoolItem({ code6: row?.code6 }),
    successMessage: `${String(row?.code6 || '').trim()} 已从 pre_pools 删除`,
  })
}

const handleSyncPrePoolToStockPool = async () => {
  await runWorkspaceAction({
    actionKey: 'workspace:pre:sync-stock',
    action: () => syncShouban30PrePoolToStockPool(),
    successMessage: '已将 pre_pools 同步到 stock_pools',
  })
}

const handleSyncPrePoolToTdx = async () => {
  await runWorkspaceAction({
    actionKey: 'workspace:pre:sync-tdx',
    action: () => syncShouban30PrePoolToTdx(),
    successMessage: `已将 pre_pools ${prePoolItems.value.length} 条同步到通达信`,
    refreshWorkspace: false,
  })
}

const handleClearPrePool = async () => {
  await runWorkspaceAction({
    actionKey: 'workspace:pre:clear',
    action: () => clearShouban30PrePool(),
    successMessage: '已清空 pre_pools',
  })
}

const handleAddStockPoolToMustPools = async (row) => {
  await runWorkspaceAction({
    actionKey: `workspace:stock:add-must:${String(row?.code6 || '').trim()}`,
    action: () => addShouban30StockPoolToMustPool({ code6: row?.code6 }),
    successMessage: (payload) => {
      const status = String(payload?.status || '').trim()
      const suffix = status === 'updated' ? '已更新 must_pools' : '已加入 must_pools'
      return `${String(row?.code6 || '').trim()} ${suffix}`
    },
    refreshWorkspace: false,
  })
}

const handleDeleteStockPoolRow = async (row) => {
  await runWorkspaceAction({
    actionKey: `workspace:stock:delete:${String(row?.code6 || '').trim()}`,
    action: () => deleteShouban30StockPoolItem({ code6: row?.code6 }),
    successMessage: `${String(row?.code6 || '').trim()} 已从 stock_pools 删除`,
  })
}

const handleSyncStockPoolToMustPool = async () => {
  await runWorkspaceAction({
    actionKey: 'workspace:stock:sync-must',
    action: () => syncShouban30StockPoolToMustPool(),
    successMessage: (payload) => `已同步 ${payload.total_count ?? 0} 条到 must_pools（created ${payload.created_count ?? 0} / updated ${payload.updated_count ?? 0}）`,
    refreshWorkspace: false,
  })
}

const handleSyncStockPoolToTdx = async () => {
  await runWorkspaceAction({
    actionKey: 'workspace:stock:sync-tdx',
    action: () => syncShouban30StockPoolToTdx(),
    successMessage: `已将 stock_pools ${stockPoolItems.value.length} 条同步到通达信`,
    refreshWorkspace: false,
  })
}

const handleClearStockPool = async () => {
  await runWorkspaceAction({
    actionKey: 'workspace:stock:clear',
    action: () => clearShouban30StockPool(),
    successMessage: '已清空 stock_pools',
  })
}

watch(
  () => [
    metricFilters.higherMultipleLte,
    metricFilters.segmentMultipleLte,
    metricFilters.biGainPercentLte,
  ],
  () => {
    if (suppressMetricFilterAutoQuery || !dayChanlunEnabled.value || !selectedScopeId.value) {
      return
    }
    scheduleMetricFilterQuery()
  },
)

watch(selectedScopeId, async (scopeId) => {
  if (!scopeId) return
  selectedCode.value = ''
  detail.value = normalizeDailyScreeningDetail({})
  suppressMetricFilterAutoQuery = true
  conditionKeys.value = []
  clsGroupKeys.value = []
  dayChanlunEnabled.value = false
  resetMetricFilters()
  suppressMetricFilterAutoQuery = false
  await refreshCurrentScope()
})

onBeforeUnmount(() => {
  if (metricFilterDebounceTimer) {
    clearTimeout(metricFilterDebounceTimer)
    metricFilterDebounceTimer = null
  }
})

onMounted(async () => {
  await loadScopes()
  await Promise.all([
    selectedScopeId.value ? refreshCurrentScope() : Promise.resolve(),
    loadWorkspace(),
  ])
})
</script>

<style scoped>
.daily-screening-body {
  padding: 24px;
}

.daily-screening-grid {
  display: grid;
  flex: 1 1 auto;
  grid-template-columns: 360px minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
  min-height: 0;
  overflow: hidden;
  align-items: stretch;
}

.daily-filter-panel,
.daily-center-stack,
.daily-detail-stack {
  min-height: 0;
  max-height: 100%;
}

.daily-filter-panel {
  overflow-y: auto;
  scrollbar-gutter: stable;
}

.daily-center-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.daily-detail-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.daily-guide-list {
  margin: 0;
  padding-left: 18px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.daily-chip-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.daily-section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.daily-condition-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.daily-metric-toggle-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
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

.daily-results-meta {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.daily-results-header {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
}

.daily-results-header__action {
  display: flex;
  align-items: center;
}

.daily-expression {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.daily-form-label {
  display: inline-flex;
  align-items: center;
}

.daily-metric-toggle-note {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.daily-info-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  background: #fff;
  color: #475569;
  cursor: pointer;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
}

.daily-help-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.daily-help-card__title {
  font-size: 14px;
  font-weight: 600;
  color: #111827;
}

.daily-help-card__section {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: #374151;
  line-height: 1.5;
}

.daily-help-card__section p {
  margin: 0;
}

.daily-help-card__label {
  font-weight: 600;
  color: #111827;
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

.daily-workspace-tab-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.daily-workspace-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.daily-workspace-row-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

@media (max-width: 1480px) {
  .daily-screening-grid {
    grid-template-columns: 320px minmax(0, 1fr) minmax(0, 1fr);
  }
}

@media (max-width: 1280px) {
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
