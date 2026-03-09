<template>
  <div class="runtime-page">
    <MyHeader />
    <div class="runtime-shell">
      <section class="runtime-section">
        <div class="runtime-title-row">
          <div>
            <h1>运行观测</h1>
            <p>链路追踪优先，健康看板同步提供。</p>
          </div>
          <el-button type="primary" :loading="loading.overview" @click="loadOverview">刷新</el-button>
        </div>
        <div class="health-grid">
          <article v-for="card in healthCards" :key="`${card.runtime_node}-${card.component}`" class="health-card">
            <div class="health-card-head">
              <strong>{{ card.component }}</strong>
              <span>{{ card.runtime_node }}</span>
            </div>
            <div class="health-card-body">
              <p>状态: {{ card.status }}</p>
              <p>心跳年龄: {{ card.heartbeat_age_s ?? '-' }}s</p>
              <ul>
                <li v-for="item in card.highlights" :key="item.key">{{ item.key }}: {{ item.value }}</li>
              </ul>
            </div>
          </article>
        </div>
      </section>

      <section class="runtime-section">
        <div class="trace-toolbar">
          <el-input v-model="query.trace_id" clearable placeholder="trace_id" />
          <el-input v-model="query.request_id" clearable placeholder="request_id" />
          <el-input v-model="query.internal_order_id" clearable placeholder="internal_order_id" />
          <el-input v-model="query.symbol" clearable placeholder="symbol" />
          <el-input v-model="query.component" clearable placeholder="component" />
          <el-button type="primary" :loading="loading.traces" @click="loadTraces">查询</el-button>
        </div>

        <div class="trace-list-summary">
          <article class="trace-list-summary-card">
            <span>可见 Trace</span>
            <strong>{{ traceListSummary.trace_count }}</strong>
          </article>
          <article class="trace-list-summary-card">
            <span>异常链路</span>
            <strong>{{ traceListSummary.issue_trace_count }}</strong>
          </article>
          <article class="trace-list-summary-card">
            <span>异常节点</span>
            <strong>{{ traceListSummary.issue_step_count }}</strong>
          </article>
          <article class="trace-list-summary-card trace-list-summary-card--wide">
            <span>组件异常分布<span v-if="activeComponentFilter"> · filter {{ activeComponentFilter }}</span></span>
            <div class="trace-list-summary-components">
              <span
                v-for="item in traceListSummary.components"
                :key="`${item.component}-${item.issue_count}-${item.trace_count}`"
              >
                {{ item.component }} · {{ item.issue_count }}/{{ item.trace_count }}
              </span>
              <span v-if="traceListSummary.components.length === 0">-</span>
            </div>
          </article>
        </div>

        <div class="trace-layout">
          <div class="trace-list">
            <el-table :data="traceRows" stripe height="460" :row-class-name="traceRowClassName" @row-click="handleTraceClick">
              <el-table-column prop="trace_id" label="Trace" min-width="180" />
              <el-table-column prop="request_ids" label="Request" min-width="160">
                <template #default="{ row }">{{ row.request_ids.join(', ') || '-' }}</template>
              </el-table-column>
              <el-table-column prop="internal_order_ids" label="Order" min-width="160">
                <template #default="{ row }">{{ row.internal_order_ids.join(', ') || '-' }}</template>
              </el-table-column>
              <el-table-column prop="step_count" label="Steps" width="80" />
              <el-table-column prop="issue_count" label="Issues" width="84" />
              <el-table-column prop="total_duration_label" label="Duration" width="96" />
              <el-table-column prop="last_node" label="Last Node" min-width="140" />
              <el-table-column prop="last_status" label="Status" width="100" />
              <el-table-column prop="last_ts" label="Latest" min-width="180" />
            </el-table>
          </div>

          <div class="trace-detail">
            <div class="trace-detail-head">
              <div>
                <strong>{{ selectedTraceDetail.trace_id || selectedTrace?.trace_key || '选择一条 Trace' }}</strong>
                <div v-if="selectedTrace" class="trace-summary-chips">
                  <span class="trace-summary-chip">steps {{ selectedTraceDetail.step_count }}</span>
                  <span class="trace-summary-chip" :class="{ 'is-issue': selectedTraceDetail.issue_count > 0 }">
                    issues {{ selectedTraceDetail.issue_count }}
                  </span>
                  <span class="trace-summary-chip">duration {{ selectedTraceDetail.total_duration_label }}</span>
                </div>
              </div>
              <div class="trace-detail-actions">
                <el-switch
                  v-model="onlyIssues"
                  :disabled="!selectedTrace"
                  inline-prompt
                  active-text="异常"
                  inactive-text="全部"
                />
                <el-button :disabled="!selectedStep" @click="openRawBrowser">Raw</el-button>
              </div>
            </div>
            <div v-if="selectedTrace" class="trace-detail-body">
              <div class="trace-timeline-panel">
                <div class="trace-summary-grid">
                  <article class="trace-summary-card">
                    <span>首个异常</span>
                    <strong>{{ traceSummaryMeta.first_issue ? `${traceSummaryMeta.first_issue.component}.${traceSummaryMeta.first_issue.node}` : '-' }}</strong>
                  </article>
                  <article class="trace-summary-card">
                    <span>最后异常</span>
                    <strong>{{ traceSummaryMeta.last_issue ? `${traceSummaryMeta.last_issue.component}.${traceSummaryMeta.last_issue.node}` : '-' }}</strong>
                  </article>
                  <article class="trace-summary-card">
                    <span>最长耗时</span>
                    <strong>{{ traceSummaryMeta.slowest_step ? `${traceSummaryMeta.slowest_step.component}.${traceSummaryMeta.slowest_step.node}` : '-' }}</strong>
                    <em>{{ traceSummaryMeta.slowest_step?.delta_from_prev_label || '-' }}</em>
                  </article>
                </div>

                <div class="trace-issue-banner" :class="{ 'is-empty': issueSummary.items.length === 0 }">
                  {{ issueSummary.headline }}
                </div>

                <div class="trace-affected-row">
                  <span>涉及组件</span>
                  <div class="trace-affected-list">
                    <span v-for="component in traceSummaryMeta.affected_components" :key="component">{{ component }}</span>
                    <span v-if="traceSummaryMeta.affected_components.length === 0">-</span>
                  </div>
                </div>

                <div class="trace-identity-grid">
                  <div v-for="group in traceIdentityGroups" :key="group.label" class="trace-identity-card">
                    <span>{{ group.label }}</span>
                    <div class="trace-identity-values">
                      <button
                        v-for="value in group.values"
                        :key="`${group.label}-${value}`"
                        type="button"
                        class="trace-copy-chip"
                        @click="copyText(value)"
                      >
                        {{ value }}
                      </button>
                      <span v-if="group.values.length === 0">-</span>
                    </div>
                  </div>
                </div>

                <div class="trace-timeline-hint">
                  <span>{{ onlyIssues ? '仅显示异常节点' : '显示全部节点' }}</span>
                  <span>可见 {{ visibleStepCount }} / {{ selectedTraceDetail.step_count }}</span>
                </div>

                <div v-if="filteredSteps.length > 0" class="trace-group-list">
                  <section v-for="group in groupedSteps" :key="group.component" class="trace-group-card">
                    <button type="button" class="trace-group-head" @click="toggleGroup(group.component)">
                      <div>
                        <strong>{{ group.component }}</strong>
                        <div class="trace-step-subline">
                          <span>steps {{ group.step_count }}</span>
                          <span>issues {{ group.issue_count }}</span>
                          <span>duration {{ group.duration_label }}</span>
                        </div>
                      </div>
                      <span>{{ isGroupCollapsed(group.component) ? '展开' : '收起' }}</span>
                    </button>

                    <div v-if="!isGroupCollapsed(group.component)" class="trace-step-list">
                      <article
                        v-for="step in group.steps"
                        :key="stepKey(step)"
                        class="trace-step-card"
                        :class="[statusClass(step.status), { active: isActiveStep(step) }]"
                        @click="handleStepSelect(step)"
                      >
                        <span class="trace-step-marker" />
                        <header>
                          <div>
                            <strong>{{ step.component }}.{{ step.node }}</strong>
                            <div class="trace-step-subline">
                              <span>#{{ step.index + 1 }}</span>
                              <span>{{ step.ts || '-' }}</span>
                            </div>
                          </div>
                          <div class="trace-step-side">
                            <span v-if="step.delta_from_prev_label" class="trace-step-delta">
                              +{{ step.delta_from_prev_label }}
                            </span>
                            <span class="trace-step-status">{{ step.status || 'info' }}</span>
                          </div>
                        </header>
                        <div v-if="step.tags.length" class="trace-step-tags">
                          <span v-for="tag in step.tags" :key="`${stepKey(step)}-${tag.key}`">
                            {{ tag.label }}: {{ tag.value }}
                          </span>
                        </div>
                        <p v-if="step.message">{{ step.message }}</p>
                        <div class="trace-step-meta">
                          <span v-if="step.request_id">request {{ step.request_id }}</span>
                          <span v-if="step.internal_order_id">order {{ step.internal_order_id }}</span>
                        </div>
                      </article>
                    </div>
                  </section>
                </div>
                <div v-else class="trace-empty">当前过滤条件下没有节点</div>
              </div>

              <aside class="step-inspector">
                <template v-if="selectedStep">
                  <div class="step-inspector-head" :class="statusClass(selectedStep.status)">
                    <div>
                      <strong>{{ selectedStep.component }}.{{ selectedStep.node }}</strong>
                      <p>{{ selectedStep.ts || '-' }}</p>
                    </div>
                    <span class="trace-step-status">{{ selectedStep.status || 'info' }}</span>
                  </div>

                  <div class="step-inspector-summary">
                    <span>step #{{ selectedStep.index + 1 }}</span>
                    <span v-if="selectedStep.delta_from_prev_label">
                      delta {{ selectedStep.delta_from_prev_label }}
                    </span>
                    <span v-if="selectedStep.event_type">{{ selectedStep.event_type }}</span>
                  </div>

                  <div class="step-inspector-flags">
                    <span v-if="isFirstIssueStep(selectedStep)" class="inspector-tag">首个异常</span>
                    <span v-if="isSlowestStep(selectedStep)" class="inspector-tag">最长耗时节点</span>
                  </div>

                  <section class="step-inspector-section">
                    <h4>关联字段</h4>
                    <div v-for="field in selectedStep.detail_fields" :key="`${stepKey(selectedStep)}-${field.key}`" class="inspector-field-row">
                      <span>{{ field.key }}</span>
                      <code>{{ field.value }}</code>
                      <button type="button" class="trace-copy-link" @click.stop="copyText(field.value)">复制</button>
                    </div>
                  </section>

                  <section v-if="selectedStep.tags.length" class="step-inspector-section">
                    <h4>分支判断</h4>
                    <div class="inspector-tag-list">
                      <span v-for="tag in selectedStep.tags" :key="`${stepKey(selectedStep)}-detail-${tag.key}`" class="inspector-tag">
                        {{ tag.label }}: {{ tag.value }}
                      </span>
                    </div>
                  </section>

                  <section v-if="selectedStep.payload_text" class="step-inspector-section">
                    <h4>Payload</h4>
                    <pre>{{ selectedStep.payload_text }}</pre>
                  </section>

                  <section v-if="selectedStep.metrics_text" class="step-inspector-section">
                    <h4>Metrics</h4>
                    <pre>{{ selectedStep.metrics_text }}</pre>
                  </section>

                  <div class="step-inspector-actions">
                    <el-button type="primary" plain @click="openRawFromStep(selectedStep)">查看 Raw</el-button>
                    <el-button text @click="copyText(buildStepCopyText(selectedStep))">复制节点摘要</el-button>
                  </div>
                </template>
                <div v-else class="trace-empty">暂无选中节点</div>
              </aside>
            </div>
            <div v-else class="trace-empty">暂无选中链路</div>
          </div>
        </div>
      </section>
    </div>

    <el-drawer v-model="rawDrawerVisible" size="55%" title="Raw Records">
      <div class="raw-toolbar">
        <el-input v-model="rawQuery.runtime_node" placeholder="runtime_node" />
        <el-input v-model="rawQuery.component" placeholder="component" />
        <el-input v-model="rawQuery.date" placeholder="YYYY-MM-DD" />
        <el-select v-model="rawQuery.file" placeholder="选择文件" filterable clearable style="width: 280px">
          <el-option v-for="item in rawFiles" :key="item.name" :label="item.name" :value="item.name" />
        </el-select>
        <el-button @click="loadRawFiles">文件</el-button>
        <el-button type="primary" :disabled="!rawQuery.file" @click="loadRawTail()">Tail</el-button>
      </div>
      <div v-if="rawFocusedIndex >= 0" class="raw-focus-banner">
        已定位到第 {{ rawFocusedIndex + 1 }} 条记录
      </div>
      <div v-if="rawRecordCards.length" class="raw-record-list">
        <article
          v-for="(record, index) in rawRecordCards"
          :key="`${record.title}-${record.subtitle}-${index}`"
          :ref="(el) => setRawRecordRef(el, index)"
          class="raw-record-card"
          :class="{ active: rawFocusedIndex === index }"
        >
          <header>
            <strong>{{ record.title }}</strong>
            <span>{{ record.subtitle }}</span>
          </header>
          <div v-if="record.badges.length" class="raw-record-badges">
            <span v-for="badge in record.badges" :key="`${record.title}-${badge}-${index}`">{{ badge }}</span>
          </div>
          <pre class="raw-content">{{ record.body }}</pre>
        </article>
      </div>
      <pre v-else class="raw-content">暂无记录</pre>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'

