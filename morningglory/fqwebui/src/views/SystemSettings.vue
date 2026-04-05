<template>
  <WorkbenchPage class="system-settings-page system-settings-shell">
    <MyHeader />
    <div class="workbench-body settings-shell" v-loading="loading">
      <WorkbenchToolbar class="settings-dense-toolbar">
        <div class="settings-dense-toolbar__title">
          <p class="settings-toolbar-kicker">System Config</p>
          <h1>系统设置</h1>
          <p class="settings-toolbar-copy">
            正式真值只保留 Bootstrap 文件与 Mongo。当前页面直接以内嵌列表编辑全部正式设置项。
          </p>
          <div class="settings-toolbar-meta">
            <StatusChip class="settings-toolbar-chip settings-toolbar-chip--path" variant="info" :title="bootstrapFilePath">
              Bootstrap
              <strong>{{ bootstrapFilePath }}</strong>
            </StatusChip>
            <StatusChip class="settings-toolbar-chip settings-toolbar-chip--muted" variant="warning">
              启动配置已改
              <strong>{{ bootstrapDirtyCount }}</strong>
            </StatusChip>
            <StatusChip class="settings-toolbar-chip settings-toolbar-chip--soft" variant="success">
              Mongo 已改
              <strong>{{ settingsDirtyCount }}</strong>
            </StatusChip>
          </div>
        </div>

        <div class="settings-dense-toolbar__actions">
          <el-button @click="loadDashboard">刷新</el-button>
          <el-button
            type="primary"
            :disabled="bootstrapDirtyCount === 0"
            :loading="savingBootstrap"
            @click="saveBootstrap"
          >
            {{ bootstrapSaveLabel }}
          </el-button>
          <el-button
            type="primary"
            plain
            :disabled="settingsDirtyCount === 0"
            :loading="savingSettings"
            @click="saveSettings"
          >
            {{ settingsSaveLabel }}
          </el-button>
        </div>
      </WorkbenchToolbar>

      <el-alert
        v-if="pageError"
        class="page-error"
        type="error"
        :title="pageError"
        show-icon
        :closable="false"
      />

      <div class="settings-dense-columns">
        <section
          v-for="column in ledgerColumns"
          :key="column.key"
          class="settings-dense-column"
        >
          <header class="settings-dense-column__head">
            <strong>{{ column.title }}</strong>
            <span>{{ column.sections.length }} 组</span>
          </header>

          <div class="settings-dense-column__body">
            <article
              v-for="section in column.sections"
              :key="section.key"
              class="settings-dense-section"
            >
              <div class="settings-dense-section__header">
                <div class="settings-dense-section__summary">
                  <div>
                    <h2>{{ section.title }}</h2>
                    <p>{{ section.description }}</p>
                  </div>
                  <StatusChip class="settings-inline-chip" :variant="sectionModeChipVariant(section)">
                    {{ section.readonly ? '只读' : section.restart_required ? '需重启' : '即时' }}
                  </StatusChip>
                </div>

                <div
                  class="settings-ledger__header"
                  :class="section.kind === 'strategy-ledger' ? 'settings-strategy-ledger__grid' : 'settings-config-ledger__grid'"
                >
                  <template v-if="section.kind === 'strategy-ledger'">
                    <span>策略</span>
                    <span>名称</span>
                    <span>说明</span>
                    <span>b62_uid</span>
                  </template>
                  <template v-else>
                    <span>设置项</span>
                    <span>当前值</span>
                    <span>生效</span>
                    <span>来源</span>
                    <span>状态</span>
                  </template>
                </div>
              </div>

              <div
                class="settings-ledger"
                :class="section.kind === 'strategy-ledger' ? 'settings-strategy-ledger' : 'settings-config-ledger'"
              >
                <template v-if="section.kind === 'strategy-ledger'">
                  <div v-if="section.rows.length">
                    <div
                      v-for="row in section.rows"
                      :key="row.key"
                      class="settings-ledger__row settings-strategy-ledger__grid"
                    >
                      <span class="settings-ledger__cell settings-ledger__cell--strong">{{ row.code }}</span>
                      <span class="settings-ledger__cell settings-ledger__cell--truncate" :title="row.name">{{ row.name }}</span>
                      <span class="settings-ledger__cell settings-ledger__cell--truncate" :title="row.desc">{{ row.desc }}</span>
                      <span class="settings-ledger__cell settings-ledger__cell--mono settings-ledger__cell--truncate" :title="row.b62_uid">{{ row.b62_uid }}</span>
                    </div>
                  </div>
                  <div v-else class="settings-ledger-empty">
                    暂无策略字典记录。
                  </div>
                </template>
                <template v-else>
                  <div
                    v-for="row in section.rows"
                    :key="row.key"
                    class="settings-ledger__row settings-ledger__row--editable settings-config-ledger__grid"
                    :class="resolveRowClass(row)"
                  >
                    <div class="settings-ledger__cell settings-ledger__cell--primary">
                      <strong>{{ row.label }}</strong>
                      <span :title="row.full_path">{{ row.full_path }}</span>
                      <small
                        v-if="row.key === 'position_management.single_symbol_position_limit'"
                        class="settings-ledger__cell-hint"
                      >
                        未为某个标的单独设置上限时，默认使用这里的值
                      </small>
                    </div>

                    <div class="settings-ledger__cell settings-ledger__cell--editor">
                      <span
                        v-if="row.readonly"
                        class="settings-ledger__readonly-value"
                        :title="row.value_label"
                      >
                        {{ row.value_label }}
                      </span>

                      <el-select
                        v-else-if="row.editor.type === 'select'"
                        :model-value="readRowValue(row)"
                        size="small"
                        @update:model-value="(value) => updateRowValue(row, value)"
                      >
                        <el-option
                          v-for="option in row.editor.options"
                          :key="option.value"
                          :label="option.label"
                          :value="option.value"
                        />
                      </el-select>

                      <el-input-number
                        v-else-if="row.editor.type === 'number'"
                        :model-value="readRowValue(row)"
                        size="small"
                        :min="row.editor.min"
                        :step="row.editor.step"
                        :precision="row.editor.precision"
                        controls-position="right"
                        @update:model-value="(value) => updateRowValue(row, value)"
                      />

                      <el-input
                        v-else
                        :model-value="readRowValue(row)"
                        size="small"
                        :type="row.editor.type === 'password' ? 'password' : 'text'"
                        :show-password="row.editor.type === 'password'"
                        @update:model-value="(value) => updateRowValue(row, value)"
                      />
                    </div>

                    <div class="settings-ledger__cell settings-ledger__cell--badge">
                      <StatusChip class="settings-inline-chip" :variant="restartModeChipVariant(row.restart_required)">
                        {{ row.restart_required ? '重启' : '即时' }}
                      </StatusChip>
                    </div>

                    <div class="settings-ledger__cell settings-ledger__cell--badge">
                      <StatusChip class="settings-inline-chip is-source" variant="info" :title="row.source">
                        {{ resolveSourceLabel(row) }}
                      </StatusChip>
                    </div>

                    <div class="settings-ledger__cell settings-ledger__cell--badge">
                      <StatusChip class="settings-inline-chip" :variant="stateChipVariant(row)">
                        {{ resolveStateLabel(row) }}
                      </StatusChip>
                    </div>
                  </div>
                </template>
              </div>
            </article>
          </div>
        </section>
      </div>
    </div>
  </WorkbenchPage>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import StatusChip from '@/components/workbench/StatusChip.vue'
