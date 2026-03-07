<template>
  <div class="kline-big-main kline-slim-main">
    <div class="kline-slim-toolbar">
      <div class="toolbar-left">
        <el-button size="small" @click="jumpToControl">股票</el-button>
        <el-input
          v-model="symbolInput"
          size="small"
          class="symbol-input"
          placeholder="请输入 symbol，例如 sh510050"
          @keyup.enter="applySymbol"
        />
        <el-button size="small" @click="applySymbol">切换</el-button>
        <el-button-group>
          <el-button
            v-for="period in periodList"
            :key="period"
            size="small"
            :type="currentPeriod === period ? 'primary' : 'default'"
            @click="switchPeriod(period)"
          >
            {{ period }}
          </el-button>
        </el-button-group>
        <el-date-picker
          v-model="endDateModel"
          type="date"
          size="small"
          value-format="YYYY-MM-DD"
          format="YYYY-MM-DD"
          clearable
          placeholder="历史日期"
          @change="applyEndDate"
        />
        <el-button size="small" @click="reloadNow">刷新</el-button>
        <el-button size="small" @click="jumpToBigChart">大图</el-button>
      </div>
      <div class="toolbar-right">
        <span class="status-chip">主图 {{ currentPeriod }}</span>
        <span class="status-chip">叠加 {{ overlayPeriod }}</span>
        <span class="status-chip">主图末 bar {{ lastMainBarLabel }}</span>
        <span class="status-chip" v-if="currentPeriod !== overlayPeriod">
          叠加末 bar {{ lastOverlayBarLabel }}
        </span>
        <span class="status-chip" :class="{ error: lastError }">{{ statusText }}</span>
      </div>
    </div>

    <div class="kline-slim-body">
      <aside class="kline-slim-sidebar">
        <section
          v-for="section in sidebarSections"
          :key="section.key"
          class="sidebar-section"
        >
          <header class="sidebar-section-header">
            <button
              type="button"
              class="sidebar-section-toggle"
              @click="toggleSidebarSection(section.key)"
            >
              <span class="sidebar-section-heading">
                <span>{{ section.label }}</span>
                <span class="sidebar-section-count">{{ section.items.length }}</span>
              </span>
              <span class="sidebar-section-action">{{ section.expanded ? '收起' : '展开' }}</span>
            </button>
          </header>
          <transition name="sidebar-section-collapse">
            <div v-show="section.expanded" class="sidebar-section-body">
              <div v-if="section.loading" class="sidebar-section-empty">加载中...</div>
              <div v-else-if="section.error" class="sidebar-section-empty error-text">
                {{ section.error }}
              </div>
              <div v-else-if="!section.items.length" class="sidebar-section-empty">暂无数据</div>
              <div v-else class="sidebar-item-list">
                <div
                  v-for="item in section.items"
                  :key="`${section.key}:${item.symbol || item.code6}`"
                  class="sidebar-item-row"
                >
                  <el-popover
                    placement="right-start"
                    :width="860"
                    popper-class="kline-slim-reason-popper"
                    trigger="hover"
                    @show="handleReasonPopoverShow(item)"
                  >
                    <template #reference>
                      <button
                        type="button"
                        class="sidebar-item-button"
                        :class="{ active: isSidebarItemActive(item) }"
                        @click="selectSidebarItem(item)"
                      >
                        <span class="sidebar-item-meta">
                          <span class="sidebar-item-title">{{ item.name || item.code6 }}</span>
                          <span class="sidebar-item-subtitle">{{ item.code6 }}</span>
                        </span>
                      </button>
                    </template>
                    <div class="reason-popover">
                      <div class="reason-popover-head">
                        <span>{{ item.name || item.code6 }}</span>
                        <span>{{ item.code6 }}</span>
                      </div>
                      <div v-if="getReasonMessage(item)" class="reason-popover-empty">
                        {{ getReasonMessage(item) }}
                      </div>
                      <div v-else class="reason-table">
                        <div class="reason-table-row reason-table-header">
                          <span>时间</span>
                          <span>来源</span>
                          <span>热门板块</span>
                          <span>板块理由</span>
                          <span>标的理由</span>
                        </div>
                        <div
                          v-for="(reason, index) in getReasonItems(item)"
                          :key="`${item.code6}:${reason.date}:${reason.time || 'na'}:${index}`"
                          class="reason-table-row"
                        >
                          <span>{{ reason.time ? `${reason.date} ${reason.time}` : reason.date }}</span>
                          <span>{{ reason.provider || '--' }}</span>
                          <span>{{ reason.plate_name || '--' }}</span>
                          <span>{{ reason.plate_reason || '--' }}</span>
                          <span>{{ reason.stock_reason || '--' }}</span>
                        </div>
                      </div>
                    </div>
                  </el-popover>
                  <el-popconfirm
                    v-if="section.deletable"
                    :title="section.deleteConfirmText"
                    :confirm-button-text="'确认'"
                    :cancel-button-text="'取消'"
                    @confirm="deleteSidebarItem(section.key, item)"
                  >
                    <template #reference>
                      <button
                        type="button"
                        class="sidebar-item-delete"
                        :disabled="isSidebarDeletePending(section.key, item)"
                        @click.stop
                      >
                        删除
                      </button>
                    </template>
                  </el-popconfirm>
                </div>
              </div>
            </div>
          </transition>
        </section>
      </aside>

      <section class="kline-slim-content">
        <div ref="chartHost" class="kline-slim-chart"></div>
        <div v-if="!routeSymbol" class="kline-slim-empty">
          {{ emptyMessage }}
        </div>
      </section>
    </div>
  </div>