import { runtimeObservabilityApi } from '../api/runtimeObservabilityApi'
import MyHeader from './MyHeader.vue'
import {
  buildTraceListSummary,
  buildIssueSummary,
  buildRawRecordSummary,
  buildTraceSummaryMeta,
  buildTraceDetail,
  buildHealthCards,
  buildRawLookupFromStep,
  buildTraceQuery,
  findRawRecordIndex,
  filterTraceSteps,
  groupStepsByComponent,
  pickDefaultTraceStep,
  sortTraceSummaries,
  summarizeTrace,
} from './runtimeObservability.mjs'

const loading = reactive({
  overview: false,
  traces: false,
  raw: false,
})

const query = reactive({
  trace_id: '',
  request_id: '',
  internal_order_id: '',
  symbol: '',
  component: '',
})

const healthCards = ref([])
const traces = ref([])
const selectedTrace = ref(null)
const selectedStep = ref(null)
const onlyIssues = ref(false)
const collapsedComponents = ref({})
const rawDrawerVisible = ref(false)
const rawFiles = ref([])
const rawRecords = ref([])
const rawFocusedIndex = ref(-1)
const rawRecordRefs = ref({})
const rawQuery = reactive({
  runtime_node: '',
  component: '',
  date: '',
  file: '',
})

