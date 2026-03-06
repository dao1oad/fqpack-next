<template>
  <div class="kline-big-main kline-slim-main">
    <div class="kline-slim-toolbar">
      <div class="toolbar-left">
        <el-button size="small" @click="jumpToControl">股票</el-button>
        <el-input
          v-model="symbolInput"
          size="small"
          class="symbol-input"
          placeholder="请输入 symbol，例如 sh510050"
          @keyup.enter="applySymbol"
        />
        <el-button size="small" @click="applySymbol">切换</el-button>
        <el-button-group>
          <el-button
            v-for="period in periodList"
            :key="period"
            size="small"
            :type="currentPeriod === period ? 'primary' : 'default'"
            @click="switchPeriod(period)"
          >
            {{ period }}
          </el-button>
        </el-button-group>
        <el-date-picker
          v-model="endDateModel"
          type="date"
          size="small"
          value-format="YYYY-MM-DD"
          format="YYYY-MM-DD"
          clearable
          placeholder="历史日期"
          @change="applyEndDate"
        />
        <el-button size="small" @click="reloadNow">刷新</el-button>
        <el-button size="small" @click="jumpToBigChart">大图</el-button>
      </div>
      <div class="toolbar-right">
        <span class="status-chip">主图 {{ currentPeriod }}</span>
        <span class="status-chip">叠加 {{ overlayPeriod }}</span>
        <span class="status-chip">主图末 bar {{ lastMainBarLabel }}</span>
        <span class="status-chip" v-if="currentPeriod !== overlayPeriod">
          叠加末 bar {{ lastOverlayBarLabel }}
        </span>
        <span class="status-chip" :class="{ error: lastError }">{{ statusText }}</span>
      </div>
    </div>

    <div ref="chartHost" class="kline-slim-chart"></div>
    <div v-if="!routeSymbol" class="kline-slim-empty">
      请输入或通过 query 传入 `symbol`，例如 `/kline-slim?symbol=sh510050`
    </div>
  </div>
</template>

<script>
import klineSlim from './js/kline-slim'

export default klineSlim
</script>

<style lang="stylus">
@import "../style/kline-big.styl";

.kline-slim-main
  display block

.kline-slim-toolbar
  position absolute
  top 0
  left 0
  right 0
  min-height 52px
  padding 8px 12px
  z-index 10
  display flex
  align-items center
  justify-content space-between
  gap 12px
  border-bottom 1px solid rgba(127, 127, 122, 0.2)
  background rgba(18, 22, 28, 0.96)

.toolbar-left
  display flex
  align-items center
  flex-wrap wrap
  gap 8px

.toolbar-right
  display flex
  align-items center
  flex-wrap wrap
  justify-content flex-end
  gap 8px

.symbol-input
  width 220px

.status-chip
  display inline-flex
  align-items center
  padding 0 10px
  height 28px
  font-size 12px
  border-radius 999px
  border 1px solid rgba(127, 127, 122, 0.2)
  background rgba(31, 41, 55, 0.72)
  color #d1d5db

.status-chip.error
  color #fca5a5
  border-color rgba(248, 113, 113, 0.4)

.kline-slim-chart
  position absolute
  top 60px
  left 0
  right 0
  bottom 0

.kline-slim-empty
  position absolute
  top 60px
  left 0
  right 0
  bottom 0
  display flex
  align-items center
  justify-content center
  color #d1d5db
  font-size 14px

@media (max-width: 1200px)
  .kline-slim-toolbar
    align-items flex-start
    flex-direction column

  .toolbar-right
    justify-content flex-start

  .kline-slim-chart
    top 120px

  .kline-slim-empty
    top 120px
</style>
