<template>
  <section class="clx-config workbench-panel" data-testid="immutable-config">
    <div class="clx-config__header">
      <div><div class="clx-config__eyebrow">不可变研究配置</div><strong>{{ run.name }}</strong></div>
      <div class="clx-config__badges"><el-tag size="small" effect="plain">{{ run.runId }}</el-tag><el-tag size="small" type="info" effect="plain">SHA {{ hashShort(run.configSha256) }}</el-tag></div>
    </div>
    <div class="clx-config__grid">
      <div class="clx-config__item"><span>模型范围</span><b>{{ modelLabel }}</b></div><div class="clx-config__item"><span>CLX 参数</span><b>W {{ config.waveOpt ?? '--' }} · S {{ config.stretchOpt ?? '--' }} · E {{ config.extOpt ?? '--' }} · T {{ config.trendOpt ?? '--' }}</b></div><div class="clx-config__item"><span>TRAIN</span><b>{{ range(config.train) }}</b></div><div class="clx-config__item"><span>VALIDATION</span><b>{{ range(config.validation) }}</b></div><div class="clx-config__item"><span>HOLDOUT</span><b>{{ range(config.holdout) }}</b></div><div class="clx-config__item"><span>成交口径</span><b>T 日确认 → T+1 开盘</b></div><div class="clx-config__item"><span>信号价格域</span><b>前复权 OHLC + 原始成交量</b></div><div class="clx-config__item"><span>交易价格域</span><b>原始价格 · A股多头</b></div>
    </div>
    <el-collapse><el-collapse-item title="查看原始配置 JSON" name="raw"><div class="clx-config__raw-actions"><el-button size="small" link @click="copyConfig">复制 JSON</el-button></div><pre>{{ prettyConfig }}</pre></el-collapse-item></el-collapse>
  </section>
</template>

<script setup>
import { computed } from "vue";
import { ElMessage } from "element-plus";
import { hashShort } from "@/utils/clxFormat";
const props = defineProps({ run: { type: Object, required: true } });
const message = ElMessage;
const config = computed(() => props.run.config ?? {});
const prettyConfig = computed(() => JSON.stringify(config.value, null, 2));
const modelLabel = computed(() => config.value.modelIds?.length ? `${config.value.modelIds.length} \u4E2A\uFF08${config.value.modelIds[0]}\u2013${config.value.modelIds.at(-1)}\uFF09` : "\u7531\u914D\u7F6E\u6E05\u5355\u5B9A\u4E49");
const range = (value) => value?.start || value?.end ? `${value.start ?? "\u2026"} \uFF5E ${value.end ?? "\u2026"}` : "--";
async function copyConfig() {
  await navigator.clipboard?.writeText(prettyConfig.value);
  message.success("\u914D\u7F6E JSON \u5DF2\u590D\u5236");
}
</script>

<style scoped>
.clx-config {
  border: 1px solid var(--fq-border-soft);
  background: var(--fq-panel-bg);
  border-radius: 10px;
  padding: 16px;
}
.clx-config__header,
.clx-config__badges,
.clx-config__raw-actions { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.clx-config__eyebrow { color: var(--fq-text-muted); font-size: 11px; margin-bottom: 4px; }
.clx-config__grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  margin: 14px 0;
  border: 1px solid var(--fq-border-soft);
  background: var(--fq-border-soft);
  border-radius: 8px;
  overflow: hidden;
}
.clx-config__item { display: flex; flex-direction: column; gap: 5px; padding: 10px 12px; background: var(--fq-panel-bg-muted); min-width: 0; }
.clx-config__item span { color: var(--fq-text-muted); font-size: 11px; }
.clx-config__item b { font-size: 12px; font-weight: 500; word-break: break-word; }
pre { max-height: 260px; overflow: auto; color: var(--fq-text-muted); font: 11px/1.6 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; }
@media (max-width: 1100px) { .clx-config__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px) {
  .clx-config__header { align-items: flex-start; flex-direction: column; }
  .clx-config__badges { flex-wrap: wrap; }
  .clx-config__grid { grid-template-columns: 1fr; }
}
</style>