const traceRows = computed(() => {
  return sortTraceSummaries(traces.value.map((item) => summarizeTrace(item)))
})
const traceListSummary = computed(() => buildTraceListSummary(traces.value))
const activeComponentFilter = computed(() => String(query.component || '').trim())

const selectedTraceDetail = computed(() => buildTraceDetail(selectedTrace.value || {}))
const traceSummaryMeta = computed(() => buildTraceSummaryMeta(selectedTraceDetail.value))
const issueSummary = computed(() => buildIssueSummary(selectedTraceDetail.value))
const filteredSteps = computed(() => {
  return filterTraceSteps(selectedTraceDetail.value.steps, { onlyIssues: onlyIssues.value })
})
const groupedSteps = computed(() => groupStepsByComponent(filteredSteps.value))
const visibleStepCount = computed(() => filteredSteps.value.length)
const traceIdentityGroups = computed(() => {
  return [
    { label: 'Intent', values: selectedTraceDetail.value.intent_ids || [] },
    { label: 'Request', values: selectedTraceDetail.value.request_ids || [] },
    { label: 'Order', values: selectedTraceDetail.value.internal_order_ids || [] },
  ]
})
const rawRecordCards = computed(() => rawRecords.value.map((record) => buildRawRecordSummary(record)))

const loadOverview = async () => {
  loading.overview = true
  try {
    const [healthResp] = await Promise.all([
      runtimeObservabilityApi.getHealthSummary(),
      loadTraces(),
    ])
    healthCards.value = buildHealthCards(healthResp?.data?.components || [])
  } finally {
    loading.overview = false
  }
}

