<script setup>
import WorkbenchPanel from './WorkbenchPanel.vue'

defineProps({
  tag: {
    type: String,
    default: 'section',
  },
})
</script>

<template>
  <WorkbenchPanel class="workbench-panel--ledger" :tag="tag" v-bind="$attrs">
    <slot />
  </WorkbenchPanel>
</template>
