<template>
  <div class="stock-control-shell">
    <MyHeader />
    <div class="stock-control-body">
      <section class="monitor-column monitor-column--signals">
        <article class="monitor-panel">
          <div class="monitor-panel__head">
            <h2>持仓监控</h2>
            <p>持仓股信号</p>
          </div>
          <div class="monitor-panel__body">
            <SignalList title="持仓股信号" category="holdings" />
          </div>
        </article>

        <article class="monitor-panel">
          <div class="monitor-panel__head">
            <h2>买入监控</h2>
            <p>must_pools买入信号</p>
          </div>
          <div class="monitor-panel__body">
            <SignalList title="must_pools买入信号" category="must_pool_buys" />
          </div>
        </article>
      </section>

      <section class="monitor-column monitor-column--model">
        <article class="monitor-panel monitor-panel--full">
          <div class="monitor-panel__head">
            <h2>模型监控</h2>
            <p>stock_pools模型信号</p>
          </div>
          <div class="monitor-panel__body">
            <ModelSignalList title="stock_pools模型信号" />
          </div>
        </article>
      </section>
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
