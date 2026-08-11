<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  DEFAULT_STATE,
  DIMENSION_META,
  EVIDENCE_GRADES,
  GRADE_META,
  SORT_OPTIONS,
  TIER_META,
  buildQueryWithState,
  decodeStateFromUrl,
  encodeStateToUrl,
  fetchFundamental,
  filterRows,
  formatMetric,
  loadStars,
  queryToSearch,
  saveStars,
  sortRows,
  toggleStar,
  virtualSlice,
} from './clxFundamentalRankingLogic.mjs'

const props = defineProps({
  tradeDate: {
    type: String,
    default: '',
  },
  industryFilter: {
    type: Array,
    default: () => [],
  },
  filterVersion: {
    type: Number,
    default: 0,
  },
})

const emit = defineEmits(['select', 'selection-time', 'pre-status', 'stats-request'])

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const error = ref('')
const latest = ref(null)
const ranking = ref(null)
const state = reactive({ ...DEFAULT_STATE })
const stars = ref([])
const expandedSymbol = ref('')
const listEl = ref(null)
const scrollTop = ref(0)
const viewportHeight = ref(600)
const filterPanelOpen = ref(false)

const ROW_HEIGHT = { compact: 34, comfortable: 52 }
const EXPANDED_ROW_HEIGHT = 44

const rowHeight = computed(() => ROW_HEIGHT[state.density] || ROW_HEIGHT.compact)

const sortedRows = computed(() =>
  sortRows(ranking.value?.rows || [], state.sort, { zoneFixed: true }),
)

const filteredRows = computed(() =>
  filterRows(sortedRows.value, {
    q: state.q,
    industries: state.industries,
    evidenceGrades: state.evidenceGrades,
    riskOnly: state.riskOnly,
    tiers: state.tiers,
    minGrades: state.minGrades,
    starOnly: state.starOnly,
    stars: stars.value,
  }),
)

const deepCount = computed(() => ranking.value?.counts?.deep ?? 0)
const snapshotCount = computed(() => ranking.value?.counts?.snapshot ?? 0)

const industries = computed(() => {
  const map = new Map()
  for (const row of ranking.value?.rows || []) {
    const name = row.primaryGroup || '未映射行业'
    map.set(name, (map.get(name) || 0) + 1)
  }
  return [...map.entries()].sort((a, b) => b[1] - a[1]).map(([name, count]) => ({ name, count }))
})

const rowOffsets = computed(() => {
  const offsets = []
  let y = 0
  for (const row of filteredRows.value) {
    offsets.push(y)
    y += row.symbol === expandedSymbol.value ? rowHeight.value + EXPANDED_ROW_HEIGHT : rowHeight.value
  }
  return { offsets, totalHeight: y }
})

const visible = computed(() => {
  const { start, end } = virtualSlice({
    rows: filteredRows.value,
    scrollTop: scrollTop.value,
    viewportHeight: viewportHeight.value,
    rowHeight: rowHeight.value,
    overscan: 12,
  })
  const rows = filteredRows.value.slice(start, end)
  return { start, end, rows }
})

const selectedIndex = computed(() =>
  filteredRows.value.findIndex((row) => row.symbol === state.selected),
)

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const result = await fetchFundamental()
    latest.value = result.latest
    ranking.value = result.ranking
    if (result.status === 'ready' && result.ranking) {
      emit('selection-time', {
        resultTime: result.ranking.generatedAt,
        tradeDate: result.ranking.tradeDate,
        batchId: result.ranking.batchId,
      })
      emit('pre-status', {
        status: 'ready',
        tradeDate: result.ranking.tradeDate,
        batchId: result.ranking.batchId,
        generationId: result.ranking.runId,
      })
      if (state.selected && !result.ranking.rows.some((row) => row.symbol === state.selected)) {
        state.selected = ''
        syncUrl()
      }
    } else {
      emit('pre-status', { status: 'no_ready', tradeDate: '', batchId: '', generationId: '' })
    }
  } catch (err) {
    error.value = err?.message || '基本面排序加载失败'
    emit('pre-status', { status: 'error', tradeDate: '', batchId: '', generationId: '' })
  } finally {
    loading.value = false
  }
}

