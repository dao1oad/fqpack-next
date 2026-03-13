<template>
  <div class="position-page">
    <MyHeader />
    <div class="position-shell" v-loading="loading">
      <section class="page-hero">
        <div>
          <p class="hero-kicker">Position Gate</p>
          <h1>仓位管理</h1>
          <p class="hero-copy">
            统一查看保证金阈值、当前仓位状态、holding scope 和规则命中，不再靠 Mongo 集合与代码默认值排查。
          </p>
        </div>
        <div class="hero-actions">
          <article class="hero-stamp">
            <span>配置更新时间</span>
            <strong>{{ configUpdatedAt }}</strong>
            <em>{{ configUpdatedBy }}</em>
          </article>
          <el-button @click="loadDashboard">刷新</el-button>
        </div>
      </section>

      <el-alert
        v-if="pageError"
        class="page-error"
        type="error"
        :title="pageError"
        show-icon
        :closable="false"
      />

      <section class="position-section">
        <div class="section-head">
          <div>
            <h2>参数 inventory</h2>
            <p>把当前真正生效的阈值、代码默认值和系统连接参数放到同一页，但保留各自边界。</p>
          </div>
        </div>
        <div class="config-grid">
          <article class="panel-card panel-card--editor">
            <div class="panel-head">
              <div>
                <h3>{{ editableSection.title }}</h3>
                <p>{{ editableSection.description }}</p>
              </div>
              <span class="panel-badge">pm_configs.thresholds</span>
            </div>

            <el-form label-position="top" class="config-form">
              <el-form-item
                v-for="item in editableSection.items"
                :key="item.key"
                :label="item.label"
              >
                <el-input-number
                  v-if="item.key === 'allow_open_min_bail'"
                  v-model="editableForm.allow_open_min_bail"
                  :min="0"
                  :step="10000"
                  controls-position="right"
                />
                <el-input-number
                  v-else-if="item.key === 'holding_only_min_bail'"
                  v-model="editableForm.holding_only_min_bail"
                  :min="0"
                  :step="10000"
                  controls-position="right"
                />
                <p class="field-hint">{{ item.description }}</p>
              </el-form-item>
            </el-form>

            <div class="editor-footer">
              <p>首期仅开放保证金阈值编辑；其余参数保持只读，避免页面配置与运行链脱节。</p>
              <el-button type="primary" :loading="saving" @click="saveThresholds">保存阈值</el-button>
            </div>
          </article>

          <article
            v-for="section in readonlySections"
            :key="section.key"
            class="panel-card"
          >
            <div class="panel-head">
              <div>
                <h3>{{ section.title }}</h3>
                <p>{{ section.description }}</p>
              </div>
            </div>
            <div class="readonly-list">
              <div
                v-for="item in section.items"
                :key="item.key"
                class="readonly-item"
              >
                <span>{{ item.label }}</span>
                <strong>{{ item.value_label }}</strong>
                <p>{{ item.description }}</p>
              </div>
            </div>
          </article>
        </div>
      </section>

      <section class="position-section">
        <div class="section-head">
          <div>
            <h2>当前仓位状态</h2>
            <p>effective state、stale 语义和资产摘要均由服务端按真实 PositionPolicy 汇总。</p>
          </div>
        </div>
        <div class="state-layout">
          <article class="state-hero-card" :class="`is-${statePanel.hero.effective_state_tone}`">
            <div class="state-hero-top">
              <span class="state-pill" :class="`is-${statePanel.hero.effective_state_tone}`">
                {{ statePanel.hero.effective_state_label }}
              </span>
              <span class="stale-pill" :class="{ 'is-stale': statePanel.hero.stale }">
                {{ statePanel.hero.stale_label }}
              </span>
            </div>
            <h3>{{ statePanel.hero.matched_rule_title }}</h3>
            <p>{{ statePanel.hero.matched_rule_detail }}</p>
            <div class="state-submeta">
              <span>raw state {{ statePanel.hero.raw_state_label }}</span>
            </div>
          </article>

          <div class="metric-grid">
            <article
              v-for="item in statePanel.stats"
              :key="item.key"
              class="metric-card"
            >
              <span>{{ item.label }}</span>
              <strong>{{ item.value_label }}</strong>
            </article>
          </div>
        </div>

        <div class="meta-grid">
          <article
            v-for="item in statePanel.meta"
            :key="item.key"
            class="meta-card"
          >
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </article>
        </div>
      </section>

      <section class="position-section">
        <div class="section-head">
          <div>
            <h2>持仓范围与规则矩阵</h2>
            <p>holding scope 使用与门禁一致的 union 口径，规则矩阵直接回答当前哪些行为允许、为什么。</p>
          </div>
        </div>
        <div class="rule-layout">
          <article class="panel-card holding-card">
            <div class="panel-head">
              <div>
                <h3>当前 holding scope</h3>
                <p>{{ holdingScope.description }}</p>
              </div>
              <span class="panel-badge">{{ holdingScope.count_label }}</span>
            </div>
            <div class="holding-source">source {{ holdingScope.source }}</div>
            <div class="code-chip-list">
              <span
                v-for="code in holdingScope.codes"
                :key="code"
                class="code-chip"
              >
                {{ code }}
              </span>
              <span v-if="holdingScope.codes.length === 0" class="code-chip code-chip--empty">
                当前无持仓代码
              </span>
            </div>
          </article>

          <div class="rule-grid">
            <article
              v-for="row in ruleMatrix"
              :key="row.key"
              class="rule-card"
              :class="`is-${row.tone}`"
            >
              <div class="rule-top">
                <span class="rule-status">{{ row.allowed_label }}</span>
                <span class="rule-code">{{ row.reason_code }}</span>
              </div>
              <strong>{{ row.label }}</strong>
              <p>{{ row.reason_text }}</p>
            </article>
          </div>
        </div>
      </section>

      <section class="position-section">
        <div class="section-head">
          <div>
            <h2>最近决策</h2>
            <p>辅助确认最近策略单被允许还是拒绝，以及对应原因码。</p>
          </div>
        </div>
        <div v-if="recentDecisionRows.length" class="decision-list">
          <article
            v-for="row in recentDecisionRows"
            :key="`${row.evaluated_at}-${row.symbol}-${row.reason_code}`"
            class="decision-card"
            :class="`is-${row.tone}`"
          >
            <div class="decision-top">
              <strong>{{ row.strategy_label }}</strong>
              <span class="decision-status">{{ row.allowed_label }}</span>
            </div>
            <p>{{ row.action_label }} {{ row.symbol_label }} · {{ row.state_label }}</p>
            <div class="decision-meta">
              <span>{{ row.reason_code || '-' }}</span>
              <span>{{ row.evaluated_at_label }}</span>
            </div>
            <div class="decision-reason">{{ row.reason_text }}</div>
          </article>
        </div>
        <div v-else class="panel-empty">
          暂无最近决策记录。
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import MyHeader from '@/views/MyHeader.vue'
import { positionManagementApi } from '@/api/positionManagementApi'
import {
  buildConfigSections,
  buildHoldingScopeView,
  buildRecentDecisionRows,
  buildRuleMatrix,
  buildStatePanel,
  readDashboardPayload,
} from './positionManagement.mjs'

