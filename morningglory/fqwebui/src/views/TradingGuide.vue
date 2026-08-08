<template>
  <WorkbenchPage class="trading-guide-page">
    <MyHeader />

    <div class="workbench-body trading-guide-body">
      <iframe
        ref="frame"
        class="trading-guide-frame"
        title="FreshQuant 交易体系课堂"
        src="/trading-guide/index.html"
      ></iframe>
    </div>
  </WorkbenchPage>
</template>

<script>
import WorkbenchPage from '@/components/workbench/WorkbenchPage.vue'
import MyHeader from '@/views/MyHeader.vue'

export default {
  name: 'trading-guide',
  components: {
    WorkbenchPage,
    MyHeader,
  },
}
</script>

<style scoped>
.trading-guide-body {
  padding: 0;
}

.trading-guide-frame {
  flex: 1 1 auto;
  width: 100%;
  height: 100%;
  min-height: 0;
  border: 0;
  display: block;
  background: #0b0f17;
}
</style>
