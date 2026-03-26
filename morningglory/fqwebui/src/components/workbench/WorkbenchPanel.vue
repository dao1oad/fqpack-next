<script setup>
defineProps({
  tag: {
    type: String,
    default: 'section',
  },
})
</script>

<template>
  <component :is="tag" class="workbench-panel" v-bind="$attrs">
    <slot />
  </component>
</template>
