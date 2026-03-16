<template>
  <div class="workbench-page subject-management-page">
    <MyHeader />

    <div class="workbench-body subject-management-body">
      <section class="workbench-toolbar">
        <div class="workbench-toolbar__header">
          <div class="workbench-title-group">
            <div class="workbench-page-title">标的管理</div>
            <div class="workbench-page-meta">
              <span>左侧高密度汇总当前配置，右侧集中编辑基础设置、Guardian、止盈三层与 buy lot 止损。</span>
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
          <span class="workbench-summary-chip">
            总标的 <strong>{{ overviewRows.length }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--muted">
            当前筛选 <strong>{{ filteredOverviewRows.length }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--success">
            持仓中 <strong>{{ holdingCount }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--warning">
            活跃止损 <strong>{{ activeStoplossCount }}</strong>
          </span>
          <span v-if="pmSummary.effective_state" class="workbench-summary-chip" :class="pmStateChipClass">
            门禁 <strong>{{ pmSummary.effective_state }}</strong>
          </span>
          <span v-if="pmSummary.allow_open_min_bail !== null" class="workbench-summary-chip workbench-summary-chip--muted">
            开仓阈值 <strong>{{ formatInteger(pmSummary.allow_open_min_bail) }}</strong>
          </span>
          <span v-if="pmSummary.holding_only_min_bail !== null" class="workbench-summary-chip workbench-summary-chip--muted">
            持仓阈值 <strong>{{ formatInteger(pmSummary.holding_only_min_bail) }}</strong>
          </span>
        </div>
      </section>

      <div class="subject-layout">
        <section class="workbench-panel subject-overview-panel">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">标的总览</div>
              <p class="workbench-panel__desc">左表直接展示当前配置摘要，不再依赖卡片。点击任一行，右栏切换到该标的编辑。</p>
            </div>
            <div class="workbench-panel__meta">
              <span>{{ filteredOverviewRows.length }} 条</span>
            </div>
          </div>

          <div class="workbench-table-wrap">
            <el-table
              v-loading="loadingOverview"
              :data="filteredOverviewRows"
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
                    <div class="subject-summary-line">{{ row.must_pool.forever ? '永久跟踪' : '普通标的' }}</div>
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
                    <div class="subject-summary-line workbench-code">{{ row.stoplossActiveCount }} / {{ row.openBuyLotCount }}</div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="运行态" min-width="172">
                <template #default="{ row }">
                  <div class="subject-summary-stack">
                    <div class="subject-summary-line">持仓 {{ row.position_quantity }} 股</div>
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
        </section>

        <main class="subject-editor-stack">
          <section v-if="detail" class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">
                  {{ detail.name || detail.symbol }}
                  <span class="workbench-muted workbench-code">{{ detail.symbol }}</span>
                </div>
                <div class="workbench-panel__meta">
                  <span>分类 {{ detail.category || '-' }}</span>
                  <span>/</span>
                  <span>当前持仓 {{ detail.runtimeSummary.position_quantity || 0 }} 股</span>
                  <span>/</span>
                  <span>open buy lot {{ detail.buyLots.length }}</span>
                </div>
              </div>

              <div class="workbench-panel__actions">
                <el-button :loading="loadingDetail" @click="reloadCurrentSymbol">刷新详情</el-button>
              </div>
            </div>
          </section>

          <section v-if="detail" class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">基础设置</div>
                <p class="workbench-panel__desc">编辑 `must_pool` 的基础真值，包括分类、止损价和首笔/常规金额。</p>
              </div>
              <div class="workbench-panel__actions">
                <el-button type="primary" :loading="savingMustPool" @click="handleSaveMustPool">保存基础设置</el-button>
              </div>
            </div>

            <el-form :model="mustPoolDraft" label-width="88px" class="subject-form-grid" size="small">
              <el-form-item label="分类">
                <el-input v-model="mustPoolDraft.category" placeholder="如：银行 / 白酒 / 守护池" />
              </el-form-item>
              <el-form-item label="止损价">
                <el-input-number
                  v-model="mustPoolDraft.stop_loss_price"
                  :min="0"
                  :step="0.01"
                  :precision="2"
                  controls-position="right"
                />
              </el-form-item>
              <el-form-item label="首笔金额">
                <el-input-number
                  v-model="mustPoolDraft.initial_lot_amount"
                  :min="0"
                  :step="1000"
                  controls-position="right"
                />
              </el-form-item>
              <el-form-item label="常规金额">
                <el-input-number
                  v-model="mustPoolDraft.lot_amount"
                  :min="0"
                  :step="1000"
                  controls-position="right"
                />
              </el-form-item>
              <el-form-item label="永久跟踪">
                <el-switch v-model="mustPoolDraft.forever" inline-prompt active-text="是" inactive-text="否" />
              </el-form-item>
            </el-form>
          </section>

          <section v-if="detail" class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">Guardian 加仓设置</div>
                <p class="workbench-panel__desc">编辑 BUY-1/2/3 阶梯价；运行态只读展示最后一次命中和 buy_active。</p>
              </div>
              <div class="workbench-panel__actions">
                <el-button type="primary" :loading="savingGuardian" @click="handleSaveGuardian">保存 Guardian 设置</el-button>
              </div>
            </div>

            <div class="subject-guardian-grid">
              <el-form :model="guardianDraft" label-width="88px" class="subject-form-grid" size="small">
                <el-form-item label="启用">
                  <el-switch v-model="guardianDraft.enabled" inline-prompt active-text="开" inactive-text="关" />
                </el-form-item>
                <el-form-item label="BUY-1">
                  <el-input-number
                    v-model="guardianDraft.buy_1"
                    :min="0"
                    :step="0.01"
                    :precision="2"
                    controls-position="right"
                  />
                </el-form-item>
                <el-form-item label="BUY-2">
                  <el-input-number
                    v-model="guardianDraft.buy_2"
                    :min="0"
                    :step="0.01"
                    :precision="2"
                    controls-position="right"
                  />
                </el-form-item>
                <el-form-item label="BUY-3">
                  <el-input-number
                    v-model="guardianDraft.buy_3"
                    :min="0"
                    :step="0.01"
                    :precision="2"
                    controls-position="right"
                  />
                </el-form-item>
              </el-form>

              <div class="workbench-block workbench-block--muted subject-runtime-block">
                <div class="subject-runtime-block__title">当前运行态</div>
                <div class="subject-summary-stack">
                  <div class="subject-summary-line">buy_active {{ guardianBuyActiveLabel }}</div>
                  <div class="subject-summary-line">last_hit_level {{ detail.guardianState.last_hit_level || '-' }}</div>
                  <div class="subject-summary-line">last_hit_price {{ formatPrice(detail.guardianState.last_hit_price) }}</div>
                  <div class="subject-summary-line workbench-code">{{ formatDateTime(detail.guardianState.last_hit_signal_time) }}</div>
                </div>
              </div>
            </div>
          </section>

          <section v-if="detail" class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">止盈止损</div>
                <p class="workbench-panel__desc">止盈固定至少三层显示，带启停开关；止损继续按 open buy lot 单独维护。</p>
              </div>
              <div class="workbench-panel__actions">
                <el-button type="primary" :loading="savingTakeprofit" @click="handleSaveTakeprofitClick">保存止盈层级</el-button>
              </div>
            </div>

            <el-table :data="takeprofitDrafts" size="small" border class="subject-table subject-takeprofit-table">
              <el-table-column label="Level" width="88">
                <template #default="{ row }">
                  <strong>L{{ row.level }}</strong>
                </template>
              </el-table-column>
              <el-table-column label="Price" min-width="156">
                <template #default="{ row }">
                  <el-input-number
                    v-model="row.price"
                    :min="0"
                    :step="0.01"
                    :precision="2"
                    controls-position="right"
                  />
                </template>
              </el-table-column>
              <el-table-column label="Enabled" width="126">
                <template #default="{ row }">
                  <el-switch
                    v-model="row.manual_enabled"
                    inline-prompt
                    active-text="开"
                    inactive-text="关"
                  />
                </template>
              </el-table-column>
              <el-table-column label="Armed" width="108">
                <template #default="{ row }">
                  <el-tag :type="armedLevels[String(row.level)] ? 'success' : 'info'">
                    {{ armedLevels[String(row.level)] ? '已布防' : '未布防' }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>

            <div class="workbench-panel__header subject-subsection-header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">按 buy lot 止损</div>
                <p class="workbench-panel__desc">只展示 open buy lot。开启止损时，`stop_price` 必须填写。</p>
              </div>
            </div>

            <el-table :data="detail.buyLots" size="small" border class="subject-table">
              <el-table-column prop="buy_lot_id" label="Buy Lot" min-width="168" />
              <el-table-column label="买入时间" min-width="142">
                <template #default="{ row }">
                  <span class="workbench-code">{{ row.date || '-' }} {{ row.time || '' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="买入价" width="92">
                <template #default="{ row }">
                  <span class="workbench-code">{{ formatPrice(row.buy_price_real) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="原始/剩余" width="116">
                <template #default="{ row }">
                  <span class="workbench-code">{{ row.original_quantity }} / {{ row.remaining_quantity }}</span>
                </template>
              </el-table-column>
              <el-table-column label="Stop Price" min-width="156">
                <template #default="{ row }">
                  <el-input-number
                    v-model="stoplossDrafts[row.buy_lot_id].stop_price"
                    :min="0"
                    :step="0.01"
                    :precision="2"
                    controls-position="right"
                  />
                </template>
              </el-table-column>
              <el-table-column label="Enabled" width="118">
                <template #default="{ row }">
                  <el-switch
                    v-model="stoplossDrafts[row.buy_lot_id].enabled"
                    inline-prompt
                    active-text="开"
                    inactive-text="关"
                  />
                </template>
              </el-table-column>
              <el-table-column label="当前绑定" width="96">
                <template #default="{ row }">
                  <span class="workbench-code">{{ row.stoplossLabel }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="88" fixed="right">
                <template #default="{ row }">
                  <el-button
                    type="primary"
                    text
                    :loading="savingStoploss[row.buy_lot_id]"
                    @click="handleSaveStoplossClick(row.buy_lot_id)"
                  >
                    保存
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </section>

          <section v-if="detail" class="workbench-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">只读运行态</div>
                <p class="workbench-panel__desc">运行态只读展示，账户级仓位门禁仅做联动摘要，不在本页编辑。</p>
              </div>
            </div>

            <div class="subject-runtime-grid">
              <div class="workbench-block workbench-block--muted subject-runtime-block">
                <div class="subject-runtime-block__title">持仓摘要</div>
                <div class="subject-summary-stack">
                  <div class="subject-summary-line">持仓数量 {{ detail.runtimeSummary.position_quantity || 0 }} 股</div>
                  <div class="subject-summary-line">持仓金额 {{ formatPrice(detail.runtimeSummary.position_amount) }}</div>
                  <div class="subject-summary-line">最近触发类型 {{ detail.runtimeSummary.last_trigger_kind || '-' }}</div>
                  <div class="subject-summary-line workbench-code">{{ formatDateTime(detail.runtimeSummary.last_trigger_time) }}</div>
                </div>
              </div>

              <div class="workbench-block workbench-block--muted subject-runtime-block">
                <div class="subject-runtime-block__title">Guardian 运行态</div>
                <div class="subject-summary-stack">
                  <div class="subject-summary-line">buy_active {{ guardianBuyActiveLabel }}</div>
                  <div class="subject-summary-line">last_hit_level {{ detail.guardianState.last_hit_level || '-' }}</div>
                  <div class="subject-summary-line">last_reset_reason {{ detail.guardianState.last_reset_reason || '-' }}</div>
                  <div class="subject-summary-line workbench-code">{{ formatDateTime(detail.guardianState.last_hit_signal_time) }}</div>
                </div>
              </div>

              <div class="workbench-block workbench-block--muted subject-runtime-block">
                <div class="subject-runtime-block__title">仓位门禁摘要</div>
                <div class="subject-summary-stack">
                  <div class="subject-summary-line">effective_state {{ pmSummary.effective_state || '-' }}</div>
                  <div class="subject-summary-line">allow_open_min_bail {{ formatInteger(pmSummary.allow_open_min_bail) }}</div>
                  <div class="subject-summary-line">holding_only_min_bail {{ formatInteger(pmSummary.holding_only_min_bail) }}</div>
                  <div class="subject-summary-line">本页只读联动展示</div>
                </div>
              </div>
            </div>
          </section>

          <section v-else class="workbench-empty">
            左侧先选择一个标的。
          </section>
        </main>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, toRefs } from 'vue'
import { ElMessage } from 'element-plus'

import { subjectManagementApi } from '@/api/subjectManagementApi'
import MyHeader from '@/views/MyHeader.vue'
import { createSubjectManagementActions } from '@/views/subjectManagement.mjs'
import { createSubjectManagementPageController } from '@/views/subjectManagementPage.mjs'

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

const formatDateTime = (value) => {
  const text = String(value || '').trim()
  return text || '-'
}

const resolveStateChipClass = (state) => {
  if (state === 'ALLOW_OPEN') return 'workbench-summary-chip--success'
  if (state === 'HOLDING_ONLY') return 'workbench-summary-chip--warning'
  if (state === 'FORCE_PROFIT_REDUCE') return 'workbench-summary-chip--danger'
  return 'workbench-summary-chip--muted'
}

const actions = createSubjectManagementActions(subjectManagementApi)
const {
  state,
  holdingCount,
  activeStoplossCount,
  refreshOverview,
  reloadCurrentSymbol,
  selectSymbol,
  handleSaveMustPool,
  handleSaveGuardian,
  handleSaveTakeprofit,
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
  savingMustPool,
  savingGuardian,
  savingTakeprofit,
  pageError,
  overviewRows,
  selectedSymbol,
  detail,
  mustPoolDraft,
  guardianDraft,
  takeprofitDrafts,
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
      row.guardianSummaryLabel,
      row.takeprofitSummaryLabel,
    ]
      .join(' ')
      .toLowerCase()
      .includes(keyword)
  })
})

const pmSummary = computed(() => detail.value?.positionManagementSummary || {
  effective_state: '',
  allow_open_min_bail: null,
  holding_only_min_bail: null,
})

const pmStateChipClass = computed(() => resolveStateChipClass(pmSummary.value.effective_state))

const guardianBuyActiveLabel = computed(() => {
  const rows = Array.isArray(detail.value?.guardianState?.buy_active) ? detail.value.guardianState.buy_active : []
  if (!rows.length) return '-'
  return rows.map((item, index) => `B${index + 1}:${item ? '开' : '关'}`).join(' / ')
})

const armedLevels = computed(() => detail.value?.takeprofit?.state?.armed_levels || {})

const overviewRowClassName = ({ row }) => {
  return row?.symbol === selectedSymbol.value ? 'subject-table-row--active' : ''
}

const handleRowClick = async (row) => {
  await selectSymbol(row?.symbol)
}

const handleSaveTakeprofitClick = async () => {
  const invalidLevel = (takeprofitDrafts.value || []).find((row) => {
    const parsed = Number(row?.price)
    return !Number.isFinite(parsed) || parsed <= 0
  })
  if (invalidLevel) {
    ElMessage.warning(`请先填写 L${invalidLevel.level} 的止盈价`)
    return
  }
  await handleSaveTakeprofit()
}

const handleSaveStoplossClick = async (buyLotId) => {
  const draft = stoplossDrafts.value?.[buyLotId] || {}
  if (draft.enabled) {
    const parsed = Number(draft.stop_price)
    if (!Number.isFinite(parsed) || parsed <= 0) {
      ElMessage.warning(`开启止损前请先填写 ${buyLotId} 的 stop_price`)
      return
    }
  }
  await handleSaveStoploss(buyLotId)
}

onMounted(async () => {
  await refreshOverview()
})
</script>

<style scoped>
.subject-management-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
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
  grid-template-columns: minmax(540px, 42%) minmax(0, 1fr);
  gap: 12px;
  min-height: calc(100vh - 228px);
}

.subject-overview-panel,
.subject-editor-stack {
  min-height: 0;
}

.subject-editor-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.subject-overview-panel :deep(.el-table) {
  height: 100%;
}

.subject-overview-panel :deep(.subject-table-row--active > td.el-table__cell) {
  background: #f4f9ff;
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

.subject-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 12px;
}

.subject-form-grid :deep(.el-form-item) {
  margin-bottom: 12px;
}

.subject-guardian-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(220px, 0.85fr);
  gap: 12px;
}

.subject-runtime-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.subject-runtime-block {
  gap: 8px;
}

.subject-runtime-block__title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.subject-subsection-header {
  margin-top: 6px;
}

.subject-table {
  width: 100%;
}

@media (max-width: 1380px) {
  .subject-layout {
    grid-template-columns: 1fr;
    min-height: auto;
  }
}

@media (max-width: 1120px) {
  .subject-toolbar-filters,
  .subject-guardian-grid,
  .subject-runtime-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 840px) {
  .subject-form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
