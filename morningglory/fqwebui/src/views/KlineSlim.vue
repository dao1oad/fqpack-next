<template>
  <WorkbenchPage class="kline-big-main kline-slim-main">
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
        <el-button size="small" :disabled="!routeSymbol" @click="resetChartViewport">重置视图</el-button>
        <el-button
          size="small"
          :type="showSubjectPanel ? 'primary' : 'default'"
          :disabled="!routeSymbol"
          @click="toggleSubjectPanel"
        >
          标的设置
        </el-button>
        <el-button
          size="small"
          :type="priceGuideEditMode ? 'warning' : 'default'"
          :disabled="!routeSymbol"
          @click="togglePriceGuideEditMode"
        >
          画线编辑
        </el-button>
        <el-button
          size="small"
          :type="showChanlunStructurePanel ? 'primary' : 'default'"
          :disabled="!routeSymbol"
          @click="toggleChanlunStructurePanel"
        >
          缠论结构
        </el-button>
        <el-button size="small" @click="jumpToBigChart">大图</el-button>
      </div>
      <div class="toolbar-right">
        <StatusChip class="kline-slim-toolbar-chip" variant="muted">主图 {{ currentPeriod }}</StatusChip>
        <StatusChip class="kline-slim-toolbar-chip" variant="muted">图例控制主图缠论层与额外周期叠加，并可关闭价格横线</StatusChip>
        <StatusChip class="kline-slim-toolbar-chip" variant="muted">主图末 bar {{ lastMainBarLabel }}</StatusChip>
        <StatusChip class="kline-slim-toolbar-chip" :variant="toolbarStatusChipVariant">{{ statusText }}</StatusChip>
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
                          <span class="sidebar-item-title">{{ item.titleLabel || item.name || item.code6 }}</span>
                          <span v-if="item.secondaryLabel" class="sidebar-item-subtitle">{{ item.secondaryLabel }}</span>
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
        <div v-if="showSubjectPanel" class="kline-slim-subject-panel kline-slim-overlay-panel">
            <div class="price-panel-header subject-panel-header">
              <div class="price-panel-header-main subject-panel-header-main">
                <div class="price-panel-title-row">
                  <span class="price-panel-title">标的设置</span>
                  <span class="price-panel-chip">{{ routeSymbol || '--' }}</span>
                <span v-if="subjectPanelState.subjectPanelDetail" class="price-panel-chip">
                  {{ subjectPanelState.subjectPanelDetail.name || subjectPanelState.subjectPanelDetail.symbol }}
                  </span>
                  <span v-if="subjectPanelState.subjectDetailLoading" class="price-panel-chip">同步中</span>
                </div>
              </div>
              <div class="price-panel-actions subject-panel-header-actions">
                <el-button
                  size="small"
                  type="primary"
                :loading="subjectPanelState.savingSubjectConfigBundle"
                :disabled="!subjectPanelState.subjectPanelDetail"
                @click="handleSaveSubjectConfigBundle"
                >
                  保存
                </el-button>
                <el-button size="small" @click="closeSubjectPanel">关闭</el-button>
              </div>
            </div>

          <div class="price-panel-body">
            <div v-if="subjectPanelState.pageError" class="price-panel-inline-error">
              {{ subjectPanelState.pageError }}
            </div>
            <div v-if="!routeSymbol" class="price-panel-state">请先从左侧选择标的</div>
            <div v-else-if="subjectPanelState.subjectDetailLoading && !subjectPanelState.subjectPanelDetail" class="price-panel-state">
              加载中...
            </div>
            <div v-else-if="!subjectPanelState.subjectPanelDetail" class="price-panel-state">
              暂无标的设置
            </div>
            <div v-else class="price-panel-sections">
              <section class="price-panel-section">
                <div class="price-panel-section-header">
                  <div class="price-panel-section-title-wrap">
                    <span class="price-panel-section-title">基础配置</span>
                  </div>
                </div>

                <div class="price-panel-summary">
                  <StatusChip class="price-panel-summary-status-chip" variant="muted">
                    当前止损 {{ formatPriceGuideValue(subjectPanelState.subjectPanelDetail.mustPool.stop_loss_price) }}
                  </StatusChip>
                  <StatusChip class="price-panel-summary-status-chip" variant="muted">
                    当前上限 {{ formatWanAmountValue(subjectPanelState.subjectPanelDetail.positionLimit.effective_limit) }}
                  </StatusChip>
                  <StatusChip class="price-panel-summary-status-chip" variant="muted">
                    市值 {{ formatWanAmountValue(subjectPanelState.subjectPanelDetail.positionLimit.market_value) }}
                  </StatusChip>
                  <StatusChip class="price-panel-summary-status-chip" :variant="subjectPositionLimitChipVariant">
                    {{ subjectPanelState.subjectPanelDetail.positionLimit.blocked ? '已阻断买入' : '允许买入' }}
                  </StatusChip>
                </div>

                <div class="subject-panel-grid">
                  <div class="subject-panel-base-row">
                    <label class="subject-panel-field">
                      <span class="subject-panel-field__label">止损价</span>
                      <span class="subject-panel-field__note">当前 {{ formatPriceGuideValue(subjectPanelState.subjectPanelDetail.mustPool.stop_loss_price) }}</span>
                      <el-input-number
                        v-model="subjectPanelState.mustPoolDraft.stop_loss_price"
                        size="small"
                        :min="0"
                        :step="0.01"
                        controls-position="right"
                      />
                    </label>

                    <label class="subject-panel-field">
                      <span class="subject-panel-field__label">首笔金额</span>
                      <span class="subject-panel-field__note">当前 {{ formatIntegerValue(subjectPanelState.subjectPanelDetail.mustPool.initial_lot_amount) }}</span>
                      <el-input-number
                        v-model="subjectPanelState.mustPoolDraft.initial_lot_amount"
                        size="small"
                        :min="0"
                        :step="1000"
                        controls-position="right"
                      />
                    </label>
                    <label class="subject-panel-field">
                      <span class="subject-panel-field__label">常规金额</span>
                      <span class="subject-panel-field__note">当前 {{ formatIntegerValue(subjectPanelState.subjectPanelDetail.mustPool.lot_amount) }}</span>
                      <el-input-number
                        v-model="subjectPanelState.mustPoolDraft.lot_amount"
                        size="small"
                        :min="0"
                        :step="1000"
                        controls-position="right"
                      />
                    </label>
                    <label class="subject-panel-field">
                      <span class="subject-panel-field__label">单标的上限设置</span>
                      <span class="subject-panel-field__note">
                        当前生效 {{ formatWanAmountValue(subjectPanelState.subjectPanelDetail.positionLimit.effective_limit) }}
                      </span>
                      <el-input-number
                        v-model="subjectPanelState.positionLimitDraft.limit"
                        size="small"
                        :min="0"
                        :step="10000"
                        controls-position="right"
                      />
                    </label>
                  </div>
                </div>
              </section>

              <section class="price-panel-section">
                <div class="price-panel-section-header">
                  <div class="price-panel-section-title-wrap">
                    <span class="price-panel-section-title">按 buy lot 止损</span>
                    <span class="price-panel-section-note">只对 open buy lot 生效，按行保存</span>
                  </div>
                  <StatusChip class="price-panel-summary-status-chip" variant="muted">
                    {{ (subjectPanelState.subjectPanelDetail.buyLots || []).length }} 条
                  </StatusChip>
                </div>

                <div v-if="!(subjectPanelState.subjectPanelDetail.buyLots || []).length" class="subject-panel-empty">
                  暂无 open buy lot
                </div>
                <div v-else class="subject-panel-stoploss-list">
                  <div
                    v-for="row in subjectPanelState.subjectPanelDetail.buyLots"
                    :key="row.buy_lot_id"
                    class="subject-panel-stoploss-row"
                  >
                    <div class="subject-panel-stoploss-head">
                      <div class="subject-panel-stoploss-title-wrap">
                        <span class="subject-panel-stoploss-title">{{ row.buyLotDisplayLabel }}</span>
                        <span class="subject-panel-stoploss-id" :title="row.buy_lot_id">{{ row.buyLotIdLabel }}</span>
                      </div>
                      <span class="price-panel-state-chip" :class="{ active: subjectPanelState.stoplossDrafts[row.buy_lot_id].enabled }">
                        {{ subjectPanelState.stoplossDrafts[row.buy_lot_id].enabled ? '生效中' : '未启用' }}
                      </span>
                    </div>

                    <span class="subject-panel-stoploss-meta" :title="row.buy_lot_id">{{ row.buyLotMetaLabel }}</span>

                    <div class="subject-panel-stoploss-editor">
                      <el-input-number
                        v-model="subjectPanelState.stoplossDrafts[row.buy_lot_id].stop_price"
                        size="small"
                        :min="0"
                        :step="0.01"
                        controls-position="right"
                      />
                      <el-switch
                        v-model="subjectPanelState.stoplossDrafts[row.buy_lot_id].enabled"
                        size="small"
                        inline-prompt
                        active-text="开"
                        inactive-text="关"
                      />
                      <el-button
                        size="small"
                        type="primary"
                        text
                        :loading="subjectPanelState.savingStoploss[row.buy_lot_id]"
                        @click="handleSaveSubjectStoploss(row.buy_lot_id)"
                      >
                        保存
                      </el-button>
                    </div>
                  </div>
                </div>
              </section>
            </div>
          </div>
        </div>

        <div v-if="showPriceGuidePanel" class="kline-slim-price-panel kline-slim-overlay-panel">
          <div class="price-panel-header">
            <div class="price-panel-header-main">
              <div class="price-panel-title-row">
                <span class="price-panel-title">画线编辑</span>
                <span class="price-panel-chip">{{ routeSymbol || '--' }}</span>
                <span v-if="subjectDetailLoading" class="price-panel-chip">同步中</span>
              </div>
            </div>
            <div class="price-panel-actions">
              <el-button
                size="small"
                type="primary"
                :loading="savingPriceGuides"
                :disabled="priceGuideEditLocked || !subjectPriceDetail"
                @click="handleSavePriceGuides"
              >
                保存
              </el-button>
              <el-button size="small" @click="closePriceGuidePanel">关闭</el-button>
            </div>
          </div>

          <div class="price-panel-body">
            <div v-if="subjectDetailError" class="price-panel-inline-error">
              {{ subjectDetailError }}
            </div>
            <div v-if="!routeSymbol" class="price-panel-state">请先从左侧选择标的</div>
            <div v-else-if="subjectDetailLoading && !subjectPriceDetail" class="price-panel-state">
              加载中...
            </div>
            <div v-else-if="!subjectPriceDetail" class="price-panel-state">
              暂无价格设置
            </div>
            <div v-else class="price-panel-sections">
              <section class="price-panel-section">
                <div class="price-panel-section-header">
                  <div class="price-panel-section-title-wrap">
                    <span class="price-panel-section-title">止盈价格</span>
                  </div>
                  <div class="price-panel-section-actions">
                    <div class="price-panel-action-buttons">
                      <el-button
                        size="small"
                        :loading="savingTakeprofitGuides"
                        :disabled="priceGuideEditLocked || !subjectPriceDetail"
                        @click="handleTakeprofitGuideEnabledAll(true)"
                      >
                        全部开启
                      </el-button>
                      <el-button
                        size="small"
                        :loading="savingTakeprofitGuides"
                        :disabled="priceGuideEditLocked || !subjectPriceDetail"
                        @click="handleTakeprofitGuideEnabledAll(false)"
                      >
                        全部关闭
                      </el-button>
                    </div>
                  </div>
                </div>

                <div class="price-panel-summary">
                  <StatusChip class="price-panel-summary-status-chip" variant="muted">
                    已开启 {{ takeprofitGuideRows.filter((row) => row.manual_enabled).length }}/3
                  </StatusChip>
                  <StatusChip class="price-panel-summary-status-chip" :variant="takeprofitRuntimeChipVariant">
                    运行态 {{ takeprofitRuntimeActiveCount }}/3
                  </StatusChip>
                </div>

                <div class="price-panel-grid">
                  <div
                    v-for="row in takeprofitGuideRows"
                    :key="row.level"
                    class="price-panel-row"
                  >
                    <span
                      class="price-guide-badge"
                      :class="['price-guide-badge--takeprofit', `price-guide-badge--${row.tone}`]"
                    >
                      {{ row.lineLabel }}
                    </span>
                    <div class="price-panel-row-editor price-panel-row-editor--multi">
                      <el-input-number
                        v-model="takeprofitDrafts[row.draftIndex].price"
                        size="small"
                        :min="0"
                        :step="0.001"
                        :precision="3"
                        :disabled="priceGuideEditLocked || !subjectPriceDetail"
                        controls-position="right"
                      />
                      <span class="price-panel-state-chip" :class="{ active: row.runtime_active }">
                        运行态 {{ row.runtimeStateLabel }}
                      </span>
                      <el-switch
                        :model-value="takeprofitDrafts[row.draftIndex].manual_enabled"
                        size="small"
                        :disabled="priceGuideEditLocked || !subjectPriceDetail"
                        inline-prompt
                        active-text="开"
                        inactive-text="关"
                        @change="handleTakeprofitGuideEnabledChange(row.level, $event)"
                      />
                    </div>
                  </div>
                </div>
              </section>

              <section class="price-panel-section">
                <div class="price-panel-section-header">
                  <div class="price-panel-section-title-wrap">
                    <span class="price-panel-section-title">Guardian 倍量价格</span>
                  </div>
                  <div class="price-panel-section-actions">
                    <div class="price-panel-action-buttons">
                      <el-button
                        size="small"
                        :loading="savingGuardianPriceGuides"
                        :disabled="priceGuideEditLocked || !subjectPriceDetail"
                        @click="handleGuardianGuideEnabledAll(true)"
                      >
                        全部开启
                      </el-button>
                      <el-button
                        size="small"
                        :loading="savingGuardianPriceGuides"
                        :disabled="priceGuideEditLocked || !subjectPriceDetail"
                        @click="handleGuardianGuideEnabledAll(false)"
                      >
                        全部关闭
                      </el-button>
                    </div>
                  </div>
                </div>

                <div class="price-panel-summary">
                  <StatusChip class="price-panel-summary-status-chip" variant="muted">
                    已开启 {{ guardianGuideRows.filter((row) => row.manual_enabled).length }}/3
                  </StatusChip>
                  <StatusChip class="price-panel-summary-status-chip" :variant="guardianRuntimeChipVariant">
                    运行态 {{ guardianRuntimeActiveCount }}/3
                  </StatusChip>
                  <StatusChip class="price-panel-summary-status-chip" variant="muted">
                    最近命中 {{ guardianLastHitLabel }}
                  </StatusChip>
                  <StatusChip v-if="guardianState.last_hit_price !== null" class="price-panel-summary-status-chip" variant="muted">
                    最近命中价 {{ formatPriceGuideValue(guardianState.last_hit_price) }}
                  </StatusChip>
                </div>

                <div class="price-panel-grid">
                  <div
                    v-for="row in guardianGuideRows"
                    :key="row.key"
                    class="price-panel-row"
                  >
                    <span
                      class="price-guide-badge"
                      :class="['price-guide-badge--guardian', `price-guide-badge--${row.tone}`]"
                    >
                      {{ row.lineLabel }}
                    </span>
                    <div class="price-panel-row-editor price-panel-row-editor--multi">
                      <el-input-number
                        v-model="guardianDraft[row.key]"
                        size="small"
                        :min="0"
                        :step="0.001"
                        :precision="3"
                        :disabled="priceGuideEditLocked || !subjectPriceDetail"
                        controls-position="right"
                      />
                      <span class="price-panel-state-chip" :class="{ active: row.runtime_active }">
                        运行态 {{ row.runtimeStateLabel }}
                      </span>
                      <el-switch
                        :model-value="guardianDraft.buy_enabled[row.index]"
                        size="small"
                        :disabled="priceGuideEditLocked || !subjectPriceDetail"
                        inline-prompt
                        active-text="开"
                        inactive-text="关"
                        @change="handleGuardianGuideEnabledChange(row.index, $event)"
                      />
                    </div>
                  </div>
                </div>
              </section>

            </div>
          </div>
        </div>

        <div v-if="showChanlunStructurePanel" class="kline-slim-chanlun-panel kline-slim-overlay-panel">
          <div class="chanlun-panel-header">
            <div class="chanlun-panel-header-main">
              <div class="chanlun-panel-title-row">
                <span class="chanlun-panel-title">缠论结构</span>
                <span class="chanlun-panel-chip">{{ routeSymbol || '--' }}</span>
                <span class="chanlun-panel-chip">{{ currentPeriod }}</span>
                <span v-if="chanlunStructureAsof" class="chanlun-panel-chip">
                  截至 {{ chanlunStructureAsof }}
                </span>
              </div>
              <div class="chanlun-panel-meta-row">
                <span>来源 {{ chanlunStructureSourceLabel }}</span>
                <span v-if="chanlunStructureMessage">{{ chanlunStructureMessage }}</span>
                <span v-if="chanlunStructureRefreshError" class="error-text">
                  {{ chanlunStructureRefreshError }}
                </span>
              </div>
            </div>
            <div class="chanlun-panel-actions">
              <el-button size="small" :loading="chanlunStructureLoading" @click="refreshChanlunStructure">
                刷新
              </el-button>
              <el-button size="small" @click="closeChanlunStructurePanel">关闭</el-button>
            </div>
          </div>

          <div class="chanlun-panel-body">
            <div v-if="chanlunStructureLoading && !chanlunStructureData" class="chanlun-panel-state">
              加载中...
            </div>
            <div v-else-if="chanlunStructureError" class="chanlun-panel-state chanlun-panel-state-error">
              <span>{{ chanlunStructureError }}</span>
              <el-button size="small" @click="retryChanlunStructure">重试</el-button>
            </div>
            <div v-else class="chanlun-panel-sections">
              <section class="chanlun-structure-section">
                <div v-if="chanlunHigherSegmentSummary" class="chanlun-summary-line">
                  <span class="chanlun-summary-line__title">高级段</span>
                  <StatusChip
                    v-for="field in chanlunHigherSegmentSummary"
                    :key="`higher:${field.label}`"
                    class="chanlun-summary-status-chip"
                    variant="info"
                  >
                    <span class="chanlun-summary-status-chip__label">{{ field.label }}</span>
                    <span class="chanlun-summary-status-chip__value">{{ field.value }}</span>
                  </StatusChip>
                </div>
                <div v-else class="chanlun-panel-empty">暂无已完成高级段</div>
              </section>

              <section class="chanlun-structure-section">
                <div v-if="chanlunSegmentSummary" class="chanlun-summary-line">
                  <span class="chanlun-summary-line__title">段</span>
                  <StatusChip
                    v-for="field in chanlunSegmentSummary"
                    :key="`segment:${field.label}`"
                    class="chanlun-summary-status-chip"
                    variant="info"
                  >
                    <span class="chanlun-summary-status-chip__label">{{ field.label }}</span>
                    <span class="chanlun-summary-status-chip__value">{{ field.value }}</span>
                  </StatusChip>
                </div>
                <div v-else class="chanlun-panel-empty">暂无已完成段</div>
              </section>

              <section class="chanlun-structure-section">
                <div v-if="chanlunBiSummary" class="chanlun-summary-line">
                  <span class="chanlun-summary-line__title">笔</span>
                  <StatusChip
                    v-for="field in chanlunBiSummary"
                    :key="`bi:${field.label}`"
                    class="chanlun-summary-status-chip"
                    variant="info"
                  >
                    <span class="chanlun-summary-status-chip__label">{{ field.label }}</span>
                    <span class="chanlun-summary-status-chip__value">{{ field.value }}</span>
                  </StatusChip>
                </div>
                <div v-else class="chanlun-panel-empty">暂无已完成笔</div>
              </section>
            </div>
          </div>
        </div>
        <div ref="chartHost" class="kline-slim-chart"></div>
        <div v-if="!routeSymbol" class="kline-slim-empty">
          {{ emptyMessage }}
        </div>
      </section>
    </div>
  </WorkbenchPage>
