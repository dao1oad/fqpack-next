<template>
  <WorkbenchPage class="stock-control-page">
    <MyHeader />

    <div class="workbench-body stock-control-body">
      <WorkbenchToolbar class="stock-control-toolbar">
        <div class="workbench-toolbar__header">
          <div class="workbench-title-group">
            <div class="workbench-page-title">股票</div>
            <div class="workbench-page-meta">
              <span>三栏信号工作台</span>
              <span>/</span>
              <span>持仓股、模型信号、must_pool 买入信号</span>
            </div>
          </div>
        </div>

        <WorkbenchSummaryRow class="stock-control-summary">
          <StatusChip variant="muted">持仓股信号</StatusChip>
          <StatusChip variant="info">stock_pools 模型信号</StatusChip>
          <StatusChip variant="warning">must_pool 买入信号</StatusChip>
        </WorkbenchSummaryRow>
      </WorkbenchToolbar>

      <div class="stock-control-grid">
        <WorkbenchLedgerPanel class="stock-control-panel">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">持仓股信号</div>
              <p class="workbench-panel__desc">当前持仓相关 signal，优先用于盘中观察现有仓位的买卖判断。</p>
            </div>
          </div>

          <div class="stock-control-panel__table">
            <SignalList title="持仓股信号" category="holdings" />
          </div>
        </WorkbenchLedgerPanel>

        <WorkbenchLedgerPanel class="stock-control-panel">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">stock_pools 模型信号</div>
              <p class="workbench-panel__desc">来自 stock_pools 的模型信号，集中观察模型筛出的候选股票。</p>
            </div>
          </div>

          <div class="stock-control-panel__table">
            <ModelSignalList title="stock_pools模型信号" />
          </div>
        </WorkbenchLedgerPanel>

        <WorkbenchLedgerPanel class="stock-control-panel">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">must_pool 买入信号</div>
              <p class="workbench-panel__desc">重点买入池入口，默认保留空态与实时数据态的一致表格结构。</p>
            </div>
          </div>

          <div class="stock-control-panel__table">
            <SignalList title="must_pools买入信号" category="must_pool_buys" />
          </div>
        </WorkbenchLedgerPanel>
      </div>
    </div>
  </WorkbenchPage>
</template>

<script>
import StatusChip from '../components/workbench/StatusChip.vue'
import WorkbenchLedgerPanel from '../components/workbench/WorkbenchLedgerPanel.vue'
import WorkbenchPage from '../components/workbench/WorkbenchPage.vue'
import WorkbenchSummaryRow from '../components/workbench/WorkbenchSummaryRow.vue'
import WorkbenchToolbar from '../components/workbench/WorkbenchToolbar.vue'
import MyHeader from '@/views/MyHeader.vue'
import ModelSignalList from '@/views/ModelSignalList.vue'
import SignalList from '@/views/SignalList.vue'

export default {
  name: 'stock-control',
  components: {
    MyHeader,
    ModelSignalList,
    SignalList,
    StatusChip,
    WorkbenchLedgerPanel,
    WorkbenchPage,
    WorkbenchSummaryRow,
    WorkbenchToolbar,
  },
}
</script>

<style lang="stylus" scoped>
@import '../style/stock-control.styl';
</style>
