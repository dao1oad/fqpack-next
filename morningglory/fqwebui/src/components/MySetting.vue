<template>
    <el-dialog title="系统配置" v-model="dialogFormVisible" class="setting-dialog">
      <div class="setting-main">
          <el-row v-loading="isLoading">
        <el-col :span="24">
          <el-divider content-position="center">系统参数设置</el-divider>
          <el-tabs v-model="activeTab" type="card">
            <!-- 通知设置 -->
            <el-tab-pane label="通知设置" name="notification">
              <el-form :model="notificationForm" label-width="120px">
                <el-divider content-position="left">钉钉机器人</el-divider>
                <el-form-item label="私人机器人">
                  <el-input v-model="notificationForm.webhook.dingtalk.private"></el-input>
                </el-form-item>
                <el-form-item label="公共机器人">
                  <el-input v-model="notificationForm.webhook.dingtalk.public"></el-input>
                </el-form-item>

                <el-divider content-position="left">邮件设置</el-divider>
                <el-form-item label="SMTP服务器">
                  <el-input v-model="notificationForm.publisher.email.smtp"></el-input>
                </el-form-item>
                <el-form-item label="端口">
                  <el-input v-model="notificationForm.publisher.email.port"></el-input>
                </el-form-item>
                <el-form-item label="用户名">
                  <el-input v-model="notificationForm.publisher.email.username"></el-input>
                </el-form-item>
                <el-form-item label="密码">
                  <el-input v-model="notificationForm.publisher.email.password" type="password" show-password></el-input>
                </el-form-item>

                <el-divider content-position="left">邮件接收人</el-divider>
                <div v-for="(email, index) in notificationForm.channels.emails" :key="index" class="email-item">
                  <el-form-item :label="'邮箱地址 ' + (index + 1)">
                    <el-input v-model="email.address"></el-input>
                  </el-form-item>
                  <el-form-item :label="'类型 ' + (index + 1)">
                    <el-input v-model="email.kind"></el-input>
                  </el-form-item>
                  <el-button type="danger" @click="removeEmail(index)" size="small">删除</el-button>
                </div>
                <el-button type="primary" @click="addEmail" size="small">添加邮箱</el-button>

                <el-form-item class="mt-20 right-actions">
                  <el-button type="primary" @click="updateSetting('notification', notificationForm)">保存</el-button>
                </el-form-item>
              </el-form>
            </el-tab-pane>

            <!-- 监控设置 -->
            <el-tab-pane label="监控设置" name="monitor">
              <el-form :model="monitorForm" label-width="120px">
                <el-form-item label="股票周期">
                  <el-select v-model="monitorForm.stock.periods" multiple placeholder="请选择">
                    <el-option label="1分钟" value="1m"></el-option>
                    <el-option label="3分钟" value="3m"></el-option>
                    <el-option label="5分钟" value="5m"></el-option>
                    <el-option label="15分钟" value="15m"></el-option>
                    <el-option label="30分钟" value="30m"></el-option>
                    <el-option label="60分钟" value="60m"></el-option>
                    <el-option label="日线" value="1d"></el-option>
                  </el-select>
                </el-form-item>
                <el-form-item class="right-actions">
                  <el-button type="primary" @click="updateSetting('monitor', monitorForm)">保存</el-button>
                </el-form-item>
              </el-form>
            </el-tab-pane>

            <!-- 迅投设置 -->
            <el-tab-pane label="迅投设置" name="xtquant">
              <el-form :model="xtquantForm" label-width="120px">
                <el-form-item label="路径">
                  <el-input v-model="xtquantForm.path"></el-input>
                </el-form-item>
                <el-form-item label="账户">
                  <el-input v-model="xtquantForm.account"></el-input>
                </el-form-item>
                <el-form-item class="right-actions">
                  <el-button type="primary" @click="updateSetting('xtquant', xtquantForm)">保存</el-button>
                </el-form-item>
              </el-form>
            </el-tab-pane>

            <!-- 通达信设置 -->
            <el-tab-pane label="通达信设置" name="tdx">
              <el-form :model="tdxForm" label-width="120px">
                <el-form-item label="行情接口">
                  <el-input v-model="tdxForm.hq.endpoint"></el-input>
                </el-form-item>
                <el-form-item label="主目录">
                  <el-input v-model="tdxForm.home"></el-input>
                </el-form-item>
                <el-form-item class="right-actions">
                  <el-button type="primary" @click="updateSetting('tdx', tdxForm)">保存</el-button>
                </el-form-item>
              </el-form>
            </el-tab-pane>

             <!-- 股票守护设置 -->
            <el-tab-pane label="股票守护设置" name="guardian">
              <el-form :model="guardianForm" label-width="120px">
                <el-form-item label="仓位百分比">
                  <el-input-number v-model="guardianForm.stock.position_pct" :min="0" :max="100"></el-input-number>
                </el-form-item>
                <el-form-item label="自动开仓">
                  <el-switch v-model="guardianForm.stock.auto_open" active-text="是" inactive-text="否"></el-switch>
                </el-form-item>
                <el-form-item label="单次买入金额">
                  <el-input-number v-model="guardianForm.stock.lot_amount" :min="0" :step="100"></el-input-number>
                </el-form-item>
                <el-form-item label="最小买入金额">
                  <el-input-number v-model="guardianForm.stock.min_amount" :min="0" :step="100"></el-input-number>
                </el-form-item>

                <el-divider class="mt-32" content-position="left">买卖阈值</el-divider>
                <el-alert
                  class="mt-20 grid-threshold-tip"
                  type="info"
                  show-icon
                  :closable="false"
                  title="上涨卖出和下跌补仓的阈值。">
                </el-alert>
                <el-form-item label="阈值模式" class="mt-20">
                  <el-radio-group v-model="guardianForm.stock.threshold.mode">
                    <el-radio label="percent">百分比</el-radio>
                    <el-radio label="atr">ATR</el-radio>
                  </el-radio-group>
                </el-form-item>

                <template v-if="guardianForm.stock.threshold.mode === 'percent'">
                  <el-form-item label="百分比(%)">
                    <el-input-number
                      v-model="guardianForm.stock.threshold.percent"
                      :min="0.1"
                      :step="0.1"
                      :precision="2">
                    </el-input-number>
                  </el-form-item>
                </template>
                <template v-else>
                  <el-form-item label="ATR周期">
                    <el-input-number
                      v-model="guardianForm.stock.threshold.atr.period"
                      :min="1"
                      :step="1">
                    </el-input-number>
                  </el-form-item>
                  <el-form-item label="ATR倍数">
                    <el-input-number
                      v-model="guardianForm.stock.threshold.atr.multiplier"
                      :min="0.1"
                      :step="0.1"
                      :precision="2">
                    </el-input-number>
                  </el-form-item>
                </template>

                <el-divider class="mt-20" content-position="left">网格间距</el-divider>
                <el-alert
                  class="mt-20 grid-interval-tip"
                  type="info"
                  show-icon
                  :closable="false"
                  title="当一次买入超过单次买入金额的时候，自动划分卖出网格的间距。">
                </el-alert>
                <el-form-item label="间距模式" class="mt-20">
                  <el-radio-group v-model="guardianForm.stock.grid_interval.mode">
                    <el-radio label="percent">百分比</el-radio>
                    <el-radio label="atr">ATR</el-radio>
                  </el-radio-group>
                </el-form-item>

                <template v-if="guardianForm.stock.grid_interval.mode === 'percent'">
                  <el-form-item label="百分比(%)">
                    <el-input-number
                      v-model="guardianForm.stock.grid_interval.percent"
                      :min="0.1"
                      :step="0.1"
                      :precision="2">
                    </el-input-number>
                  </el-form-item>
                </template>
                <template v-else>
                  <el-form-item label="ATR周期">
                    <el-input-number
                      v-model="guardianForm.stock.grid_interval.atr.period"
                      :min="1"
                      :step="1">
                    </el-input-number>
                  </el-form-item>
                  <el-form-item label="ATR倍数">
                    <el-input-number
                      v-model="guardianForm.stock.grid_interval.atr.multiplier"
                      :min="0.1"
                      :step="0.1"
                      :precision="2">
                    </el-input-number>
                  </el-form-item>
                </template>

                

                <el-form-item class="right-actions">
                  <el-button type="primary" @click="updateSetting('guardian', guardianForm)">保存</el-button>
                </el-form-item>
              </el-form>
            </el-tab-pane>
          </el-tabs>
        </el-col>
      </el-row>
        </div>
    </el-dialog>