</template>

<script>
import WorkbenchPage from '../components/workbench/WorkbenchPage.vue'
import StatusChip from '../components/workbench/StatusChip.vue'
import klineSlim from './js/kline-slim'

export default {
  ...klineSlim,
  components: {
    ...(klineSlim.components || {}),
    WorkbenchPage,
    StatusChip,
  },
}
</script>

<style lang="stylus">
@import "../style/kline-big.styl";

.kline-slim-main
  display flex
  flex-direction column

.kline-slim-toolbar
  position relative
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

.kline-slim-toolbar-chip
  white-space nowrap

.kline-slim-body
  position relative
  display flex
  flex 1
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
  gap 4px
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
  line-height 1.35
  color #94a3b8

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

.kline-slim-overlay-panel
  position absolute
  top 12px
  left 12px
  z-index 9
  overflow hidden
  backdrop-filter blur(14px)
  box-shadow 0 24px 48px rgba(2, 6, 23, 0.4)

.kline-slim-price-panel
  bottom 12px
  width 372px
  max-width calc(100% - 24px)
  display flex
  flex-direction column
  border 1px solid rgba(148, 163, 184, 0.24)
  border-radius 18px
  background linear-gradient(180deg, rgba(15, 23, 42, 0.94), rgba(10, 14, 20, 0.96))

