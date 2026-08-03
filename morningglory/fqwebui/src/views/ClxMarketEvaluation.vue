<template>
  <div class="clx-eval-page">
    <MyHeader />
    <main class="clx-eval-main">
      <section class="clx-eval-hero">
        <div>
          <h1>CLX 日线评价</h1>
          <p>基于固定快照 contract 展示当日分组排序、组内排序、统计分析和映射审计。</p>
        </div>
        <div v-if="data" class="clx-eval-badges">
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

      <section v-if="data" class="clx-eval-run">
        <dl>
          <dt>tradeDate</dt><dd>{{ data.tradeDate }}</dd>
          <dt>runId</dt><dd>{{ data.runId }}</dd>
          <dt>动态行数</dt><dd>members {{ data.members.length }} / summary.stockRows {{ data.summary.stockRows }}</dd>
          <dt>动态分组</dt><dd>groups {{ data.groups.length }} / summary.groupCount {{ data.summary.groupCount }}</dd>
          <dt>marketStateHash</dt><dd>{{ shortHash(data.marketStateHash) }}</dd>
          <dt>sourceHashFiles</dt><dd>{{ Object.keys(data.sourceHashes || {}).length }}</dd>
        </dl>
      </section>

      <section v-if="data" class="clx-eval-stats">
        <div v-for="box in statBoxes" :key="box.title" class="clx-eval-stat-box">
          <h3>{{ box.title }}</h3>
          <div v-for="row in box.rows" :key="row[0]" class="clx-eval-stat-row">
            <span>{{ row[0] }}</span>
            <strong>{{ row[1] }}</strong>
          </div>
        </div>
      </section>

      <section v-if="data" class="clx-eval-panel">
        <div class="clx-eval-panel-head">
          <h2>组间排序 <small>({{ data.groups.length }})</small></h2>
        </div>
        <div class="clx-eval-table-wrap clx-eval-table-wrap--groups">
          <table>
            <thead>
              <tr>
                <th>组排名</th>
                <th>分组</th>
                <th>市场线索</th>
                <th>吻合度</th>
                <th>主题</th>
                <th>CLX数</th>
                <th>shortlist</th>
                <th>金额(亿)</th>
                <th>代表标的</th>
                <th>理由</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="group in data.groups"
                :key="`${group.groupRank}-${group.groupName}`"
                :class="{ 'clx-eval-row--selected': selectedGroupName === group.groupName }"
                @click="selectGroup(group)"
              >
                <td>{{ group.groupRank }}</td>
                <td><strong>{{ group.groupName }}</strong></td>
                <td>{{ group.marketLane }}</td>
                <td>{{ group.marketFitGrade }}</td>
                <td>{{ group.themeId || '—' }}</td>
                <td>{{ group.clxStockCount }}</td>
                <td>{{ group.shortlistCount }}</td>
                <td>{{ formatNumber(group.clxGroupAmountYi) }}</td>
                <td>{{ (group.representativeSymbols || []).join('；') }}</td>
                <td>{{ group.fitReason || '—' }}</td>
                <td>
                  <el-button
                    size="small"
                    type="primary"
                    :loading="runningTdxGroup === group.groupName"
                    @click.stop="importGroupToTdx(group)"
                  >
                    导入通达信
                  </el-button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="data" class="clx-eval-panel">
        <div class="clx-eval-panel-head">
          <h2>组内全量排序 <small>({{ filteredMembers.length }}/{{ data.members.length }})</small></h2>
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
        <div class="clx-eval-table-wrap">
          <table>
            <thead>
              <tr>
                <th>全局</th>
                <th>组/组内</th>
                <th>代码</th>
                <th>名称</th>
                <th>主分组</th>
                <th>市场线索</th>
                <th>主题</th>
                <th>吻合度</th>
                <th>shortlist</th>
                <th>映射来源</th>
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
                <td>{{ member.marketLane }}</td>
                <td>{{ member.marketThemeId || '—' }}</td>
                <td>{{ member.marketFitGrade }}</td>
                <td>{{ member.shortlistEligible }}</td>
                <td>{{ member.mappingSourceRank }}</td>
                <td>{{ formatNumber(member.sameDayReturnPctDiagnostic) }}</td>
                <td>{{ formatNumber(member.amountYi) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="data" class="clx-eval-panel">
        <div class="clx-eval-panel-head">
          <h2>映射审计</h2>
        </div>
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
    ['主题映射', summary.marketThemeMapped],
    ['shortlist', summary.shortlistCount],
    ['remainingUnmapped', summary.remainingUnmapped],
  ].map(([label, value]) => ({ label, value }))
})

const statBoxes = computed(() => {
  if (!data.value) return []
  const statistics = data.value.statistics || {}
  return [
    ['Lane 分布', statistics.laneCounts],
    ['marketFitGrade 分布', statistics.marketFitGradeCounts],
    ['mappingSourceRank 分布', statistics.mappingSourceRankCounts],
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

const shortHash = (value) => value ? `${String(value).slice(0, 12)}…` : '—'

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
.clx-eval-run,
.clx-eval-panel,
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

.clx-eval-hero p {
  margin: 8px 0 0;
  color: #64748b;
}

.clx-eval-badges {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.clx-eval-badges span {
  padding: 4px 8px;
  border-radius: 999px;
  background: #e0f2fe;
  color: #075985;
  font-size: 12px;
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

.clx-eval-run {
  margin-top: 12px;
  padding: 12px 16px;
}

.clx-eval-run dl {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr) 150px minmax(0, 1fr);
  gap: 8px 12px;
  margin: 0;
  font-size: 12px;
}

.clx-eval-run dt {
  color: #64748b;
}

.clx-eval-run dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.clx-eval-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
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

.clx-eval-panel {
  margin-top: 12px;
  overflow: hidden;
}

.clx-eval-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid #e5e7eb;
}

.clx-eval-panel-head h2 {
  margin: 0;
  font-size: 16px;
}

.clx-eval-panel-head small {
  color: #64748b;
}

.clx-eval-filters {
  display: grid;
  grid-template-columns: 200px 220px 180px 120px 108px;
  gap: 8px;
}

.clx-eval-table-wrap {
  max-height: 620px;
  overflow: auto;
}

.clx-eval-table-wrap--groups {
  max-height: 420px;
}

.clx-eval-table-wrap--audit {
  max-height: 260px;
}

table {
  width: 100%;
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

.clx-eval-row--selected,
.clx-eval-row--selected:hover {
  background: #eff6ff;
  box-shadow: inset 3px 0 0 #2563eb;
}

@media (max-width: 1280px) {
  .clx-eval-kpis,
  .clx-eval-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .clx-eval-run dl {
    grid-template-columns: 120px minmax(0, 1fr);
  }

  .clx-eval-panel-head {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
