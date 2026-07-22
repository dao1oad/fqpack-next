<template>
  <el-drawer :model-value="show" size="min(960px, 94vw)" direction="rtl" @update:model-value="$emit('update:show', $event)">
    <template #header><div class="clx-kline__title"><span>{{ signal?.code }} {{ signal?.name }}</span><el-tag v-if="signal" size="small" :type="isPositive ? 'danger' : 'success'" effect="plain">{{ isPositive ? '正向' : '负向' }} · {{ signal.modelId }}</el-tag></div></template>
    <el-alert v-if="error" type="error" :closable="false" :title="error" style="margin-bottom: 12px" />
    <div v-if="signal" class="clx-kline__facts"><div><span>信号日</span><b>{{ signal.signalDate }}</b></div><div><span>可见日</span><b>{{ signal.revealDate }}</b></div><div><span>第几次</span><b>{{ signal.occurrence || '--' }}</b></div><div><span>主触发</span><b>{{ signal.primaryTrigger || '--' }}</b></div><div class="clx-kline__wide"><span>同K线并发触发</span><b>{{ signal.concurrentTriggers.join(' · ') || '--' }}</b></div></div>
    <section class="clx-kline__chart"><div class="clx-kline__chart-title">日线（前后窗口）</div><ClxChart :option="option" :loading="loading" :empty="!candles.length" height="520px" empty-text="暂无该标的K线数据" /></section>
    <el-alert type="info" :closable="false" class="clx-kline__note" title="图中标记对应 signal_date；reveal_date 用于判断信息何时可见。实际撮合最早在下一交易日开盘，并使用原始价格域。" />
  </el-drawer>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { clxBacktestApi, describeApiError } from "@/api/clxBacktestApi";
import ClxChart from "./ClxChart.vue";
const props = defineProps({
  show: { type: Boolean, default: false },
  signal: { type: Object, default: null },
});
defineEmits(["update:show"]);
const candles = ref([]);
const loading = ref(false);
const error = ref("");
const isPositive = computed(() => ["BUY", "LONG", "POSITIVE", "1"].includes(String(props.signal?.direction).toUpperCase()));
async function load() {
  if (!props.show || !props.signal?.code) return;
  loading.value = true;
  error.value = "";
  candles.value = [];
  try {
    candles.value = await clxBacktestApi.getCandles(props.signal.code, props.signal.revealDate || props.signal.signalDate);
  } catch (reason) {
    error.value = describeApiError(reason);
  } finally {
    loading.value = false;
  }
}
watch(() => [props.show, props.signal?.signalId], load, { immediate: true });
const option = computed(() => ({
  animation: false,
  backgroundColor: "transparent",
  color: ["#f38ba8", "#94e2d5"],
  tooltip: { trigger: "axis", axisPointer: { type: "cross" }, confine: true },
  axisPointer: { link: [{ xAxisIndex: [0, 1] }] },
  grid: [
    { left: 62, right: 24, top: 28, height: "66%" },
    { left: 62, right: 24, top: "77%", bottom: 28 }
  ],
  xAxis: [
    { type: "category", data: candles.value.map((item) => item.date), boundaryGap: true, axisLabel: { show: false }, axisLine: { lineStyle: { color: "#45475a" } } },
    { type: "category", gridIndex: 1, data: candles.value.map((item) => item.date), boundaryGap: true, axisLabel: { color: "#a6adc8", fontSize: 9 }, axisLine: { lineStyle: { color: "#45475a" } } }
  ],
  yAxis: [
    { scale: true, axisLabel: { color: "#a6adc8" }, splitLine: { lineStyle: { color: "rgba(255,255,255,.05)" } } },
    { gridIndex: 1, scale: true, axisLabel: { color: "#a6adc8" }, splitLine: { show: false } }
  ],
  dataZoom: [{ type: "inside", xAxisIndex: [0, 1], start: Math.max(0, 100 - 80) }, { type: "slider", xAxisIndex: [0, 1], bottom: 0, height: 14 }],
  series: [
    {
      name: "\u65E5\u7EBF",
      type: "candlestick",
      data: candles.value.map((item) => [item.open, item.close, item.low, item.high]),
      itemStyle: { color: "#f38ba8", color0: "#94e2d5", borderColor: "#f38ba8", borderColor0: "#94e2d5" },
      markPoint: props.signal ? {
        symbol: isPositive.value ? "pin" : "arrow",
        symbolSize: 44,
        label: { formatter: props.signal.modelId, color: "#11111b", fontSize: 9 },
        itemStyle: { color: isPositive.value ? "#f9e2af" : "#89b4fa" },
        data: [{ coord: [props.signal.signalDate, isPositive.value ? candles.value.find((item) => item.date === props.signal?.signalDate)?.low : candles.value.find((item) => item.date === props.signal?.signalDate)?.high] }]
      } : void 0
    },
    {
      name: "\u6210\u4EA4\u91CF",
      type: "bar",
      xAxisIndex: 1,
      yAxisIndex: 1,
      data: candles.value.map((item, index) => ({ value: item.volume ?? 0, itemStyle: { color: index && item.close < candles.value[index - 1].close ? "#94e2d5" : "#f38ba8", opacity: 0.65 } }))
    }
  ]
}));
</script>

<style scoped>
.clx-kline__title { display: flex; gap: 10px; align-items: center; }
.clx-kline__facts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; overflow: hidden; border: 1px solid var(--fq-border-soft); border-radius: 8px; background: var(--fq-border-soft); margin-bottom: 14px; }
.clx-kline__facts > div { display: flex; flex-direction: column; gap: 5px; padding: 10px; background: var(--fq-panel-bg-muted); }
.clx-kline__facts span { color: var(--fq-text-muted); font-size: 11px; }
.clx-kline__facts b { font-size: 12px; font-weight: 500; }
.clx-kline__wide { grid-column: span 4; }
.clx-kline__chart { border: 1px solid var(--fq-border-soft); border-radius: 8px; padding: 12px; background: var(--fq-panel-bg); }
.clx-kline__chart-title { font-size: 12px; font-weight: 600; margin-bottom: 4px; }
.clx-kline__note { margin-top: 12px; font-size: 12px; }
@media (max-width: 680px) { .clx-kline__facts { grid-template-columns: repeat(2, minmax(0, 1fr)); } .clx-kline__wide { grid-column: span 2; } }
</style>