<template>
  <el-popover
    :placement="placement"
    :width="width"
    trigger="hover"
    popper-class="shouban30-reason-popper"
  >
    <template #reference>
      <slot name="reference">
        <div class="shouban30-reason-trigger" :class="{ 'is-empty': !normalizedReferenceText }">
          {{ normalizedReferenceText || emptyText }}
        </div>
      </slot>
    </template>

    <div class="shouban30-reason-card">
      <div v-if="title || subtitle" class="shouban30-reason-card__head">
        <div class="shouban30-reason-card__title">{{ title || emptyText }}</div>
        <div v-if="subtitle" class="shouban30-reason-card__subtitle">{{ subtitle }}</div>
      </div>

      <div class="shouban30-reason-card__body">
        <slot>
          <div class="shouban30-reason-text">{{ normalizedContentText || emptyText }}</div>
        </slot>
      </div>
    </div>
  </el-popover>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  referenceText: {
    type: [String, Number],
    default: '',
  },
  contentText: {
    type: [String, Number],
    default: '',
  },
  title: {
    type: [String, Number],
    default: '',
  },
  subtitle: {
    type: [String, Number],
    default: '',
  },
  emptyText: {
    type: String,
    default: '-',
  },
  placement: {
    type: String,
    default: 'top-start',
  },
  width: {
    type: Number,
    default: 580,
  },
})

const toText = (value) => String(value ?? '').trim()

const normalizedReferenceText = computed(() => toText(props.referenceText))
const normalizedContentText = computed(() => {
  return toText(props.contentText) || normalizedReferenceText.value
})
</script>

<style>
.shouban30-reason-popper.el-popper {
  max-width: min(720px, calc(100vw - 24px));
  padding: 0 !important;
  border: 1px solid #e5dccb;
  border-radius: 18px;
  overflow: hidden;
  box-shadow: 0 18px 42px rgba(15, 23, 42, 0.18);
}

.shouban30-reason-popper.el-popper .el-popper__arrow::before {
  background: #fffdf8;
  border-color: #e5dccb;
}

.shouban30-reason-card {
  background: linear-gradient(180deg, #fffdf8 0%, #f5f7f2 100%);
  color: #1f2937;
}

.shouban30-reason-card__head {
  padding: 14px 18px 12px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
  background: linear-gradient(180deg, rgba(254, 252, 232, 0.92), rgba(255, 255, 255, 0.96));
}

.shouban30-reason-card__title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
  line-height: 1.4;
}

.shouban30-reason-card__subtitle {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.5;
  color: #64748b;
}

.shouban30-reason-card__body {
  padding: 14px 18px 16px;
}

.shouban30-reason-text,
.shouban30-reason-section__body,
.shouban30-reason-grid__value {
  font-size: 13px;
  line-height: 1.65;
  color: #334155;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.shouban30-reason-grid {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 8px 12px;
  margin-bottom: 14px;
}

.shouban30-reason-grid__label,
.shouban30-reason-section__label {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}

.shouban30-reason-section + .shouban30-reason-section {
  margin-top: 14px;
}

.shouban30-reason-section__label {
  margin-bottom: 6px;
}

@media (max-width: 900px) {
  .shouban30-reason-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>

<style scoped>
.shouban30-reason-trigger {
  display: block;
  min-width: 0;
  overflow: hidden;
  color: #374151;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}

.shouban30-reason-trigger.is-empty {
  color: #9ca3af;
}
</style>
