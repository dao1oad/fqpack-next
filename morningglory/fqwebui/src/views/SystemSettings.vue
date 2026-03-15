<template>
  <div class="system-settings-page">
    <MyHeader />
    <div class="settings-shell" v-loading="loading">
      <section class="settings-hero">
        <div>
          <p class="hero-kicker">System Config</p>
          <h1>系统设置</h1>
          <p class="hero-copy">
            新系统正式配置只保留两处真值：Bootstrap 文件负责启动配置，Mongo 负责运行参数。这里统一查看、编辑并保存。
          </p>
        </div>
        <div class="hero-actions">
          <article class="hero-stamp">
            <span>Bootstrap 文件</span>
            <strong>{{ bootstrapFilePath }}</strong>
            <em>保存启动配置后需要按提示重启相关服务</em>
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

      <section class="settings-section">
        <div class="section-head">
          <div>
            <h2>启动配置</h2>
            <p>这部分写入 `freshquant_bootstrap.yaml`，是系统启动前就必须知道的连接与路径配置。</p>
          </div>
          <span class="section-pill">Source: Bootstrap File</span>
        </div>
        <div class="settings-grid">
          <article class="panel-card panel-card--editor">
            <div class="panel-head">
              <div>
                <h3>编辑 Bootstrap 配置</h3>
                <p>保存后会直接覆盖 Bootstrap 文件，建议按模块重启相关服务。</p>
              </div>
              <span class="panel-badge">需重启</span>
            </div>

            <div class="form-grid">
              <section class="form-section">
                <h4>MongoDB</h4>
                <el-form label-position="top">
                  <el-form-item label="主机">
                    <el-input v-model="bootstrapForm.mongodb.host" />
                  </el-form-item>
                  <el-form-item label="端口">
                    <el-input-number v-model="bootstrapForm.mongodb.port" :min="1" controls-position="right" />
                  </el-form-item>
                  <el-form-item label="主库">
                    <el-input v-model="bootstrapForm.mongodb.db" />
                  </el-form-item>
                  <el-form-item label="Gantt 库">
                    <el-input v-model="bootstrapForm.mongodb.gantt_db" />
                  </el-form-item>
                </el-form>
              </section>

              <section class="form-section">
                <h4>Redis</h4>
                <el-form label-position="top">
                  <el-form-item label="主机">
                    <el-input v-model="bootstrapForm.redis.host" />
                  </el-form-item>
                  <el-form-item label="端口">
                    <el-input-number v-model="bootstrapForm.redis.port" :min="1" controls-position="right" />
                  </el-form-item>
                  <el-form-item label="DB">
                    <el-input-number v-model="bootstrapForm.redis.db" :min="0" controls-position="right" />
                  </el-form-item>
                  <el-form-item label="密码">
                    <el-input v-model="bootstrapForm.redis.password" show-password type="password" />
                  </el-form-item>
                </el-form>
              </section>

              <section class="form-section">
                <h4>Order / Position Management</h4>
                <el-form label-position="top">
                  <el-form-item label="Order Management Mongo 库">
                    <el-input v-model="bootstrapForm.order_management.mongo_database" />
                  </el-form-item>
                  <el-form-item label="Order Projection 库">
                    <el-input v-model="bootstrapForm.order_management.projection_database" />
                  </el-form-item>
                  <el-form-item label="Position Management Mongo 库">
                    <el-input v-model="bootstrapForm.position_management.mongo_database" />
                  </el-form-item>
                </el-form>
              </section>

              <section class="form-section">
                <h4>Memory</h4>
                <el-form label-position="top">
                  <el-form-item label="Memory Mongo 主机">
                    <el-input v-model="bootstrapForm.memory.mongodb.host" />
                  </el-form-item>
                  <el-form-item label="Memory Mongo 端口">
                    <el-input-number v-model="bootstrapForm.memory.mongodb.port" :min="1" controls-position="right" />
                  </el-form-item>
                  <el-form-item label="Memory Mongo 库">
                    <el-input v-model="bootstrapForm.memory.mongodb.db" />
                  </el-form-item>
                  <el-form-item label="冷目录">
                    <el-input v-model="bootstrapForm.memory.cold_root" />
                  </el-form-item>
                  <el-form-item label="Artifact 根目录">
                    <el-input v-model="bootstrapForm.memory.artifact_root" />
                  </el-form-item>
                </el-form>
              </section>

              <section class="form-section">
                <h4>TDX / API / XTData / Runtime</h4>
                <el-form label-position="top">
                  <el-form-item label="TDX 主目录">
                    <el-input v-model="bootstrapForm.tdx.home" />
                  </el-form-item>
                  <el-form-item label="TDX 行情接口">
                    <el-input v-model="bootstrapForm.tdx.hq.endpoint" />
                  </el-form-item>
                  <el-form-item label="API Base URL">
                    <el-input v-model="bootstrapForm.api.base_url" />
                  </el-form-item>
                  <el-form-item label="XTData 端口">
                    <el-input-number v-model="bootstrapForm.xtdata.port" :min="1" controls-position="right" />
                  </el-form-item>
                  <el-form-item label="Runtime 日志目录">
                    <el-input v-model="bootstrapForm.runtime.log_dir" />
                  </el-form-item>
                </el-form>
              </section>
            </div>

            <div class="editor-footer">
              <p>这部分变更不会自动热更新到所有进程；保存成功后，请按页面提示重启相关服务。</p>
              <el-button type="primary" :loading="savingBootstrap" @click="saveBootstrap">
                保存启动配置
              </el-button>
            </div>
          </article>

          <div class="summary-column">
            <article
              v-for="section in bootstrapSections"
              :key="section.key"
              class="panel-card"
            >
              <div class="panel-head">
                <div>
                  <h3>{{ section.title }}</h3>
                  <p>{{ section.description }}</p>
                </div>
                <span class="panel-badge">{{ section.restart_label }}</span>
              </div>
              <div class="summary-list">
                <div v-for="item in section.items" :key="item.key" class="summary-item">
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value_label }}</strong>
                </div>
              </div>
            </article>
          </div>
        </div>
      </section>

      <section class="settings-section">
        <div class="section-head">
          <div>
            <h2>系统设置</h2>
            <p>这部分写入 Mongo 真值，主要服务 XTData、Guardian、仓位管理和通知链路。</p>
          </div>
          <span class="section-pill section-pill--soft">Source: Mongo</span>
        </div>
        <div class="settings-grid">
          <article class="panel-card panel-card--editor">
            <div class="panel-head">
              <div>
                <h3>编辑 Mongo 系统设置</h3>
                <p>保存后系统会按下次轮询或刷新使用新值，适合参数调试和运行期观察。</p>
              </div>
              <span class="panel-badge panel-badge--soft">即时生效</span>
            </div>

            <div class="form-grid">
              <section class="form-section">
                <h4>通知</h4>
                <el-form label-position="top">
                  <el-form-item label="私人钉钉机器人">
                    <el-input v-model="settingsForm.notification.webhook.dingtalk.private" />
                  </el-form-item>
                  <el-form-item label="公共钉钉机器人">
                    <el-input v-model="settingsForm.notification.webhook.dingtalk.public" />
                  </el-form-item>
                </el-form>
              </section>

              <section class="form-section">
                <h4>监控</h4>
                <el-form label-position="top">
                  <el-form-item label="股票周期">
                    <el-select v-model="settingsForm.monitor.stock.periods" multiple placeholder="请选择周期">
                      <el-option v-for="period in monitorPeriods" :key="period" :label="period" :value="period" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="XTData 模式">
                    <el-select v-model="settingsForm.monitor.xtdata.mode">
                      <el-option label="guardian_1m" value="guardian_1m" />
                      <el-option label="clx_15_30" value="clx_15_30" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="最大订阅数">
                    <el-input-number v-model="settingsForm.monitor.xtdata.max_symbols" :min="1" controls-position="right" />
                  </el-form-item>
                  <el-form-item label="队列背压阈值">
                    <el-input-number v-model="settingsForm.monitor.xtdata.queue_backlog_threshold" :min="1" controls-position="right" />
                  </el-form-item>
                  <el-form-item label="预热 bars">
                    <el-input-number v-model="settingsForm.monitor.xtdata.prewarm.max_bars" :min="1" controls-position="right" />
                  </el-form-item>
                </el-form>
              </section>

              <section class="form-section">
                <h4>XTQuant</h4>
                <el-form label-position="top">
                  <el-form-item label="MiniQMT 路径">
                    <el-input v-model="settingsForm.xtquant.path" />
                  </el-form-item>
                  <el-form-item label="账户">
                    <el-input v-model="settingsForm.xtquant.account" />
                  </el-form-item>
                  <el-form-item label="账户类型">
                    <el-select v-model="settingsForm.xtquant.account_type">
                      <el-option label="STOCK" value="STOCK" />
                      <el-option label="CREDIT" value="CREDIT" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="Broker Submit Mode">
                    <el-select v-model="settingsForm.xtquant.broker_submit_mode">
                      <el-option label="normal" value="normal" />
                      <el-option label="observe_only" value="observe_only" />
                    </el-select>
                  </el-form-item>
                </el-form>
              </section>

              <section class="form-section">
                <h4>Guardian</h4>
                <el-form label-position="top">
                  <el-form-item label="仓位百分比">
                    <el-input-number v-model="settingsForm.guardian.stock.position_pct" :min="0" :max="100" controls-position="right" />
                  </el-form-item>
                  <el-form-item label="自动开仓">
                    <el-switch v-model="settingsForm.guardian.stock.auto_open" active-text="是" inactive-text="否" />
                  </el-form-item>
                  <el-form-item label="单次买入金额">
                    <el-input-number v-model="settingsForm.guardian.stock.lot_amount" :min="0" :step="100" controls-position="right" />
                  </el-form-item>
                  <el-form-item label="最小买入金额">
                    <el-input-number v-model="settingsForm.guardian.stock.min_amount" :min="0" :step="100" controls-position="right" />
                  </el-form-item>
                  <el-form-item label="阈值模式">
                    <el-radio-group v-model="settingsForm.guardian.stock.threshold.mode">
                      <el-radio label="percent">百分比</el-radio>
                      <el-radio label="atr">ATR</el-radio>
                    </el-radio-group>
                  </el-form-item>
                  <template v-if="settingsForm.guardian.stock.threshold.mode === 'percent'">
                    <el-form-item label="阈值百分比">
                      <el-input-number v-model="settingsForm.guardian.stock.threshold.percent" :min="0.1" :step="0.1" :precision="2" controls-position="right" />
                    </el-form-item>
                  </template>
                  <template v-else>
                    <el-form-item label="阈值 ATR 周期">
                      <el-input-number v-model="settingsForm.guardian.stock.threshold.atr.period" :min="1" controls-position="right" />
                    </el-form-item>
                    <el-form-item label="阈值 ATR 倍数">
                      <el-input-number v-model="settingsForm.guardian.stock.threshold.atr.multiplier" :min="0.1" :step="0.1" :precision="2" controls-position="right" />
                    </el-form-item>
                  </template>
                  <el-form-item label="网格模式">
                    <el-radio-group v-model="settingsForm.guardian.stock.grid_interval.mode">
                      <el-radio label="percent">百分比</el-radio>
                      <el-radio label="atr">ATR</el-radio>
                    </el-radio-group>
                  </el-form-item>
                  <template v-if="settingsForm.guardian.stock.grid_interval.mode === 'percent'">
                    <el-form-item label="网格百分比">
                      <el-input-number v-model="settingsForm.guardian.stock.grid_interval.percent" :min="0.1" :step="0.1" :precision="2" controls-position="right" />
                    </el-form-item>
                  </template>
                  <template v-else>
                    <el-form-item label="网格 ATR 周期">
                      <el-input-number v-model="settingsForm.guardian.stock.grid_interval.atr.period" :min="1" controls-position="right" />
                    </el-form-item>
                    <el-form-item label="网格 ATR 倍数">
                      <el-input-number v-model="settingsForm.guardian.stock.grid_interval.atr.multiplier" :min="0.1" :step="0.1" :precision="2" controls-position="right" />
                    </el-form-item>
                  </template>
                </el-form>
              </section>

              <section class="form-section">
                <h4>仓位管理</h4>
                <el-form label-position="top">
                  <el-form-item label="允许开新仓最低保证金">
                    <el-input-number v-model="settingsForm.position_management.allow_open_min_bail" :min="0" :step="10000" controls-position="right" />
                  </el-form-item>
                  <el-form-item label="仅允许持仓内买入最低保证金">
                    <el-input-number v-model="settingsForm.position_management.holding_only_min_bail" :min="0" :step="10000" controls-position="right" />
                  </el-form-item>
                </el-form>
              </section>
            </div>

            <div class="editor-footer">
              <p>Mongo 配置保存后会立刻成为系统真值，适合实盘时段内多次微调并观察行为变化。</p>
              <el-button type="primary" :loading="savingSettings" @click="saveSettings">
                保存系统设置
              </el-button>
            </div>
          </article>

          <div class="summary-column">
            <article
              v-for="section in settingsSections"
              :key="section.key"
              class="panel-card"
            >
              <div class="panel-head">
                <div>
                  <h3>{{ section.title }}</h3>
                  <p>{{ section.description }}</p>
                </div>
                <span class="panel-badge panel-badge--soft">{{ section.restart_label }}</span>
              </div>
              <div class="summary-list">
                <div v-for="item in section.items" :key="item.key" class="summary-item">
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value_label }}</strong>
                </div>
              </div>
            </article>

            <article class="panel-card">
              <div class="panel-head">
                <div>
                  <h3>策略字典</h3>
                  <p>当前新系统依赖的策略字典真值，按 `strategies` 只读展示。</p>
                </div>
                <span class="panel-badge panel-badge--soft">只读</span>
              </div>
              <div class="strategy-list">
                <div v-for="strategy in strategies" :key="strategy.code" class="strategy-item">
                  <strong>{{ strategy.code }}</strong>
                  <span>{{ strategy.name || '-' }}</span>
                  <p>{{ strategy.b62_uid || '-' }}</p>
                </div>
                <div v-if="strategies.length === 0" class="panel-empty">
                  暂无策略字典记录。
                </div>
              </div>
            </article>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import MyHeader from '@/views/MyHeader.vue'
