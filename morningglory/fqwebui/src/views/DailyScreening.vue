<script setup>
import { reactive, ref } from 'vue'

import MyHeader from './MyHeader.vue'
import WorkbenchPage from '../components/workbench/WorkbenchPage.vue'
import StatusChip from '../components/workbench/StatusChip.vue'
import ClxResultPanel from '../components/clx-workbench/ClxResultPanel.vue'
import ClxEvaluationPanel from '../components/clx-workbench/ClxEvaluationPanel.vue'
import PoolWorkspacePanel from '../components/clx-workbench/PoolWorkspacePanel.vue'

const selection = reactive({
  resultTime: '',
  tradeDate: '',
  batchId: '',
})

const evaluation = reactive({
  generatedAt: '',
  tradeDate: '',
  evaluatedBatchId: '',
})

const preStatus = ref({
  status: '',
  tradeDate: '',
  batchId: '',
  generationId: '',
})

const resultPanel = ref(null)
const evaluationPanel = ref(null)
const poolsPanel = ref(null)

const refreshAll = () => {
  resultPanel.value?.refresh?.()
  evaluationPanel.value?.refresh?.()
  poolsPanel.value?.loadAll?.()
}

const preStatusLabel = () => {
  const status = preStatus.value.status
  if (!status) return '预选池状态未知'
  if (status === 'no_ready') return '当日 CLX 尚未发布'
  if (status === 'ready') return '预选池已就绪'
  return '预选池同步中'
}
</script>

<template>
  <WorkbenchPage class="clx-workbench-page">
    <MyHeader />
    <div class="workbench-body clx-workbench-body">
      <header class="clx-workbench-topbar">
        <div class="clx-workbench-topbar__title">
          <div class="workbench-page-title">每日选股工作台</div>
          <div class="workbench-page-meta">
            <span>选股结果时间 <strong>{{ selection.resultTime || '—' }}</strong></span>
            <span>评价结果时间 <strong>{{ evaluation.generatedAt || '—' }}</strong></span>
            <span>评价对象时间 <strong>{{ evaluation.tradeDate || '—' }}</strong></span>
          </div>
        </div>
        <div class="clx-workbench-topbar__actions">
          <StatusChip variant="info">{{ preStatusLabel() }}</StatusChip>
          <el-button size="small" @click="refreshAll">刷新全部</el-button>
        </div>
      </header>

      <div class="clx-workbench-grid">
        <ClxResultPanel
          ref="resultPanel"
          class="clx-workbench-grid__result"
          @selection-time="Object.assign(selection, $event)"
          @pre-status="preStatus = $event"
        />
        <ClxEvaluationPanel
          ref="evaluationPanel"
          class="clx-workbench-grid__evaluation"
          @evaluation-time="Object.assign(evaluation, $event)"
        />
        <PoolWorkspacePanel ref="poolsPanel" class="clx-workbench-grid__pools" />
      </div>
    </div>
  </WorkbenchPage>
</template>

<style scoped>
.clx-workbench-page {
  height: 100dvh;
  overflow: hidden;
}

.clx-workbench-body {
  overflow: hidden;
  padding: 12px 16px 16px;
}

.clx-workbench-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex: 0 0 auto;
  margin-bottom: 12px;
}

.clx-workbench-topbar__title {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.clx-workbench-topbar__actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 0 0 auto;
}

.clx-workbench-grid {
  display: grid;
  flex: 1 1 auto;
  grid-template-columns:
    minmax(760px, 30fr)
    minmax(1100px, 46fr)
    minmax(560px, 24fr);
  gap: 12px;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
}

.clx-workbench-grid__result,
.clx-workbench-grid__evaluation,
.clx-workbench-grid__pools {
  min-height: 0;
  min-width: 0;
  overflow: hidden;
}
</style>