const syncUrl = () => {
  const next = buildQueryWithState(route.query, state)
  const current = new URLSearchParams(queryToSearch(route.query).replace(/^\?/, ''))
  if (new URLSearchParams(next).toString() === current.toString()) return
  router.replace({ query: next }).catch(() => {})
}

const applyUrlState = (search) => {
  const decoded = decodeStateFromUrl(search)
  Object.assign(state, decoded)
}

watch(
  () => route.query,
  () => {
    const decoded = decodeStateFromUrl(queryToSearch(route.query))
    Object.assign(state, decoded)
  },
)

watch(
  () => [state.sort, state.q, state.industries.join(','), state.evidenceGrades.join(','),
    state.riskOnly, state.tiers.join(','), JSON.stringify(state.minGrades), state.starOnly,
    state.density, state.selected],
  () => syncUrl(),
)

watch(
  () => [props.industryFilter.join(','), props.filterVersion],
  () => {
    if (!props.industryFilter.length) return
    state.industries = [...new Set([...state.industries, ...props.industryFilter])]
  },
)

const handleToggleStar = (symbol) => {
  stars.value = toggleStar(stars.value, symbol)
  saveStars(stars.value)
}

const isStarred = (symbol) => stars.value.includes(symbol)

const selectRow = (row) => {
  state.selected = row.symbol
  expandedSymbol.value = ''
  emit('select', row)
  syncUrl()
}

const expandRow = (row) => {
  expandedSymbol.value = expandedSymbol.value === row.symbol ? '' : row.symbol
}

const moveSelection = (delta) => {
  const rows = filteredRows.value
  if (!rows.length) return
  const current = selectedIndex.value
  const target = Math.max(0, Math.min(rows.length - 1, current === -1 ? 0 : current + delta))
  const row = rows[target]
  state.selected = row.symbol
  emit('select', row)
  ensureVisible(target)
}

const ensureVisible = (index) => {
  nextTick(() => {
    const el = listEl.value
    if (!el) return
    const top = rowOffsets.value.offsets[index] ?? 0
    if (top < el.scrollTop) el.scrollTop = top
    else if (top + rowHeight.value > el.scrollTop + el.clientHeight) {
      el.scrollTop = top + rowHeight.value - el.clientHeight
    }
  })
}

const onKeydown = (event) => {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    moveSelection(1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    moveSelection(-1)
  } else if (event.key === 'Enter') {
    const row = filteredRows.value[selectedIndex.value]
    if (row) {
      selectRow(row)
      emit('stats-request', { action: 'open-detail', symbol: row.symbol })
    }
  } else if (event.key === 'Escape') {
    expandedSymbol.value = ''
  }
}

const onScroll = () => {
  const el = listEl.value
  if (!el) return
  scrollTop.value = el.scrollTop
  viewportHeight.value = el.clientHeight
}

const resetFilters = () => {
  Object.assign(state, DEFAULT_STATE)
  filterPanelOpen.value = false
  syncUrl()
}

const toggleMinGrade = (dimension, grade) => {
  state.minGrades = { ...state.minGrades, [dimension]: grade }
}

const setSort = (key) => {
  state.sort = key
}

const gradeDotTitle = (row) =>
  Object.entries(DIMENSION_META)
    .map(([key, meta]) => `${meta.label}：${GRADE_META[row.dimensionGrades[key]]?.label || '—'}`)
    .join(' | ')

onMounted(() => {
  stars.value = loadStars()
  applyUrlState(queryToSearch(route.query))
  load()
})

const focusList = () => {
  nextTick(() => {
    listEl.value?.focus()
  })
}