import WorkbenchPage from '@/components/workbench/WorkbenchPage.vue'
import WorkbenchToolbar from '@/components/workbench/WorkbenchToolbar.vue'
import { positionManagementApi } from '@/api/positionManagementApi'
import MyHeader from '@/views/MyHeader.vue'
import { systemConfigApi } from '@/api/systemConfigApi'
import {
  buildBootstrapLedgerSections,
  buildLedgerColumns,
  buildPositionInventorySupplementSection,
  buildSettingsLedgerSections,
  buildStrategyLedgerSection,
  countDirtyRows,
  flattenLedgerRows,
  readSystemConfigPayload,
} from './systemSettings.mjs'

const loading = ref(false)
const savingBootstrap = ref(false)
const savingSettings = ref(false)
const pageError = ref('')
const dashboard = ref({})
const positionInventoryDashboard = ref({})
const bootstrapBaseline = ref(defaultBootstrapForm())
const settingsBaseline = ref(defaultSettingsForm())

const bootstrapForm = reactive(defaultBootstrapForm())
const settingsForm = reactive(defaultSettingsForm())

const bootstrapFilePath = computed(() => dashboard.value?.bootstrap?.file_path || '未发现 bootstrap 文件')
const bootstrapLedgerSections = computed(() => buildBootstrapLedgerSections(dashboard.value, {
  currentValues: bootstrapForm,
  baselineValues: bootstrapBaseline.value,
}))
const settingsLedgerSections = computed(() => buildSettingsLedgerSections(dashboard.value, {
  currentValues: settingsForm,
  baselineValues: settingsBaseline.value,
}))
const strategyLedgerSection = computed(() => buildStrategyLedgerSection(dashboard.value))
const positionInventorySupplementSection = computed(() => buildPositionInventorySupplementSection(
  positionInventoryDashboard.value,
  flattenLedgerRows(settingsLedgerSections.value),
))
const ledgerColumns = computed(() => buildLedgerColumns([
  ...bootstrapLedgerSections.value,
  ...settingsLedgerSections.value,
  ...(positionInventorySupplementSection.value?.rows?.length ? [positionInventorySupplementSection.value] : []),
  strategyLedgerSection.value,
]))
const bootstrapDirtyCount = computed(() => countDirtyRows(bootstrapLedgerSections.value))
const settingsDirtyCount = computed(() => countDirtyRows(settingsLedgerSections.value))
const bootstrapSaveLabel = computed(() => (
  bootstrapDirtyCount.value > 0 ? `保存启动配置 (${bootstrapDirtyCount.value})` : '保存启动配置'
))
const settingsSaveLabel = computed(() => (
  settingsDirtyCount.value > 0 ? `保存系统设置 (${settingsDirtyCount.value})` : '保存系统设置'
))

