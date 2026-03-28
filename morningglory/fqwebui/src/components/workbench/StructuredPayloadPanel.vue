<script setup>
const props = defineProps({
  title: {
    type: String,
    default: '',
  },
  emptyLabel: {
    type: String,
    default: '',
  },
  entries: {
    type: Array,
    default: () => [],
  },
})

const normalizeEntryValue = (value) => {
  const normalized = String(value ?? '').trim()
  return normalized || '-'
}
</script>

<template>
  <section class="structured-payload-panel">
    <div v-if="title" class="structured-payload-panel__title">{{ title }}</div>
    <div v-if="entries.length" class="structured-payload-panel__body">
      <article
        v-for="entry in entries"
        :key="entry.key"
        class="structured-payload-field"
      >
        <div class="structured-payload-field__label">{{ entry.label }}</div>
        <div
          :class="[
            'structured-payload-field__value',
            `is-${entry.kind || 'short'}`,
          ]"
        >
          {{ normalizeEntryValue(entry.value) }}
        </div>
      </article>
    </div>
    <div v-else class="structured-payload-panel__empty">
      {{ emptyLabel || '-' }}
    </div>
  </section>
</template>

<style scoped>
.structured-payload-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border: 1px solid #e2eaf4;
  border-radius: 10px;
  background: #fbfdff;
  overflow: hidden;
}

.structured-payload-panel__title {
  padding: 8px 10px;
  border-bottom: 1px solid #e6eef7;
  background: #f6f9fc;
  color: #66829c;
  font-size: 12px;
  font-weight: 600;
}

.structured-payload-panel__body {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.structured-payload-field {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 6px;
  padding: 8px 10px;
  border-top: 1px solid #edf2f7;
}

.structured-payload-field:first-child {
  border-top: 0;
}

.structured-payload-field__label {
  min-width: 0;
  color: #68829b;
  font-size: 12px;
  line-height: 1.4;
}

.structured-payload-field__value {
  min-width: 0;
  color: #21405e;
  font-size: 12px;
  line-height: 1.45;
}

.structured-payload-field__value.is-short,
.structured-payload-field__value.is-empty {
  overflow-wrap: anywhere;
  word-break: break-word;
}

.structured-payload-field__value.is-machine {
  overflow-x: auto;
  overflow-y: hidden;
  white-space: nowrap;
  font-family: Consolas, 'Courier New', monospace;
  scrollbar-width: thin;
}

.structured-payload-field__value.is-multiline {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.structured-payload-panel__empty {
  padding: 10px;
  color: #69829b;
  font-size: 12px;
}
</style>