watch(
  () => ranking.value,
  (next) => {
    if (!next || !state.selected) return
    const row = next.rows.find((item) => item.symbol === state.selected)
    if (row) emit('select', row)
  },
)

defineExpose({ load, refresh: () => load(), focusList })
</script>

<template>
  <section class="clx-workbench-panel clx-fund-ranking-panel">
    <header class="clx-panel-head">
      <div>
        <h2>CLX 基本面排序</h2>
        <p class="clx-panel-time">
          交易日 <strong>{{ ranking?.tradeDate || latest?.tradeDate || '—' }}</strong>
          <template v-if="ranking?.runId">（{{ ranking.runId }}）</template>
        </p>
      </div>
      <div class="clx-panel-actions">
        <el-button size="small" :loading="loading" @click="load()">刷新</el-button>
        <el-button
          size="small"
          :type="state.starOnly ? 'warning' : 'default'"
          @click="state.starOnly = !state.starOnly"
        >
          ★ 星标{{ state.starOnly ? '：开' : '' }}
        </el-button>
        <el-button
          size="small"
          :type="state.density === 'comfortable' ? 'primary' : 'default'"
          @click="state.density = state.density === 'compact' ? 'comfortable' : 'compact'"
        >
          {{ state.density === 'compact' ? '紧凑' : '舒适' }}
        </el-button>
      </div>
    </header>

    <div class="clx-panel-kpis">
      <span>全量 <strong>{{ ranking?.counts?.total ?? 0 }}</strong></span>
      <span>深析 <strong>{{ deepCount }}</strong></span>
      <span>初评 <strong>{{ snapshotCount }}</strong></span>
      <span>深析完成 <strong>{{ ranking?.counts?.deepComplete ?? 0 }}</strong></span>
    </div>

    <div v-if="error" class="clx-panel-error">{{ error }}</div>
    <div v-else-if="!ranking" class="clx-panel-empty">
      {{ loading ? '加载中...' : '当日无基本面排序产物（无 ranking）' }}
    </div>
    <template v-else>
      <div class="clx-fund-toolbar">
        <el-input
          v-model="state.q"
          size="small"
          clearable
          placeholder="搜索代码/名称/行业"
          class="clx-fund-toolbar__search"
        />
        <el-select v-model="state.sort" size="small" class="clx-fund-toolbar__sort" @change="setSort">
          <el-option
            v-for="option in SORT_OPTIONS"
            :key="option.key"
            :label="option.label"
            :value="option.key"
          />
        </el-select>
        <el-popover
          v-model:visible="filterPanelOpen"
          placement="bottom-start"
          width="360"
          trigger="click"
        >
          <template #reference>
            <el-button size="small">筛选</el-button>
          </template>
          <div class="clx-fund-filter">
            <div class="clx-fund-filter__row">
              <span class="clx-fund-filter__label">分区</span>
              <el-checkbox-group v-model="state.tiers" size="small">
                <el-checkbox-button value="deep">深析</el-checkbox-button>
                <el-checkbox-button value="snapshot">初评</el-checkbox-button>
              </el-checkbox-group>
            </div>
            <div class="clx-fund-filter__row">
              <span class="clx-fund-filter__label">证据</span>
              <el-checkbox-group v-model="state.evidenceGrades" size="small">
                <el-checkbox-button v-for="grade in EVIDENCE_GRADES" :key="grade" :value="grade">
                  {{ grade }}
                </el-checkbox-button>
              </el-checkbox-group>
            </div>
            <div class="clx-fund-filter__row">
              <span class="clx-fund-filter__label">行业</span>
              <div class="clx-fund-filter__chips">
                <button
                  v-for="item in industries"
                  :key="item.name"
                  type="button"
                  class="clx-fund-filter__chip"
                  :class="{ 'clx-fund-filter__chip--on': state.industries.includes(item.name) }"
                  @click="state.industries = state.industries.includes(item.name)
                    ? state.industries.filter((name) => name !== item.name)
                    : [...state.industries, item.name]"
                >
                  {{ item.name }} {{ item.count }}
                </button>
              </div>
            </div>
            <div class="clx-fund-filter__row">
              <span class="clx-fund-filter__label">单维下限</span>
              <div class="clx-fund-filter__mingrades">
                <el-select
                  v-for="(meta, key) in DIMENSION_META"
                  :key="key"
                  :model-value="state.minGrades[key] || ''"
                  size="small"
                  :placeholder="meta.label"
                  @change="(grade) => toggleMinGrade(key, grade)"
                >
                  <el-option label="不限" value="" />
                  <el-option v-for="grade in ['strong', 'good', 'neutral', 'watch', 'weak']" :key="grade" :label="grade" :value="grade" />
                </el-select>
              </div>
            </div>
            <div class="clx-fund-filter__row">
              <el-checkbox v-model="state.riskOnly">仅看有风险标记</el-checkbox>
            </div>
            <div class="clx-fund-filter__actions">
              <el-button size="small" @click="resetFilters">重置</el-button>
              <el-button size="small" type="primary" @click="filterPanelOpen = false">完成</el-button>
            </div>
          </div>
        </el-popover>
      </div>

      <div
        ref="listEl"
        class="clx-fund-list"
        tabindex="0"
        @scroll="onScroll"
        @keydown="onKeydown"
      >
        <div v-if="filteredRows.length === 0" class="clx-panel-empty">无匹配标的</div>
        <div v-else class="clx-fund-list__inner" :style="{ height: `${rowOffsets.totalHeight}px` }">
          <template v-for="(item, index) in visible.rows" :key="item.symbol">
            <div
              class="clx-fund-row"
              :class="{
                'clx-fund-row--selected': state.selected === item.symbol,
                'clx-fund-row--expanded': expandedSymbol === item.symbol,
                'clx-fund-row--snapshot': item.tier === 'snapshot',
                'clx-fund-row--zone-start':
                  item.tier === 'snapshot' &&
                  (index === 0 || visible.rows[index - 1].tier === 'deep'),
              }"
              :style="{
                top: `${rowOffsets.offsets[visible.start + index]}px`,
                height: `${rowHeight}px`,
              }"
              role="option"
              :aria-selected="state.selected === item.symbol"
              @click="selectRow(item)"
            >
              <span
                v-if="item.tier === 'snapshot' && (index === 0 || visible.rows[index - 1].tier === 'deep')"
                class="clx-fund-row__zone-chip"
              >
                初评区
              </span>
              <button
                type="button"
                class="clx-fund-row__expand"
                :aria-label="expandedSymbol === item.symbol ? '收起' : '展开'"
                @click.stop="expandRow(item)"
              >
                {{ expandedSymbol === item.symbol ? '▾' : '▸' }}
              </button>
              <span class="clx-fund-row__rank">{{ item.rank }}</span>
              <span
                v-if="item.consecutiveSelectionDays > 1"
                class="clx-fund-row__streak"
                :title="`近${item.consecutiveSelectionDays}个交易日连续入选`"
              >
                ×{{ item.consecutiveSelectionDays }}
              </span>
              <span class="clx-fund-row__code">{{ item.symbol }}</span>
              <span class="clx-fund-row__name">{{ item.name }}</span>
              <span
                class="clx-fund-row__tier"
                :class="`clx-fund-row__tier--${item.tier}`"
              >
                {{ TIER_META[item.tier].label }}
              </span>
              <span
                class="clx-fund-row__grade"
                :class="`clx-fund-row__grade--${item.compositeGrade}`"
                :title="`综合等级：${item.compositeGrade}`"
              >
                {{ GRADE_META[item.compositeGrade]?.label }}
              </span>
              <span
                class="clx-fund-row__dots"
                :title="gradeDotTitle(item)"
              >
                <i
                  v-for="(meta, key) in DIMENSION_META"
                  :key="key"
                  class="clx-fund-row__dot"
                  :style="{ background: GRADE_META[item.dimensionGrades[key]]?.color }"
                />
              </span>
              <span class="clx-fund-row__metrics">
                ROE {{ formatMetric(item.metrics.roePct, { suffix: '%' }) }}
                · 毛利 {{ formatMetric(item.metrics.grossMarginPct, { suffix: '%' }) }}
                · 净利 {{ formatMetric(item.metrics.netProfitYoyPct, { suffix: '%' }) }}
                · PE {{ formatMetric(item.metrics.pe) }}
                · PB {{ formatMetric(item.metrics.pb) }}
              </span>
              <span
                v-if="item.riskFlags.length"
                class="clx-fund-row__risk"
                :title="item.riskFlags.join('；')"
              >
                ⚠{{ item.riskFlags.length }}
              </span>
              <span class="clx-fund-row__evidence" :title="`证据等级 ${item.evidenceGrade}`">
                {{ item.evidenceGrade }}
              </span>
              <button
                type="button"
                class="clx-fund-row__star"
                :class="{ 'clx-fund-row__star--on': isStarred(item.symbol) }"
                :aria-label="isStarred(item.symbol) ? '取消星标' : '加星标'"
                @click.stop="handleToggleStar(item.symbol)"
              >
                {{ isStarred(item.symbol) ? '★' : '☆' }}
              </button>
            </div>
            <div
              v-if="expandedSymbol === item.symbol"
              class="clx-fund-row-detail"
              :style="{
                top: `${rowOffsets.offsets[visible.start + index] + rowHeight}px`,
              }"
            >
              <div class="clx-fund-row-detail__cols">
                <span>行业 {{ item.primaryGroup }} / {{ item.exactIndustry || '—' }}</span>
                <span>报告期 {{ item.financialReportDate || '—' }}</span>
                <span>证据 {{ item.evidenceGrade }}（{{ item.evidenceIds.length }} 条）</span>
                <span>风险 {{ item.riskFlags.length ? item.riskFlags.join('；') : '无' }}</span>
              </div>
              <el-button size="small" type="primary" @click="selectRow(item)">
                打开详情
              </el-button>
            </div>
          </template>
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

