<template>
  <WorkbenchPage class="position-page">
    <MyHeader />

    <div class="workbench-body position-body" v-loading="loading">
      <el-alert
        v-if="pageError"
        class="workbench-alert"
        type="error"
        :title="pageError"
        show-icon
        :closable="false"
      />

      <section class="position-workbench-grid">
        <div class="position-workbench-column position-workbench-column--left">
          <WorkbenchDetailPanel class="position-state-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">当前仓位状态</div>
              </div>

              <div class="workbench-toolbar__actions">
                <el-button @click="loadDashboard">刷新</el-button>
              </div>
            </div>

            <div class="position-panel-body">
              <div class="position-state-hero">
                <div class="position-state-hero__chips">
                  <StatusChip :variant="stateToneChipVariant">
                    {{ statePanel.hero.effective_state_label }}
                  </StatusChip>
                  <StatusChip :variant="staleChipVariant">
                    {{ statePanel.hero.stale_label }}
                  </StatusChip>
                  <StatusChip variant="muted">
                    raw state <strong>{{ statePanel.hero.raw_state_label }}</strong>
                  </StatusChip>
                </div>

                <div class="position-state-actions" aria-label="当前门禁结果">
                  <article
                    v-for="row in ruleMatrix"
                    :key="row.key"
                    class="position-state-action-chip"
                    :class="{ 'position-state-action-chip--blocked': !row.allowed }"
                    :title="row.label"
                  >
                    <span class="position-state-action-chip__label">{{ compactRuleLabel(row.key, row.label) }}</span>
                    <StatusChip class="runtime-inline-status" :variant="ruleStatusChipVariant(row.allowed)">
                      {{ row.allowed_label }}
                    </StatusChip>
                  </article>
                </div>
              </div>

              <div class="position-state-summary position-state-metric-grid">
                <div
                  class="position-state-note position-state-summary-card"
                  :title="statePanel.hero.matched_rule_title || '-'"
                >
                  <span>当前命中规则</span>
                  <strong>{{ statePanel.hero.matched_rule_title }}</strong>
                </div>

                <article
                  v-for="item in stateMetricSummaryRows"
                  :key="item.key"
                  class="position-state-metric-item position-state-summary-card"
                >
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value_label }}</strong>
                </article>
              </div>
            </div>
          </WorkbenchDetailPanel>

          <PositionSubjectOverviewPanel
            class="position-subject-overview-host"
            :workbench="subjectWorkbenchRuntime"
            :selected-symbol="selectedSubjectSymbol"
            @symbol-select="handleSelectedSubjectChange"
          />
        </div>

        <div class="position-workbench-column position-workbench-column--right">
          <WorkbenchLedgerPanel class="position-selection-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">选中标的工作区</div>
                <div class="workbench-panel__desc">
                  当前统一承载持仓账本、相关订单、对账结果与 Resolution 排障。
                </div>
              </div>
            </div>

            <div class="workbench-summary-row">
              <StatusChip variant="muted">
                当前标的 <strong>{{ selectedSubjectSymbol || '-' }}</strong>
              </StatusChip>
              <StatusChip variant="muted">
                名称 <strong>{{ selectedSubjectName }}</strong>
              </StatusChip>
              <StatusChip :variant="selectedAuditChipVariant">
                检查结果 <strong>{{ selectedAuditStatusLabel }}</strong>
              </StatusChip>
              <StatusChip :variant="selectedReconciliationStateChipVariant">
                对账状态 <strong>{{ selectedReconciliationStateLabel }}</strong>
              </StatusChip>
              <StatusChip variant="muted">
                当前入口 <strong>{{ selectedSubjectSelectedEntry?.entryCompactLabel || '-' }}</strong>
              </StatusChip>
              <StatusChip
                v-for="item in selectedSubjectSummaryChips.slice(0, 3)"
                :key="item.key"
                :variant="item.tone"
              >
                {{ item.label }} <strong>{{ item.value }}</strong>
              </StatusChip>
            </div>

            <el-alert
              v-if="reconciliationPageError"
              class="workbench-alert"
              type="error"
              :title="reconciliationPageError"
              :closable="false"
              show-icon
            />

            <el-tabs
              v-model="selectedWorkbenchTab"
              class="position-selection-tabs"
              @tab-change="handleTroubleshootTabChange"
            >
              <el-tab-pane name="ledger" label="持仓账本">
                <div
                  v-if="selectedSubjectSymbol && selectedSubjectDetail"
                  class="position-selection-panel__body"
                >
                  <section class="position-selection-section">
                    <div class="position-selection-section__title">聚合买入列表 / 按持仓入口止损</div>
                    <div v-if="selectedSubjectEntryRows.length" class="position-selection-table-wrap">
                      <el-table
                        :data="selectedSubjectEntryRows"
                        row-key="entry_id"
                        size="small"
                        border
                        :fit="true"
                        height="100%"
                        highlight-current-row
                        :current-row-key="selectedSubjectEntryId"
                        class="position-selection-entry-table"
                        @row-click="handleSelectedEntryChange"
                        @current-change="handleSelectedEntryChange"
                      >
                        <el-table-column label="入口" min-width="84">
                          <template #default="{ row }">
                            <div
                              class="position-selection-entry-cell position-selection-entry-cell--inline"
                              :title="`${row.entryDisplayLabel || '-'} / ${row.entryIdLabel || row.entry_id || '-'}`"
                            >
                              <strong>{{ row.entryCompactLabel || '-' }}</strong>
                            </div>
                          </template>
                        </el-table-column>

                        <el-table-column label="买入时间" min-width="132">
                          <template #default="{ row }">
                            <span class="workbench-code position-selection-cell__nowrap">{{ row.entrySummaryDisplay?.entryDateTimeLabel || '-' }}</span>
                          </template>
                        </el-table-column>

                        <el-table-column label="买入价" min-width="74" align="right">
                          <template #default="{ row }">
                            <span class="workbench-code">{{ row.entrySummaryDisplay?.entryPriceLabel || '-' }}</span>
                          </template>
                        </el-table-column>

                        <el-table-column label="买入数量" min-width="82" align="right">
                          <template #default="{ row }">
                            <span class="workbench-code">{{ row.entrySummaryDisplay?.originalQuantityLabel || '-' }}</span>
                          </template>
                        </el-table-column>

                        <el-table-column label="剩余 / 占比" min-width="126" align="right">
                          <template #default="{ row }">
                            <span class="workbench-code position-selection-cell__nowrap">{{ row.entrySummaryDisplay?.remainingPositionLabel || '-' }}</span>
                          </template>
                        </el-table-column>

                        <el-table-column label="市值" min-width="78" align="right">
                          <template #default="{ row }">
                            <span class="workbench-code">{{ row.entrySummaryDisplay?.remainingMarketValueLabel || '-' }}</span>
                          </template>
                        </el-table-column>

                        <el-table-column label="单笔止损" min-width="96">
                          <template #default="{ row }">
                            <el-input-number
                              v-if="subjectWorkbenchRuntime.state.stoplossDrafts[selectedSubjectSymbol]?.[row.entry_id]"
                              v-model="subjectWorkbenchRuntime.state.stoplossDrafts[selectedSubjectSymbol][row.entry_id].stop_price"
                              size="small"
                              :min="0"
                              :step="0.01"
                              :precision="2"
                              controls-position="right"
                            />
                            <span v-else class="position-selection-inline-empty">-</span>
                          </template>
                        </el-table-column>

                        <el-table-column label="启用" min-width="72" align="center">
                          <template #default="{ row }">
                            <el-switch
                              v-if="subjectWorkbenchRuntime.state.stoplossDrafts[selectedSubjectSymbol]?.[row.entry_id]"
                              v-model="subjectWorkbenchRuntime.state.stoplossDrafts[selectedSubjectSymbol][row.entry_id].enabled"
                            />
                            <span v-else class="position-selection-inline-empty">-</span>
                          </template>
                        </el-table-column>

                        <el-table-column label="保存" min-width="76" fixed="right">
                          <template #default="{ row }">
                            <el-button
                              size="small"
                              type="primary"
                              :loading="Boolean(subjectWorkbenchRuntime.state.savingStoploss[selectedSubjectSymbol])"
                              @click="saveSubjectStoploss(selectedSubjectSymbol, row.entry_id)"
                            >
                              保存
                            </el-button>
                          </template>
                        </el-table-column>
                      </el-table>
                    </div>
                    <div v-else class="runtime-empty-panel">
                      <strong>当前标的没有 open entry</strong>
                    </div>
                  </section>

                  <section class="position-selection-section">
                    <div class="position-selection-section__title">切片明细</div>
                    <div v-if="selectedSubjectSliceRows.length" class="position-selection-table-wrap">
                      <el-table
                        :data="selectedSubjectSliceRows"
                        size="small"
                        border
                        :fit="true"
                        height="100%"
                        class="position-selection-slice-table"
                      >
                        <el-table-column label="入口" min-width="92">
                          <template #default="{ row }">
                            <div class="position-selection-entry-cell position-selection-entry-cell--inline" :title="`${row.entryDisplayLabel || '-'} / ${row.entryIdLabel || row.entry_id || '-'}`">
                              <strong>{{ row.entryCompactLabel || '-' }}</strong>
                            </div>
                          </template>
                        </el-table-column>
                        <el-table-column label="序号" min-width="62" align="center">
                          <template #default="{ row }">
                            <span class="workbench-code">{{ formatInteger(row.slice_seq) }}</span>
                          </template>
                        </el-table-column>
                        <el-table-column label="守护价" min-width="72" align="right">
                          <template #default="{ row }">
                            <span class="workbench-code">{{ formatPrice(row.guardian_price) }}</span>
                          </template>
                        </el-table-column>
                        <el-table-column label="原始数量" min-width="76" align="right">
                          <template #default="{ row }">
                            <span class="workbench-code">{{ formatInteger(row.original_quantity) }}</span>
                          </template>
                        </el-table-column>

                        <el-table-column label="剩余数量" min-width="76" align="right">
                          <template #default="{ row }">
                            <span class="workbench-code">{{ formatInteger(row.remaining_quantity) }}</span>
                          </template>
                        </el-table-column>

                        <el-table-column label="市值" min-width="74" align="right">
                          <template #default="{ row }">
                            <span class="workbench-code">{{ formatWanAmount(row.remaining_amount) }}</span>
                          </template>
                        </el-table-column>
                      </el-table>
                    </div>
                    <div v-else class="runtime-empty-panel">
                      <strong>{{ selectedSubjectSelectedEntry ? '当前选中入口没有 open 切片' : '请先选择一个持仓入口' }}</strong>
                    </div>
                  </section>
                </div>

                <div v-else class="runtime-empty-panel">
                  <strong>{{ selectedSubjectSymbol ? '当前标的详情加载中' : '请先在标的总览中选择一个标的' }}</strong>
                </div>
              </el-tab-pane>

              <el-tab-pane name="orders" label="相关订单">
                <div class="position-troubleshoot-tab-stack">
                  <div class="workbench-summary-row">
                    <StatusChip variant="muted">
                      当前订单 <strong>{{ orderStats.total || 0 }}</strong>
                    </StatusChip>
                    <StatusChip variant="warning">
                      缺 broker <strong>{{ orderStats.missing_broker_order_count || 0 }}</strong>
                    </StatusChip>
                    <StatusChip v-if="activeOrderFilterChips.length === 0" variant="muted">
                      当前无额外筛选
                    </StatusChip>
                    <StatusChip
                      v-for="chip in activeOrderFilterChips"
                      :key="chip"
                      variant="muted"
                    >
                      {{ chip }}
                    </StatusChip>
                  </div>

                  <div class="position-troubleshoot-order-toolbar">
                    <el-select
                      v-model="orderFilters.state"
                      placeholder="状态"
                      clearable
                      class="position-troubleshoot-order-toolbar__control position-troubleshoot-order-toolbar__control--select"
                    >
                      <el-option
                        v-for="item in orderStateOptions"
                        :key="item.value"
                        :label="item.label"
                        :value="item.value"
                      />
                    </el-select>
                    <el-input
                      v-model="orderFilters.source"
                      clearable
                      placeholder="source"
                      class="position-troubleshoot-order-toolbar__control position-troubleshoot-order-toolbar__control--query"
                    />
                    <el-button @click="toggleAdvancedOrderFilters">
                      {{ showAdvancedOrderFilters ? '收起筛选' : '高级筛选' }}
                    </el-button>
                    <el-button @click="handleResetOrderFilters">重置</el-button>
                    <el-button
                      type="primary"
                      :loading="loadingOrders || loadingOrderStats"
                      @click="handleApplyOrderFilters"
                    >
                      刷新订单
                    </el-button>
                  </div>

                  <div v-if="showAdvancedOrderFilters" class="position-troubleshoot-filter-grid">
                    <el-input v-model="orderFilters.side" placeholder="方向 buy / sell" clearable />
                    <el-input v-model="orderFilters.strategy_name" placeholder="strategy_name" clearable />
                    <el-input v-model="orderFilters.account_type" placeholder="account_type" clearable />
                    <el-input v-model="orderFilters.internal_order_id" placeholder="internal_order_id" clearable />
                    <el-input v-model="orderFilters.request_id" placeholder="request_id" clearable />
                    <el-input v-model="orderFilters.broker_order_id" placeholder="broker_order_id" clearable />
                  </div>

                  <div class="position-troubleshoot-grid position-troubleshoot-grid--orders">
                    <article class="workbench-block position-troubleshoot-block position-troubleshoot-block--table" v-loading="loadingOrders">
                      <div class="position-troubleshoot-block__head">订单列表</div>
                      <div class="position-troubleshoot-table-wrap">
                        <el-empty v-if="orderRows.length === 0" description="当前筛选下没有订单。" />
                        <el-table
                          v-else
                          :data="orderRows"
                          row-key="orderLookupId"
                          size="small"
                          border
                          height="100%"
                          highlight-current-row
                          :current-row-key="selectedOrderId"
                          @row-click="handleOrderRowClick"
                        >
                          <el-table-column label="标的" min-width="132">
                            <template #default="{ row }">
                              <div class="position-troubleshoot-symbol-cell">
                                <strong>{{ row.symbol || '-' }}</strong>
                                <span>{{ row.name || '-' }}</span>
                              </div>
                            </template>
                          </el-table-column>
                          <el-table-column label="更新时间" min-width="160">
                            <template #default="{ row }">
                              {{ formatOrderTimestamp(row.updated_at || row.created_at) }}
                            </template>
                          </el-table-column>
                          <el-table-column prop="side" label="方向" width="76" />
                          <el-table-column label="状态" width="96">
                            <template #default="{ row }">
                              <StatusChip class="runtime-inline-status" :variant="row.state_chip_variant || 'muted'">
                                {{ row.state_label || row.state || '-' }}
                              </StatusChip>
                            </template>
                          </el-table-column>
                          <el-table-column label="委托价 / 量" min-width="126">
                            <template #default="{ row }">
                              {{ formatOrderPrice(row.price) }} / {{ formatOrderQuantity(row.quantity) }}
                            </template>
                          </el-table-column>
                          <el-table-column label="成交量 / 均价" min-width="136">
                            <template #default="{ row }">
                              {{ formatOrderQuantity(row.filled_quantity) }} / {{ formatOrderPrice(row.avg_filled_price) }}
                            </template>
                          </el-table-column>
                        </el-table>
                      </div>
                    </article>

                    <article class="workbench-block position-troubleshoot-block position-troubleshoot-block--detail" v-loading="loadingOrderDetail">
                      <div class="position-troubleshoot-block__head">订单详情</div>
                      <template v-if="orderDetail">
                        <div class="position-troubleshoot-scroll">
                          <el-descriptions :column="1" border size="small">
                            <el-descriptions-item label="internal_order_id">
                              {{ orderDetail.order.internal_order_id || '-' }}
                            </el-descriptions-item>
                            <el-descriptions-item label="broker_order_id">
                              {{ orderDetail.order.broker_order_id || '-' }}
                            </el-descriptions-item>
                            <el-descriptions-item label="symbol">
                              {{ orderDetail.order.symbol || '-' }}
                            </el-descriptions-item>
                            <el-descriptions-item label="state">
                              {{ orderDetail.order.state_label || orderDetail.order.state || '-' }}
                            </el-descriptions-item>
                            <el-descriptions-item label="request">
                              {{ orderDetail.request.request_id || '-' }}
                            </el-descriptions-item>
                            <el-descriptions-item label="scope">
                              {{ orderDetail.request.scope_type || '-' }} / {{ orderDetail.request.scope_ref_id || '-' }}
                            </el-descriptions-item>
                          </el-descriptions>

                          <div class="position-troubleshoot-mini-table">
                            <div class="position-troubleshoot-mini-table__title">状态流转</div>
                            <el-table :data="orderDetail.timelineRows" size="small" border>
                              <el-table-column prop="created_at" label="时间" min-width="152" />
                              <el-table-column prop="event_type" label="event" min-width="116" />
                              <el-table-column label="state" min-width="96">
                                <template #default="{ row }">
                                  <StatusChip class="runtime-inline-status" :variant="row.state_chip_variant || 'muted'">
                                    {{ row.state_label || row.state || '-' }}
                                  </StatusChip>
                                </template>
                              </el-table-column>
                            </el-table>
                          </div>

                          <div class="position-troubleshoot-mini-table">
                            <div class="position-troubleshoot-mini-table__title">成交回报</div>
                            <el-table :data="orderDetail.tradeRows" size="small" border>
                              <el-table-column prop="trade_fact_id" label="Trade Fact" min-width="128" />
                              <el-table-column prop="quantity" label="Qty" width="84" />
                              <el-table-column label="Price" width="84">
                                <template #default="{ row }">
                                  {{ formatOrderPrice(row.price) }}
                                </template>
                              </el-table-column>
                              <el-table-column prop="trade_time_label" label="时间" min-width="156" />
                            </el-table>
                          </div>
                        </div>
                      </template>
                      <div v-else class="runtime-empty-panel">
                        <strong>先从左侧订单列表选择一笔订单。</strong>
                      </div>
                    </article>
                  </div>

                  <div class="position-ledger-pagination">
                    <el-pagination
                      background
                      layout="total,sizes,prev,pager,next"
                      :current-page="orderPage"
                      :page-size="orderSize"
                      :total="orderTotal"
                      :page-sizes="[20, 50, 100]"
                      @current-change="handleOrderPageChange"
                      @size-change="handleOrderPageSizeChange"
                    />
                  </div>
                </div>
              </el-tab-pane>

              <el-tab-pane name="overview" label="对账结果">
                <div v-if="selectedOverviewRow" class="position-troubleshoot-tab-stack">
                  <div class="workbench-summary-row">
                    <StatusChip :variant="selectedOverviewRow.audit_status_chip_variant || 'muted'">
                      检查结果 <strong>{{ selectedOverviewRow.audit_status_label || selectedOverviewRow.audit_status }}</strong>
                    </StatusChip>
                    <StatusChip :variant="selectedOverviewRow.reconciliation_state_chip_variant || 'muted'">
                      对账状态 <strong>{{ selectedOverviewRow.reconciliation_state_label || '-' }}</strong>
                    </StatusChip>
                    <StatusChip variant="muted">
                      latest resolution <strong>{{ selectedOverviewRow.latest_resolution_label || '-' }}</strong>
                    </StatusChip>
                    <StatusChip variant="muted">
                      mismatch <strong>{{ selectedOverviewRow.mismatch_explanations?.length || 0 }}</strong>
                    </StatusChip>
                  </div>

                  <div class="position-troubleshoot-grid">
                    <article class="workbench-block position-troubleshoot-block position-troubleshoot-block--table">
                      <div class="position-troubleshoot-block__head">规则检查</div>
                      <div class="position-troubleshoot-table-wrap">
                        <el-table :data="selectedOverviewRuleRows" size="small" border height="100%">
                          <el-table-column prop="id" label="规则" width="72" />
                          <el-table-column prop="label" label="说明" min-width="136" />
                          <el-table-column label="结果" width="92">
                            <template #default="{ row }">
                              <StatusChip class="runtime-inline-status" :variant="row.status_chip_variant || 'muted'">
                                {{ row.status_label || '-' }}
                              </StatusChip>
                            </template>
                          </el-table-column>
                          <el-table-column prop="expected_relation" label="关系" min-width="128" />
                        </el-table>
                      </div>
                    </article>

                    <article class="workbench-block position-troubleshoot-block position-troubleshoot-block--table">
                      <div class="position-troubleshoot-block__head">视图对照</div>
                      <div class="position-troubleshoot-table-wrap">
                        <el-table :data="selectedOverviewSurfaceRows" size="small" border height="100%">
                          <el-table-column prop="label" label="surface" min-width="112" />
                          <el-table-column prop="quantity_label" label="数量" width="92" />
                          <el-table-column prop="market_value_label" label="市值" width="108" />
                          <el-table-column prop="quantity_source_label" label="数量来源" min-width="120" />
                        </el-table>
                      </div>
                    </article>
                  </div>
                </div>

                <div v-else class="runtime-empty-panel">
                  <strong>{{ selectedSubjectSymbol ? '当前标的暂无对账结果。' : '请先在标的总览中选择一个标的' }}</strong>
                </div>
              </el-tab-pane>

              <el-tab-pane name="resolution" label="Resolution">
                <div class="position-troubleshoot-tab-stack position-troubleshoot-tab-stack--fill">
                  <div class="workbench-summary-row">
                    <StatusChip variant="muted">
                      gap / resolution / rejection <strong>{{ resolutionRows.length }}</strong>
                    </StatusChip>
                    <StatusChip variant="muted">
                      TPSL 触发历史 <strong>{{ workspaceHistoryRows.length }}</strong>
                    </StatusChip>
                    <StatusChip v-if="resolutionEndpointMissing" variant="warning">
                      Resolution 数据源 <strong>后端接口未部署</strong>
                    </StatusChip>
                    <StatusChip v-else-if="resolutionSymbolNotTracked" variant="warning">
                      Resolution 数据源 <strong>symbol 未纳入对账</strong>
                    </StatusChip>
                  </div>

                  <el-alert
                    v-if="resolutionEndpointMissing"
                    class="position-resolution-alert"
                    type="warning"
                    :closable="false"
                    show-icon
                    title="当前运行中的后端未暴露 reconciliation-workspace 接口，因此 Resolution 只能显示为空。"
                  />
                  <el-alert
                    v-else-if="resolutionSymbolNotTracked"
                    class="position-resolution-alert"
                    type="warning"
                    :closable="false"
                    show-icon
                    :title="resolutionSymbolNotTrackedTitle"
                  />

                  <article class="workbench-block position-troubleshoot-block position-troubleshoot-block--table">
                    <div class="position-troubleshoot-block__head">Resolution 列表</div>
                    <div class="position-troubleshoot-table-wrap">
                      <el-empty v-if="resolutionRows.length === 0" :description="resolutionEmptyDescription" />
                      <el-table v-else :data="resolutionRows" row-key="row_id" size="small" border height="100%">
                        <el-table-column label="类型" width="104">
                          <template #default="{ row }">
                            <StatusChip :variant="resolutionRowVariant(row.row_type)">
                              {{ row.row_type }}
                            </StatusChip>
                          </template>
                        </el-table-column>
                        <el-table-column prop="row_id" label="id" min-width="164" />
                        <el-table-column prop="state" label="state" width="96" />
                        <el-table-column prop="side" label="side" width="72" />
                        <el-table-column prop="quantity_delta" label="quantity" width="92" />
                        <el-table-column prop="resolution_type" label="resolution_type" min-width="144" />
                        <el-table-column prop="time_label" label="时间" min-width="148" />
                      </el-table>
                    </div>
                  </article>

                  <article class="workbench-block position-troubleshoot-block position-troubleshoot-block--table">
                    <div class="position-troubleshoot-block__head">TPSL / 触发历史</div>
                    <div class="position-troubleshoot-table-wrap">
                      <el-empty v-if="workspaceHistoryRows.length === 0" description="当前没有历史事件。" />
                      <el-table v-else :data="workspaceHistoryRows" size="small" border height="100%">
                        <el-table-column prop="kind" label="kind" width="92" />
                        <el-table-column prop="created_at" label="created_at" min-width="156" />
                        <el-table-column prop="batch_id" label="batch_id" min-width="132" />
                        <el-table-column prop="entry_label" label="entry" min-width="132" />
                        <el-table-column prop="downstreamLabel" label="downstream" min-width="168" />
                      </el-table>
                    </div>
                  </article>
                </div>
              </el-tab-pane>
            </el-tabs>
          </WorkbenchLedgerPanel>

          <WorkbenchLedgerPanel class="position-decision-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">最近决策与上下文</div>
              </div>
            </div>

            <div class="workbench-summary-row">
              <StatusChip variant="muted">
                覆盖范围 <strong>全部标的</strong>
              </StatusChip>
              <StatusChip variant="muted">
                当前页 <strong>{{ pagedDecisionRows.length }}</strong>
              </StatusChip>
              <StatusChip variant="muted">
                排序 <strong>时间从近到远</strong>
              </StatusChip>
              <StatusChip variant="muted">
                默认分页 <strong>{{ decisionPagination.pageSize }} / 页</strong>
              </StatusChip>
              <StatusChip variant="muted">
                当前页码 <strong>{{ decisionPagination.page }}</strong>
              </StatusChip>
            </div>

            <div v-if="pagedDecisionRows.length" class="position-decision-table-wrap">
              <el-table
                :data="pagedDecisionRows"
                row-key="selection_key"
                size="small"
                border
                :fit="true"
                height="100%"
                class="position-decision-table"
                :row-class-name="decisionRowClassName"
              >
                <el-table-column label="触发时间" min-width="152" resizable show-overflow-tooltip>
                  <template #default="{ row }">
                    <span class="workbench-code">{{ row.evaluated_at_label }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="标的" min-width="144" resizable show-overflow-tooltip>
                  <template #default="{ row }">
                    <strong class="position-decision-cell-strong">{{ row.symbol_display }}</strong>
                  </template>
                </el-table-column>
                <el-table-column label="动作" min-width="68" resizable show-overflow-tooltip prop="action_label" />
                <el-table-column label="结果" min-width="108" resizable>
                  <template #default="{ row }">
                    <StatusChip class="runtime-inline-status" :variant="decisionStatusChipVariant(row.tone)">
                      {{ row.allowed_label }}
                    </StatusChip>
                  </template>
                </el-table-column>
                <el-table-column label="门禁状态" min-width="128" resizable show-overflow-tooltip prop="state_label" />
                <el-table-column label="触发来源" min-width="180" resizable show-overflow-tooltip prop="source_display" />
                <el-table-column label="策略" min-width="112" resizable show-overflow-tooltip prop="strategy_label" />
                <el-table-column label="说明" min-width="180" resizable show-overflow-tooltip prop="reason_display" />
                <el-table-column label="持仓标的" min-width="92" resizable show-overflow-tooltip prop="holding_symbol_display" />
                <el-table-column label="实时市值" min-width="118" resizable align="right" show-overflow-tooltip prop="symbol_market_value_label" />
                <el-table-column label="仓位上限" min-width="118" resizable align="right" show-overflow-tooltip prop="symbol_position_limit_label" />
                <el-table-column label="市值来源" min-width="156" resizable show-overflow-tooltip prop="market_value_source_display" />
                <el-table-column label="数量来源" min-width="156" resizable show-overflow-tooltip prop="quantity_source_display" />
                <el-table-column label="盈利减仓" min-width="92" resizable show-overflow-tooltip prop="force_profit_reduce_display" />
                <el-table-column label="减仓模式" min-width="108" resizable show-overflow-tooltip prop="profit_reduce_mode_display" />
                <el-table-column label="Trace" min-width="144" resizable show-overflow-tooltip>
                  <template #default="{ row }">
                    <span class="workbench-code">{{ row.trace_display }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="Intent" min-width="144" resizable show-overflow-tooltip>
                  <template #default="{ row }">
                    <span class="workbench-code">{{ row.intent_display }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="附加上下文" min-width="260" resizable show-overflow-tooltip prop="extra_context_label" />
              </el-table>
            </div>

            <div v-else class="runtime-empty-panel">
              <strong>暂无最近决策记录</strong>
            </div>

            <div class="position-ledger-pagination">
              <el-pagination
                background
                layout="total,sizes,prev,pager,next"
                :current-page="decisionPagination.page"
                :page-size="decisionPagination.pageSize"
                :total="decisionLedgerRows.length"
                :page-sizes="[100, 200, 500]"
                @current-change="handleDecisionPageChange"
                @size-change="handleDecisionPageSizeChange"
              />
            </div>
          </WorkbenchLedgerPanel>
        </div>
      </section>
    </div>
  </WorkbenchPage>
</template>

<script setup>
import { computed, onMounted, reactive, ref, toRefs, watch } from 'vue'
import { ElMessage } from 'element-plus'

import StatusChip from '../components/workbench/StatusChip.vue'
import WorkbenchDetailPanel from '../components/workbench/WorkbenchDetailPanel.vue'
import WorkbenchLedgerPanel from '../components/workbench/WorkbenchLedgerPanel.vue'
import WorkbenchPage from '../components/workbench/WorkbenchPage.vue'
import PositionSubjectOverviewPanel from '../components/position-management/PositionSubjectOverviewPanel.vue'
import MyHeader from '@/views/MyHeader.vue'
import { orderManagementApi } from '@/api/orderManagementApi'
import { positionManagementApi } from '@/api/positionManagementApi'
import { subjectManagementApi } from '@/api/subjectManagementApi'
import { tpslApi } from '@/api/tpslApi'
import { ORDER_STATE_FILTER_OPTIONS, formatOrderPrice, formatOrderQuantity, formatOrderTimestamp } from './orderManagement.mjs'
import { buildPositionReconciliationRows } from './positionReconciliation.mjs'
import { createDefaultReconciliationOrderFilters, createReconciliationWorkbenchPageController } from './reconciliationWorkbenchPage.mjs'
import { createReconciliationWorkbenchActions } from './reconciliationWorkbench.mjs'
import {
  buildDetailSummaryChips,
  createSubjectManagementActions,
} from '@/views/subjectManagement.mjs'
import { createPositionManagementSubjectWorkbenchController } from '@/views/positionManagementSubjectWorkbench.mjs'
import {
  buildRecentDecisionLedgerRows,
  buildRuleMatrix,
  buildStatePanel,
  readDashboardPayload,
} from './positionManagement.mjs'

const loading = ref(false)
const pageError = ref('')
const dashboard = ref({})
const selectedSubjectSymbol = ref('')
const showAdvancedOrderFilters = ref(false)

const decisionPagination = reactive({
  page: 1,
  pageSize: 100,
})

const mergeSubjectOverviewWithAudit = (overviewRows = [], reconciliationRows = []) => {
  const auditRows = Array.isArray(reconciliationRows) ? reconciliationRows : []
  const auditMap = new Map(auditRows.map((row) => [String(row?.symbol || '').trim(), row]))
  return (Array.isArray(overviewRows) ? overviewRows : []).map((row) => {
    const symbol = String(row?.symbol || '').trim()
    const auditRow = auditMap.get(symbol)
    if (!auditRow) {
      return {
        ...row,
        audit_status: 'UNTRACKED',
        audit_status_label: '未跟踪',
        audit_status_chip_variant: 'muted',
        reconciliation_state: '',
        reconciliation_state_label: '-',
        reconciliation_state_chip_variant: 'muted',
        latest_resolution_label: '-',
      }
    }
    return {
      ...row,
      audit_status: auditRow.audit_status,
      audit_status_label: auditRow.audit_status_label || auditRow.audit_status,
      audit_status_chip_variant: auditRow.audit_status_chip_variant || 'muted',
      reconciliation_state: auditRow.reconciliation_state,
      reconciliation_state_label: auditRow.reconciliation_state_label || '-',
      reconciliation_state_chip_variant: auditRow.reconciliation_state_chip_variant || 'muted',
      latest_resolution_label: auditRow.latest_resolution_label || '-',
    }
  })
}

const baseSubjectActions = createSubjectManagementActions(subjectManagementApi)
const subjectActions = {
  ...baseSubjectActions,
  async loadOverview() {
    const [overviewRows, reconciliationRows] = await Promise.all([
      baseSubjectActions.loadOverview(),
      (async () => {
        try {
          return buildPositionReconciliationRows(await positionManagementApi.getReconciliation())
        } catch {
          return []
        }
      })(),
    ])
    return mergeSubjectOverviewWithAudit(overviewRows, reconciliationRows)
  },
}

const subjectWorkbenchController = createPositionManagementSubjectWorkbenchController({
  actions: subjectActions,
  notify: ElMessage,
  reactiveImpl: reactive,
})

const reconciliationActions = createReconciliationWorkbenchActions({
  positionApi: positionManagementApi,
  orderApi: orderManagementApi,
  tpslApi,
  reconciliationApi: positionManagementApi,
})
const reconciliationWorkbenchController = createReconciliationWorkbenchPageController({
  actions: reconciliationActions,
})
reconciliationWorkbenchController.setActiveTab('ledger')

const {
  state: reconciliationWorkbenchState,
  refreshOverview: refreshReconciliationOverview,
  selectSymbol: selectReconciliationSymbol,
  setActiveTab: setReconciliationActiveTab,
  selectOrder: selectReconciliationOrder,
  changeOrderPage: changeReconciliationOrderPage,
  changeOrderSize: changeReconciliationOrderSize,
  refreshOrderRows: refreshReconciliationOrderRows,
  refreshOrderStats: refreshReconciliationOrderStats,
  syncSelectedOrder: syncReconciliationSelectedOrder,
} = reconciliationWorkbenchController

const {
  loadingOrders,
  loadingOrderStats,
  loadingOrderDetail,
  loadingWorkspace,
  pageError: reconciliationPageError,
  activeTab: selectedWorkbenchTab,
  overviewRows: reconciliationOverviewRows,
  orderFilters,
  orderRows,
  orderStats,
  orderDetail,
  selectedOrderId,
  orderPage,
  orderSize,
  orderTotal,
  workspaceDetail,
} = toRefs(reconciliationWorkbenchState)

const formatPrice = (value) => {
  if (value === null || value === undefined || value === '') return '-'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '-'
  return Number.isInteger(parsed) ? parsed.toFixed(1) : String(parsed)
}

const formatInteger = (value) => {
  if (value === null || value === undefined || value === '') return '-'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '-'
  return String(Math.trunc(parsed))
}

const formatWanAmount = (value) => {
  if (value === null || value === undefined || value === '') return '-'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '-'
  return `${(parsed / 10000).toFixed(2)} 万`
}

const resolveOrderLookupId = (row = {}) => String(
  row?.orderLookupId || row?.internal_order_id || row?.broker_order_id || row?.broker_order_key || '',
).trim()

const resolutionRowVariant = (rowType) => (
  rowType === 'gap' ? 'warning' : rowType === 'resolution' ? 'success' : rowType === 'rejection' ? 'danger' : 'muted'
)

const saveSubjectConfigBundle = async (symbol) => {
  const parsed = Number(subjectWorkbenchController.state.positionLimitDrafts?.[symbol]?.limit)
  if (!Number.isFinite(parsed) || parsed <= 0) {
    ElMessage.warning(`请先填写 ${symbol} 的有效单标的上限`)
    return
  }
  await subjectWorkbenchController.saveConfigBundle(symbol)
}

const saveSubjectStoploss = async (symbol, entryId) => {
  const draft = subjectWorkbenchController.state.stoplossDrafts?.[symbol]?.[entryId] || {}
  if (draft.enabled) {
    const parsed = Number(draft.stop_price)
    if (!Number.isFinite(parsed) || parsed <= 0) {
      ElMessage.warning(`开启止损前请先填写 ${entryId} 的 stop_price`)
      return
    }
  }
  await subjectWorkbenchController.saveStoploss(symbol, entryId)
}

const subjectWorkbenchRuntime = {
  state: subjectWorkbenchController.state,
  refreshOverview: async (options) => subjectWorkbenchController.refreshOverview(options),
  ensureSymbolsHydrated: async (symbols) => subjectWorkbenchController.ensureSymbolsHydrated(symbols),
  selectEntry: (symbol, entryId) => subjectWorkbenchController.selectEntry(symbol, entryId),
  getSelectedEntryId: (symbol) => subjectWorkbenchController.getSelectedEntryId(symbol),
  getSelectedEntry: (symbol) => subjectWorkbenchController.getSelectedEntry(symbol),
  getSelectedEntrySlices: (symbol) => subjectWorkbenchController.getSelectedEntrySlices(symbol),
  saveConfigBundle: async (symbol) => saveSubjectConfigBundle(symbol),
  saveStoploss: async (symbol, entryId) => saveSubjectStoploss(symbol, entryId),
}

const statePanel = computed(() => buildStatePanel(dashboard.value))
const ruleMatrix = computed(() => buildRuleMatrix(dashboard.value))
const stateMetricSummaryRows = computed(() => {
  const metricMap = Object.fromEntries((statePanel.value?.stats || []).map((item) => [item.key, item]))
  return ['available_bail_balance', 'total_asset', 'market_value', 'total_debt']
    .map((key) => metricMap[key])
    .filter(Boolean)
})
const decisionLedgerRows = computed(() => buildRecentDecisionLedgerRows(dashboard.value))
const pagedDecisionRows = computed(() => {
  const start = (decisionPagination.page - 1) * decisionPagination.pageSize
  return decisionLedgerRows.value.slice(start, start + decisionPagination.pageSize)
})
const stateToneChipVariant = computed(() => {
  const tone = statePanel.value?.hero?.effective_state_tone
  if (tone === 'allow') return 'success'
  if (tone === 'hold') return 'warning'
  if (tone === 'reduce') return 'danger'
  return 'muted'
})
const staleChipVariant = computed(() => (statePanel.value?.hero?.stale ? 'warning' : 'muted'))
const selectedSubjectOverviewRow = computed(() => (
  subjectWorkbenchController.state.overviewRows.find((row) => row.symbol === selectedSubjectSymbol.value) || null
))
const selectedSubjectDetail = computed(() => (
  subjectWorkbenchController.state.detailMap[selectedSubjectSymbol.value] || null
))
const selectedSubjectEntryRows = computed(() => selectedSubjectDetail.value?.entries || [])
const selectedSubjectEntryId = computed(() => subjectWorkbenchRuntime.getSelectedEntryId(selectedSubjectSymbol.value))
const selectedSubjectSelectedEntry = computed(() => subjectWorkbenchRuntime.getSelectedEntry(selectedSubjectSymbol.value))
const selectedSubjectSliceRows = computed(() => subjectWorkbenchRuntime.getSelectedEntrySlices(selectedSubjectSymbol.value))
const selectedSubjectSummaryChips = computed(() => (
  selectedSubjectDetail.value ? buildDetailSummaryChips(selectedSubjectDetail.value).slice(0, 5) : []
))
const selectedSubjectName = computed(() => (
  selectedSubjectDetail.value?.name || selectedSubjectOverviewRow.value?.name || '-'
))
const selectedOverviewRow = computed(() => (
  reconciliationOverviewRows.value.find((row) => row.symbol === selectedSubjectSymbol.value) || null
))
const selectedOverviewRuleRows = computed(() => selectedOverviewRow.value?.rule_badges || [])
const selectedOverviewSurfaceRows = computed(() => selectedOverviewRow.value?.surface_sections || [])
const selectedAuditChipVariant = computed(() => (
  selectedOverviewRow.value?.audit_status_chip_variant
  || selectedSubjectOverviewRow.value?.audit_status_chip_variant
  || 'muted'
))
const selectedAuditStatusLabel = computed(() => (
  selectedOverviewRow.value?.audit_status_label
  || selectedSubjectOverviewRow.value?.audit_status_label
  || '未跟踪'
))
const selectedReconciliationStateChipVariant = computed(() => (
  selectedOverviewRow.value?.reconciliation_state_chip_variant
  || selectedSubjectOverviewRow.value?.reconciliation_state_chip_variant
  || 'muted'
))
const selectedReconciliationStateLabel = computed(() => (
  selectedOverviewRow.value?.reconciliation_state_label
  || selectedSubjectOverviewRow.value?.reconciliation_state_label
  || '-'
))
const workspaceHistoryRows = computed(() => workspaceDetail.value?.historyRows || [])
const workspaceResolutionStatus = computed(() => String(workspaceDetail.value?.resolutionDataStatus || 'loaded').trim() || 'loaded')
const workspaceResolutionErrorMessage = computed(() => String(workspaceDetail.value?.resolutionErrorMessage || '').trim())
const activeOrderFilterChips = computed(() => [
  ['side', '方向'],
  ['state', '状态'],
  ['source', 'source'],
  ['strategy_name', 'strategy'],
  ['account_type', '账户'],
  ['internal_order_id', 'internal'],
  ['request_id', 'request'],
  ['broker_order_id', 'broker'],
].map(([key, label]) => {
  const value = String(orderFilters.value?.[key] || '').trim()
  return value ? `${label}: ${value}` : ''
}).filter(Boolean))
const resolutionRows = computed(() => [
  ...(workspaceDetail.value?.gaps || []).map((row) => ({
    ...row,
    row_type: 'gap',
    row_id: row.gap_id || `${selectedSubjectSymbol.value}-gap`,
    time_label: formatOrderTimestamp(row.detected_at || row.pending_until || row.confirmed_at),
  })),
  ...(workspaceDetail.value?.resolutions || []).map((row) => ({
    ...row,
    row_type: 'resolution',
    row_id: row.resolution_id || `${selectedSubjectSymbol.value}-resolution`,
    time_label: formatOrderTimestamp(row.created_at || row.confirmed_at || row.resolved_at),
  })),
  ...(workspaceDetail.value?.rejections || []).map((row) => ({
    ...row,
    row_type: 'rejection',
    row_id: row.rejection_id || `${selectedSubjectSymbol.value}-rejection`,
    time_label: formatOrderTimestamp(row.trade_time || row.detected_at || row.created_at),
  })),
])
const resolutionEndpointMissing = computed(() => workspaceResolutionStatus.value === 'workspace_endpoint_missing')
const resolutionSymbolNotTracked = computed(() => workspaceResolutionStatus.value === 'workspace_symbol_not_tracked')
const resolutionSymbolNotTrackedTitle = computed(() => (
  workspaceResolutionErrorMessage.value || '当前 symbol 未纳入对账跟踪，因此 Resolution 暂无可展示明细。'
))
const resolutionEmptyDescription = computed(() => {
  if (resolutionEndpointMissing.value) return '当前运行中的后端未暴露 reconciliation-workspace 接口，因此 Resolution 只能显示为空。'
  if (resolutionSymbolNotTracked.value) return resolutionSymbolNotTrackedTitle.value
  return '当前 symbol 暂无 gap / resolution / rejection 明细。'
})
const orderStateOptions = ORDER_STATE_FILTER_OPTIONS

watch(
  () => [decisionLedgerRows.value.length, decisionPagination.pageSize],
  () => {
    const totalPages = Math.max(1, Math.ceil(decisionLedgerRows.value.length / decisionPagination.pageSize))
    if (decisionPagination.page > totalPages) {
      decisionPagination.page = totalPages
    }
  },
  { immediate: true },
)

watch(
  () => selectedSubjectSymbol.value,
  async (symbol) => {
    await selectReconciliationSymbol(symbol)
  },
  { immediate: true },
)

const resolveErrorMessage = (error, fallback) => (
  error?.response?.data?.error || error?.message || fallback
)

const decisionStatusChipVariant = (tone) => (tone === 'allow' ? 'success' : 'danger')
const decisionRowClassName = ({ row }) => (row?.tone === 'reject' ? 'position-decision-row--blocked' : '')
const ruleStatusChipVariant = (allowed) => (allowed ? 'success' : 'danger')

const compactRuleLabel = (key, fallbackLabel) => {
  if (key === 'buy_new') return '新买入'
  if (key === 'buy_holding') return '持仓买入'
  if (key === 'sell') return '卖出'
  return fallbackLabel || '-'
}

const handleDecisionPageChange = (page) => {
  decisionPagination.page = page
}

const handleDecisionPageSizeChange = (pageSize) => {
  decisionPagination.pageSize = pageSize
  decisionPagination.page = 1
}

const handleSelectedEntryChange = (row) => {
  const entryId = row?.entry_id
  if (!selectedSubjectSymbol.value || !entryId) return
  subjectWorkbenchRuntime.selectEntry(selectedSubjectSymbol.value, entryId)
}

const handleSelectedSubjectChange = (symbol) => {
  selectedSubjectSymbol.value = String(symbol || '').trim()
}

const handleTroubleshootTabChange = (tab) => {
  setReconciliationActiveTab(tab)
}

const handleOrderRowClick = async (row) => {
  await selectReconciliationOrder(resolveOrderLookupId(row))
}

const handleApplyOrderFilters = async () => {
  orderPage.value = 1
  await refreshReconciliationOrderRows()
  await refreshReconciliationOrderStats()
  await syncReconciliationSelectedOrder()
}

const handleResetOrderFilters = async () => {
  orderFilters.value = {
    ...createDefaultReconciliationOrderFilters(),
    symbol: selectedSubjectSymbol.value || '',
  }
  orderPage.value = 1
  await refreshReconciliationOrderRows()
  await refreshReconciliationOrderStats()
  await syncReconciliationSelectedOrder()
}

const handleOrderPageChange = async (page) => {
  await changeReconciliationOrderPage(page)
  await syncReconciliationSelectedOrder()
}

const handleOrderPageSizeChange = async (size) => {
  await changeReconciliationOrderSize(size)
  await syncReconciliationSelectedOrder()
}

const toggleAdvancedOrderFilters = () => {
  showAdvancedOrderFilters.value = !showAdvancedOrderFilters.value
}

const loadDashboard = async () => {
  loading.value = true
  pageError.value = ''
  const subjectOverviewPromise = subjectWorkbenchRuntime.refreshOverview()
  const reconciliationPromise = refreshReconciliationOverview()
  const [dashboardResult] = await Promise.allSettled([
    positionManagementApi.getDashboard(),
  ])
  if (dashboardResult.status === 'fulfilled') {
    dashboard.value = readDashboardPayload(dashboardResult.value, {})
  } else {
    pageError.value = resolveErrorMessage(dashboardResult.reason, '加载仓位管理面板失败')
  }
  await Promise.allSettled([subjectOverviewPromise, reconciliationPromise])
  if (selectedSubjectSymbol.value) {
    await selectReconciliationSymbol(selectedSubjectSymbol.value)
  }
  loading.value = false
}

onMounted(() => {
  loadDashboard()
})
</script>

<style scoped>
.position-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.position-workbench-grid {
  --position-workbench-left-width: 1.32fr;
  --position-workbench-right-width: 0.8fr;
  display: grid;
  grid-template-columns:
    minmax(0, var(--position-workbench-left-width))
    minmax(0, var(--position-workbench-right-width));
  gap: 12px;
  align-items: stretch;
  flex: 1 1 auto;
  min-height: 0;
}

.position-workbench-column {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
  min-height: 0;
}

.position-workbench-column--left {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-height: 0;
  overflow: hidden;
}

.position-workbench-column--right {
  display: grid;
  grid-template-rows: repeat(2, minmax(0, 1fr));
  min-height: 0;
  overflow: hidden;
}

.position-workbench-column > .workbench-panel,
.position-subject-overview-host {
  min-height: 0;
}

.position-state-panel,
.position-subject-overview-host,
.position-selection-panel,
.position-decision-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.position-panel-body {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  flex-direction: column;
  gap: 6px;
  overflow: hidden;
}

.position-state-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: nowrap;
  padding: 6px 8px;
  border: 1px solid #dbe6f2;
  border-radius: 12px;
  background: linear-gradient(135deg, #f8fbff 0%, #eef5ff 100%);
}

.position-state-hero__chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.position-state-summary {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  align-items: stretch;
  gap: 6px;
}

.position-state-metric-grid {
  align-items: stretch;
}

.position-state-summary-card {
  display: flex;
  min-height: 64px;
  height: 64px;
}

.position-state-metric-item {
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
  padding: 10px 14px;
  border: 1px solid #e5edf5;
  border-radius: 10px;
  background: #f8fbff;
}

.position-state-metric-item span {
  color: #68839d;
  font-size: 12px;
  line-height: 1.4;
  white-space: nowrap;
}

.position-state-metric-item strong {
  color: #21405e;
  font-size: 17px;
  line-height: 1.25;
  font-weight: 700;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.position-panel-section__title,
.position-selection-section__title {
  color: #21405e;
  font-size: 13px;
  font-weight: 600;
}

.position-state-actions {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
  min-width: 0;
}

.position-state-action-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  padding: 4px 8px;
  border: 1px solid #e5edf5;
  border-radius: 999px;
  background: #f8fbff;
}

.position-state-action-chip--blocked {
  background: #fff7f5;
}

.position-state-action-chip__label {
  min-width: 0;
  color: #21405e;
  font-weight: 600;
  font-size: 10px;
  line-height: 1.35;
  white-space: nowrap;
}

.position-state-action-chip :deep(.runtime-inline-status) {
  min-width: 52px;
  padding: 3px 6px;
  font-size: 11px;
}

.position-state-note {
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  min-width: 0;
  padding: 10px 14px;
  border: 1px solid #e5edf5;
  border-radius: 10px;
  background: #f8fbff;
}

.position-state-note span {
  color: #68839d;
  font-size: 12px;
  line-height: 1.4;
}

.position-state-note strong {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #21405e;
  font-size: 17px;
  line-height: 1.25;
  font-weight: 700;
}

.position-selection-tabs {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.position-selection-tabs :deep(.el-tabs__header) {
  margin-bottom: 10px;
}

.position-selection-tabs :deep(.el-tabs__content) {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.position-selection-tabs :deep(.el-tab-pane) {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.position-selection-panel__body {
  display: grid;
  grid-template-rows: repeat(2, minmax(0, 1fr));
  gap: 10px;
  flex: 1 1 auto;
  min-height: 0;
}

.position-selection-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
}

.position-selection-table-wrap {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.position-selection-entry-table,
.position-selection-slice-table {
  height: 100%;
}

.position-selection-entry-table :deep(.el-input-number),
.position-selection-slice-table :deep(.el-input-number) {
  width: 100%;
}

.position-selection-entry-table :deep(.el-table__body tr.current-row > td.el-table__cell) {
  background: #eef5ff;
}

.position-selection-entry-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.position-selection-entry-cell--inline {
  flex-direction: row;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.position-selection-entry-cell strong {
  color: #21405e;
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.position-selection-entry-cell span,
.position-selection-inline-empty {
  color: #68839d;
  font-size: 12px;
  line-height: 1.45;
}

.position-selection-entry-cell--inline span {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.position-selection-cell__nowrap {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  vertical-align: middle;
}

.position-selection-entry-table :deep(.el-table__header .cell),
.position-selection-slice-table :deep(.el-table__header .cell) {
  white-space: nowrap;
}

.position-troubleshoot-tab-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.position-troubleshoot-tab-stack--fill > .position-troubleshoot-block,
.position-troubleshoot-tab-stack--fill > .workbench-block {
  flex: 1 1 0;
}

.position-troubleshoot-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.position-troubleshoot-grid--orders {
  grid-template-columns: minmax(0, 1.1fr) minmax(320px, 0.9fr);
}

.position-troubleshoot-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  overflow: hidden;
}

.position-troubleshoot-block--table,
.position-troubleshoot-block--detail {
  flex: 1 1 0;
}

.position-troubleshoot-block__head {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.position-troubleshoot-table-wrap {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  scrollbar-gutter: stable both-edges;
}

.position-troubleshoot-table-wrap :deep(.el-table) {
  height: 100%;
}

.position-troubleshoot-order-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.position-troubleshoot-order-toolbar__control {
  min-width: 0;
}

.position-troubleshoot-order-toolbar__control--select {
  width: 168px;
}

.position-troubleshoot-order-toolbar__control--query {
  width: min(320px, 100%);
}

.position-troubleshoot-filter-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.position-troubleshoot-symbol-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  min-width: 0;
}

.position-troubleshoot-symbol-cell strong {
  color: #21405e;
}

.position-troubleshoot-symbol-cell span {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  line-height: 1.3;
  color: #6b7280;
}

.position-troubleshoot-scroll {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  scrollbar-gutter: stable both-edges;
}

.position-troubleshoot-mini-table {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
}

.position-troubleshoot-mini-table__title {
  color: #21405e;
  font-size: 12px;
  font-weight: 600;
}

.position-resolution-alert {
  margin: 0;
}

.position-decision-table-wrap {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.position-decision-table {
  height: 100%;
}

.position-decision-table :deep(.el-table__cell) {
  padding-top: 6px;
  padding-bottom: 6px;
  vertical-align: middle;
}

.position-decision-table :deep(.el-table__header .cell) {
  white-space: nowrap;
}

.position-decision-table :deep(.cell) {
  white-space: nowrap;
}

.position-decision-table :deep(.el-table__body tr.position-decision-row--blocked > td.el-table__cell) {
  background: #fff7f5;
}

.position-decision-table :deep(.el-table__body tr.position-decision-row--blocked:hover > td.el-table__cell) {
  background: #fff1ed;
}

.position-decision-cell-strong {
  color: #21405e;
}

.runtime-empty-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 120px;
  border: 1px dashed #dbe1ea;
  border-radius: 12px;
  background: #f8fbff;
  color: #68839d;
}

.runtime-inline-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 76px;
  gap: 0;
  padding: 4px 8px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
}

.position-ledger-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

@media (max-width: 1680px) {
  .position-workbench-grid {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  }
}

@media (max-width: 1440px) {
  .position-troubleshoot-grid,
  .position-troubleshoot-grid--orders,
  .position-troubleshoot-filter-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 1260px) {
  .position-workbench-grid,
  .position-state-metric-grid {
    grid-template-columns: 1fr;
  }

  .position-state-summary {
    grid-template-columns: 1fr;
  }

  .position-state-actions {
    flex-wrap: wrap;
    justify-content: flex-start;
  }

  .position-state-hero {
    flex-wrap: wrap;
  }

  .position-workbench-column--left,
  .position-workbench-column--right,
  .position-selection-panel__body {
    display: flex;
    flex-direction: column;
  }

  .position-troubleshoot-order-toolbar__control--select,
  .position-troubleshoot-order-toolbar__control--query {
    width: 100%;
  }
}
</style>
