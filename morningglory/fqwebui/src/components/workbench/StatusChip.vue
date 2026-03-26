<script setup>
import { computed } from 'vue'

const props = defineProps({
  variant: {
    type: String,
    default: 'muted',
  },
})

const chipClasses = computed(() => ({
  'workbench-summary-chip--info': props.variant === 'info',
  'workbench-summary-chip--muted': props.variant === 'muted',
  'workbench-summary-chip--success': props.variant === 'success',
  'workbench-summary-chip--warning': props.variant === 'warning',
  'workbench-summary-chip--danger': props.variant === 'danger',
  'workbench-summary-chip--skipped': props.variant === 'skipped',
}))
</script>

<template>
  <span class="workbench-summary-chip workbench-status-chip" :class="chipClasses" v-bind="$attrs">
    <slot />
  </span>
</template>