.clx-panel-kpis {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--fq-border-soft, #ebeef5);
}

.clx-panel-kpis span {
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--fq-chip-bg-muted, #f8fafc);
  color: var(--fq-text-secondary, #606266);
  font-size: 12px;
}

.clx-panel-kpis strong {
  margin-left: 4px;
}

.clx-fund-toolbar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--fq-border-soft, #ebeef5);
}

.clx-fund-toolbar__search {
  flex: 1 1 auto;
  min-width: 120px;
}

.clx-fund-toolbar__sort {
  width: 128px;
}

.clx-fund-filter {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.clx-fund-filter__row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.clx-fund-filter__label {
  color: var(--fq-text-muted, #909399);
  font-size: 12px;
}

.clx-fund-filter__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 140px;
  overflow: auto;
}

.clx-fund-filter__chip {
  padding: 2px 8px;
  border: 1px solid var(--fq-border-muted, #e5e7eb);
  border-radius: 999px;
  background: #fff;
  color: var(--fq-text-secondary, #606266);
  font-size: 12px;
  cursor: pointer;
}

.clx-fund-filter__chip--on {
  border-color: var(--fq-status-primary, #409eff);
  background: var(--fq-chip-bg-primary, #f4f9ff);
  color: var(--fq-status-primary, #409eff);
}

.clx-fund-filter__mingrades {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}

.clx-fund-filter__actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}

.clx-fund-list {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 4px 10px 10px;
  outline: none;
}

.clx-fund-list__inner {
  position: relative;
}

.clx-fund-row {
  position: absolute;
  left: 0;
  right: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 8px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--fq-text-primary, #303133);
  cursor: pointer;
  box-sizing: border-box;
}

.clx-fund-row:hover {
  background: var(--fq-chip-bg-primary, #f4f9ff);
}

.clx-fund-row--selected {
  border-color: var(--fq-status-primary, #409eff);
  background: var(--fq-chip-bg-primary, #f4f9ff);
}

.clx-fund-row--snapshot {
  opacity: 0.72;
}

.clx-fund-row--zone-start {
  margin-top: 0;
  border-top: 2px solid var(--fq-border-soft, #ebeef5);
}

.clx-fund-row__zone-chip {
  position: absolute;
  top: -8px;
  left: 8px;
  padding: 0 6px;
  border: 1px dashed var(--fq-border-muted, #e5e7eb);
  border-radius: 4px;
  background: var(--fq-panel-bg, #fff);
  color: var(--fq-text-muted, #909399);
  font-size: 10px;
}

.clx-fund-row__expand {
  border: 0;
  background: transparent;
  color: var(--fq-text-muted, #909399);
  font-size: 12px;
  cursor: pointer;
  padding: 0;
  width: 16px;
}

.clx-fund-row__rank {
  width: 26px;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  color: var(--fq-text-muted, #909399);
  text-align: right;
}

.clx-fund-row__streak {
  padding: 0 4px;
  border-radius: 4px;
  background: var(--fq-chip-bg-warning, #fef3c7);
  color: var(--fq-status-warning, #d97706);
  font-size: 10px;
  font-weight: 700;
}

.clx-fund-row__code {
  width: 52px;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-weight: 600;
  font-size: 12px;
}

.clx-fund-row__name {
  min-width: 0;
  flex: 1 1 auto;
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.clx-fund-row__tier {
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10px;
}

.clx-fund-row__tier--deep {
  background: var(--fq-chip-bg-success, #f0fdf4);
  color: var(--fq-status-success, #16a34a);
}

.clx-fund-row__tier--snapshot {
  border: 1px dashed var(--fq-border-muted, #e5e7eb);
  color: var(--fq-text-muted, #909399);
}

.clx-fund-row__grade {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  color: #fff;
  font-size: 10px;
  font-weight: 700;
}

.clx-fund-row__grade--strong { background: #16a34a; }
.clx-fund-row__grade--good { background: #2563eb; }
.clx-fund-row__grade--neutral { background: #9ca3af; }
.clx-fund-row__grade--watch { background: #d97706; }
.clx-fund-row__grade--weak { background: #dc2626; }
.clx-fund-row__grade--evidence_gap { background: #b8b8c0; }

.clx-fund-row__dots {
  display: flex;
  gap: 2px;
  width: 42px;
}

.clx-fund-row__dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
}

.clx-fund-row__metrics {
  min-width: 0;
  overflow: hidden;
  color: var(--fq-text-muted, #909399);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.clx-fund-row__risk {
  color: var(--fq-status-danger, #dc2626);
  font-size: 11px;
}

.clx-fund-row__evidence {
  width: 18px;
  color: var(--fq-text-muted, #909399);
  font-size: 10px;
  text-align: center;
}

.clx-fund-row__star {
  border: 0;
  background: transparent;
  color: var(--fq-text-muted, #c0c4cc);
  font-size: 14px;
  cursor: pointer;
}

.clx-fund-row__star--on {
  color: var(--fq-status-warning, #d97706);
}

.clx-fund-row-detail {
  position: absolute;
  left: 0;
  right: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 10px;
  border: 1px solid var(--fq-border-soft, #ebeef5);
  border-radius: 6px;
  background: var(--fq-panel-bg-muted, #f8fafc);
}

.clx-fund-row-detail__cols {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  min-width: 0;
  color: var(--fq-text-secondary, #606266);
  font-size: 11px;
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