</template>

<script>
import klineSlim from './js/kline-slim'

export default klineSlim
</script>

<style lang="stylus">
@import "../style/kline-big.styl";

.kline-slim-main
  display block

.kline-slim-toolbar
  position absolute
  top 0
  left 0
  right 0
  min-height 52px
  padding 8px 12px
  z-index 10
  display flex
  align-items center
  justify-content space-between
  gap 12px
  border-bottom 1px solid rgba(127, 127, 122, 0.2)
  background rgba(18, 22, 28, 0.96)

.toolbar-left
  display flex
  align-items center
  flex-wrap wrap
  gap 8px

.toolbar-right
  display flex
  align-items center
  flex-wrap wrap
  justify-content flex-end
  gap 8px

.symbol-input
  width 220px

.status-chip
  display inline-flex
  align-items center
  padding 0 10px
  height 28px
  font-size 12px
  border-radius 999px
  border 1px solid rgba(127, 127, 122, 0.2)
  background rgba(31, 41, 55, 0.72)
  color #d1d5db

.status-chip.error
  color #fca5a5
  border-color rgba(248, 113, 113, 0.4)

.kline-slim-body
  position absolute
  top 60px
  left 0
  right 0
  bottom 0
  display flex
  min-height 0

.kline-slim-sidebar
  width 280px
  padding 12px
  border-right 1px solid rgba(127, 127, 122, 0.2)
  background linear-gradient(180deg, rgba(20, 26, 34, 0.98), rgba(14, 18, 24, 0.98))
  overflow-y auto

.sidebar-section
  margin-bottom 14px

.sidebar-section-header
  margin-bottom 8px

.sidebar-section-toggle
  width 100%
  display flex
  align-items center
  justify-content space-between
  gap 12px
  padding 10px 12px
  border 1px solid rgba(127, 127, 122, 0.18)
  border-radius 12px
  background rgba(15, 23, 42, 0.48)
  color #e5e7eb
  cursor pointer
  text-align left
  font-size 12px
  letter-spacing 0.04em
  transition background 0.15s ease, border-color 0.15s ease

.sidebar-section-toggle:hover
  background rgba(30, 41, 59, 0.72)
  border-color rgba(96, 165, 250, 0.35)

.sidebar-section-heading
  display inline-flex
  align-items center
  gap 8px

.sidebar-section-action
  color #93c5fd

.sidebar-section-body
  padding-top 8px

.sidebar-section-count
  color #94a3b8

