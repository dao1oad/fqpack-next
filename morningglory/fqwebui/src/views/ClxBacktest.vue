<template>
  <WorkbenchPage class="clx-backtest-page" data-testid="clx-workbench">
    <MyHeader />
    <div class="workbench-body workbench-body--scroll clx-backtest-body">
      <WorkbenchToolbar class="clx-workbench__toolbar">
        <div class="workbench-toolbar__header">
          <div class="clx-workbench__identity">
            <div class="clx-workbench__mark">CLX</div>
            <div class="workbench-title-group">
              <span class="clx-workbench__eyebrow">FRESHQUANT RESEARCH</span>
              <h1 class="workbench-page-title">CLX 大规模回测研究工作台</h1>
              <div class="workbench-page-meta">S0000～S0017 · 因果逐日前缀 · A股多头组合 · TRAIN / VALIDATION / HOLDOUT</div>
            </div>
          </div>
          <div class="workbench-toolbar__actions clx-workbench__status">
            <el-tag size="small" :type="healthState === 'online' ? 'success' : healthState === 'offline' ? 'danger' : 'info'" effect="plain" round><span class="clx-health-dot" :class="healthState" />{{ healthState === 'online' ? '研究 API 正常' : healthState === 'offline' ? '研究 API 异常' : '正在探测 API' }}</el-tag>
            <StatusChip variant="info">T+1 OPEN</StatusChip><StatusChip variant="warning">HOLDOUT SEALED</StatusChip>
          </div>
        </div>
        <nav class="clx-workbench__tabs" aria-label="CLX研究功能">
          <button v-for="item in tabs" :key="item.value" :class="{ active: activeTab === item.value }" :data-testid="`tab-${item.value}`" @click="activeTab = item.value"><span class="clx-tab-index">{{ item.index }}</span><span><b>{{ item.label }}</b><small>{{ item.description }}</small></span></button>
        </nav>
      </WorkbenchToolbar>
      <main class="clx-workbench__content">
        <ClxResultsPanel v-if="activeTab === 'results'" :initial-run-id="focusRunId" />
        <ClxExperimentsPanel v-else-if="activeTab === 'experiments'" @open-results="openResults" />
        <ClxComparePanel v-else />
      </main>
    </div>
  </WorkbenchPage>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { clxBacktestApi } from "@/api/clxBacktestApi";
import MyHeader from "./MyHeader.vue";
import WorkbenchPage from "@/components/workbench/WorkbenchPage.vue";
import WorkbenchToolbar from "@/components/workbench/WorkbenchToolbar.vue";
import StatusChip from "@/components/workbench/StatusChip.vue";
import ClxResultsPanel from "@/components/clx-backtest/ClxResultsPanel.vue";
import ClxExperimentsPanel from "@/components/clx-backtest/ClxExperimentsPanel.vue";
import ClxComparePanel from "@/components/clx-backtest/ClxComparePanel.vue";
const route = useRoute();
const router = useRouter();
const tabValues = ["results", "experiments", "compare"];
const queryTab = String(route.query.tab ?? "");
const activeTab = ref(tabValues.includes(queryTab) ? queryTab : "results");
const focusRunId = ref(String(route.query.run_id ?? ""));
const healthState = ref("checking");
const tabs = [
  { value: "results", index: "F1", label: "\u7ED3\u679C\u5206\u6790", description: "\u6392\u884C \xB7 \u70ED\u529B\u56FE \xB7 \u4E0B\u94BB" },
  { value: "experiments", index: "F2", label: "\u5B9E\u9A8C\u8FD0\u884C", description: "\u521B\u5EFA \xB7 \u8FDB\u5EA6 \xB7 \u590D\u73B0" },
  { value: "compare", index: "F3", label: "\u5BF9\u6BD4\u4E0E\u5BA1\u8BA1", description: "\u51BB\u7ED3 \xB7 \u63ED\u793A \xB7 \u5BFC\u51FA" }
];
watch(activeTab, (value) => {
  router.replace({ query: { ...route.query, tab: value, run_id: focusRunId.value || void 0 } });
});
function openResults(runId) {
  focusRunId.value = runId;
  activeTab.value = "results";
}
async function probeHealth() {
  try {
    await clxBacktestApi.health();
    healthState.value = "online";
  } catch {
    healthState.value = "offline";
  }
}
onMounted(() => {
  document.body.classList.add("clx-backtest-page");
  probeHealth();
});
onBeforeUnmount(() => document.body.classList.remove("clx-backtest-page"));
</script>