const loading = ref(false)
const saving = ref(false)
const pageError = ref('')
const dashboard = ref({})

const editableForm = reactive({
  allow_open_min_bail: 0,
  holding_only_min_bail: 0,
})

const configSections = computed(() => buildConfigSections(dashboard.value))
const editableSection = computed(() => (
  configSections.value.find((section) => section.key === 'editable_thresholds') || {
    title: '已生效且可编辑',
    description: '',
    items: [],
  }
))
const readonlySections = computed(() => (
  configSections.value.filter((section) => section.key !== 'editable_thresholds')
))
const statePanel = computed(() => buildStatePanel(dashboard.value))
const holdingScope = computed(() => buildHoldingScopeView(dashboard.value))
const ruleMatrix = computed(() => buildRuleMatrix(dashboard.value))
const recentDecisionRows = computed(() => buildRecentDecisionRows(dashboard.value))
const configUpdatedAt = computed(() => dashboard.value?.config?.updated_at || '未配置')
const configUpdatedBy = computed(() => dashboard.value?.config?.updated_by || 'unknown')

const syncEditableForm = () => {
  const thresholds = dashboard.value?.config?.thresholds || {}
  editableForm.allow_open_min_bail = Number(thresholds.allow_open_min_bail || 0)
  editableForm.holding_only_min_bail = Number(thresholds.holding_only_min_bail || 0)
}

const resolveErrorMessage = (error, fallback) => {
  const responseMessage = error?.response?.data?.error
  const directMessage = error?.message
  return responseMessage || directMessage || fallback
}

const loadDashboard = async () => {
  loading.value = true
  pageError.value = ''
  try {
    const payload = readDashboardPayload(
      await positionManagementApi.getDashboard(),
      {},
    )
    dashboard.value = payload
    syncEditableForm()
  } catch (error) {
    pageError.value = resolveErrorMessage(error, '加载仓位管理面板失败')
  } finally {
    loading.value = false
  }
}