.sidebar-section-empty
  padding 10px 12px
  border 1px dashed rgba(127, 127, 122, 0.2)
  border-radius 10px
  color #94a3b8
  font-size 12px
  background rgba(15, 23, 42, 0.4)

.sidebar-item-list
  display flex
  flex-direction column
  gap 6px

.sidebar-item-row
  display flex
  align-items stretch
  gap 8px

.sidebar-item-button
  flex 1
  display flex
  align-items center
  justify-content flex-start
  padding 10px 12px
  border 1px solid rgba(127, 127, 122, 0.18)
  border-radius 12px
  background rgba(30, 41, 59, 0.58)
  color #e5e7eb
  text-align left
  cursor pointer
  transition background 0.15s ease, border-color 0.15s ease

.sidebar-item-button:hover
  background rgba(51, 65, 85, 0.76)
  border-color rgba(96, 165, 250, 0.35)

.sidebar-item-button.active
  background rgba(30, 64, 175, 0.28)
  border-color rgba(96, 165, 250, 0.7)

.sidebar-item-meta
  display flex
  flex-direction column
  gap 2px
  min-width 0

.sidebar-item-title
  font-size 13px
  line-height 1.35
  color #f8fafc
  overflow hidden
  text-overflow ellipsis
  white-space nowrap

.sidebar-item-subtitle
  font-size 12px
  line-height 1.3
  color #93c5fd

.sidebar-item-delete
  align-self center
  min-width 52px
  padding 0 10px
  border 1px solid rgba(248, 113, 113, 0.28)
  border-radius 10px
  background rgba(127, 29, 29, 0.12)
  color #fecaca
  font-size 12px
  cursor pointer
  transition background 0.15s ease, border-color 0.15s ease, opacity 0.15s ease

.sidebar-item-delete:hover:enabled
  background rgba(153, 27, 27, 0.24)
  border-color rgba(248, 113, 113, 0.48)

.sidebar-item-delete:disabled
  cursor wait
  opacity 0.56

.sidebar-section-collapse-enter-active,
.sidebar-section-collapse-leave-active
  transition opacity 0.15s ease, transform 0.15s ease

.sidebar-section-collapse-enter-from,
.sidebar-section-collapse-leave-to
  opacity 0
  transform translateY(-4px)

.sidebar-item-title,
.sidebar-item-subtitle
  min-width 0
  overflow hidden
  text-overflow ellipsis
  white-space nowrap

.kline-slim-content
  position relative
  flex 1

.kline-slim-chart
  position absolute
  top 0
  left 0
  right 0
  bottom 0

.kline-slim-empty
  position absolute
  top 0
  left 0
  right 0
  bottom 0
  display flex
  align-items center
  justify-content center
  color #d1d5db
  font-size 14px

.reason-popover
  color #0f172a
  max-width calc(100vw - 72px)

.reason-popover-head
  display flex
  align-items center
  justify-content space-between
  margin-bottom 10px
  font-weight 600

.reason-popover-empty
  padding 12px 0
  color #64748b

.reason-table
  display flex
  flex-direction column
  gap 6px
  width 100%

.reason-table-row
  display grid
  grid-template-columns 110px 72px 120px minmax(140px, 1fr) minmax(0, 2fr)
  gap 8px
  align-items flex-start
  font-size 12px
  line-height 1.4
  word-break break-word

.reason-table-row > span
  display block
  min-width 0
  overflow-wrap anywhere
  white-space pre-wrap

.kline-slim-reason-popper
  max-width calc(100vw - 24px)

.reason-table-header
  font-weight 600
  color #334155

.error-text
  color #fca5a5

@media (max-width: 1200px)
  .kline-slim-toolbar
    align-items flex-start
    flex-direction column

  .toolbar-right
    justify-content flex-start

  .kline-slim-body
    top 120px

@media (max-width: 900px)
  .kline-slim-body
    flex-direction column

  .kline-slim-sidebar
    width auto
    max-height 220px
    border-right none
    border-bottom 1px solid rgba(127, 127, 122, 0.2)

  .kline-slim-content
    min-height 0

  .reason-table-row
    grid-template-columns repeat(2, minmax(0, 1fr))
</style>
