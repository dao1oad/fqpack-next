<template>
  <div class="header-main">
    <div class="header-menu">
      <MySetting ref="mySetting"></MySetting>
      <el-button-group>
        <el-button type="primary" @click="goSetting">设置</el-button>
      </el-button-group>
      <el-button-group>
        <el-button type="primary" @click="jumpToControl('futures')" size="small">
          期货
        </el-button>
      </el-button-group>
      <el-button-group>
        <el-button type="warning" @click="jumpToControl('klineSlim')" size="small">
          行情图表
        </el-button>
        <el-button type="success" @click="jumpToControl('orders')" size="small">
          订单管理
        </el-button>
        <el-button type="success" @click="jumpToControl('positionManagement')" size="small">
          仓位管理
        </el-button>
        <el-button type="warning" plain @click="jumpToControl('tpsl')" size="small">
          TPSL
        </el-button>
        <el-button type="danger" @click="jumpToControl('runtime')" size="small">
          运行观测
        </el-button>
      </el-button-group>
      <el-button-group>
        <el-button type="success" @click="jumpToControl('gantt')" size="small">
          板块趋势
        </el-button>
        <el-button type="warning" @click="jumpToControl('shouban30')" size="small">
          首板选股
        </el-button>
      </el-button-group>
      <el-button-group>
        <el-button type="primary" @click="jumpToControl('stock')" size="small">
          股票
        </el-button>
        <el-button type="primary" @click="jumpToControl('pool')" size="small">
          股票池
        </el-button>
        <el-button type="primary" @click="jumpToControl('cjsd')" size="small">
          超级赛道
        </el-button>
      </el-button-group>
    </div>
    <div class="header-tip">
      <span>顺势而为 抓大放小 以小博大 提高胜率比（双盘|二买|完备|三买）</span>
    </div>
  </div>
</template>

<script>
import MySetting from '@/components/MySetting.vue'

export default {
  name: 'my-header',
  components: {
    MySetting
  },
  methods: {
    jumpToControl (type) {
      if (type === 'futures') {
        this.$router.replace('/futures-control')
      } else if (type === 'klineSlim') {
        this.$router.replace('/kline-slim')
      } else if (type === 'orders') {
        this.$router.replace('/order-management')
      } else if (type === 'positionManagement') {
        this.$router.replace('/position-management')
      } else if (type === 'orders') {
        this.$router.replace('/order-management')
      } else if (type === 'positionManagement') {
        this.$router.replace('/position-management')
      } else if (type === 'runtime') {
        this.$router.replace('/runtime-observability')
      } else if (type === 'tpsl') {
        this.$router.replace('/tpsl')
      } else if (type === 'gantt') {
        this.$router.replace('/gantt?p=xgb')
      } else if (type === 'shouban30') {
        this.$router.replace('/gantt/shouban30?p=xgb&stock_window_days=30')
      } else if (type === 'stock') {
        this.$router.replace('/stock-control')
      } else if (type === 'pool') {
        this.$router.replace('/stock-pools')
      } else if (type === 'cjsd') {
        this.$router.replace('/stock-cjsd')
      }
    },
    goSetting () {
      this.$refs.mySetting.init()
    }
  }
}
</script>

<style lang="stylus">
@import "../style/my-header.styl";
</style>
