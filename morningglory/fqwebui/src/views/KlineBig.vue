<template>
    <div class="kline-big-main">
        <KlineHeader ref="klineHeader" :periodList="periodList" :endDate="$route.query.endDate" :inputSymbol="$route.query.symbol"
            :quickCalc="quickCalc" :submitSymbol="submitSymbol" :quickCalcMaxCount="quickCalcMaxCount"
            :quickSwitchDay="quickSwitchDay" :switchPeriod="switchPeriod" :jumpToControl="jumpToControl"
            :showPeriodList="true" :changeDate="changeDate" :jumpToMultiPeriod="jumpToMultiPeriod"
            :quickSwitchSymbol="quickSwitchSymbol" :futureSymbolList="futureSymbolList"></KlineHeader>
        <div class="echarts-item-big" id="mainParent">
            <div id="main">
            </div>
        </div>
    </div>
</template>
<script>
import klineBig from './js/kline-big.js'
export default klineBig
</script>
<style lang="stylus">
    @import "../style/kline-big.styl";
</style>
