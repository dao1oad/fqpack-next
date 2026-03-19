<template>
  <div class="stock-control-shell">
    <MyHeader />
    <div class="stock-control-body">
      <div class="stock-control-grid">
        <section class="panel-card">
          <div class="panel-card-header">
            <span>持仓股信号</span>
          </div>
          <div class="panel-table">
            <SignalList title="持仓股信号" category="holdings" />
          </div>
        </section>

        <section class="panel-card">
          <div class="panel-card-header">
            <span>stock_pools模型信号</span>
          </div>
          <div class="panel-table">
            <ModelSignalList title="stock_pools模型信号" />
          </div>
        </section>

        <section class="panel-card">
          <div class="panel-card-header">
            <span>must_pools买入信号</span>
          </div>
          <div class="panel-table">
            <SignalList title="must_pools买入信号" category="must_pool_buys" />
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script>
import MyHeader from '@/views/MyHeader.vue'
import ModelSignalList from '@/views/ModelSignalList.vue'
import SignalList from '@/views/SignalList.vue'

export default {
  name: 'stock-control',
  components: {
    MyHeader,
    ModelSignalList,
    SignalList
  }
}
</script>

<style lang="stylus" scoped>
@import '../style/stock-control.styl';
</style>
