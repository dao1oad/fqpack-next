<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { clxDailySelectionApi } from '@/api/clxDailySelectionApi.js'
import {
  fetchEvaluation,
  filterEvaluationGroups,
  filterEvaluationMembers,
  buildEvaluationExportPayload,
  formatEvaluationTime,
} from './clxEvaluationPanelLogic.mjs'

const emit = defineEmits(['evaluation-time'])

const loading = ref(false)
const exporting = ref(false)
const error = ref('')
const evaluation = ref(null)
const groupSearch = ref('')
const selectedGroupName = ref('')
const filters = reactive({
  q: '',
  primaryGroup: '',
  marketLane: '',
  shortlistEligible: '',
})

const generatedAt = computed(() =>
  formatEvaluationTime(evaluation.value?.generatedAt),
)
const evaluatedTime = computed(() => {
  const value = evaluation.value
  if (!value) return '—'
  const parts = [value.tradeDate ? `交易日 ${value.tradeDate}` : '']
  if (value.evaluatedBatchId) parts.push(value.evaluatedBatchId)
  return parts.filter(Boolean).join(' / ') || '—'
})

const visibleGroups = computed(() =>
  filterEvaluationGroups(evaluation.value?.groups || [], groupSearch.value),
)

const filteredMembers = computed(() =>
  filterEvaluationMembers(evaluation.value?.members || [], {
    q: filters.q,
    groupName: selectedGroupName.value,
    primaryGroup: filters.primaryGroup,
    marketLane: filters.marketLane,
    shortlistEligible: filters.shortlistEligible,
  }),
)

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const next = await fetchEvaluation()
    evaluation.value = next
    emit('evaluation-time', {
      generatedAt: next.generatedAt,
      tradeDate: next.tradeDate,
      evaluatedBatchId: next.evaluatedBatchId,
    })
  } catch (err) {
    error.value = err?.message || '评价结果加载失败'
    evaluation.value = { status: 'pending' }
  } finally {
    loading.value = false
  }
}

const selectGroup = (group) => {
  selectedGroupName.value = group?.groupName || ''
  filters.primaryGroup = ''
}

const getGroupMembers = (group) => {
  const groupName = group?.groupName || ''
  if (!groupName) return []
  return (evaluation.value?.members || [])
    .filter((member) => member.primaryGroup === groupName)
    .slice()
    .sort(
      (a, b) =>
        Number(a.memberRank ?? 0) - Number(b.memberRank ?? 0) ||
        Number(a.globalRank ?? 0) - Number(b.globalRank ?? 0),
    )
}

const exportToTdx = async () => {
  if (!selectedGroupName.value) {
    ElMessage.warning('请先选择要导出的评价分组')
    return
  }
  const members = getGroupMembers({ groupName: selectedGroupName.value })
  const payload = buildEvaluationExportPayload(evaluation.value, members)
  if (!payload) {
    ElMessage.warning('当前评价产物未记录评价对象批次，无法导出')
    return
  }
  exporting.value = true
  try {
    const response = await clxDailySelectionApi.syncSelectedBatchResultsToTdx(
      payload.batchId,
      { items: payload.items },
    )
    const data = response?.data ?? response ?? {}
    ElMessage.success(
      `已导出当前评价分组到 CLX_18：${data.written_count ?? payload.items.length} 只`,
    )
  } catch (err) {
    const fallbackOk = await fallbackExportToTdx(payload)
    if (!fallbackOk) {
      ElMessage.error(
        err?.response?.data?.message || err?.message || '导出 CLX_18 失败',
      )
    }
  } finally {
    exporting.value = false
  }
}

const fallbackExportToTdx = async (payload) => {
  try {
    const response = await fetch('/api/clx-evaluator/tdx-sync-group', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        scope_id: payload.batchId,
        trade_date: evaluation.value?.tradeDate || '',
        group_name: selectedGroupName.value || 'clx_18',
        items: payload.items,
      }),
    })
    const result = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(result?.message || '本地导入失败')
    ElMessage.success(
      `已通过本地适配导出当前评价分组到 CLX_18：${result.written_count ?? payload.items.length} 只`,
    )
    return true
  } catch (err) {
    ElMessage.error(err?.message || '导出 CLX_18 失败')
    return false
  }
}

onMounted(load)

defineExpose({ load, refresh: () => load() })
</script>