<style scoped>
.clx-workbench { min-height: 100%; display: flex; flex-direction: column; gap: 14px; color: var(--fq-text-primary); }
.clx-workbench__header { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 2px 2px 0; }
.clx-workbench__identity { display: flex; align-items: center; gap: 13px; min-width: 0; }
.clx-workbench__mark { width: 46px; height: 46px; display: grid; place-items: center; border: 1px solid color-mix(in srgb, var(--fq-status-primary) 48%, transparent); border-radius: 11px; background: linear-gradient(145deg, color-mix(in srgb, var(--fq-status-primary) 16%, var(--fq-panel-bg)), var(--fq-panel-bg)); color: var(--fq-status-primary); font: 700 13px ui-monospace, monospace; box-shadow: inset 0 0 20px rgba(137,180,250,.05); flex: 0 0 auto; }
.clx-workbench__eyebrow { color: var(--fq-status-primary); font-size: 9px; letter-spacing: .16em; }
.clx-workbench h1 { font-size: 18px; margin: 2px 0 3px; letter-spacing: .01em; }.clx-workbench__identity p { margin: 0; color: var(--fq-text-muted); font-size: 10px; }
.clx-workbench__status { display: flex; align-items: center; justify-content: flex-end; gap: 6px; flex-wrap: wrap; }.clx-health-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; margin-right: 5px; background: var(--fq-text-muted); }.clx-health-dot.online { background: var(--fq-status-success); box-shadow: 0 0 7px var(--fq-status-success); }.clx-health-dot.offline { background: var(--fq-status-danger); }
.clx-workbench__tabs { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; padding: 6px; border: 1px solid var(--fq-border-soft); border-radius: 11px; background: var(--fq-panel-bg-muted); position: sticky; top: -20px; z-index: 20; }
.clx-workbench__tabs button { appearance: none; border: 1px solid transparent; border-radius: 8px; background: transparent; color: var(--fq-text-muted); padding: 9px 12px; display: flex; align-items: center; gap: 10px; text-align: left; cursor: pointer; transition: all .16s; min-width: 0; }.clx-workbench__tabs button:hover { background: var(--fq-panel-bg-muted); color: var(--fq-text-primary); }.clx-workbench__tabs button.active { border-color: var(--fq-border-soft); background: var(--fq-panel-bg-muted); color: var(--fq-text-primary); box-shadow: 0 4px 14px rgba(0,0,0,.16); }
.clx-tab-index { width: 27px; height: 27px; display: grid; place-items: center; border-radius: 6px; background: var(--fq-panel-bg); color: var(--fq-text-muted); font: 700 10px ui-monospace, monospace; flex: 0 0 auto; }.active .clx-tab-index { color: var(--fq-panel-bg-muted); background: var(--fq-status-primary); }.clx-workbench__tabs b, .clx-workbench__tabs small { display: block; }.clx-workbench__tabs b { font-size: 12px; }.clx-workbench__tabs small { margin-top: 2px; color: var(--fq-text-muted); font-size: 9px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.clx-workbench__content { min-width: 0; padding-bottom: 20px; }
@media (max-width: 760px) { .clx-workbench__header { align-items: flex-start; flex-direction: column; }.clx-workbench__status { justify-content: flex-start; }.clx-workbench__identity p { display: none; }.clx-workbench__tabs { top: -20px; }.clx-workbench__tabs button { padding: 8px; }.clx-workbench__tabs small { display: none; } }
@media (max-width: 640px) { :global(body.clx-backtest-page .fq-statusbar) { justify-content: space-between; } :global(body.clx-backtest-page .fq-statusbar__center) { display: none; } }
@media (max-width: 430px) { .clx-workbench h1 { font-size: 15px; }.clx-workbench__mark { width: 40px; height: 40px; }.clx-tab-index { display: none; }.clx-workbench__tabs button { justify-content: center; text-align: center; } }
</style>