.kline-slim-subject-panel
  left 12px
  width 436px
  max-width calc(100% - 24px)
  max-height calc(100% - 24px)
  display flex
  flex-direction column
  border 1px solid rgba(148, 163, 184, 0.24)
  border-radius 18px
  background linear-gradient(180deg, rgba(15, 23, 42, 0.94), rgba(10, 14, 20, 0.96))

.price-panel-header
  display flex
  align-items flex-start
  justify-content space-between
  gap 16px
  padding 16px 18px 14px
  border-bottom 1px solid rgba(148, 163, 184, 0.18)
  background linear-gradient(180deg, rgba(30, 41, 59, 0.78), rgba(15, 23, 42, 0.34))

.price-panel-header-main
  display flex
  flex-direction column
  gap 8px
  min-width 0

.price-panel-title-row
  display flex
  align-items center
  flex-wrap wrap
  gap 8px

.price-panel-title
  font-size 16px
  font-weight 600
  color #f8fafc
  white-space nowrap

.price-panel-chip
  display inline-flex
  align-items center
  min-height 24px
  padding 0 10px
  border-radius 999px
  border 1px solid rgba(148, 163, 184, 0.2)
  background rgba(30, 41, 59, 0.62)
  color #cbd5e1
  font-size 12px

.price-panel-meta-row
  display flex
  align-items center
  flex-wrap wrap
  gap 10px
  font-size 12px
  color #94a3b8