const loadTraces = async () => {
  loading.traces = true
  try {
    const response = await runtimeObservabilityApi.listTraces(buildTraceQuery(query))
    traces.value = response?.data?.traces || []
    const currentTraceId = selectedTrace.value?.trace_id
    selectedTrace.value = traces.value.find((item) => item.trace_id === currentTraceId) || traces.value[0] || null
  } finally {
    loading.traces = false
  }
}

const handleTraceClick = async (row) => {
  if (!row?.trace_id) return
  const response = await runtimeObservabilityApi.getTraceDetail(row.trace_id)
  selectedTrace.value = response?.data?.trace || null
  collapsedComponents.value = {}
}

const handleStepSelect = (step) => {
  selectedStep.value = step || null
}

const openRawBrowser = async () => {
  if (selectedStep.value) {
    await openRawFromStep(selectedStep.value)
    return
  }
  rawDrawerVisible.value = true
}

const openRawFromStep = async (step) => {
  const lookup = buildRawLookupFromStep(step)
  if (!lookup) return
  rawQuery.runtime_node = lookup.runtime_node
  rawQuery.component = lookup.component
  rawQuery.date = lookup.date
  rawQuery.file = ''
  rawDrawerVisible.value = true
  await loadRawFiles()
  if (rawFiles.value.length > 0) {
    rawQuery.file = rawFiles.value[0].name
    await loadRawTail(step)
  }
}

