<script setup>
import WorkbenchPanel from './WorkbenchPanel.vue'

defineProps({
  tag: {
    type: String,
    default: 'aside',
  },
})
</script>

<template>
  <WorkbenchPanel class="workbench-panel--sidebar" :tag="tag" v-bind="$attrs">
    <slot />
  </WorkbenchPanel>
</template>
