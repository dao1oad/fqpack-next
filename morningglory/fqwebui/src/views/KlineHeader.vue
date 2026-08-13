<template>
  <div class="kline-header-main">
    <div class="input-form">
      <el-space>
        <el-button
          type="danger"
          @click="jumpToControl('stock')"
          size="small"
          class="primary-button"
          >股票</el-button
        >
        <el-button
          type="success"
          @click="jumpToMultiPeriod"
          size="small"
          v-if="showPeriodList"
          class="primary-button"
          >多周期</el-button
        >
      </el-space>
      <el-space>
        <el-date-picker
          v-model="internalEndDate"
          type="date"
          placeholder="选择日期"
          format="YYYY 年 MM 月 DD 日"
          value-format="YYYY-MM-DD"
          size="small"
          @change="changeDate"
          class="ml-5 mr-5"
        >
        </el-date-picker>
      </el-space>
      <el-space>
        <el-button
          type="primary"
          class="primary-button"
          @click="quickSwitchDay('pre')"
          size="small"
          >前一天</el-button
        >
        <el-button
          type="primary"
          class="primary-button"
          @click="quickSwitchDay('next')"
          size="small"
          >后一天</el-button
        >
      </el-space>
      <el-space>
        <el-input
          v-model="internalInputSymbol"
          placeholder="请输入代码"
          size="small"
          class="search-symbol-input ml-5 mr-5"
          @change="submitSymbol"
        />
      </el-space>
      <el-space v-if="showPeriodList">
        <el-button
          type="primary"
          class="primary-button"
          v-for="period in periodList"
          :key="period"
          size="small"
          @click="switchPeriod(period)"
          >{{ period }}</el-button
        >
      </el-space>
    </div>
  </div>
</template>
<script>
export default {
  name: 'KlineHeader',
  data () {
    return {
      internalEndDate: this.endDate,
      internalInputSymbol: this.inputSymbol,
    }
  },
  emits: ['update:endDate', 'update:inputSymbol'],
  props: {
    showPeriodList: {
      type: Boolean,
      default: false
    },
    quickCalc: {
      type: Object,
      default: null
    },
    submitSymbol: {
      type: Function,
      default: null
    },
    quickCalcMaxCount: {
      type: Function,
      default: null
    },
    quickSwitchDay: {
      type: Function,
      default: null
    },
    switchPeriod: {
      type: Function,
      default: null
    },
    jumpToControl: {
      type: Function,
      default: null
    },
    changeDate: {
      type: Function,
      default: null
    },
    jumpToMultiPeriod: {
      type: Function,
      default: null
    },
    quickSwitchSymbol: {
      type: Function,
      default: null
    },
    periodList: {
      type: Array,
      default: null
    },
    inputSymbol: {
      type: String,
      default: ''
    },
    endDate: {
      type: String,
      default: ''
    },
    futureSymbolList: {
      type: Array,
      default: null
    }
  },
  watch: {
    endDate (newVal) {
      this.internalEndDate = newVal
    },
    inputSymbol (newVal) {
      this.internalInputSymbol = newVal
    }
  },
  methods: {
    setELDatePicker (endDate) {
      this.internalEndDate = endDate
    }
  }
}
</script>
<style lang="stylus">
@import "../style/kline-header.styl";

.kline-header-main
  display flex
  align-items center
.input-form
  display flex
  align-items center
  width 100%
  gap 10px
</style>