.price-panel-actions
  display flex
  align-items center
  gap 8px

.subject-panel-header
  align-items flex-start

.subject-panel-header-main
  gap 10px

.subject-panel-header-actions
  justify-content flex-end
  flex-wrap wrap

.price-panel-body
  flex 1
  overflow-y auto
  padding 16px 18px 18px

.price-panel-inline-error
  margin-bottom 12px
  padding 10px 12px
  border 1px solid rgba(248, 113, 113, 0.28)
  border-radius 12px
  background rgba(127, 29, 29, 0.18)
  color #fecaca
  font-size 12px

.price-panel-state
  display flex
  align-items center
  justify-content center
  min-height 180px
  padding 0 12px
  color #cbd5e1
  font-size 13px
  text-align center

.price-panel-sections
  display flex
  flex-direction column
  gap 14px

.price-panel-section
  display flex
  flex-direction column
  gap 14px
  padding 14px
  border 1px solid rgba(148, 163, 184, 0.14)
  border-radius 16px
  background rgba(15, 23, 42, 0.5)

.price-panel-section-header
  display flex
  align-items flex-start
  justify-content space-between
  gap 12px

.price-panel-section-actions
  display flex
  align-items center
  justify-content flex-end
  flex-wrap wrap
  gap 8px

.price-panel-action-buttons
  display flex
  align-items center
  flex-wrap nowrap
  gap 8px