const loadRawFiles = async () => {
  loading.raw = true
  try {
    const response = await runtimeObservabilityApi.listRawFiles({
      runtime_node: rawQuery.runtime_node,
      component: rawQuery.component,
      date: rawQuery.date,
    })
    rawFiles.value = response?.data?.files || []
  } finally {
    loading.raw = false
  }
}

const loadRawTail = async (targetStep = selectedStep.value) => {
  if (!rawQuery.file) return
  loading.raw = true
  try {
    const response = await runtimeObservabilityApi.tailRawFile({
      runtime_node: rawQuery.runtime_node,
      component: rawQuery.component,
      date: rawQuery.date,
      file: rawQuery.file,
      lines: 120,
    })
    rawRecords.value = response?.data?.records || []
    rawFocusedIndex.value = findRawRecordIndex(rawRecords.value, targetStep)
    await scrollToFocusedRawRecord()
  } finally {
    loading.raw = false
  }
}

const stepKey = (step) => {
  return [
    step?.ts || '',
    step?.component || '',
    step?.node || '',
    step?.index ?? '',
  ].join('|')
}

const isActiveStep = (step) => {
  return stepKey(selectedStep.value) === stepKey(step)
}

const isFirstIssueStep = (step) => {
  return stepKey(traceSummaryMeta.value.first_issue) === stepKey(step)
}

const isSlowestStep = (step) => {
  return stepKey(traceSummaryMeta.value.slowest_step) === stepKey(step)
}

const statusClass = (status) => {
  const normalized = String(status || 'info').trim()
  if (normalized === 'success') return 'is-success'
  if (normalized === 'warning') return 'is-warning'
  if (normalized === 'failed' || normalized === 'error') return 'is-failed'
  if (normalized === 'skipped') return 'is-skipped'
  return 'is-info'
}

const buildStepCopyText = (step) => {
  if (!step) return ''
  const lines = [
    `${step.component}.${step.node}`,
    `status: ${step.status || 'info'}`,
    step.ts ? `ts: ${step.ts}` : '',
    ...(step.detail_fields || []).map((field) => `${field.key}: ${field.value}`),
    ...(step.tags || []).map((tag) => `${tag.label}: ${tag.value}`),
  ].filter(Boolean)
  return lines.join('\n')
}

const copyText = async (value) => {
  const text = String(value || '').trim()
  if (!text) return
  try {
    if (window?.navigator?.clipboard?.writeText) {
      await window.navigator.clipboard.writeText(text)
    }
  } catch {
    return
  }
}

const syncSelectedStep = () => {
  const steps = filteredSteps.value
  if (!steps.length) {
    selectedStep.value = null
    return
  }
  const currentKey = stepKey(selectedStep.value)
  selectedStep.value = steps.find((step) => stepKey(step) === currentKey) || pickDefaultTraceStep(steps)
}

const traceRowClassName = ({ row }) => {
  return row?.issue_count > 0 ? 'runtime-trace-row--issue' : ''
}

const toggleGroup = (component) => {
  const key = String(component || '')
  if (!key) return
  collapsedComponents.value = {
    ...collapsedComponents.value,
    [key]: !collapsedComponents.value[key],
  }
}