const saveThresholds = async () => {
  if (editableForm.allow_open_min_bail <= editableForm.holding_only_min_bail) {
    ElMessage.error('允许开新仓最低保证金必须大于仅允许持仓内买入最低保证金')
    return
  }

  saving.value = true
  try {
    await positionManagementApi.updateConfig({
      allow_open_min_bail: editableForm.allow_open_min_bail,
      holding_only_min_bail: editableForm.holding_only_min_bail,
      updated_by: 'web-ui',
    })
    ElMessage.success('仓位管理阈值已保存')
    await loadDashboard()
  } catch (error) {
    ElMessage.error(resolveErrorMessage(error, '保存仓位管理阈值失败'))
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadDashboard()
})
</script>

<style lang="stylus" scoped>
.position-page
  min-height 100vh
  background radial-gradient(circle at top left, rgba(212, 235, 255, 0.9), rgba(250, 246, 240, 0.95) 38%, #f7fafc 68%)

.position-shell
  padding 24px
  display grid
  gap 18px

.page-hero
  display flex
  justify-content space-between
  gap 16px
  padding 24px
  border 1px solid #d6e3ee
  border-radius 24px
  background linear-gradient(135deg, rgba(17, 53, 84, 0.95), rgba(42, 94, 123, 0.92))
  color #f8fbff
  box-shadow 0 18px 40px rgba(23, 56, 86, 0.16)

.hero-kicker
  margin 0
  text-transform uppercase
  letter-spacing 0.14em
  font-size 12px
  color rgba(226, 239, 251, 0.82)

.page-hero h1
  margin 10px 0 0
  font-size 34px

.hero-copy
  margin 12px 0 0
  max-width 720px
  color rgba(233, 242, 250, 0.88)
  line-height 1.6

.hero-actions
  min-width 240px
  display flex
  flex-direction column
  align-items flex-end
  gap 12px

.hero-stamp
  width 100%
  padding 16px
  border-radius 18px
  background rgba(255, 255, 255, 0.08)
  border 1px solid rgba(255, 255, 255, 0.16)

.hero-stamp span,
.hero-stamp em
  display block
  color rgba(228, 239, 249, 0.78)
  font-size 12px

.hero-stamp strong
  display block
  margin 8px 0 4px
  color #ffffff
  font-size 18px

.page-error
  margin-top -4px

.position-section
  padding 20px
  border 1px solid #d9e4ee
  border-radius 22px
  background rgba(255, 255, 255, 0.82)
  backdrop-filter blur(10px)

.section-head
  display flex
  justify-content space-between
  gap 12px
  align-items flex-start
  margin-bottom 16px

.section-head h2
  margin 0
  color #19324b
  font-size 22px

.section-head p
  margin 6px 0 0
  color #5b738c
  line-height 1.6

.config-grid,
.state-layout,
.rule-layout
  display grid
  gap 14px

.config-grid
  grid-template-columns minmax(320px, 1.15fr) repeat(2, minmax(240px, 0.9fr))

.panel-card
  border 1px solid #d9e5ef
  border-radius 18px
  padding 16px
  background linear-gradient(180deg, #ffffff 0%, #f7fafc 100%)

.panel-card--editor
  background linear-gradient(180deg, #ffffff 0%, #f3f8fc 100%)

.panel-head
  display flex
  justify-content space-between
  gap 12px
  align-items flex-start
  margin-bottom 14px

.panel-head h3
  margin 0
  color #1f3a56

.panel-head p
  margin 6px 0 0
  color #668097
  line-height 1.5

.panel-badge
  display inline-flex
  align-items center
  padding 6px 10px
  border-radius 999px
  background #e7f0f7
  color #30506b
  font-size 12px

.config-form :deep(.el-input-number)
  width 100%

.field-hint
  margin 8px 0 0
  color #6d879d
  font-size 12px
  line-height 1.5

.editor-footer
  display flex
  justify-content space-between
  gap 12px
  align-items center
  margin-top 8px
  padding-top 14px
  border-top 1px solid #e4ecf3

.editor-footer p
  margin 0
  color #5f7890
  line-height 1.5

.readonly-list
  display grid
  gap 10px

.readonly-item
  padding 14px
  border-radius 14px
  background #f7fbff
  border 1px solid #e2ebf3

.readonly-item span
  display block
  color #627c94
  font-size 12px

.readonly-item strong
  display block
  margin-top 8px
  color #1f3c58
  font-size 18px

.readonly-item p
  margin 8px 0 0
  color #69839b
  line-height 1.5
  font-size 12px

.state-layout
  grid-template-columns minmax(320px, 1.05fr) minmax(0, 1.2fr)
  align-items stretch

.state-hero-card
  padding 18px
  border-radius 20px
  color #17324a
  background linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(243, 248, 252, 0.96))
  border 1px solid #d9e5ef

.state-hero-card.is-allow
  background linear-gradient(180deg, #f0fbf5 0%, #ffffff 100%)

.state-hero-card.is-hold
  background linear-gradient(180deg, #fff8ea 0%, #ffffff 100%)

.state-hero-card.is-reduce
  background linear-gradient(180deg, #fff2ef 0%, #ffffff 100%)

.state-hero-top
  display flex
  justify-content space-between
  gap 10px
  align-items center

.state-pill,
.stale-pill,
.rule-status,
.decision-status
  display inline-flex
  align-items center
  justify-content center
  padding 6px 12px
  border-radius 999px
  font-size 12px

.state-pill.is-allow
  background #1d9b62
  color #fff

.state-pill.is-hold
  background #dd921e
  color #fff

.state-pill.is-reduce
  background #d15041
  color #fff

.stale-pill
  background #e8f1f7
  color #35536f

.stale-pill.is-stale
  background #f6e8c7
  color #8f6112

.state-hero-card h3
  margin 18px 0 0
  font-size 24px
  line-height 1.35

.state-hero-card p
  margin 10px 0 0
  color #526c84
  line-height 1.65

.state-submeta
  display flex
  flex-wrap wrap
  gap 8px
  margin-top 16px
  color #607b93
  font-size 12px

.metric-grid
  display grid
  grid-template-columns repeat(3, minmax(0, 1fr))
  gap 12px

.metric-card,
.meta-card
  padding 14px
  border-radius 16px
  border 1px solid #dde8f1
  background #ffffff

.metric-card span,
.meta-card span
  display block
  color #69829b
  font-size 12px

.metric-card strong,
.meta-card strong
  display block
  margin-top 8px
  color #1d3b58
  font-size 20px
  line-height 1.2

.meta-grid
  margin-top 14px
  display grid
  grid-template-columns repeat(5, minmax(0, 1fr))
  gap 12px

.meta-card strong
  font-size 14px
  word-break break-all

.rule-layout
  grid-template-columns minmax(280px, 0.9fr) minmax(0, 1.3fr)

.holding-source
  color #6a859e
  font-size 12px

.code-chip-list
  display flex
  flex-wrap wrap
  gap 8px
  margin-top 14px

.code-chip
  padding 8px 12px
  border-radius 999px
  background #edf4fa
  color #25425d
  font-size 12px

.code-chip--empty
  background #f2f6fa
  color #6a849d

.rule-grid
  display grid
  grid-template-columns repeat(3, minmax(0, 1fr))
  gap 12px

.rule-card,
.decision-card
  padding 16px
  border-radius 18px
  border 1px solid #dbe6ef
  background #fff

.rule-card.is-allow,
.decision-card.is-allow
  background linear-gradient(180deg, #f0fbf5 0%, #ffffff 100%)

.rule-card.is-reject,
.decision-card.is-reject
  background linear-gradient(180deg, #fff4ef 0%, #ffffff 100%)

.rule-top,
.decision-top,
.decision-meta
  display flex
  justify-content space-between
  gap 10px
  align-items center

.rule-status,
.decision-status
  background #19324a
  color #fff

.rule-code
  color #67839c
  font-size 12px

.rule-card strong,
.decision-card strong
  display block
  margin-top 14px
  color #1f3c58

.rule-card p,
.decision-card p,
.decision-reason
  margin 10px 0 0
  color #58728a
  line-height 1.6

.decision-list
  display grid
  grid-template-columns repeat(auto-fit, minmax(260px, 1fr))
  gap 12px

.decision-meta
  margin-top 12px
  color #6b859c
  font-size 12px

.panel-empty
  min-height 120px
  display grid
  place-items center
  border 1px dashed #d4e0ea
  border-radius 18px
  color #6b849b
  background #f7fafc

@media (max-width: 1180px)
  .config-grid,
  .state-layout,
  .rule-layout,
  .metric-grid,
  .meta-grid,
  .rule-grid
    grid-template-columns 1fr

@media (max-width: 900px)
  .position-shell
    padding 16px

  .page-hero,
  .panel-head,
  .editor-footer,
  .hero-actions,
  .state-hero-top,
  .rule-top,
  .decision-top,
  .decision-meta
    flex-direction column
    align-items stretch

  .hero-actions
    min-width 0

  .page-hero h1
    font-size 28px
</style>