.price-panel-section-title-wrap
  display flex
  flex-direction column
  gap 6px
  min-width 0

.price-panel-section-title
  font-size 14px
  font-weight 600
  color #f8fafc

.price-panel-section-note
  font-size 12px
  color #93c5fd

.price-panel-summary
  display flex
  align-items center
  flex-wrap wrap
  gap 8px

.price-panel-summary-status-chip
  white-space nowrap

.price-panel-grid
  display flex
  flex-direction column
  gap 10px

.price-panel-row
  display grid
  grid-template-columns max-content auto
  gap 10px
  align-items center
  padding 12px
  border 1px solid rgba(127, 127, 122, 0.16)
  border-radius 14px
  background rgba(15, 23, 42, 0.44)

.price-panel-row--stacked
  align-items stretch

.price-panel-row-editor
  display flex
  align-items center
  justify-content flex-end
  gap 8px

.price-panel-row-editor--multi
  flex-wrap wrap

.price-panel-row-editor :deep(.el-input-number)
  width 132px

.price-guide-badge
  white-space nowrap
  display inline-flex
  align-items center
  justify-content center
  min-width 68px
  height 26px
  padding 0 10px
  border-radius 999px
  font-size 12px
  font-weight 600
  letter-spacing 0.04em
  border 1px solid transparent