</template>

<script>
import { stockApi } from '@/api/stockApi'
import _ from 'lodash'

export default {
  name: 'MySetting',
  components: {

  },
  data () {
    return {
      activeTab: 'notification',
      dialogFormVisible: false,
      isLoading: false,
      // 通知设置
      notificationForm: {
        webhook: {
          dingtalk: {
            private: '',
            public: ''
          }
        },
        publisher: {
          email: {
            smtp: '',
            port: '',
            username: '',
            password: ''
          }
        },
        channels: {
          emails: []
        }
      },
      // 监控设置
      monitorForm: {
        stock: {
          periods: []
        }
      },
      // 迅投设置
      xtquantForm: {
        path: '',
        account: ''
      },
      // 通达信设置
      tdxForm: {
        hq: {
          endpoint: ''
        },
        home: ''
      },
      // 股票守护设置 (合并了gardian和guardian)
      guardianForm: {
        stock: {
          position_pct: 30,
          auto_open: true,
          lot_amount: 3000,
          min_amount: 1000,
          threshold: {
            mode: 'percent', // percent或者atr
            percent: 1, // 1表示1%
            atr: {
              period: 14,
              multiplier: 1
            }
          },
          grid_interval: {
            mode: 'percent', // percent或者atr
            percent: 3, // 3表示3%
            atr: {
              period: 14,
              multiplier: 1
            }
          }
        }
      }
    }
  },
  methods: {
    init () {
      this.dialogFormVisible = true
      this.$nextTick(() => {
        this.getSettings()
      })
    },
    // 获取所有设置
    getSettings () {
      this.isLoading = true
      stockApi.getSettings()
        .then(res => {
          if (res && res.length > 0) {
            // 处理返回的设置数据
            res.forEach(item => {
              switch (item.code) {
                case 'notification':
                  this.notificationForm = _.merge({}, this.notificationForm, item.value)
                  break
                case 'monitor':
                  this.monitorForm = _.merge({}, this.monitorForm, item.value)
                  break
                case 'xtquant':
                  this.xtquantForm = _.merge({}, this.xtquantForm, item.value)
                  break
                case 'tdx':
                  this.tdxForm = _.merge({}, this.tdxForm, item.value)
                  break
                case 'guardian':
                  this.guardianForm = _.merge({}, this.guardianForm, item.value)
                  break
              }
            })
          }
        })
        .catch(error => {
          console.error('获取设置失败:', error)
          this.$message.error('获取设置失败')
        })
        .finally(() => {
          this.isLoading = false
        })
    },

    // 更新设置
    updateSetting (code, value) {
      this.isLoading = true
      console.log(code, JSON.stringify(value))
      stockApi.updateSetting(code, value)
        .then(res => {
          if (res && res.code === '0') {
            this.$message.success('保存成功')
          } else {
            this.$message.error('保存失败')
          }
        })
        .catch(error => {
          console.error('保存设置失败:', error)
          this.$message.error('保存设置失败')
        })
        .finally(() => {
          this.isLoading = false
        })
    },

    // 添加邮箱
    addEmail () {
      this.notificationForm.channels.emails.push({
        address: '',
        kind: ''
      })
    },

    // 删除邮箱
    removeEmail (index) {
      this.notificationForm.channels.emails.splice(index, 1)
    }
  }
}
</script>

