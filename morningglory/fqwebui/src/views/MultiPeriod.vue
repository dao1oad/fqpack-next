<template>
    <div class="multi-period-main">
        <KlineHeader ref="klineHeader" :periodList="periodList"
            :quickCalc="quickCalc" :submitSymbol="submitSymbol" :quickCalcMaxCount="quickCalcMaxCount"
            :quickSwitchDay="quickSwitchDay" :switchPeriod="switchPeriod" :jumpToControl="jumpToControl"
            :showPeriodList="false" :changeDate="changeDate" :jumpToMultiPeriod="jumpToMultiPeriod"
            :quickSwitchSymbol="quickSwitchSymbol" :futureSymbolList="futureSymbolList"></KlineHeader>
        <div class="echarts-list">
            <div class="echarts-item" id="main15Parent">
                <div id="main15" class="echarts">
                </div>
            </div>
            <div class="echarts-item" id="main60Parent">
                <div id="main60" class="echarts">
                </div>
            </div>
            <div class="echarts-item" id="main1dParent">
                <div id="main1d" class="echarts">
                </div>
            </div>
            <div class="echarts-item" id="main1Parent">
                <div id="main1" class="echarts">
                </div>
            </div>
            <div class="echarts-item" id="main5Parent">
                <div id="main5" class="echarts">
                </div>
            </div>
            <div class="echarts-item" id="main30Parent">
                <div id="main30" class="echarts">
                </div>
            </div>
            <div class="echarts-item" id="main240Parent">
                <div id="main240" class="echarts">
                </div>
            </div>
        </div>
    </div>
</template>
<script>
import multiPeriod from "./js/multi-period.js"
export default multiPeriod
</script>
<style lang="stylus">
    @import "../style/multi-period.styl";
</style>