const isGroupCollapsed = (component) => {
  return Boolean(collapsedComponents.value[String(component || '')])
}

const setRawRecordRef = (element, index) => {
  rawRecordRefs.value = {
    ...rawRecordRefs.value,
    [index]: element || null,
  }
}

const scrollToFocusedRawRecord = async () => {
  if (rawFocusedIndex.value < 0) return
  await nextTick()
  rawRecordRefs.value[rawFocusedIndex.value]?.scrollIntoView({
    block: 'nearest',
    behavior: 'smooth',
  })
}

watch([selectedTraceDetail, onlyIssues], () => {
  syncSelectedStep()
})

watch(() => selectedTrace.value?.trace_id || selectedTrace.value?.trace_key || '', () => {
  collapsedComponents.value = {}
})

watch(rawRecords, () => {
  rawRecordRefs.value = {}
})

onMounted(() => {
  loadOverview()
})
</script>

<style scoped>
.runtime-page {
  min-height: 100vh;
  background:
    linear-gradient(180deg, #eef4ff 0%, #f9fbff 38%, #f5f7fa 100%);
}

.runtime-shell {
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.runtime-section {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #dfe7f3;
  border-radius: 18px;
  padding: 18px;
  box-shadow: 0 12px 36px rgba(20, 48, 84, 0.06);
}

.runtime-title-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 14px;
}

.runtime-title-row h1 {
  margin: 0;
  font-size: 26px;
  color: #17324d;
}

.runtime-title-row p {
  margin: 6px 0 0;
  color: #56718d;
}

.health-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
}

.health-card {
  border-radius: 14px;
  padding: 14px;
  background: linear-gradient(180deg, #ffffff 0%, #f4f8fc 100%);
  border: 1px solid #dbe5ef;
}

.health-card-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  color: #1f3c5b;
}

.health-card-head span {
  color: #6a8198;
  font-size: 12px;
}

.health-card-body p,
.health-card-body li {
  margin: 6px 0;
  color: #39546f;
}

.health-card-body ul {
  padding-left: 16px;
  margin: 0;
}

.trace-toolbar {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr)) auto;
  gap: 10px;
  margin-bottom: 14px;
}

.trace-list-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr)) minmax(280px, 1.6fr);
  gap: 10px;
  margin-bottom: 14px;
}

