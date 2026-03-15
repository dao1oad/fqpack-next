<template>
  <div>
    <MyHeader></MyHeader>
    <el-row>
      <el-col :span="12">
        <StockPositionList />
        <SignalList title="must_pools买入信号" category="must_pool_buys" />
      </el-col>
      <el-col :span="12">
        <SignalList title="持仓股信号" category="holdings" />
        <ModelSignalList title="stock_pools模型信号" />
      </el-col>
    </el-row>
  </div>
</template>

<script>
import MyHeader from '@/views/MyHeader.vue'
import ModelSignalList from '@/views/ModelSignalList.vue'
import StockPositionList from '@/views/StockPositionList.vue'
import SignalList from '@/views/SignalList.vue'

export default {
  name: 'stock-control',
  components: {
    MyHeader,
    ModelSignalList,
    StockPositionList,
    SignalList
  }
}
</script>
<style lang="stylus" scoped>
@import '../style/stock-control.styl';
</style>