.price-guide-badge--guardian
  box-shadow inset 0 0 0 1px rgba(148, 163, 184, 0.08)

.price-guide-badge--takeprofit
  box-shadow inset 0 0 0 1px rgba(148, 163, 184, 0.08)
  opacity 0.92

.price-guide-badge--blue
  color #bfdbfe
  border-color rgba(59, 130, 246, 0.35)
  background rgba(30, 64, 175, 0.24)

.price-guide-badge--red
  color #fecaca
  border-color rgba(239, 68, 68, 0.35)
  background rgba(127, 29, 29, 0.22)

.price-guide-badge--green
  color #bbf7d0
  border-color rgba(34, 197, 94, 0.35)
  background rgba(20, 83, 45, 0.24)

.price-panel-state-chip
  display inline-flex
  align-items center
  justify-content center
  min-width 48px
  height 26px
  padding 0 10px
  border-radius 999px
  border 1px solid rgba(127, 127, 122, 0.18)
  background rgba(30, 41, 59, 0.5)
  color #94a3b8
  font-size 12px

.price-panel-state-chip.active
  color #dbeafe
  border-color rgba(96, 165, 250, 0.35)
  background rgba(30, 64, 175, 0.24)

.subject-panel-grid
  display flex
  flex-direction column
  gap 10px