.trace-list-summary-card {
  border: 1px solid #d8e2ee;
  border-radius: 12px;
  background: linear-gradient(180deg, #ffffff 0%, #f5f8fc 100%);
  padding: 12px;
}

.trace-list-summary-card > span {
  display: block;
  margin-bottom: 8px;
  color: #69829b;
  font-size: 12px;
}

.trace-list-summary-card strong {
  display: block;
  color: #21405e;
  font-size: 24px;
  line-height: 1;
}

.trace-list-summary-card--wide strong {
  font-size: 18px;
}

.trace-list-summary-components {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.trace-list-summary-components span {
  padding: 4px 8px;
  border-radius: 999px;
  background: #edf4fb;
  color: #35506c;
  font-size: 12px;
}

.trace-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(320px, 0.9fr);
  gap: 16px;
}

.trace-list,
.trace-detail {
  min-width: 0;
}

.trace-detail {
  border: 1px solid #dfe7f3;
  border-radius: 14px;
  background: linear-gradient(180deg, #fbfdff 0%, #f4f8fc 100%);
  padding: 14px;
}

.trace-detail-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.trace-detail-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.trace-summary-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.trace-summary-chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  background: #edf4fb;
  color: #31506e;
  font-size: 12px;
}

.trace-summary-chip.is-issue {
  background: #fff1f0;
  color: #9f2d24;
}

.trace-detail-body {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(280px, 0.9fr);
  gap: 14px;
}

.trace-summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.trace-summary-card {
  border: 1px solid #d8e2ee;
  border-radius: 12px;
  background: #fff;
  padding: 12px;
}

.trace-summary-card span {
  display: block;
  color: #68829b;
  font-size: 12px;
  margin-bottom: 8px;
}

.trace-summary-card strong {
  display: block;
  color: #21405e;
}

.trace-summary-card em {
  display: inline-block;
  margin-top: 6px;
  color: #56718d;
  font-size: 12px;
  font-style: normal;
}

.trace-issue-banner {
  margin-bottom: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  background: #fff4f2;
  color: #8f342b;
  border: 1px solid #f5d2ce;
  font-size: 13px;
}

.trace-issue-banner.is-empty {
  background: #eef7f1;
  color: #2f6a48;
  border-color: #cde8d7;
}

.trace-affected-row {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 12px;
}

.trace-affected-row > span {
  min-width: 72px;
  color: #68829b;
  font-size: 12px;
}

.trace-affected-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.trace-affected-list span {
  padding: 4px 8px;
  border-radius: 999px;
  background: #edf4fb;
  color: #35506c;
  font-size: 12px;
}

.trace-timeline-panel,
.step-inspector {
  min-width: 0;
}

.trace-identity-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.trace-identity-card {
  border: 1px solid #d8e2ee;
  border-radius: 12px;
  background: #fff;
  padding: 12px;
}

.trace-identity-card > span {
  display: block;
  margin-bottom: 8px;
  color: #5e7690;
  font-size: 12px;
  text-transform: uppercase;
}

.trace-identity-values {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  color: #35506c;
  font-size: 12px;
}

.trace-copy-chip,
.trace-copy-link {
  border: 0;
  background: none;
  padding: 0;
  color: inherit;
  cursor: pointer;
  font: inherit;
}

.trace-copy-chip {
  padding: 4px 10px;
  border-radius: 999px;
  background: #edf4fb;
}

.trace-copy-chip:hover,
.trace-copy-link:hover {
  color: #0f5ba7;
}

.trace-timeline-hint {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  color: #64809b;
  font-size: 12px;
}

.trace-step-list {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 420px;
  overflow: auto;
  padding-left: 20px;
  border-left: 2px solid #dbe5ef;
}

.trace-group-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.trace-group-card {
  border: 1px solid #d8e2ee;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.8);
  overflow: hidden;
}

.trace-group-head {
  width: 100%;
  border: 0;
  background: linear-gradient(180deg, #ffffff 0%, #f5f8fc 100%);
  padding: 12px 14px;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  cursor: pointer;
  text-align: left;
  color: #21405e;
}

.trace-group-head:hover {
  background: linear-gradient(180deg, #ffffff 0%, #edf4fb 100%);
}

.trace-step-card {
  position: relative;
  border: 1px solid #d8e2ee;
  border-radius: 12px;
  padding: 12px;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.18s ease, transform 0.18s ease, box-shadow 0.18s ease;
}

.trace-step-card:hover,
.trace-step-card.active {
  border-color: #5d8fbd;
  box-shadow: 0 10px 24px rgba(35, 73, 115, 0.1);
  transform: translateX(2px);
}

.trace-step-marker {
  position: absolute;
  left: -27px;
  top: 18px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #7390ac;
  box-shadow: 0 0 0 4px #eef4fb;
}

.trace-step-card header {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

.trace-step-subline,
.trace-step-meta,
.step-inspector-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  color: #66829c;
  font-size: 12px;
}

.trace-step-subline {
  margin-top: 6px;
}

.trace-step-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
}

.trace-step-delta {
  color: #6d879f;
  font-size: 12px;
}

.trace-step-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 66px;
  padding: 4px 8px;
  border-radius: 999px;
  background: #edf4fb;
  color: #35506c;
  font-size: 12px;
  text-transform: lowercase;
}

.trace-step-tags,
.inspector-tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 8px 0 0;
}

.trace-step-tags span,
.inspector-tag {
  padding: 4px 8px;
  border-radius: 999px;
  background: #f1f5fa;
  color: #4b6580;
  font-size: 12px;
}

.trace-step-card p {
  margin: 4px 0;
  color: #46607a;
}

.trace-step-card.is-success .trace-step-marker,
.trace-step-card.is-success .trace-step-status,
.step-inspector-head.is-success .trace-step-status {
  background: #1e9b61;
  color: #fff;
}

.trace-step-card.is-warning .trace-step-marker,
.trace-step-card.is-warning .trace-step-status,
.step-inspector-head.is-warning .trace-step-status {
  background: #de8f1f;
  color: #fff;
}

.trace-step-card.is-failed .trace-step-marker,
.trace-step-card.is-failed .trace-step-status,
.step-inspector-head.is-failed .trace-step-status {
  background: #cf4a3c;
  color: #fff;
}