function defaultBootstrapForm () {
  return {
    mongodb: { host: '', port: 27027, db: '', gantt_db: '' },
    redis: { host: '', port: 6380, db: 1, password: '' },
    order_management: { mongo_database: '', projection_database: '' },
    position_management: { mongo_database: '' },
    memory: {
      mongodb: { host: '', port: 27027, db: '' },
      cold_root: '',
      artifact_root: '',
    },
    tdx: { home: '', hq: { endpoint: '' } },
    api: { base_url: '' },
    xtdata: { port: 58610 },
    runtime: { log_dir: '' },
  }
}

function defaultSettingsForm () {
  return {
    notification: {
      webhook: {
        dingtalk: {
          private: '',
          public: '',
        },
      },
    },
    monitor: {
      xtdata: {
        mode: 'guardian_1m',
        max_symbols: 60,
        queue_backlog_threshold: 500,
        prewarm: { max_bars: 240 },
      },
    },
    xtquant: {
      path: '',
      account: '',
      account_type: 'STOCK',
      broker_submit_mode: 'normal',
      auto_repay: {
        enabled: true,
        reserve_cash: 5000,
      },
    },
    guardian: {
      stock: {
        initial_lot_amount_default: 100000,
        lot_amount: 50000,
        threshold: {
          mode: 'percent',
          percent: 1,
          atr: { period: 14, multiplier: 1 },
        },
        grid_interval: {
          mode: 'percent',
          percent: 3,
          atr: { period: 14, multiplier: 1 },
        },
      },
    },
    position_management: {
      allow_open_min_bail: 800000,
      holding_only_min_bail: 100000,
      single_symbol_position_limit: 800000,
    },
  }
}

const cloneValue = (value) => JSON.parse(JSON.stringify(value || {}))

const assignReactive = (target, source) => {
  Object.keys(target).forEach((key) => {
    delete target[key]
  })
  Object.entries(source || {}).forEach(([key, value]) => {
    target[key] = value
  })
}

const syncFormsFromDashboard = (payload) => {
  const nextBootstrap = {
    ...defaultBootstrapForm(),
    ...(cloneValue(payload?.bootstrap?.values)),
  }
  const nextSettings = {
    ...defaultSettingsForm(),
    ...(cloneValue(payload?.settings?.values)),
  }
  assignReactive(bootstrapForm, nextBootstrap)
  assignReactive(settingsForm, nextSettings)
  bootstrapBaseline.value = cloneValue(nextBootstrap)
  settingsBaseline.value = cloneValue(nextSettings)
}