<style lang="stylus" scoped>
.setting-main {
  padding: 20px;

  .el-tabs {
    margin-top: 20px;
  }

  .email-item {
    border: 1px dashed #ccc;
    padding: 10px;
    margin-bottom: 10px;
    border-radius: 4px;
    position: relative;
  }

  .mt-20 {
    margin-top: 20px;
  }

  .mt-32 {
    margin-top: 32px;
  }
}
:deep(.setting-dialog .el-dialog__header)
  background #f0f4ff
  color #1f2d3d

:deep(.setting-dialog .el-dialog__body)
  background #fafcff
  color #1f2d3d

:deep(.el-tabs--card > .el-tabs__header)
  background #eef3ff
  border-color #dbe4ff

:deep(.el-tabs__item)
  color #475569
:deep(.el-tabs__item.is-active)
  color #1f2d3d
  background #ffffff

:deep(.el-divider__text)
  color #334155

:deep(.el-form-item__label)
  color #334155

.email-item
  background #f6f8fc
  border 1px dashed #dce3f0

.right-actions
  :deep(.el-form-item__content)
    justify-content flex-end
.grid-interval-tip
  background #f5faff
  :deep(.el-alert__title)
    font-size 12px
.grid-threshold-tip
  background #f5faff
  :deep(.el-alert__title)
    font-size 12px
</style>
