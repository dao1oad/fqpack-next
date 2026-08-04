<template>
  <div class="clx-eval-page">
    <MyHeader />
    <main class="clx-eval-main">
      <section class="clx-eval-hero">
        <div>
          <h1>CLX 日线评价</h1>
          <p>基于固定快照 contract 展示市场吻合度、基本面承载力、ETF 暴露确认、sell 诊断和映射审计。</p>
        </div>
        <div v-if="data" class="clx-eval-badges">
          <span>tradeDate={{ data.tradeDate }}</span>
          <span>run={{ data.runId }}</span>
          <span>{{ data.schemaVersion }}</span>
          <span>{{ data.validationStatus }}</span>
          <span>latest={{ data.review?.promotedToLatest }}</span>
        </div>
      </section>

      <el-alert
        v-if="error"
        class="clx-eval-alert"
        type="error"
        :closable="false"
        show-icon
        :title="error"
      />

      <section v-if="data" class="clx-eval-kpis">
        <article v-for="item in kpis" :key="item.label">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </article>
      </section>

      <section v-if="data" class="clx-eval-workbench">
        <aside class="clx-eval-groups" aria-label="CLX 分组导航">
          <div class="clx-eval-panel-head clx-eval-panel-head--compact">
            <div>
              <h2>分组导航 <small>({{ visibleGroups.length }}/{{ data.groups.length }})</small></h2>
              <p>按分组切换右侧成员表，审计信息移至底部折叠区。</p>
            </div>
            <el-input
              v-model="groupSearch"
              clearable
              size="small"
              placeholder="搜索分组/线索/主题"
            />
          </div>
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
                <div>
                  <span>CLX数</span>
                  <strong>{{ group.clxStockCount }}</strong>
                </div>
                <div>
                  <span>shortlist</span>
                  <strong>{{ group.shortlistCount }}</strong>
                </div>
                <div>
                  <span>金额(亿)</span>
                  <strong>{{ formatNumber(group.clxGroupAmountYi) }}</strong>
                </div>
              </div>
              <div class="clx-eval-representatives">
                <span
                  v-for="symbol in representativePreview(group.representativeSymbols)"
                  :key="symbol"
                >
                  {{ symbol }}
                </span>
                <em v-if="(group.representativeSymbols || []).length > 3">
                  +{{ group.representativeSymbols.length - 3 }}
                </em>
              </div>
              <p class="clx-eval-fit-reason" :title="group.fitReason || ''">
                {{ group.fitReason || '—' }}
              </p>
              <div class="clx-eval-group-actions">
                <el-button
                  size="small"
                  type="primary"
                  :loading="runningTdxGroup === group.groupName"
                  @click.stop="importGroupToTdx(group)"
                >
                  导入通达信
                </el-button>
              </div>
            </article>
          </div>
        </aside>

        <section class="clx-eval-members" aria-label="CLX 组内成员">
          <div class="clx-eval-members-toolbar">
            <div>
              <h2>
                组内股票
                <small>({{ filteredMembers.length }}/{{ data.members.length }})</small>
              </h2>
              <p v-if="selectedGroupName">当前分组：{{ selectedGroupName }}</p>
              <p v-else>未选择分组时展示全量成员。</p>
            </div>
            <div class="clx-eval-filters">
              <el-input v-model="filters.q" clearable size="small" placeholder="代码/名称/分组" />
              <el-select v-model="filters.primaryGroup" clearable size="small" placeholder="分组">
                <el-option v-for="value in filterOptions.primaryGroup" :key="value" :label="value" :value="value" />
              </el-select>
              <el-select v-model="filters.marketLane" clearable size="small" placeholder="市场线索">
                <el-option v-for="value in filterOptions.marketLane" :key="value" :label="value" :value="value" />
              </el-select>
              <el-select v-model="filters.shortlistEligible" clearable size="small" placeholder="shortlist">
                <el-option label="true" value="true" />
                <el-option label="false" value="false" />
              </el-select>
              <el-button size="small" :disabled="!selectedGroupName" @click="clearSelectedGroup">
                清除组筛选
              </el-button>
            </div>
          </div>

          <article v-if="selectedGroup" class="clx-eval-selected-summary">
            <div>
              <h3>{{ selectedGroup.groupName }}</h3>
              <p>{{ selectedGroup.fitReason || '—' }}</p>
              <p v-if="selectedGroup.contraEvidence" class="clx-eval-contra">
                反证：{{ selectedGroup.contraEvidence }}
              </p>
            </div>
            <div class="clx-eval-selected-side">
              <div class="clx-eval-representatives">
                <span
                  v-for="symbol in representativePreview(selectedGroup.representativeSymbols, 6)"
                  :key="symbol"
                >
                  {{ symbol }}
                </span>
              </div>
              <el-button
                size="small"
                type="primary"
                :loading="runningTdxGroup === selectedGroup.groupName"
                @click="importGroupToTdx(selectedGroup)"
              >
                导入通达信
              </el-button>
            </div>
          </article>

          <div class="clx-eval-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>全局</th>
                  <th>组/组内</th>
                  <th>代码</th>
                  <th>名称</th>
                  <th>主分组</th>
                  <th>细分行业</th>
                  <th>市场线索</th>
                  <th>主题</th>
                  <th>吻合度</th>
                  <th>基本面</th>
                  <th>成长</th>
                  <th>盈利</th>
                  <th>现金流/负债</th>
                  <th>估值</th>
                  <th>风险</th>
                  <th>容量</th>
                  <th>财报期</th>
                  <th>映射来源</th>
                  <th>shortlist</th>
                  <th>当日涨幅</th>
                  <th>金额(亿)</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="member in filteredMembers" :key="`${member.globalRank}-${member.symbol}`">
                  <td>{{ member.globalRank }}</td>
                  <td>{{ member.groupRank }}/{{ member.memberRank }}</td>
                  <td><strong>{{ member.symbol }}</strong></td>
                  <td>{{ member.name }}</td>
                  <td>{{ member.primaryGroup }}</td>
                  <td>{{ member.exactIndustry || '—' }}</td>
                  <td>{{ member.marketLane }}</td>
                  <td>{{ member.marketThemeId || '—' }}</td>
                  <td>{{ member.marketFitGrade }}</td>
                  <td>{{ member.fundamentalQualityGrade || '—' }}</td>
                  <td>{{ member.growthGrade || '—' }}</td>
                  <td>{{ member.profitabilityGrade || '—' }}</td>
                  <td>{{ member.cashflowBalanceGrade || '—' }}</td>
                  <td>{{ member.valuationGrade || '—' }}</td>
                  <td :title="joinValues(member.riskFlags)">{{ member.riskFlagGrade || '—' }}</td>
                  <td>{{ member.liquidityCapacityGrade || '—' }}</td>
                  <td>{{ member.financialReportDate || '—' }}</td>
                  <td>{{ member.mappingSourceRank || '—' }}</td>
                  <td>{{ member.shortlistEligible }}</td>
                  <td>{{ formatNumber(member.sameDayReturnPctDiagnostic) }}</td>
                  <td>{{ formatNumber(member.amountYi) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </section>

      <section v-if="data" class="clx-eval-audit-stack" aria-label="CLX 运行与审计">
        <details class="clx-eval-details">
          <summary>运行合同</summary>
          <dl class="clx-eval-run-contract">
            <dt>tradeDate</dt><dd>{{ data.tradeDate }}</dd>
            <dt>runId</dt><dd>{{ data.runId }}</dd>
            <dt>动态行数</dt><dd>members {{ data.members.length }} / summary.stockRows {{ data.summary.stockRows }}</dd>
            <dt>动态分组</dt><dd>groups {{ data.groups.length }} / summary.groupCount {{ data.summary.groupCount }}</dd>
            <dt>marketStateHash</dt><dd>{{ shortHash(data.marketStateHash) }}</dd>
            <dt>sourceHashFiles</dt><dd>{{ Object.keys(data.sourceHashes || {}).length }}</dd>
          </dl>
        </details>

        <details class="clx-eval-details">
          <summary>统计分布</summary>
          <div class="clx-eval-stats">
            <div v-for="box in statBoxes" :key="box.title" class="clx-eval-stat-box">
              <h3>{{ box.title }}</h3>
              <div v-for="row in box.rows" :key="row[0]" class="clx-eval-stat-row">
                <span>{{ row[0] }}</span>
                <strong>{{ row[1] }}</strong>
              </div>
            </div>
          </div>
        </details>

        <details class="clx-eval-details">
          <summary>映射审计</summary>
          <div class="clx-eval-table-wrap clx-eval-table-wrap--audit">
            <table>
              <thead><tr><th>指标</th><th>值</th><th>说明</th></tr></thead>
              <tbody>
                <tr v-for="row in data.mappingAudit" :key="row.metric">
                  <td>{{ row.metric }}</td>
                  <td>{{ row.value }}</td>
                  <td>{{ row.detail }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </details>

        <details class="clx-eval-details">
          <summary>
            ETF 暴露确认
            ({{ data.diagnostics?.etfConfirmations?.length || 0 }}；有效确认
            {{ data.diagnostics?.directionSummary?.eligible_etf_confirmation_count || 0 }})
          </summary>
          <div class="clx-eval-table-wrap clx-eval-table-wrap--audit">
            <table>
              <thead>
                <tr>
                  <th>排名</th><th>代码</th><th>名称</th><th>底层暴露</th><th>映射</th>
                  <th>组大小</th><th>代表产品</th><th>重复暴露</th><th>有效确认</th><th>主题</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in data.diagnostics?.etfConfirmations || []" :key="row.symbol">
                  <td>{{ row.rank }}</td>
                  <td><strong>{{ row.symbol }}</strong></td>
                  <td>{{ row.name }}</td>
                  <td>{{ row.underlying_exposure_key || '—' }}</td>
                  <td>{{ row.exposure_mapping_status }}</td>
                  <td>{{ row.exposure_group_size }}</td>
                  <td>{{ row.exposure_representative }}</td>
                  <td>{{ row.duplicate_exposure }}</td>
                  <td>{{ row.confirmation_eligible }}</td>
                  <td>{{ joinValues(row.theme_ids) || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </details>

        <details class="clx-eval-details">
          <summary>sell / mixed 诊断 ({{ data.diagnostics?.sellDiagnostics?.length || 0 }})</summary>
          <div class="clx-eval-table-wrap clx-eval-table-wrap--audit">
            <table>
              <thead>
                <tr>
                  <th>代码</th><th>名称</th><th>类型</th><th>方向</th><th>分类</th>
                  <th>主题</th><th>独立信号家族</th><th>诊断理由</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in data.diagnostics?.sellDiagnostics || []" :key="`${row.security_type}-${row.symbol}`">
                  <td><strong>{{ row.symbol }}</strong></td>
                  <td>{{ row.name }}</td>
                  <td>{{ row.security_type }}</td>
                  <td>{{ row.direction }}</td>
                  <td>{{ row.classification }}</td>
                  <td>{{ joinValues(row.theme_ids) || '—' }}</td>
                  <td>{{ row.independent_signal_family_count }}</td>
                  <td>{{ row.rationale }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </details>

        <details class="clx-eval-details">
          <summary>信号事件勾稽</summary>
          <dl class="clx-eval-run-contract">
            <dt>official signal_event_count</dt>
            <dd>{{ data.diagnostics?.signalEventReconciliation?.official_unique_signal_event_count }}</dd>
            <dt>row sum</dt>
            <dd>{{ data.diagnostics?.signalEventReconciliation?.row_signal_event_count_sum }}</dd>
            <dt>旧方向展开诊断数</dt>
            <dd>{{ data.diagnostics?.signalEventReconciliation?.direction_expanded_membership_count_previous }}</dd>
            <dt>状态</dt>
            <dd>{{ data.diagnostics?.signalEventReconciliation?.reconciliation_status }}</dd>
          </dl>
        </details>
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { clxDailySelectionApi } from '@/api/clxDailySelectionApi.js'
import MyHeader from './MyHeader.vue'

const data = ref(null)
const error = ref('')
const selectedGroupName = ref('')
const runningTdxGroup = ref('')
const groupSearch = ref('')
const filters = reactive({
  q: '',
  primaryGroup: '',
  marketLane: '',
  shortlistEligible: '',
})

const sortCounts = (counts = {}) => Object.entries(counts).sort((a, b) => b[1] - a[1])

const kpis = computed(() => {
  if (!data.value) return []
  const summary = data.value.summary || {}
  return [
    ['Stock buy', summary.stockRows],
    ['分组数', summary.groupCount],
    ['业务覆盖', summary.businessPrimaryGroupCovered],
    ['财报覆盖', summary.fundamentalReportCovered],
    ['ETF映射', summary.mappedEtfCount],
    ['sell诊断', summary.sellDiagnosticCount],
    ['signal events', summary.officialSignalEventCount],
  ].map(([label, value]) => ({ label, value }))
})

const statBoxes = computed(() => {
  if (!data.value) return []
  const statistics = data.value.statistics || {}
  return [
    ['Lane 分布', statistics.laneCounts],
    ['marketFitGrade 分布', statistics.marketFitGradeCounts],
    ['mappingSourceRank 分布', statistics.mappingSourceRankCounts],
    ['基本面质量分布', statistics.fundamentalQualityGradeCounts],
    ['成长分布', statistics.growthGradeCounts],
    ['估值分布', statistics.valuationGradeCounts],
    ['shortlist 分布', statistics.shortlistCounts],
  ].map(([title, counts]) => ({ title, rows: sortCounts(counts) }))
})

const filterOptions = computed(() => {
  const members = data.value?.members || []
  const unique = (key) => [...new Set(members.map((item) => item[key]).filter(Boolean))]
    .sort((a, b) => String(a).localeCompare(String(b), 'zh-Hans-CN'))
  return {
    primaryGroup: unique('primaryGroup'),
    marketLane: unique('marketLane'),
  }
})

const visibleGroups = computed(() => {
  const groups = data.value?.groups || []
  const q = groupSearch.value.trim().toLowerCase()
  if (!q) return groups
  return groups.filter((group) => [
    group.groupName,
    group.marketLane,
    group.themeId,
  ].some((value) => String(value || '').toLowerCase().includes(q)))
})

const selectedGroup = computed(() => {
  const groupName = selectedGroupName.value
  if (!groupName) return null
  return (data.value?.groups || []).find((group) => group.groupName === groupName) || null
})

const filteredMembers = computed(() => {
  const members = data.value?.members || []
  const q = filters.q.trim().toLowerCase()
  return members
    .filter((member) => {
      if (q && ![member.symbol, member.name, member.primaryGroup].some((value) => String(value || '').toLowerCase().includes(q))) return false
      if (selectedGroupName.value && member.primaryGroup !== selectedGroupName.value) return false
      if (filters.primaryGroup && member.primaryGroup !== filters.primaryGroup) return false
      if (filters.marketLane && member.marketLane !== filters.marketLane) return false
      if (filters.shortlistEligible && String(Boolean(member.shortlistEligible)) !== filters.shortlistEligible) return false
      return true
    })
    .slice()
    .sort((a, b) => a.globalRank - b.globalRank)
})

const formatNumber = (value) => {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value !== 'number') return value
  return Number.isInteger(value) ? String(value) : value.toFixed(3)
}

const joinValues = (values = []) => Array.isArray(values) ? values.join('；') : String(values || '')

const shortHash = (value) => value ? `${String(value).slice(0, 12)}…` : '—'

const representativePreview = (symbols = [], limit = 3) => (
  Array.isArray(symbols) ? symbols.slice(0, limit) : []
)

const selectGroup = (group) => {
  selectedGroupName.value = group?.groupName || ''
  filters.primaryGroup = ''
}

const clearSelectedGroup = () => {
  selectedGroupName.value = ''
}

const getGroupMembers = (group) => {
  const groupName = group?.groupName || ''
  if (!groupName) return []
  return (data.value?.members || [])
    .filter((member) => member.primaryGroup === groupName)
    .slice()
    .sort((a, b) => a.memberRank - b.memberRank || a.globalRank - b.globalRank)
}

const resolveSnapshotBatchId = () => {
  const snapshot = data.value || {}
  const manifest = snapshot.sourceManifest || {}
  return snapshot.clxBatchId ||
    snapshot.batchId ||
    snapshot.scopeId ||
    manifest.clxBatchId ||
    manifest.batchId ||
    manifest.scopeId ||
    ''
}

const buildTdxItems = (members) => members.map((member) => ({
  asset_type: 'stock',
  symbol: member.symbol,
}))

const shouldFallbackToLocalTdxAdapter = (err) => {
  const status = Number(err?.response?.status || 0)
  const message = String(err?.response?.data?.message || err?.message || '')
  return status === 502 ||
    status === 504 ||
    !err?.response ||
    /Bad Gateway|Network Error|timeout|ECONNREFUSED|api_proxy_failed/i.test(message)
}

const syncGroupToTdxViaLocalAdapter = async (groupName, members) => {
  const response = await fetch('/api/clx-evaluator/tdx-sync-group', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      scope_id: resolveSnapshotBatchId() || data.value?.runId || '',
      trade_date: data.value?.tradeDate || '',
      group_name: groupName,
      items: buildTdxItems(members),
    }),
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(payload?.message || `${groupName} 本地通达信导入失败`)
  }
  return payload
}

const importGroupToTdx = async (group) => {
  const groupName = group?.groupName || ''
  const members = getGroupMembers(group)
  if (!data.value || !groupName || !members.length) return

  runningTdxGroup.value = groupName
  try {
    const batchId = resolveSnapshotBatchId()
    if (!batchId) {
      const result = await syncGroupToTdxViaLocalAdapter(groupName, members)
      ElMessage.success(`已通过本地适配导入通达信 ${result.group_name || 'clx_18'}：${result.written_count ?? members.length} 只（${groupName}）`)
      return
    }
    const payload = await clxDailySelectionApi.syncSelectedBatchResultsToTdx(
      batchId,
      {
        items: buildTdxItems(members),
      },
    )
    const result = payload?.data || payload || {}
    ElMessage.success(`已导入通达信 ${result.group_name || 'clx_18'}：${result.written_count ?? members.length} 只（${groupName}）`)
  } catch (err) {
    if (shouldFallbackToLocalTdxAdapter(err)) {
      try {
        const result = await syncGroupToTdxViaLocalAdapter(groupName, members)
        ElMessage.success(`已通过本地适配导入通达信 ${result.group_name || 'clx_18'}：${result.written_count ?? members.length} 只（${groupName}）`)
      } catch (fallbackErr) {
        ElMessage.error(fallbackErr?.message || `${groupName} 导入通达信失败`)
      }
    } else {
      ElMessage.error(err?.response?.data?.message || err?.message || `${groupName} 导入通达信失败`)
    }
  } finally {
    runningTdxGroup.value = ''
  }
}

const loadSnapshot = async () => {
  error.value = ''
  try {
    const latestResponse = await fetch('/data/clx-evaluator/latest.json')
    if (!latestResponse.ok) throw new Error(`latest.json HTTP ${latestResponse.status}`)
    const latest = await latestResponse.json()
    const snapshotResponse = await fetch(latest.href)
    if (!snapshotResponse.ok) throw new Error(`clx-eval.v1.json HTTP ${snapshotResponse.status}`)
    data.value = await snapshotResponse.json()
  } catch (err) {
    error.value = err?.message || 'CLX 日线评价快照加载失败'
  }
}

onMounted(loadSnapshot)
</script>

<style scoped>
.clx-eval-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: #eef1f5;
  color: #172033;
}

.clx-eval-main {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 16px;
}

.clx-eval-hero,
.clx-eval-groups,
.clx-eval-members,
.clx-eval-details,
.clx-eval-stat-box,
.clx-eval-kpis article {
  border: 1px solid #d7dde6;
  border-radius: 10px;
  background: #fff;
}

.clx-eval-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 16px;
}

.clx-eval-hero h1 {
  margin: 0;
  font-size: 24px;
}

.clx-eval-hero p,
.clx-eval-panel-head p,
.clx-eval-members-toolbar p,
.clx-eval-selected-summary p {
  margin: 6px 0 0;
  color: #64748b;
}

.clx-eval-badges {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.clx-eval-badges span,
.clx-eval-chips span,
.clx-eval-representatives span,
.clx-eval-representatives em {
  padding: 4px 8px;
  border-radius: 999px;
  background: #e0f2fe;
  color: #075985;
  font-size: 12px;
  font-style: normal;
}

.clx-eval-alert {
  margin-top: 12px;
}

.clx-eval-kpis {
  display: grid;
  grid-template-columns: repeat(6, minmax(120px, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.clx-eval-kpis article {
  padding: 12px;
}

.clx-eval-kpis span {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.clx-eval-kpis strong {
  display: block;
  margin-top: 5px;
  font-size: 24px;
}

.clx-eval-workbench {
  display: grid;
  grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
  gap: 12px;
  align-items: start;
  margin-top: 12px;
}

.clx-eval-groups,
.clx-eval-members {
  min-width: 0;
  overflow: hidden;
}

.clx-eval-panel-head,
.clx-eval-members-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid #e5e7eb;
}

.clx-eval-panel-head--compact {
  flex-direction: column;
}

.clx-eval-panel-head h2,
.clx-eval-members-toolbar h2,
.clx-eval-selected-summary h3 {
  margin: 0;
  font-size: 16px;
}

.clx-eval-panel-head small,
.clx-eval-members-toolbar small {
  color: #64748b;
}

.clx-eval-group-list {
  max-height: calc(100vh - 284px);
  min-height: 560px;
  overflow: auto;
  padding: 10px;
}

.clx-eval-group-card {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
}

.clx-eval-group-card + .clx-eval-group-card {
  margin-top: 10px;
}

.clx-eval-group-card:hover,
.clx-eval-group-card--selected {
  border-color: #2563eb;
  box-shadow: 0 8px 20px rgba(37, 99, 235, 0.12);
}

.clx-eval-group-card--selected {
  background: #eff6ff;
}

.clx-eval-group-card__title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.clx-eval-rank {
  color: #2563eb;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-weight: 700;
}

.clx-eval-chips,
.clx-eval-representatives {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.clx-eval-chips span:nth-child(2) {
  background: #dcfce7;
  color: #166534;
}

.clx-eval-group-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.clx-eval-group-metrics div {
  padding: 8px;
  border-radius: 8px;
  background: #f8fafc;
}

.clx-eval-group-metrics span {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.clx-eval-group-metrics strong {
  display: block;
  margin-top: 2px;
  font-size: 16px;
}

.clx-eval-fit-reason {
  display: -webkit-box;
  min-height: 34px;
  margin: 0;
  overflow: hidden;
  color: #475569;
  font-size: 12px;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.clx-eval-group-actions {
  display: flex;
  justify-content: flex-end;
}

.clx-eval-members {
  position: relative;
}

.clx-eval-members-toolbar {
  position: sticky;
  top: 0;
  z-index: 3;
  background: #fff;
}

.clx-eval-filters {
  display: grid;
  grid-template-columns: 180px 200px 160px 120px 108px;
  gap: 8px;
}

.clx-eval-selected-summary {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin: 12px;
  padding: 12px;
  border: 1px solid #dbeafe;
  border-radius: 10px;
  background: #f8fbff;
}

.clx-eval-contra {
  color: #b45309;
}

.clx-eval-selected-side {
  display: grid;
  justify-items: end;
  gap: 10px;
  min-width: 220px;
}

.clx-eval-table-wrap {
  max-height: calc(100vh - 360px);
  overflow: auto;
}

.clx-eval-table-wrap--audit {
  max-height: 260px;
}

table {
  width: 100%;
  min-width: 980px;
  border-collapse: collapse;
  font-size: 12px;
}

th,
td {
  padding: 8px 10px;
  border-bottom: 1px solid #eef2f7;
  text-align: left;
  vertical-align: top;
}

th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #f8fafc;
  color: #475569;
  font-weight: 700;
}

tbody tr:hover {
  background: #f8fbff;
}

.clx-eval-audit-stack {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}

.clx-eval-details {
  overflow: hidden;
}

.clx-eval-details summary {
  cursor: pointer;
  padding: 12px 14px;
  color: #334155;
  font-weight: 700;
}

.clx-eval-run-contract {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr) 150px minmax(0, 1fr);
  gap: 8px 12px;
  margin: 0;
  padding: 0 14px 14px;
  font-size: 12px;
}

.clx-eval-run-contract dt {
  color: #64748b;
}

.clx-eval-run-contract dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.clx-eval-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  padding: 0 14px 14px;
}

.clx-eval-stat-box {
  min-height: 160px;
  padding: 12px;
}

.clx-eval-stat-box h3 {
  margin: 0 0 8px;
  font-size: 14px;
}

.clx-eval-stat-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 0;
  border-top: 1px solid #eef2f7;
  font-size: 12px;
}

@media (max-width: 1280px) {
  .clx-eval-kpis,
  .clx-eval-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .clx-eval-workbench {
    grid-template-columns: minmax(0, 1fr);
  }

  .clx-eval-group-list,
  .clx-eval-table-wrap {
    max-height: none;
    min-height: 0;
  }

  .clx-eval-members-toolbar,
  .clx-eval-selected-summary {
    align-items: stretch;
    flex-direction: column;
  }

  .clx-eval-selected-side {
    justify-items: start;
    min-width: 0;
  }

  .clx-eval-filters {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .clx-eval-run-contract {
    grid-template-columns: 120px minmax(0, 1fr);
  }
}
</style>