const resolveErrorMessage = (error, fallback) => {
  const responseMessage = error?.response?.data?.error
  const directMessage = error?.message
  return responseMessage || directMessage || fallback
}

const readValueAtPath = (target, dottedPath) => {
  let current = target
  for (const part of dottedPath.split('.')) {
    if (!current || typeof current !== 'object' || !(part in current)) return undefined
    current = current[part]
  }
  return current
}

const writeValueAtPath = (target, dottedPath, value) => {
  const parts = dottedPath.split('.')
  let current = target
  for (const part of parts.slice(0, -1)) {
    if (!current[part] || typeof current[part] !== 'object') {
      current[part] = {}
    }
    current = current[part]
  }
  current[parts[parts.length - 1]] = value
}

const resolveTargetForm = (row) => (row.scope === 'bootstrap' ? bootstrapForm : settingsForm)

const readRowValue = (row) => readValueAtPath(resolveTargetForm(row), row.full_path)

const updateRowValue = (row, value) => {
  writeValueAtPath(resolveTargetForm(row), row.full_path, value)
}

const resolveSourceLabel = (row) => {
  if (row.source === 'bootstrap_file') return 'Bootstrap'
  if (row.source === 'pm_configs.thresholds') return 'PM'
  if (String(row.source || '').startsWith('runtime_default')) return '默认'
  if (String(row.source || '').startsWith('params.')) return 'Mongo'
  return '只读'
}

const sectionModeChipVariant = (section) => {
  if (section?.readonly) return 'muted'
  if (section?.restart_required) return 'warning'
  return 'success'
}

const restartModeChipVariant = (restartRequired) => (
  restartRequired ? 'warning' : 'success'
)

const resolveStateLabel = (row) => {
  if (row.readonly) return '只读'
  if (row.dirty) return '已改'
  if (row.inactive) return '未用'
  return '当前'
}

const stateChipVariant = (row) => {
  if (row.readonly) return 'muted'
  if (row.dirty) return 'warning'
  if (row.inactive) return 'muted'
  return 'success'
}

const resolveRowClass = (row) => ({
  'is-dirty': row.dirty,
  'is-inactive': row.inactive,
})

const loadDashboard = async () => {
  loading.value = true
  pageError.value = ''
  try {
    const [settingsResult, positionInventoryResult] = await Promise.allSettled([
      systemConfigApi.getDashboard(),
      positionManagementApi.getDashboard(),
    ])
    if (settingsResult.status !== 'fulfilled') {
      throw settingsResult.reason
    }
    const payload = readSystemConfigPayload(settingsResult.value, {})
    dashboard.value = payload
    syncFormsFromDashboard(payload)
    if (positionInventoryResult.status === 'fulfilled') {
      positionInventoryDashboard.value = positionInventoryResult.value?.data || positionInventoryResult.value || {}
    } else {
      positionInventoryDashboard.value = {}
    }
  } catch (error) {
    pageError.value = resolveErrorMessage(error, '加载系统设置失败')
  } finally {
    loading.value = false
  }
}

const saveBootstrap = async () => {
  savingBootstrap.value = true
  try {
    const response = await systemConfigApi.updateBootstrap(cloneValue(bootstrapForm))
    const payload = readSystemConfigPayload({
      ...dashboard.value,
      bootstrap: response.data,
      settings: dashboard.value?.settings || {},
    })
    dashboard.value = payload
    syncFormsFromDashboard(payload)
    ElMessage.success('启动配置已保存，请按需重启相关服务')
  } catch (error) {
    ElMessage.error(resolveErrorMessage(error, '保存启动配置失败'))
  } finally {
    savingBootstrap.value = false
  }
}

const saveSettings = async () => {
  if (Number(settingsForm.position_management.allow_open_min_bail) <= Number(settingsForm.position_management.holding_only_min_bail)) {
    ElMessage.error('允许开新仓最低保证金必须大于仅允许持仓内买入最低保证金')
    return
  }

  savingSettings.value = true
  try {
    const response = await systemConfigApi.updateSettings(cloneValue(settingsForm))
    const payload = readSystemConfigPayload({
      ...dashboard.value,
      bootstrap: dashboard.value?.bootstrap || {},
      settings: response.data,
    })
    dashboard.value = payload
    syncFormsFromDashboard(payload)
    ElMessage.success('系统设置已保存')
  } catch (error) {
    ElMessage.error(resolveErrorMessage(error, '保存系统设置失败'))
  } finally {
    savingSettings.value = false
  }
}

