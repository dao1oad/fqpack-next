<template>
  <WorkbenchPage class="subject-management-page">
    <MyHeader />

    <div class="workbench-body subject-management-body">
      <WorkbenchToolbar class="subject-management-toolbar">
        <div class="workbench-toolbar__header">
          <div class="workbench-title-group">
            <div class="workbench-page-title">标的管理</div>
            <div class="workbench-page-meta">
              <span>左侧高密度汇总当前配置，右侧集中编辑基础设置、单标的仓位上限与持仓入口止损。</span>
              <template v-if="detail">
                <span>/</span>
                <span>当前标的 <span class="workbench-code">{{ detail.symbol }}</span> {{ detail.name }}</span>
              </template>
            </div>
          </div>

          <div class="workbench-toolbar__actions">
            <el-button type="primary" :loading="loadingOverview" @click="refreshOverview">刷新</el-button>
          </div>
        </div>

        <el-alert
          v-if="pageError"
          class="workbench-alert"
          type="error"
          :title="pageError"
          :closable="false"
          show-icon
        />

        <div class="subject-toolbar-filters">
          <el-input
            v-model="filters.keyword"
            clearable
            placeholder="搜索代码 / 名称 / 分类"
            class="subject-filter-input"
          />
          <el-select v-model="filters.category" clearable placeholder="全部分类" class="subject-filter-select">
            <el-option
              v-for="option in categoryOptions"
              :key="option"
              :label="option"
              :value="option"
            />
          </el-select>
          <div class="subject-filter-checks">
            <el-checkbox v-model="filters.onlyMustPool">仅 must_pool</el-checkbox>
            <el-checkbox v-model="filters.onlyHolding">仅持仓中</el-checkbox>
            <el-checkbox v-model="filters.onlyTakeprofit">仅已配止盈</el-checkbox>
            <el-checkbox v-model="filters.onlyStoploss">仅有活跃止损</el-checkbox>
          </div>
        </div>

        <div class="workbench-summary-row">
          <StatusChip>
            总标的 <strong>{{ overviewRows.length }}</strong>
          </StatusChip>
          <StatusChip variant="muted">
            当前筛选 <strong>{{ filteredOverviewRows.length }}</strong>
          </StatusChip>
          <StatusChip variant="success">
            持仓中 <strong>{{ holdingCount }}</strong>
          </StatusChip>
          <StatusChip variant="warning">
            活跃止损 <strong>{{ activeStoplossCount }}</strong>
          </StatusChip>
          <StatusChip v-if="pmSummary.effective_state" :variant="pmSummary.effective_state_chip_variant">
            门禁 <strong>{{ pmSummary.effective_state_label }}</strong>
          </StatusChip>
          <StatusChip v-if="pmSummary.allow_open_min_bail !== null" variant="muted">
            开仓阈值 <strong>{{ formatInteger(pmSummary.allow_open_min_bail) }}</strong>
          </StatusChip>
          <StatusChip v-if="pmSummary.holding_only_min_bail !== null" variant="muted">
            持仓阈值 <strong>{{ formatInteger(pmSummary.holding_only_min_bail) }}</strong>
          </StatusChip>
        </div>
      </WorkbenchToolbar>

      <div class="subject-layout">
        <WorkbenchLedgerPanel class="subject-overview-panel">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">标的总览</div>
              <p class="workbench-panel__desc">左表直接展示当前配置摘要，不再依赖卡片。点击任一行，右栏切换到该标的编辑。</p>
            </div>
            <div class="workbench-panel__meta">
              <span>{{ overviewPage.total }} 条</span>
              <span>第 {{ overviewPage.page }} / {{ overviewPage.totalPages }} 页</span>
            </div>
          </div>

          <div class="workbench-table-wrap subject-overview-table-wrap">
            <el-table
              v-loading="loadingOverview"
              :data="overviewPage.rows"
              row-key="symbol"
              size="small"
              border
              height="100%"
              :row-class-name="overviewRowClassName"
              @row-click="handleRowClick"
            >
              <el-table-column label="代码" width="92">
                <template #default="{ row }">
                  <div class="subject-code-cell">
                    <span class="workbench-code">{{ row.symbol }}</span>
                    <span class="subject-inline-state" :class="{ active: row.has_position }">{{ row.has_position ? '持仓' : '观察' }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column prop="name" label="名称" min-width="112" show-overflow-tooltip />
              <el-table-column prop="category" label="分类" min-width="88" show-overflow-tooltip />
              <el-table-column label="基础设置" min-width="178">
                <template #default="{ row }">
                  <div class="subject-summary-stack">
                    <div class="subject-summary-line">SL {{ formatPrice(row.must_pool.stop_loss_price) }}</div>
                    <div class="subject-summary-line">首/常 {{ formatInteger(row.must_pool.initial_lot_amount) }} / {{ formatInteger(row.must_pool.lot_amount) }}</div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="Guardian" min-width="176">
                <template #default="{ row }">
                  <div class="subject-summary-stack">
                    <div class="subject-summary-line">
                      <span class="subject-inline-state" :class="{ active: row.guardian.enabled }">{{ row.guardian.enabled ? '开启' : '关闭' }}</span>
                      <span>命中 {{ row.runtime?.last_hit_level || '-' }}</span>
                    </div>
                    <div class="subject-summary-line workbench-code">B1 {{ formatPrice(row.guardian.buy_1) }}</div>
                    <div class="subject-summary-line workbench-code">B2 {{ formatPrice(row.guardian.buy_2) }}</div>
                    <div class="subject-summary-line workbench-code">B3 {{ formatPrice(row.guardian.buy_3) }}</div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="仓位上限" min-width="182">
                <template #default="{ row }">
                  <div class="subject-summary-stack">
                    <div class="subject-summary-line">市值 {{ formatWanAmount(row.positionLimitSummary.market_value) }}</div>
                    <div class="subject-summary-line">上限 {{ formatWanAmount(row.positionLimitSummary.effective_limit) }}</div>
                    <div class="subject-summary-line">{{ row.positionLimitSummary.using_override ? '单独设置' : '系统默认值' }}</div>
                    <div class="subject-summary-line">
                      <span class="subject-inline-state" :class="{ active: !row.positionLimitSummary.blocked }">
                        {{ row.positionLimitSummary.blocked ? '阻断' : '允许' }}
                      </span>
                    </div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="止盈" min-width="188">
                <template #default="{ row }">
                  <div class="subject-takeprofit-grid">
                    <div
                      v-for="item in row.takeprofitSummary"
                      :key="`${row.symbol}-tp-${item.level}`"
                      class="subject-takeprofit-line"
                    >
                      <span class="workbench-code">L{{ item.level }}</span>
                      <span class="workbench-code">{{ item.priceLabel }}</span>
                      <span class="subject-inline-state" :class="{ active: item.enabled }">{{ item.enabledLabel }}</span>
                    </div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="止损" min-width="112">
                <template #default="{ row }">
                  <div class="subject-summary-stack">
                    <div class="subject-summary-line">活跃 / open</div>
                    <div class="subject-summary-line workbench-code">{{ row.stoplossActiveCount }} / {{ row.openEntryCount }}</div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="运行态" min-width="172">
                <template #default="{ row }">
                  <div class="subject-summary-stack">
                    <div class="subject-summary-line">仓位 {{ formatWanAmount(row.position_amount) }}</div>
                    <div class="subject-summary-line">持仓 {{ row.position_quantity }} 股</div>
                    <div class="subject-summary-line">
                      上限 {{ formatWanAmount(row.positionLimitSummary.effective_limit) }}
                      {{ row.positionLimitSummary.using_override ? '单独' : '默认' }}
                    </div>
                    <div class="subject-summary-line">{{ row.runtime?.last_hit_level || '-' }}</div>
                    <div class="subject-summary-line workbench-code">{{ formatDateTime(row.runtime?.last_trigger_time) }}</div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="76" fixed="right">
                <template #default="{ row }">
                  <el-button type="primary" text @click.stop="handleRowClick(row)">编辑</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <div class="subject-overview-pagination">
            <el-pagination
              background
              layout="total,sizes,prev,pager,next"
              :current-page="overviewPage.page"
              :page-size="overviewPage.pageSize"
              :total="overviewPage.total"
              :page-sizes="overviewPageSizeOptions"
              @current-change="handleOverviewPageChange"
              @size-change="handleOverviewPageSizeChange"
            />
          </div>
        </WorkbenchLedgerPanel>

        <main class="subject-editor-stack">
          <template v-if="detail">
            <section class="subject-editor-summarybar">
              <div class="subject-editor-summarybar__main">
                <div class="subject-editor-summarybar__headline">
                  <span class="workbench-code">{{ detail.symbol }}</span>
                  <span class="subject-editor-summarybar__name">{{ detail.name || detail.symbol }}</span>
                </div>
                <div class="subject-editor-summarybar__meta">
                  <span>最近触发 {{ detail.runtimeSummary.last_trigger_kind || '-' }}</span>
                  <span>/</span>
                  <span class="workbench-code">{{ formatDateTime(detail.runtimeSummary.last_trigger_time) }}</span>
                  <span>/</span>
                  <span>Guardian {{ detail.guardianState.last_hit_level || '-' }}</span>
                  <span>/</span>
                  <span class="workbench-code">{{ formatPrice(detail.guardianState.last_hit_price) }}</span>
                </div>
              </div>

              <div class="subject-editor-summarybar__chips">
                <StatusChip
                  v-for="chip in detailSummaryChips"
                  :key="chip.key"
                  class="subject-editor-chip"
                  :variant="chip.tone"
                >
                  <span class="subject-editor-chip__label">{{ chip.label }}</span>
                  <strong>{{ chip.value }}</strong>
                </StatusChip>
              </div>

              <div class="subject-editor-summarybar__actions">
                <el-button size="small" :loading="loadingDetail" @click="reloadCurrentSymbol">刷新当前标的</el-button>
              </div>
            </section>

            <WorkbenchDetailPanel class="subject-editor-table-panel">
              <div class="subject-editor-table-header">
                <div class="subject-editor-table-heading">
                  <div class="subject-editor-table-title">基础配置 + 单标的仓位上限</div>
                  <div class="subject-editor-table-subtitle">当前生效值会显示来源；未配置项会明确标记，保存成系统默认值时后端会自动删除单独设置</div>
                </div>
                <el-button
                  size="small"
                  type="primary"
                  :loading="savingConfigBundle"
                  @click="handleSaveConfigBundleClick"
                >
                  保存基础设置与仓位上限
                </el-button>
              </div>

              <el-table
                :data="configEditorRows"
                size="small"
                border
                class="subject-table subject-editor-config-table"
              >
                <el-table-column prop="group" label="分组" width="82" />
                <el-table-column prop="label" label="项" width="108" />
                <el-table-column label="当前生效" min-width="110">
                  <template #default="{ row }">
                    <span class="subject-editor-current">
                      {{ row.currentLabel }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column label="编辑值" min-width="190">
                  <template #default="{ row }">
                    <el-input
                      v-if="row.key === 'category'"
                      v-model.trim="mustPoolDraft.category"
                      size="small"
                      placeholder="如：银行 / 守护池"
                    />
                    <el-input-number
                      v-else-if="row.key === 'stop_loss_price'"
                      v-model="mustPoolDraft.stop_loss_price"
                      size="small"
                      :min="0"
                      :step="0.01"
                      :precision="2"
                      controls-position="right"
                    />
                    <el-input-number
                      v-else-if="row.key === 'initial_lot_amount'"
                      v-model="mustPoolDraft.initial_lot_amount"
                      size="small"
                      :min="0"
                      :step="1000"
                      controls-position="right"
                    />
                    <el-input-number
                      v-else-if="row.key === 'lot_amount'"
                      v-model="mustPoolDraft.lot_amount"
                      size="small"
                      :min="0"
                      :step="1000"
                      controls-position="right"
                    />
                    <el-input-number
                      v-else-if="row.key === 'position_limit_value'"
                      v-model="positionLimitDraft.limit"
                      size="small"
                      :min="0"
                      :step="10000"
                      controls-position="right"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="状态" width="112">
                  <template #default="{ row }">
                    <el-tag size="small" :type="resolveConfigRowTagType(row)">
                      {{ row.statusLabel }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="说明" min-width="180" show-overflow-tooltip>
                  <template #default="{ row }">
                    <span class="subject-editor-note">
                      {{ row.note }}
                    </span>
                  </template>
                </el-table-column>
              </el-table>
            </WorkbenchDetailPanel>

            <WorkbenchDetailPanel class="subject-editor-table-panel">
              <div class="subject-editor-table-header">
                <div class="subject-editor-table-heading">
                  <div class="subject-editor-table-title">按持仓入口止损</div>
                  <div class="subject-editor-table-subtitle">左侧聚合买入列表，右侧展示当前聚合买入的详细切片；只展示 open entry，按行保存</div>
                </div>
                <div class="subject-editor-table-meta">{{ detail.entries.length }} 条 open entry</div>
              </div>

              <div v-if="detail.entries.length" class="subject-editor-stoploss-layout">
                <section class="subject-editor-stoploss-master">
                  <div class="subject-editor-stoploss-pane-header">
                    <div class="subject-editor-stoploss-pane-title">聚合买入列表</div>
                    <div class="subject-editor-stoploss-pane-meta">点击左侧条目，右侧查看详细切片</div>
                  </div>

                  <div class="subject-editor-stoploss-master__list">
                    <article
                      v-for="row in detail.entries"
                      :key="row.entry_id"
                      class="subject-editor-stoploss-card"
                      :class="{ 'subject-editor-stoploss-card--active': row.entry_id === selectedStoplossEntry?.entry_id }"
                      @click="selectStoplossEntry(row.entry_id)"
                    >
                      <div class="subject-editor-stoploss-entry__head">
                        <div class="subject-editor-stoploss-entry__title-wrap">
                          <span class="subject-editor-stoploss-entry__title">{{ row.entryDisplayLabel }}</span>
                          <span
                            class="subject-editor-stoploss-entry__id"
                            :title="row.entry_id"
                          >
                            {{ row.entryIdLabel }}
                          </span>
                        </div>
                        <el-tag size="small" :type="row.entry_id === selectedStoplossEntry?.entry_id ? 'primary' : 'info'">
                          {{ row.entry_id === selectedStoplossEntry?.entry_id ? '当前查看' : '点击查看' }}
                        </el-tag>
                      </div>

                      <div class="subject-editor-stoploss-entry__meta" :title="row.entryMetaLabel">
                        <span class="subject-editor-stoploss-entry__meta-line">
                          <span class="subject-editor-stoploss-entry__meta-item subject-editor-stoploss-entry__meta-item--accent">
                            <span class="subject-editor-stoploss-entry__meta-label">买入价：</span>
                            <span class="subject-editor-stoploss-entry__meta-value">{{ row.entrySummaryDisplay.entryPriceLabel }}</span>
                          </span>
                          <span class="subject-editor-stoploss-entry__meta-separator">；</span>
                          <span class="subject-editor-stoploss-entry__meta-item">
                            <span class="subject-editor-stoploss-entry__meta-label">买入</span>
                            <span class="subject-editor-stoploss-entry__meta-value">{{ row.entrySummaryDisplay.originalQuantityLabel }}</span>
                          </span>
                          <span class="subject-editor-stoploss-entry__meta-item subject-editor-stoploss-entry__meta-item--accent">
                            <span class="subject-editor-stoploss-entry__meta-label">剩</span>
                            <span class="subject-editor-stoploss-entry__meta-value">{{ row.entrySummaryDisplay.remainingQuantityLabel }}</span>
                          </span>
                        </span>
                        <span class="subject-editor-stoploss-entry__meta-line">
                          <span class="subject-editor-stoploss-entry__meta-item">
                            <span class="subject-editor-stoploss-entry__meta-label">买入时间：</span>
                            <span class="subject-editor-stoploss-entry__meta-value">{{ row.entrySummaryDisplay.entryDateTimeLabel }}</span>
                          </span>
                          <span class="subject-editor-stoploss-entry__meta-separator">；</span>
                          <span class="subject-editor-stoploss-entry__meta-item subject-editor-stoploss-entry__meta-item--accent">
                            <span class="subject-editor-stoploss-entry__meta-label">剩余市值：</span>
                            <span class="subject-editor-stoploss-entry__meta-value">{{ row.entrySummaryDisplay.remainingMarketValueLabel }}</span>
                          </span>
                        </span>
                      </div>

                      <div class="subject-editor-stoploss-card__chips">
                        <StatusChip variant="muted">
                          聚合买入 <strong>{{ (row.aggregation_members || []).length }}</strong>
                        </StatusChip>
                        <StatusChip variant="muted">
                          切片 <strong>{{ (row.entry_slices || []).length }}</strong>
                        </StatusChip>
                        <StatusChip :variant="stoplossDrafts[row.entry_id].enabled ? 'danger' : 'muted'">
                          止损 <strong>{{ stoplossDrafts[row.entry_id].enabled ? '开启' : '关闭' }}</strong>
                        </StatusChip>
                      </div>

                      <div class="subject-editor-stoploss-card__editor" @click.stop>
                        <div class="subject-editor-stoploss-card__editor-grid">
                          <div class="subject-editor-stoploss-card__editor-field">
                            <span class="subject-editor-stoploss-card__editor-label">当前绑定</span>
                            <span class="workbench-code">{{ row.stoplossLabel }}</span>
                          </div>
                          <div class="subject-editor-stoploss-card__editor-field">
                            <span class="subject-editor-stoploss-card__editor-label">编辑价</span>
                            <el-input-number
                              v-model="stoplossDrafts[row.entry_id].stop_price"
                              size="small"
                              :min="0"
                              :step="0.01"
                              :precision="2"
                              controls-position="right"
                            />
                          </div>
                          <div class="subject-editor-stoploss-card__editor-field">
                            <span class="subject-editor-stoploss-card__editor-label">启用</span>
                            <el-switch
                              v-model="stoplossDrafts[row.entry_id].enabled"
                              size="small"
                              inline-prompt
                              active-text="开"
                              inactive-text="关"
                            />
                          </div>
                          <div class="subject-editor-stoploss-card__editor-actions">
                            <el-button
                              type="primary"
                              text
                              :loading="savingStoploss[row.entry_id]"
                              @click="handleSaveStoplossClick(row.entry_id)"
                            >
                              保存
                            </el-button>
                          </div>
                        </div>
                      </div>
                    </article>
                  </div>
                </section>

                <section class="subject-editor-stoploss-detail">
                  <div class="subject-editor-stoploss-pane-header">
                    <div class="subject-editor-stoploss-pane-title">切片明细</div>
                    <div v-if="selectedStoplossEntry" class="subject-editor-stoploss-pane-meta">
                      {{ (selectedStoplossEntry.entry_slices || []).length }} 条 open 切片
                    </div>
                  </div>

                  <template v-if="selectedStoplossEntry">
                    <section class="subject-editor-stoploss-entry__detail-section">
                      <div class="subject-editor-stoploss-entry__detail-header">
                        <div class="subject-editor-stoploss-entry__detail-title">切片明细</div>
                        <div class="subject-editor-stoploss-entry__detail-meta">
                          {{ (selectedStoplossEntry.entry_slices || []).length }} 条
                        </div>
                      </div>
                      <div
                        v-if="!(selectedStoplossEntry.entry_slices || []).length"
                        class="subject-editor-stoploss-entry__detail-empty"
                      >
                        当前入口没有 open 切片。
                      </div>
                      <div v-else class="subject-editor-stoploss-entry__slice-table">
                        <div class="subject-editor-stoploss-entry__slice-head">
                          <span>序号</span>
                          <span>守护价</span>
                          <span>原始数量</span>
                          <span>剩余数量</span>
                          <span>剩余市值</span>
                        </div>
                        <div
                          v-for="slice in selectedStoplossEntry.entry_slices"
                          :key="slice.entry_slice_id"
                          class="subject-editor-stoploss-entry__slice-row"
                        >
                          <span class="workbench-code">{{ formatInteger(slice.slice_seq) }}</span>
                          <span class="workbench-code">{{ formatPrice(slice.guardian_price) }}</span>
                          <span class="workbench-code">{{ formatInteger(slice.original_quantity) }}</span>
                          <span class="workbench-code">{{ formatInteger(slice.remaining_quantity) }}</span>
                          <span class="workbench-code">{{ formatWanAmount(slice.remaining_amount) }}</span>
                        </div>
                      </div>
                    </section>
                  </template>

                  <div v-else class="subject-editor-stoploss-entry__detail-empty">
                    左侧先选择一个聚合买入。
                  </div>
                </section>
              </div>

              <section v-else class="workbench-empty">
                当前标的没有 open entry。
              </section>
            </WorkbenchDetailPanel>
          </template>

          <section v-else class="workbench-empty">
            左侧先选择一个标的。
          </section>
        </main>
      </div>
    </div>
  </WorkbenchPage>
</template>

<script setup>
import { computed, onMounted, reactive, toRefs, watch } from 'vue'
import { ElMessage } from 'element-plus'

import StatusChip from '../components/workbench/StatusChip.vue'
import WorkbenchDetailPanel from '../components/workbench/WorkbenchDetailPanel.vue'
import WorkbenchLedgerPanel from '../components/workbench/WorkbenchLedgerPanel.vue'
import WorkbenchPage from '../components/workbench/WorkbenchPage.vue'
import WorkbenchToolbar from '../components/workbench/WorkbenchToolbar.vue'
import { subjectManagementApi } from '@/api/subjectManagementApi'
import MyHeader from '@/views/MyHeader.vue'
import {
  DEFAULT_OVERVIEW_PAGE_SIZE,
  OVERVIEW_PAGE_SIZE_OPTIONS,
  paginateOverviewRows,
} from '@/views/subjectManagementOverviewPagination.mjs'
import {
  buildDenseConfigRows,
  buildDetailSummaryChips,
  createSubjectManagementActions,
} from '@/views/subjectManagement.mjs'
import { createSubjectManagementPageController } from '@/views/subjectManagementPage.mjs'
import { formatBeijingTimestamp } from '../tool/beijingTime.mjs'

const formatPrice = (value) => {
  if (value === null || value === undefined || value === '') return '-'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '-'
  return Number.isInteger(parsed) ? parsed.toFixed(1) : String(parsed)
}

const formatInteger = (value) => {
  if (value === null || value === undefined || value === '') return '-'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '-'
  return String(Math.trunc(parsed))
}

const formatWanAmount = (value) => {
  if (value === null || value === undefined || value === '') return '-'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '-'
  return `${(parsed / 10000).toFixed(2)} 万`
}

const formatDateTime = (value) => {
  return formatBeijingTimestamp(value)
}

const resolveStateChipVariant = (state) => {
  if (state === 'ALLOW_OPEN') return 'success'
  if (state === 'HOLDING_ONLY') return 'warning'
  if (state === 'FORCE_PROFIT_REDUCE') return 'danger'
  return 'muted'
}

const actions = createSubjectManagementActions(subjectManagementApi)
const {
  state,
  holdingCount,
  activeStoplossCount,
  refreshOverview,
  reloadCurrentSymbol,
  selectSymbol,
  handleSaveConfigBundle,
  handleSaveStoploss,
} = createSubjectManagementPageController({
  actions,
  notify: ElMessage,
  reactiveImpl: reactive,
  computedImpl: computed,
})

const {
  loadingOverview,
  loadingDetail,
  savingConfigBundle,
  pageError,
  overviewRows,
  selectedSymbol,
  detail,
  mustPoolDraft,
  positionLimitDraft,
  stoplossDrafts,
  savingStoploss,
} = toRefs(state)

const filters = reactive({
  keyword: '',
  category: '',
  onlyMustPool: false,
  onlyHolding: false,
  onlyTakeprofit: false,
  onlyStoploss: false,
})

const overviewPagination = reactive({
  page: 1,
  pageSize: DEFAULT_OVERVIEW_PAGE_SIZE,
})

const overviewPageSizeOptions = OVERVIEW_PAGE_SIZE_OPTIONS

const categoryOptions = computed(() => {
  return Array.from(new Set((overviewRows.value || []).map((row) => String(row.category || '').trim()).filter(Boolean)))
    .sort((left, right) => left.localeCompare(right))
})

const filteredOverviewRows = computed(() => {
  const keyword = String(filters.keyword || '').trim().toLowerCase()
  return (overviewRows.value || []).filter((row) => {
    if (filters.category && row.category !== filters.category) return false
    if (filters.onlyMustPool && !row.hasMustPoolConfig) return false
    if (filters.onlyHolding && !row.has_position) return false
    if (filters.onlyTakeprofit && !row.hasTakeprofitConfig) return false
    if (filters.onlyStoploss && !row.hasActiveStoploss) return false
    if (!keyword) return true
    return [
      row.symbol,
      row.name,
      row.category,
      row.positionLimitSummaryLabel,
      row.guardianSummaryLabel,
      row.takeprofitSummaryLabel,
    ]
      .join(' ')
      .toLowerCase()
      .includes(keyword)
  })
})

const overviewPage = computed(() => paginateOverviewRows(
  filteredOverviewRows.value,
  overviewPagination,
))

const pmSummary = computed(() => detail.value?.positionManagementSummary || {
  effective_state: '',
  allow_open_min_bail: null,
  holding_only_min_bail: null,
})

const pmStateChipVariant = computed(() => resolveStateChipVariant(pmSummary.value.effective_state))

const detailSummaryChips = computed(() => buildDetailSummaryChips(detail.value || {}))
const configEditorRows = computed(() => buildDenseConfigRows(detail.value || {}))
const stoplossPaneState = reactive({
  selectedEntryId: '',
})
const selectedStoplossEntry = computed(() => {
  const entries = detail.value?.entries || []
  return entries.find((row) => row.entry_id === stoplossPaneState.selectedEntryId) || entries[0] || null
})

watch(
  () => [
    filters.keyword,
    filters.category,
    filters.onlyMustPool,
    filters.onlyHolding,
    filters.onlyTakeprofit,
    filters.onlyStoploss,
  ],
  () => {
    overviewPagination.page = 1
  },
)

watch(
  () => [overviewPage.value.page, overviewPage.value.pageSize],
  ([page, pageSize]) => {
    if (overviewPagination.page !== page) {
      overviewPagination.page = page
    }
    if (overviewPagination.pageSize !== pageSize) {
      overviewPagination.pageSize = pageSize
    }
  },
  { immediate: true },
)

watch(
  () => (detail.value?.entries || []).map((row) => row.entry_id).filter(Boolean),
  (entryIds) => {
    if (!entryIds.length) {
      stoplossPaneState.selectedEntryId = ''
      return
    }
    if (!entryIds.includes(stoplossPaneState.selectedEntryId)) {
      stoplossPaneState.selectedEntryId = entryIds[0]
    }
  },
  { immediate: true },
)

const overviewRowClassName = ({ row }) => {
  return row?.symbol === selectedSymbol.value ? 'subject-table-row--active' : ''
}

const resolveConfigRowTagType = (row) => {
  if (row?.statusTone) {
    return row.statusTone
  }
  if (row?.key === 'stop_loss_price') {
    return 'danger'
  }
  if (row?.key === 'position_limit_value') {
    return row?.statusLabel === '单独设置' ? 'warning' : 'info'
  }
  return 'info'
}

const handleRowClick = async (row) => {
  await selectSymbol(row?.symbol)
}

const handleOverviewPageChange = (page) => {
  overviewPagination.page = page
}

const handleOverviewPageSizeChange = (pageSize) => {
  overviewPagination.pageSize = pageSize
  overviewPagination.page = 1
}

const handleSaveConfigBundleClick = async () => {
  const parsed = Number(positionLimitDraft.value?.limit)
  if (!Number.isFinite(parsed) || parsed <= 0) {
    ElMessage.warning('请先填写有效的单标的上限')
    return
  }
  await handleSaveConfigBundle()
}

const handleSaveStoplossClick = async (entryId) => {
  const draft = stoplossDrafts.value?.[entryId] || {}
  if (draft.enabled) {
    const parsed = Number(draft.stop_price)
    if (!Number.isFinite(parsed) || parsed <= 0) {
      ElMessage.warning(`开启止损前请先填写 ${entryId} 的 stop_price`)
      return
    }
  }
  await handleSaveStoploss(entryId)
}

const selectStoplossEntry = (entryId) => {
  if (!entryId) return
  stoplossPaneState.selectedEntryId = entryId
}

onMounted(async () => {
  await refreshOverview()
})
</script>

<style scoped>
.subject-management-page {
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
}

.subject-management-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.subject-toolbar-filters {
  display: grid;
  grid-template-columns: minmax(220px, 1.5fr) minmax(140px, 0.8fr) minmax(0, 2fr);
  gap: 10px;
  align-items: center;
}

.subject-filter-input,
.subject-filter-select {
  width: 100%;
}

.subject-filter-checks {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  min-width: 0;
}

.subject-layout {
  display: grid;
  grid-template-columns: minmax(420px, 0.92fr) minmax(0, 1.08fr);
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  align-items: stretch;
  overflow: hidden;
}

.subject-overview-panel,
.subject-editor-stack {
  min-height: 0;
}

.subject-overview-panel {
  overflow: hidden;
}

.subject-overview-table-wrap {
  overflow: hidden;
}

.subject-editor-stack {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  overflow: auto;
  scrollbar-gutter: stable;
}

.subject-overview-panel :deep(.el-table) {
  height: 100%;
}

.subject-overview-panel :deep(.subject-table-row--active > td.el-table__cell) {
  background: #f4f9ff;
}

.subject-overview-pagination {
  display: flex;
  justify-content: flex-end;
  padding-top: 10px;
}

.subject-code-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.subject-summary-stack,
.subject-takeprofit-grid {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.subject-summary-line,
.subject-takeprofit-line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  font-size: 12px;
  color: #606266;
  line-height: 1.45;
}

.subject-inline-state {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 34px;
  padding: 1px 6px;
  border-radius: 999px;
  background: #eef2f7;
  color: #64748b;
  font-size: 11px;
}

.subject-inline-state.active {
  background: #ecfdf3;
  color: #15803d;
}

.subject-table {
  width: 100%;
}

.subject-editor-summarybar {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1.5fr) auto;
  gap: 10px;
  align-items: start;
  padding: 10px 12px;
  border: 1px solid #d9e1ec;
  border-radius: 10px;
  background: linear-gradient(180deg, #fbfdff 0%, #f4f8fc 100%);
}

.subject-editor-summarybar__main,
.subject-editor-summarybar__chips {
  min-width: 0;
}

.subject-editor-summarybar__headline {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: #1f2937;
  line-height: 1.3;
}

.subject-editor-summarybar__name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.subject-editor-summarybar__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
  margin-top: 4px;
  font-size: 12px;
  color: #606266;
}

.subject-editor-summarybar__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.subject-editor-summarybar__actions {
  display: flex;
  justify-content: flex-end;
}

.subject-editor-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
  padding: 0 10px;
  border: 1px solid #dbe5f0;
  border-radius: 999px;
  background: #f7f9fc;
  color: #475569;
  font-size: 12px;
  white-space: nowrap;
}

.subject-editor-chip__label {
  color: #64748b;
}

.subject-editor-table-panel {
  padding: 10px 12px 12px;
}

.subject-editor-table-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

.subject-editor-table-heading {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.subject-editor-table-title {
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
}

.subject-editor-table-subtitle,
.subject-editor-table-meta,
.subject-editor-note {
  font-size: 12px;
  color: #6b7280;
  line-height: 1.4;
}

.subject-editor-current {
  color: #1f2937;
}

.subject-editor-stoploss-layout {
  display: grid;
  grid-template-columns: minmax(340px, 0.95fr) minmax(360px, 1.05fr);
  gap: 12px;
  min-height: 0;
}

.subject-editor-stoploss-master,
.subject-editor-stoploss-detail {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  padding: 10px;
  border: 1px solid #dbe5f0;
  border-radius: 10px;
  background: linear-gradient(180deg, #fbfdff 0%, #f7fbff 100%);
}

.subject-editor-stoploss-pane-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.subject-editor-stoploss-pane-title {
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
}

.subject-editor-stoploss-pane-meta {
  font-size: 12px;
  color: #64748b;
  text-align: right;
}

.subject-editor-stoploss-master__list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  overflow: auto;
  padding-right: 2px;
}

.subject-editor-stoploss-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid #dbe5f0;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.subject-editor-stoploss-card:hover {
  border-color: #bfd6ee;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06);
  transform: translateY(-1px);
}

.subject-editor-stoploss-card--active {
  border-color: #60a5fa;
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.12);
  background: linear-gradient(180deg, #ffffff 0%, #f5faff 100%);
}

.subject-editor-stoploss-card__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.subject-editor-stoploss-card__editor {
  padding-top: 4px;
  border-top: 1px dashed #dbe5f0;
}

.subject-editor-stoploss-card__editor-grid {
  display: grid;
  grid-template-columns: minmax(86px, 0.9fr) minmax(136px, 1.25fr) minmax(84px, 0.8fr) auto;
  gap: 10px;
  align-items: end;
}

.subject-editor-stoploss-card__editor-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.subject-editor-stoploss-card__editor-label {
  font-size: 11px;
  color: #64748b;
}

.subject-editor-stoploss-card__editor-actions {
  display: flex;
  justify-content: flex-end;
}

.subject-editor-stoploss-entry__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.subject-editor-stoploss-entry__title-wrap {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.subject-editor-stoploss-entry__title {
  font-size: 12px;
  font-weight: 600;
  color: #1f2937;
}

.subject-editor-stoploss-entry__id {
  color: #64748b;
  font-size: 11px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}

.subject-editor-stoploss-entry__meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.subject-editor-stoploss-entry__meta-line {
  display: flex;
  flex-wrap: wrap;
  gap: 0 6px;
  min-width: 0;
  font-size: 12px;
  line-height: 1.45;
}

.subject-editor-stoploss-entry__meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  color: #475569;
}

.subject-editor-stoploss-entry__meta-item--accent .subject-editor-stoploss-entry__meta-value {
  color: #0f766e;
}

.subject-editor-stoploss-entry__meta-label {
  color: #64748b;
}

.subject-editor-stoploss-entry__meta-value {
  color: #1f2937;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}

.subject-editor-stoploss-entry__meta-separator {
  color: #94a3b8;
}

.subject-editor-stoploss-entry__details {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid #dbe5f0;
  border-radius: 8px;
  background: #f8fbff;
}

.subject-editor-stoploss-entry__detail-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.subject-editor-stoploss-entry__detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.subject-editor-stoploss-entry__detail-title {
  font-size: 12px;
  font-weight: 600;
  color: #1f2937;
}

.subject-editor-stoploss-entry__detail-meta,
.subject-editor-stoploss-entry__detail-empty {
  font-size: 12px;
  color: #64748b;
}

.subject-editor-stoploss-entry__slice-table {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.subject-editor-stoploss-entry__slice-head,
.subject-editor-stoploss-entry__slice-row {
  display: grid;
  grid-template-columns: 56px 78px 88px 88px minmax(84px, 1fr);
  gap: 8px;
  align-items: center;
  font-size: 12px;
  line-height: 1.45;
}

.subject-editor-stoploss-entry__slice-head {
  color: #64748b;
}

.subject-editor-stoploss-entry__slice-row {
  color: #1f2937;
}

.subject-editor-config-table :deep(.el-input-number),
.subject-editor-takeprofit-table :deep(.el-input-number),
.subject-editor-stoploss-table :deep(.el-input-number),
.subject-editor-stoploss-card__editor-grid :deep(.el-input-number) {
  width: 100%;
}

.subject-editor-config-table :deep(.el-table__cell),
.subject-editor-takeprofit-table :deep(.el-table__cell),
.subject-editor-stoploss-table :deep(.el-table__cell) {
  padding-top: 7px;
  padding-bottom: 7px;
}

@media (max-width: 1360px) {
  .subject-management-body {
    overflow: auto;
  }

  .subject-layout {
    grid-template-columns: 1fr;
    min-height: auto;
    overflow: visible;
  }

  .subject-editor-stack {
    overflow: visible;
  }

  .subject-editor-stoploss-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 1120px) {
  .subject-toolbar-filters,
  .subject-editor-summarybar {
    grid-template-columns: 1fr;
  }

  .subject-editor-summarybar__actions {
    justify-content: flex-start;
  }

  .subject-editor-stoploss-pane-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .subject-editor-stoploss-pane-meta {
    text-align: left;
  }

  .subject-editor-stoploss-card__editor-grid {
    grid-template-columns: 1fr;
  }

  .subject-editor-stoploss-card__editor-actions {
    justify-content: flex-start;
  }
}
</style>