.trace-step-card.is-skipped .trace-step-marker,
.trace-step-card.is-skipped .trace-step-status,
.step-inspector-head.is-skipped .trace-step-status {
  background: #7d74b6;
  color: #fff;
}

.trace-step-card.is-success {
  background: linear-gradient(180deg, #ffffff 0%, #f2fbf6 100%);
}

.trace-step-card.is-warning {
  background: linear-gradient(180deg, #ffffff 0%, #fff8ec 100%);
}

.trace-step-card.is-failed {
  background: linear-gradient(180deg, #ffffff 0%, #fff1f0 100%);
}

.trace-step-card.is-skipped {
  background: linear-gradient(180deg, #ffffff 0%, #f5f2ff 100%);
}

.step-inspector {
  border: 1px solid #d8e2ee;
  border-radius: 12px;
  background: #fff;
  padding: 12px;
  min-height: 320px;
}

.step-inspector-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  padding: 12px;
  border-radius: 12px;
  margin-bottom: 10px;
  background: #f4f8fc;
}

.step-inspector-head strong {
  display: block;
  color: #1d3b58;
}

.step-inspector-head p {
  margin: 6px 0 0;
  color: #6b859e;
  font-size: 12px;
}

.step-inspector-head.is-success {
  background: #eefaf3;
}

.step-inspector-head.is-warning {
  background: #fff6e6;
}

.step-inspector-head.is-failed {
  background: #fff0ef;
}

.step-inspector-head.is-skipped {
  background: #f4f1ff;
}

.step-inspector-section {
  margin-top: 14px;
}

.step-inspector-flags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.step-inspector-section h4 {
  margin: 0 0 8px;
  color: #274564;
}

.inspector-field-row {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 8px 0;
  border-top: 1px solid #edf2f7;
}

.inspector-field-row:first-of-type {
  border-top: 0;
}

.inspector-field-row span {
  color: #68829b;
  font-size: 12px;
}

.inspector-field-row code {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #2e4d69;
}

.step-inspector pre {
  margin: 0;
  padding: 12px;
  border-radius: 10px;
  background: #0f2034;
  color: #dff0ff;
  font-size: 12px;
  line-height: 1.55;
  overflow: auto;
}

.step-inspector-actions {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-top: 16px;
}

.trace-empty {
  min-height: 200px;
  display: grid;
  place-items: center;
  color: #6a8198;
}

.raw-toolbar {
  display: grid;
  grid-template-columns: 1fr 1fr 160px 280px auto auto;
  gap: 10px;
  margin-bottom: 14px;
}

.raw-focus-banner {
  margin-bottom: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #eef4fb;
  color: #35506c;
  font-size: 12px;
}

.raw-record-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 70vh;
  overflow: auto;
}

.raw-record-card {
  border: 1px solid #d8e2ee;
  border-radius: 12px;
  background: #fff;
  padding: 12px;
}

.raw-record-card.active {
  border-color: #5d8fbd;
  box-shadow: 0 10px 24px rgba(35, 73, 115, 0.1);
}

.raw-record-card header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.raw-record-card header strong {
  color: #20405e;
}

.raw-record-card header span {
  color: #6a8198;
  font-size: 12px;
}

.raw-record-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.raw-record-badges span {
  padding: 4px 8px;
  border-radius: 999px;
  background: #edf4fb;
  color: #35506c;
  font-size: 12px;
}

.raw-content {
  margin: 0;
  min-height: 120px;
  max-height: 48vh;
  overflow: auto;
  padding: 16px;
  border-radius: 12px;
  background: #102033;
  color: #dff0ff;
  font-size: 12px;
  line-height: 1.55;
}

:deep(.runtime-trace-row--issue) td {
  background: #fff7f5 !important;
}

@media (max-width: 1080px) {
  .trace-toolbar,
  .trace-list-summary,
  .raw-toolbar,
  .trace-layout,
  .trace-detail-body,
  .trace-identity-grid,
  .trace-summary-grid {
    grid-template-columns: 1fr;
  }

  .trace-detail-head,
  .step-inspector-actions,
  .trace-timeline-hint,
  .trace-affected-row,
  .raw-record-card header {
    flex-direction: column;
    align-items: stretch;
  }

  .inspector-field-row {
    grid-template-columns: 1fr;
  }
}
</style>