import { systemConfigApi } from '@/api/systemConfigApi'
import {
  buildBootstrapSections,
  buildSettingsSections,
  readSystemConfigPayload,
} from './systemSettings.mjs'

const monitorPeriods = ['1min', '3min', '5min', '15min', '30min', '60min', '1d']

const loading = ref(false)
const savingBootstrap = ref(false)
const savingSettings = ref(false)
const pageError = ref('')
const dashboard = ref({})

const bootstrapForm = reactive(defaultBootstrapForm())
const settingsForm = reactive(defaultSettingsForm())

const bootstrapSections = computed(() => buildBootstrapSections(dashboard.value))
const settingsSections = computed(() => buildSettingsSections(dashboard.value))
const bootstrapFilePath = computed(() => dashboard.value?.bootstrap?.file_path || '未发现 bootstrap 文件')
const strategies = computed(() => (
  Array.isArray(dashboard.value?.settings?.strategies)
    ? dashboard.value.settings.strategies
    : []
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
      stock: { periods: [] },
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
    },
    guardian: {
      stock: {
        position_pct: 30,
        auto_open: false,
        lot_amount: 1500,
        min_amount: 1000,
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
  assignReactive(
    bootstrapForm,
    {
      ...defaultBootstrapForm(),
      ...(cloneValue(payload?.bootstrap?.values)),
    },
  )
  assignReactive(
    settingsForm,
    {
      ...defaultSettingsForm(),
      ...(cloneValue(payload?.settings?.values)),
    },
  )
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
    const payload = readSystemConfigPayload(await systemConfigApi.getDashboard(), {})
    dashboard.value = payload
    syncFormsFromDashboard(payload)
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
  min-height 100vh
  background radial-gradient(circle at top left, rgba(206, 230, 255, 0.88), rgba(248, 243, 233, 0.94) 38%, #f7fafc 72%)

.settings-shell
  padding 24px
  display grid
  gap 18px

.settings-hero
  display flex
  justify-content space-between
  gap 16px
  padding 24px
  border 1px solid #d6e3ee
  border-radius 24px
  background linear-gradient(140deg, rgba(14, 46, 73, 0.96), rgba(30, 101, 119, 0.92))
  color #f8fbff
  box-shadow 0 18px 40px rgba(23, 56, 86, 0.16)

.hero-kicker
  margin 0
  text-transform uppercase
  letter-spacing 0.14em
  font-size 12px
  color rgba(226, 239, 251, 0.82)

.settings-hero h1
  margin 10px 0 0
  font-size 34px

.hero-copy
  margin 12px 0 0
  max-width 760px
  color rgba(233, 242, 250, 0.88)
  line-height 1.65

.hero-actions
  min-width 280px
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
  font-size 16px
  line-height 1.45
  word-break break-all

.page-error
  margin-top -4px

.settings-section
  padding 20px
  border 1px solid #d9e4ee
  border-radius 22px
  background rgba(255, 255, 255, 0.84)
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

.section-pill
  display inline-flex
  align-items center
  padding 6px 10px
  border-radius 999px
  background #e9f2f7
  color #2d4f68
  font-size 12px

.section-pill--soft
  background #eef5ef
  color #335e46

.settings-grid
  display grid
  grid-template-columns minmax(0, 1.25fr) minmax(320px, 0.85fr)
  gap 16px

.panel-card
  border 1px solid #d9e5ef
  border-radius 18px
  padding 16px
  background linear-gradient(180deg, #ffffff 0%, #f7fafc 100%)

.panel-card--editor
  background linear-gradient(180deg, #ffffff 0%, #f2f8fc 100%)

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
  background #f9ead0
  color #8c5b00
  font-size 12px
  text-align center

.panel-badge--soft
  background #e7f3e9
  color #2b5f3b

.form-grid
  display grid
  grid-template-columns repeat(2, minmax(0, 1fr))
  gap 14px

.form-section
  padding 14px
  border-radius 16px
  border 1px solid #deebf3
  background rgba(255, 255, 255, 0.92)

.form-section h4
  margin 0 0 12px
  color #20405d

.form-section :deep(.el-input-number)
  width 100%

.editor-footer
  display flex
  justify-content space-between
  gap 12px
  align-items center
  margin-top 14px
  padding-top 14px
  border-top 1px solid #e4ecf3

.editor-footer p
  margin 0
  color #5f7890
  line-height 1.6

.summary-column
  display grid
  gap 14px

.summary-list,
.strategy-list
  display grid
  gap 10px

.summary-item,
.strategy-item
  padding 12px 14px
  border-radius 14px
  background #f7fbff
  border 1px solid #e2ebf3

.summary-item span,
.strategy-item span
  display block
  color #627c94
  font-size 12px

.summary-item strong,
.strategy-item strong
  display block
  margin-top 8px
  color #1f3c58
  font-size 16px
  line-height 1.35
  word-break break-all

.strategy-item p
  margin 8px 0 0
  color #69839b
  font-size 12px
  line-height 1.5
  word-break break-all

.panel-empty
  min-height 80px
  display grid
  place-items center
  border 1px dashed #d4e0ea
  border-radius 18px
  color #6b849b
  background #f7fafc

@media (max-width: 1280px)
  .settings-grid,
  .form-grid
    grid-template-columns 1fr

@media (max-width: 900px)
  .settings-shell
    padding 16px

  .settings-hero,
  .hero-actions,
  .section-head,
  .panel-head,
  .editor-footer
    flex-direction column
    align-items stretch

  .hero-actions
    min-width 0

  .settings-hero h1
    font-size 28px
</style>
