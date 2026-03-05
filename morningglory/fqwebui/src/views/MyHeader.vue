<template>
  <div class="header-main">
    <div class="header-menu">
      <MySetting ref="mySetting"></MySetting>
      <el-button-group>
        <el-button type="primary" @click="goSetting">设置</el-button>
      </el-button-group>
      <el-button-group>
        <el-button type="primary" @click="jumpToControl('futures')" size="small"
          >期货</el-button
        >
      </el-button-group>
      <el-button-group>
        <el-button type="primary" @click="jumpToControl('stock')" size="small"
          >股票</el-button
        >
        <el-button type="primary" @click="jumpToControl('pool')" size="small"
          >股票池</el-button
        >
        <el-button type="primary" @click="jumpToControl('cjsd')" size="small"
          >超级赛道</el-button
        >
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
  data () {
    return {}
  },
  components: {
    MySetting
  },
  methods: {
    jumpToControl (type) {
      if (type === 'futures') {
        this.$router.replace('/futures-control')
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