<template>
  <section class="clx-workbench-panel clx-eval-panel">
    <header class="clx-panel-head">
      <div>
        <h2>最新 CLX 评价</h2>
        <p class="clx-panel-time">
          评价结果时间 <strong>{{ generatedAt }}</strong>
          <template v-if="evaluation?.runId">（run {{ evaluation.runId }}）</template>
        </p>
        <p class="clx-panel-time">评价对象时间 <strong>{{ evaluatedTime }}</strong></p>
      </div>
      <div class="clx-panel-actions">
        <el-button size="small" :loading="loading" @click="load()">刷新</el-button>
        <el-button
          size="small"
          type="primary"
          :loading="exporting"
          :disabled="!evaluation || evaluation.status !== 'ready' || !selectedGroupName"
          @click="exportToTdx"
        >
          导出当前评价分组到 CLX_18
        </el-button>
      </div>
    </header>

    <div class="clx-panel-kpis">
      <span>评价股票数 <strong>{{ evaluation?.summary?.stockRows ?? 0 }}</strong></span>
      <span>分组数 <strong>{{ evaluation?.summary?.groupCount ?? 0 }}</strong></span>
      <span>未映射 <strong>{{ evaluation?.summary?.remainingUnmapped ?? 0 }}</strong></span>
      <span>财报缺口 <strong>{{ evaluation?.summary?.fundamentalEvidenceGap ?? 0 }}</strong></span>
    </div>

    <div v-if="error" class="clx-panel-error">{{ error }}</div>
    <div v-else-if="!evaluation || evaluation.status === 'pending'" class="clx-panel-empty">
      评价尚未生成
    </div>
    <template v-else>
      <el-input
        v-model="groupSearch"
        size="small"
        clearable
        placeholder="搜索分组/线索/主题"
      />
      <div class="clx-eval-group-list">
        <article
          v-for="group in visibleGroups"
          :key="`${group.groupRank}-${group.groupName}`"
          class="clx-eval-group-card"
          :class="{ 'clx-eval-group-card--selected': selectedGroupName === group.groupName }"
          role="button"
          tabindex="0"
          @click="selectGroup(group)"
          @keyup.enter="selectGroup(group)"
        >
          <div class="clx-eval-group-card__title">
            <span class="clx-eval-rank">#{{ group.groupRank }}</span>
            <strong>{{ group.groupName }}</strong>
          </div>
          <div class="clx-eval-chips">
            <span>{{ group.marketLane || '未分类线索' }}</span>
            <span>{{ group.marketFitGrade || '未评级' }}</span>
            <span>{{ group.themeId || '无主题' }}</span>
          </div>
          <div class="clx-eval-group-metrics">
            <div><span>CLX数</span><strong>{{ group.clxStockCount }}</strong></div>
            <div><span>shortlist</span><strong>{{ group.shortlistCount }}</strong></div>
            <div><span>金额(亿)</span><strong>{{ group.clxGroupAmountYi }}</strong></div>
          </div>
          <p class="clx-eval-fit-reason" :title="group.fitReason || ''">
            {{ group.fitReason || '—' }}
          </p>
        </article>
        <div v-if="visibleGroups.length === 0" class="clx-panel-empty">无匹配分组</div>
      </div>

      <div class="clx-eval-members-head">
        <strong>组内成员（{{ filteredMembers.length }}）</strong>
        <span v-if="selectedGroupName">当前分组：{{ selectedGroupName }}</span>
        <el-button v-if="selectedGroupName" link type="primary" @click="selectedGroupName = ''">
          清除分组
        </el-button>
      </div>
      <div class="clx-eval-table-wrap">
        <table>
          <thead>
            <tr>
              <th>代码</th>
              <th>名称</th>
              <th>主分组</th>
              <th>吻合度</th>
              <th>基本面</th>
              <th>风险</th>
              <th>shortlist</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="member in filteredMembers" :key="`${member.globalRank}-${member.symbol}`">
              <td><strong>{{ member.symbol }}</strong></td>
              <td>{{ member.name }}</td>
              <td>{{ member.primaryGroup }}</td>
              <td>{{ member.marketFitGrade }}</td>
              <td>{{ member.fundamentalQualityGrade || '—' }}</td>
              <td :title="String(member.riskFlags || '').split(',').join('；')">
                {{ member.riskFlagGrade || '—' }}
              </td>
              <td>{{ member.shortlistEligible }}</td>
            </tr>
            <tr v-if="filteredMembers.length === 0">
              <td colspan="7" class="clx-panel-empty">无匹配成员</td>
            </tr>
          </tbody>
        </table>
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

.clx-panel-time strong {
  color: var(--fq-text-primary, #303133);
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

.clx-eval-group-list {
  flex: 0 1 44%;
  min-height: 0;
  overflow: auto;
  padding: 8px 10px;
  border-bottom: 1px solid var(--fq-border-soft, #ebeef5);
}

.clx-eval-group-card {
  display: grid;
  gap: 6px;
  padding: 10px 12px;
  border: 1px solid var(--fq-border-muted, #e5e7eb);
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
}

.clx-eval-group-card + .clx-eval-group-card {
  margin-top: 8px;
}

.clx-eval-group-card:hover,
.clx-eval-group-card--selected {
  border-color: var(--fq-status-primary, #409eff);
  background: var(--fq-chip-bg-primary, #f4f9ff);
}

.clx-eval-group-card__title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.clx-eval-rank {
  color: var(--fq-status-primary, #409eff);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-weight: 700;
}

.clx-eval-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.clx-eval-chips span {
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--fq-chip-bg-info, #edf4fb);
  color: var(--fq-text-secondary, #606266);
  font-size: 12px;
}

.clx-eval-group-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.clx-eval-group-metrics div {
  padding: 6px 8px;
  border-radius: 8px;
  background: var(--fq-panel-bg-muted, #f8fafc);
}

.clx-eval-group-metrics span {
  display: block;
  color: var(--fq-text-muted, #909399);
  font-size: 12px;
}

.clx-eval-group-metrics strong {
  display: block;
  margin-top: 2px;
}

.clx-eval-fit-reason {
  display: -webkit-box;
  min-height: 32px;
  margin: 0;
  overflow: hidden;
  color: var(--fq-text-secondary, #606266);
  font-size: 12px;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.clx-eval-members-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--fq-border-soft, #ebeef5);
  font-size: 12px;
}

.clx-eval-members-head span {
  color: var(--fq-text-muted, #909399);
}

.clx-eval-table-wrap {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 0 10px 10px;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

th,
td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--fq-border-soft, #ebeef5);
  text-align: left;
  white-space: nowrap;
}

th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--fq-panel-bg-muted, #f8fafc);
  color: var(--fq-text-secondary, #606266);
  font-weight: 700;
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