.subject-panel-base-row
  display grid
  grid-template-columns repeat(2, minmax(0, 1fr))
  gap 10px

.subject-panel-field
  display flex
  flex-direction column
  gap 6px
  padding 12px
  border 1px solid rgba(127, 127, 122, 0.16)
  border-radius 14px
  background rgba(15, 23, 42, 0.44)

.subject-panel-field__label
  font-size 12px
  font-weight 600
  color #f8fafc

.subject-panel-field__note
  font-size 12px
  line-height 1.5
  color #94a3b8

.subject-panel-empty
  padding 10px 12px
  border 1px dashed rgba(148, 163, 184, 0.2)
  border-radius 12px
  color #94a3b8
  font-size 12px
  background rgba(15, 23, 42, 0.32)

.subject-panel-stoploss-list
  display flex
  flex-direction column
  gap 10px

.subject-panel-stoploss-row
  display flex
  flex-direction column
  gap 8px
  padding 10px 12px
  border 1px solid rgba(127, 127, 122, 0.16)
  border-radius 14px
  background rgba(15, 23, 42, 0.44)

.subject-panel-stoploss-head
  display flex
  align-items flex-start
  justify-content space-between
  gap 10px
  min-width 0

.subject-panel-stoploss-title-wrap
  display flex
  align-items center
  flex-wrap wrap
  gap 8px
  min-width 0

.subject-panel-stoploss-title
  font-size 13px
  font-weight 600
  color #f8fafc
  white-space nowrap

.subject-panel-stoploss-id
  display inline-flex
  align-items center
  min-height 22px
  padding 0 8px
  border-radius 999px
  border 1px solid rgba(127, 127, 122, 0.18)
  background rgba(30, 41, 59, 0.42)
  color #94a3b8
  font-size 11px

.subject-panel-stoploss-meta
  font-size 12px
  line-height 1.5
  color #94a3b8
  overflow-wrap anywhere

.subject-panel-stoploss-main
  display flex
  flex-direction column
  gap 6px
  min-width 0

.subject-panel-stoploss-editor
  display grid
  grid-template-columns minmax(0, 1fr) auto auto
  gap 8px
  align-items center

.subject-panel-field :deep(.el-input-number),
.subject-panel-stoploss-editor :deep(.el-input-number)
  width 100%