onMounted(() => {
  loadDashboard()
})
</script>

<style lang="stylus" scoped>
.system-settings-page
  display flex
  flex-direction column
  height 100vh
  height 100dvh
  overflow hidden
  background radial-gradient(circle at top left, rgba(206, 230, 255, 0.88), rgba(248, 243, 233, 0.94) 38%, #f7fafc 72%)

.settings-shell
  display flex
  flex 1 1 auto
  flex-direction column
  gap 12px
  min-height 0
  overflow hidden
  padding 14px

.settings-dense-toolbar
  display grid
  grid-template-columns minmax(0, 1.45fr) auto
  gap 14px
  padding 14px 16px
  border 1px solid #d9e4ee
  border-radius 12px
  background rgba(255, 255, 255, 0.92)
  color #19324b

.settings-dense-toolbar__title
  min-width 0

.settings-ledger__readonly-value
  display inline-flex
  align-items center
  min-height 24px
  color #35516d
  font-variant-numeric tabular-nums

.settings-toolbar-kicker
  margin 0
  text-transform uppercase
  letter-spacing 0.14em
  font-size 11px
  color #6f88a1

.settings-dense-toolbar h1
  margin 6px 0 0
  font-size 24px

.settings-toolbar-copy
  margin 6px 0 0
  color #5b738c
  line-height 1.5

.settings-toolbar-meta
  display flex
  flex-wrap wrap
  gap 8px
  margin-top 10px

.settings-toolbar-chip
  display inline-flex
  gap 6px
  align-items center
  padding 5px 9px
  border-radius 999px
  background #edf4fb
  color #35506c
  font-size 12px

.settings-toolbar-chip strong
  max-width 300px
  overflow hidden
  text-overflow ellipsis
  white-space nowrap

.settings-toolbar-chip--path
  max-width 100%
  background #f7fbff

.settings-toolbar-chip--muted
  background #f1f5f8

.settings-toolbar-chip--soft
  background #eef6f0
  color #2e6543

.settings-dense-toolbar__actions
  display flex
  align-items flex-start
  justify-content flex-end
  flex-wrap wrap
  gap 8px

.page-error
  margin-top -2px

.settings-dense-columns
  display grid
  grid-template-columns repeat(3, minmax(0, 1fr))
  gap 12px
  flex 1 1 auto
  min-height 0
  overflow hidden

.settings-dense-column
  display flex
  flex-direction column
  min-height 0
  overflow hidden
  padding 10px 12px 12px
  border 1px solid #d9e4ee
  border-radius 12px
  background rgba(255, 255, 255, 0.9)

.settings-dense-column__body
  display flex
  flex 1 1 auto
  flex-direction column
  min-height 0
  overflow auto
  scrollbar-gutter stable

.settings-dense-column__head
  display flex
  justify-content space-between
  gap 10px
  align-items center
  padding 4px 0 10px
  background rgba(255, 255, 255, 0.96)
  border-bottom 1px solid #e4ecf3
  color #21405e

.settings-dense-column__head span
  color #68829b
  font-size 12px

.settings-dense-section
  display flex
  flex-direction column
  padding-top 12px
  margin-top 12px
  border-top 1px solid #e7eef5

.settings-dense-section:first-of-type
  padding-top 12px
  margin-top 0
  border-top 0

.settings-dense-section__header
  display flex
  flex-direction column

.settings-dense-section__summary
  display flex
  justify-content space-between
  gap 10px
  align-items flex-start
  padding 8px 10px 10px
  border 1px solid #e4ecf3
  border-bottom 0
  border-radius 10px 10px 0 0
  background rgba(255, 255, 255, 0.98)

.settings-dense-section__summary h2
  margin 0
  color #1f3a56
  font-size 15px

.settings-dense-section__summary p
  margin 4px 0 0
  color #69839b
  font-size 12px
  line-height 1.45

.settings-inline-badge,
.settings-inline-chip
  display inline-flex
  align-items center
  justify-content center
  padding 4px 8px
  border-radius 999px
  font-size 11px
  line-height 1
  white-space nowrap

.settings-inline-badge.is-restart,
.settings-inline-chip.is-restart
  background #f9ead0
  color #8c5b00

.settings-inline-badge.is-live,
.settings-inline-chip.is-live
  background #e7f3e9
  color #2b5f3b

.settings-inline-badge.is-readonly,
.settings-inline-chip.is-readonly
  background #eef2f7
  color #4e667e

.settings-inline-chip.is-source
  background #eef4fb
  color #35506c

.settings-inline-chip.is-dirty
  background #fff2d6
  color #a25c00

.settings-inline-chip.is-inactive
  background #f1f3f6
  color #7c8ea1

.settings-inline-chip.is-current
  background #eef6f0
  color #2b5f3b

.settings-ledger
  display flex
  flex-direction column
  min-width 0
  border 1px solid #e4ecf3
  border-top 0
  border-radius 0 0 10px 10px
  background #fff
  overflow hidden

.settings-ledger__header,
.settings-ledger__row
  display grid
  align-items center
  gap 8px
  padding 7px 10px
  font-size 12px

.settings-ledger__header
  background #f6f9fc
  color #68839d
  border 1px solid #e4ecf3
  border-top 0
  border-bottom 0

.settings-ledger__row
  border-top 1px solid #eef3f8

.settings-ledger__row:first-of-type
  border-top 0

.settings-ledger__row--editable
  position relative

.settings-ledger__row--editable::before
  content ''
  position absolute
  left 0
  top 0
  bottom 0
  width 2px
  background transparent

.settings-ledger__row--editable.is-dirty
  background #fffaf1

.settings-ledger__row--editable.is-dirty::before
  background #c97800

.settings-ledger__row--editable.is-inactive
  opacity 0.7

.settings-config-ledger__grid
  grid-template-columns minmax(0, 1.45fr) minmax(160px, 1.15fr) 54px 64px 54px

.settings-strategy-ledger__grid
  grid-template-columns 78px minmax(88px, 0.95fr) minmax(0, 1.35fr) minmax(110px, 1fr)

.settings-ledger__cell
  min-width 0
  color #21405e

.settings-ledger__cell--primary strong,
.settings-ledger__cell--strong
  display block
  color #1f3c58
  font-weight 600

.settings-ledger__cell--primary span
  display block
  margin-top 2px
  color #69839b
  font-size 11px
  overflow hidden
  text-overflow ellipsis
  white-space nowrap

.settings-ledger__cell-hint
  display block
  margin-top 4px
  color #516d87
  font-size 11px
  line-height 1.45

.settings-ledger__cell--truncate
  overflow hidden
  text-overflow ellipsis
  white-space nowrap

.settings-ledger__cell--mono
  font-family Consolas, 'Courier New', monospace
  font-size 11px

.settings-ledger__cell--editor
  min-width 0

.settings-ledger__cell--badge
  display flex
  justify-content flex-end

.settings-ledger__cell--editor :deep(.el-input-number),
.settings-ledger__cell--editor :deep(.el-select),
.settings-ledger__cell--editor :deep(.el-input)
  width 100%

.settings-ledger-empty
  display grid
  place-items center
  min-height 80px
  color #6b849b
  background #fbfdff

@media (max-width: 1599px)
  .settings-dense-toolbar
    grid-template-columns 1fr

  .settings-dense-columns
    grid-template-columns repeat(3, minmax(0, 1fr))

  .settings-config-ledger__grid
    grid-template-columns minmax(0, 1.35fr) minmax(140px, 1.05fr) 50px 58px 50px

@media (max-width: 1279px)
  .settings-dense-columns
    grid-template-columns repeat(2, minmax(0, 1fr))

@media (max-width: 899px)
  .settings-shell
    padding 12px

  .settings-dense-columns
    grid-template-columns 1fr

  .settings-dense-toolbar__actions
    justify-content flex-start

  .settings-ledger__header
    display none

  .settings-config-ledger__grid,
  .settings-strategy-ledger__grid,
  .settings-ledger__row
    grid-template-columns 1fr

  .settings-ledger__cell--badge
    justify-content flex-start

</style>