.kline-slim-chanlun-panel
  right 12px
  max-height calc(100% - 24px)
  display flex
  flex-direction column
  border 1px solid rgba(148, 163, 184, 0.28)
  border-radius 16px
  background rgba(15, 23, 42, 0.82)

.chanlun-panel-header
  display flex
  align-items flex-start
  justify-content space-between
  gap 16px
  padding 16px 18px 14px
  border-bottom 1px solid rgba(148, 163, 184, 0.18)
  background linear-gradient(180deg, rgba(30, 41, 59, 0.72), rgba(15, 23, 42, 0.36))

.chanlun-panel-header-main
  display flex
  flex-direction column
  gap 8px
  min-width 0

.chanlun-panel-title-row
  display flex
  align-items center
  flex-wrap wrap
  gap 8px

.chanlun-panel-title
  font-size 16px
  font-weight 600
  color #f8fafc

.chanlun-panel-chip
  display inline-flex
  align-items center
  min-height 24px
  padding 0 10px
  border-radius 999px
  background rgba(59, 130, 246, 0.16)
  border 1px solid rgba(96, 165, 250, 0.28)
  color #bfdbfe
  font-size 12px

.chanlun-panel-meta-row
  display flex
  align-items center
  flex-wrap wrap
  gap 10px
  font-size 12px
  color #cbd5e1

.chanlun-panel-actions
  display flex
  align-items center
  gap 8px

.chanlun-panel-body
  overflow-y auto
  padding 16px 18px 18px

.chanlun-panel-state
  display flex
  align-items center
  justify-content center
  gap 12px
  min-height 160px
  color #e2e8f0
  font-size 13px

.chanlun-panel-state-error
  color #fecaca

.chanlun-panel-sections
  display flex
  flex-direction column
  gap 14px

.chanlun-structure-section
  padding 12px 14px
  border 1px solid rgba(148, 163, 184, 0.14)
  border-radius 14px
  background rgba(15, 23, 42, 0.52)

.chanlun-summary-line
  display flex
  align-items center
  flex-wrap wrap
  gap 8px

.chanlun-summary-line__title
  flex 0 0 auto
  min-width 40px
  color #f8fafc
  font-size 14px
  font-weight 600

.chanlun-summary-status-chip
  gap 6px

.chanlun-summary-status-chip__label
  color #93c5fd

.chanlun-summary-status-chip__value
  color #f8fafc

.chanlun-panel-empty
  padding 10px 12px
  border 1px dashed rgba(148, 163, 184, 0.2)
  border-radius 12px
  color #94a3b8
  font-size 12px
  background rgba(15, 23, 42, 0.32)

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

  .kline-slim-price-panel
    width 348px

  .kline-slim-subject-panel
    width 392px

  .price-panel-row
    grid-template-columns max-content minmax(0, 1fr)

  .price-panel-row-editor
    grid-column 1 / -1

  .subject-panel-base-row
    grid-template-columns 1fr

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

  .kline-slim-overlay-panel
    top 8px
    left 8px

  .kline-slim-chanlun-panel
    right 8px
    max-height calc(100% - 16px)

  .kline-slim-price-panel
    right 8px
    bottom 8px
    width auto
    max-height calc(100% - 16px)

  .kline-slim-subject-panel
    right 8px
    width auto
    max-height calc(100% - 16px)

  .chanlun-panel-header
    flex-direction column
    align-items stretch

  .price-panel-header
    flex-direction column
    align-items stretch

  .price-panel-actions
    justify-content flex-end

  .subject-panel-header-actions
    justify-content flex-end

  .price-panel-section-header
    flex-direction column
    align-items stretch

  .price-panel-section-actions
    justify-content flex-start

  .price-panel-action-buttons
    overflow-x auto

  .price-panel-row-editor
    justify-content flex-start

  .subject-panel-stoploss-editor
    grid-template-columns minmax(0, 1fr) auto

  .subject-panel-stoploss-editor :deep(.el-button)
    grid-column 1 / -1
    justify-self end

  .chanlun-panel-actions
    justify-content flex-end

  .chanlun-summary-line
    align-items flex-start

  .reason-table-row
    grid-template-columns repeat(2, minmax(0, 1fr))
</style>
