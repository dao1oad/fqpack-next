<template>
  <WorkbenchPage class="position-review-page">
    <MyHeader />

    <div class="workbench-body position-review-body">
      <WorkbenchToolbar class="position-review-toolbar">
        <div class="workbench-toolbar__header position-review-toolbar__header">
          <div class="workbench-title-group">
            <div class="workbench-page-title">持仓复盘</div>
            <div class="workbench-page-meta">
              <span>覆盖所有历史交易标的</span>
              <span>/</span>
              <span>按真实成交重建仓位</span>
              <span>/</span>
              <span>逐单对照当时策略应有结果</span>
            </div>
          </div>

          <div class="workbench-toolbar__actions position-review-filter-actions">
            <el-input
              v-model="filters.query"
              clearable
              placeholder="代码或名称"
              class="position-review-search"
              @keyup.enter="applyCatalogFilters"
            />
            <el-select
              v-model="filters.status"
              class="position-review-status-filter"
              placeholder="复盘结论"
              @change="applyCatalogFilters"
            >
              <el-option
                v-for="item in statusFilterOptions"
                :key="item.value || 'all'"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
            <el-button
              :loading="loading.symbols"
              @click="applyCatalogFilters"
            >
              筛选目录
            </el-button>
            <el-button @click="resetFilters">重置</el-button>
            <el-button
              type="primary"
              :loading="loading.summary || loading.symbols || loading.detail"
              @click="refreshData"
            >
              刷新复盘
            </el-button>
          </div>
        </div>

        <WorkbenchSummaryRow>
          <StatusChip variant="info">
            范围 <strong>全历史</strong>
          </StatusChip>
          <StatusChip
            v-for="item in summaryKpis"
            :key="item.key"
            :variant="item.tone"
          >
            {{ item.label }} <strong>{{ item.value }}</strong>
          </StatusChip>
          <StatusChip variant="muted">
            数据截至 <strong>{{ summary.generatedAtLabel }}</strong>
          </StatusChip>
          <StatusChip
            :variant="summary.dataQuality.warningCount ? 'warning' : 'info'"
            :title="summaryDataQualityTitle"
          >
            成交真值 <strong>{{ summary.dataQuality.canonicalTradeSourceLabel }}</strong>
          </StatusChip>
        </WorkbenchSummaryRow>
      </WorkbenchToolbar>

      <div class="position-review-layout">
        <WorkbenchSidebarPanel
          class="position-review-symbol-panel"
          v-loading="loading.symbols"
        >
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">历史标的目录</div>
              <p class="workbench-panel__desc">
                包含已经清仓的标的；异常和证据不足优先展示。
              </p>
            </div>
            <div class="workbench-panel__meta">
              共 {{ symbolResult.total }} 个
            </div>
          </div>

          <div v-if="symbolResult.rows.length" class="position-review-symbol-list">
            <button
              v-for="item in symbolResult.rows"
              :key="item.symbol"
              type="button"
              class="position-review-symbol-row"
              :class="{ active: item.symbol === selectedSymbol }"
              @click="selectSymbol(item.symbol)"
            >
              <span class="position-review-symbol-row__head">
                <span class="position-review-symbol-row__identity">
                  <strong>{{ item.name || item.symbol }}</strong>
                  <span>{{ item.symbol }}</span>
                </span>
                <StatusChip
                  class="position-review-inline-chip"
                  :variant="item.statusChipVariant"
                >
                  {{ item.statusLabel }}
                </StatusChip>
              </span>
              <span class="position-review-symbol-row__metrics">
                <span>请求 {{ formatInteger(item.requestCount) }}</span>
                <span>成交 {{ formatInteger(item.fillCount) }}</span>
                <span>异常 {{ formatInteger(item.counts.ANOMALY) }}</span>
                <span>符合率 {{ item.passRateLabel }}</span>
              </span>
              <span class="position-review-symbol-row__foot">
                <span>{{ item.isHolding ? `当前 ${formatInteger(item.currentQuantity)} 股` : '已清仓' }}</span>
                <span>{{ item.lastTradeAtLabel }}</span>
              </span>
            </button>
          </div>

          <div v-else class="workbench-empty position-review-symbol-empty">
            <el-empty
              :description="loading.symbols ? '正在加载历史标的…' : '当前筛选下没有历史交易标的'"
              :image-size="72"
            />
          </div>

          <el-pagination
            v-if="symbolResult.total > symbolResult.size"
            class="position-review-symbol-pagination"
            small
            background
            layout="prev, pager, next"
            :total="symbolResult.total"
            :page-size="symbolResult.size"
            :current-page="symbolResult.page"
            :pager-count="5"
            @current-change="changeSymbolPage"
          />
        </WorkbenchSidebarPanel>

        <div class="position-review-main">
          <div
            v-if="activeLoadErrors.length"
            class="position-review-error-stack"
          >
            <div
              v-for="item in activeLoadErrors"
              :key="item.scope"
              class="position-review-error-row"
            >
              <el-alert
                class="workbench-alert"
                type="error"
                :title="item.message"
                :closable="false"
                show-icon
              />
              <el-button
                type="danger"
                plain
                :loading="loading[item.scope]"
                @click="retryLoadError(item.scope)"
              >
                重试
              </el-button>
            </div>
          </div>

          <el-alert
            v-if="activeDataQualityWarnings.length"
            class="workbench-alert position-review-quality-alert"
            type="warning"
            title="当前复盘存在数据口径提示"
            :description="activeDataQualityWarnings.join('；')"
            :closable="false"
            show-icon
          />

          <section class="position-review-section position-review-portfolio-section">
            <div class="position-review-section__head">
              <div class="workbench-panel__title">组合总览</div>
              <p class="workbench-panel__desc">
                与左侧持仓列表联动：账户净资产曲线（QMT 口径：净资产 = 总资产 − 总负债；日/周/月可切换，交易发生的周期标注交易点）、月度成交额、复盘结论与标的贡献。
              </p>
            </div>
            <PortfolioOverview @drill-symbol="drillToSymbol" />
          </section>

          <section
            ref="symbolSectionRef"
            class="position-review-section position-review-symbol-section"
          >
            <div class="position-review-section__head">
              <div class="workbench-panel__title">标的复盘</div>
              <p class="workbench-panel__desc">
                成本价曲线（Y 轴 = 持仓成本价，X 轴从首个持仓/订单点开始）与订单证据；点击左侧持仓列表或贡献表行联动到对应标的。
              </p>
            </div>
            <div class="position-review-symbol-grid">
              <div class="position-review-center">
          <WorkbenchDetailPanel
            class="position-review-subject-panel"
            v-loading="loading.detail"
          >
            <template v-if="selectedDetail">
              <div class="workbench-panel__header">
                <div class="workbench-title-group">
                  <div class="workbench-panel__title">
                    {{ selectedDetail.displayName }}
                  </div>
                  <div class="workbench-panel__meta">
                    <span>
                      {{ selectedDetail.firstTradeAt ? formatTimestamp(selectedDetail.firstTradeAt) : '-' }}
                      至
                      {{ selectedDetail.lastTradeAt ? formatTimestamp(selectedDetail.lastTradeAt) : '-' }}
                    </span>
                    <span>/</span>
                    <span>{{ selectedDetail.isHolding ? '当前持仓' : '历史已清仓' }}</span>
                  </div>
                </div>
                <div class="workbench-panel__meta position-review-scope-meta">
                  <span :title="selectedDetail.dataQuality.canonicalTradeSource">
                    成交真值 {{ selectedDetail.dataQuality.canonicalTradeSourceLabel }}
                  </span>
                  <span
                    v-if="selectedDetail.initialPositionQuantity !== null"
                    :title="[
                      selectedDetail.initialPositionFormula,
                      selectedDetail.initialPositionAssumption,
                    ].filter(Boolean).join('；')"
                  >
                    / 期初仓为推导值
                  </span>
                  <span v-if="selectedDetail.dataQuality.reviewEngineVersion">
                    / 引擎 {{ selectedDetail.dataQuality.reviewEngineVersion }}
                  </span>
                  <span v-if="selectedDetail.dataQuality.strategyVersion">
                    / 策略 {{ selectedDetail.dataQuality.strategyVersion }}
                  </span>
                </div>
              </div>

              <el-alert
                v-if="selectedOutsideCatalog"
                class="position-review-inline-alert"
                type="info"
                title="当前详情来自深链或已被目录筛选条件排除"
                description="详情仍按标的代码直接加载；重置筛选可尝试在左侧目录中定位该标的。"
                :closable="false"
                show-icon
              />

              <WorkbenchSummaryRow>
                <StatusChip
                  v-for="item in detailKpis"
                  :key="item.key"
                  :variant="item.tone"
                >
                  {{ item.label }} <strong>{{ item.value }}</strong>
                </StatusChip>
              </WorkbenchSummaryRow>
            </template>

            <div v-else class="workbench-empty">
              <el-empty description="请从左侧选择一个历史交易标的" :image-size="72" />
            </div>
          </WorkbenchDetailPanel>

          <WorkbenchPanel
            v-if="selectedDetail"
            class="position-review-timeline-panel"
          >
            <div class="workbench-panel__header">
            <div class="workbench-title-group">
                <div class="workbench-panel__title">订单与成本价复盘主图</div>
                <p class="workbench-panel__desc">
                  Y 轴 = 持仓成本价，X 轴从首个持仓/订单点开始；订单事件来自当前订单账本（重建订单 + 真实订单），颜色表达买卖方向、形状表达信号类型；点击 marker 固定订单并查看完整条件证据。
                </p>
              </div>
            </div>
            <SymbolReviewChart
              :symbol="selectedSymbol"
              :period="'5m'"
              @fix-event="openFixedEvent"
            />
          </WorkbenchPanel>

          <el-collapse
            v-model="ledgerCollapse"
            class="position-review-ledger-collapse"
          >
            <el-collapse-item name="ledger-executions" title="订单成交明细">
          <WorkbenchLedgerPanel
            v-if="selectedDetail"
            class="position-review-ledger-panel"
          >
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">订单成交明细</div>
                <p class="workbench-panel__desc">
                  只展示与当前订单账本关联的真实成交（{{ selectedDetail.dataQuality.canonicalTradeSourceLabel }}）；账本重建初始化订单为虚拟订单，尚无真实成交，后续真实订单的成交将在此展示。
                </p>
              </div>
              <div class="workbench-panel__meta position-review-ledger-counts">
                <span>共 {{ selectedDetail.executions.length }} 笔</span>
                <StatusChip
                  v-if="selectedDetail.unassociatedExecutionCount"
                  variant="danger"
                >
                  未关联 {{ selectedDetail.unassociatedExecutionCount }} 笔
                </StatusChip>
              </div>
            </div>

            <div class="workbench-table-wrap position-review-table-wrap">
              <el-table
                v-if="selectedDetail.executions.length"
                :data="selectedDetail.executions"
                row-key="id"
                stripe
                border
                height="100%"
                highlight-current-row
                :row-class-name="executionRowClassName"
                @row-click="openExecutionDrawer"
              >
                <el-table-column label="成交时间" min-width="168">
                  <template #default="{ row }">
                    <span class="workbench-code">{{ row.timeLabel }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="方向" width="72" align="center">
                  <template #default="{ row }">
                    <span :class="`position-review-side position-review-side--${row.side}`">
                      {{ row.sideLabel }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column label="成交价" min-width="96" align="right">
                  <template #default="{ row }">
                    <span class="workbench-code">{{ formatPrice(row.price) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="成交量" min-width="92" align="right">
                  <template #default="{ row }">
                    <strong class="workbench-code">{{ formatInteger(row.quantity) }}</strong>
                  </template>
                </el-table-column>
                <el-table-column label="成交 ID" min-width="188">
                  <template #default="{ row }">
                    <span
                      class="workbench-code position-review-ellipsis"
                      :title="row.brokerTradeId"
                    >
                      {{ row.brokerTradeId || '—' }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column label="关联请求" min-width="188">
                  <template #default="{ row }">
                    <span
                      v-if="row.isAssociated"
                      class="workbench-code position-review-ellipsis"
                      :title="row.requestId"
                    >
                      {{ row.requestId }}
                    </span>
                    <StatusChip v-else class="position-review-inline-chip" variant="danger">
                      未关联
                    </StatusChip>
                  </template>
                </el-table-column>
                <el-table-column label="关联质量" min-width="116">
                  <template #default="{ row }">
                    <StatusChip
                      class="position-review-inline-chip"
                      :variant="row.associationChipVariant"
                    >
                      {{ row.associationLabel }}
                    </StatusChip>
                  </template>
                </el-table-column>
                <el-table-column label="关联方式" min-width="136">
                  <template #default="{ row }">
                    <span class="workbench-code">{{ row.associationMethod || '—' }}</span>
                  </template>
                </el-table-column>
              </el-table>

              <div v-else class="workbench-empty">
                <el-empty description="当前为账本重建初始化订单（虚拟），暂无真实成交；后续真实订单的成交将在此展示。" :image-size="72" />
              </div>
            </div>
          </WorkbenchLedgerPanel>
            </el-collapse-item>

            <el-collapse-item name="ledger-reviews" title="逐单策略复盘">
          <WorkbenchLedgerPanel
            v-if="selectedDetail"
            class="position-review-ledger-panel"
          >
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">逐单策略复盘</div>
                <p class="workbench-panel__desc">
                  实际成交量与策略应有量分别展示；点击任一行查看公式、来源切片与完整证据 ID。
                </p>
              </div>
              <div class="workbench-panel__meta">
                共 {{ selectedDetail.reviews.length }} 笔
              </div>
            </div>

            <div class="workbench-table-wrap position-review-table-wrap">
              <el-table
                v-if="selectedDetail.reviews.length"
                ref="reviewTableRef"
                :data="selectedDetail.reviews"
                row-key="id"
                stripe
                border
                height="100%"
                highlight-current-row
                :row-class-name="reviewRowClassName"
                @row-click="openReviewDrawer"
              >
                <el-table-column label="时间" min-width="168">
                  <template #default="{ row }">
                    <span class="workbench-code">{{ row.timeLabel }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="方向" width="72" align="center">
                  <template #default="{ row }">
                    <span :class="`position-review-side position-review-side--${row.side}`">
                      {{ row.sideLabel }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column label="信号/委托价" min-width="104" align="right">
                  <template #default="{ row }">
                    <span class="workbench-code">{{ formatPrice(row.requestPrice) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="策略阈值" min-width="100" align="right">
                  <template #default="{ row }">
                    <span class="workbench-code">{{ formatPrice(row.thresholdPrice) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="请求量" min-width="86" align="right">
                  <template #default="{ row }">
                    <span class="workbench-code">{{ formatInteger(row.requestQuantity) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="策略应有量" min-width="98" align="right">
                  <template #default="{ row }">
                    <strong v-if="row.expectedQuantity !== null" class="workbench-code">
                      {{ formatInteger(row.expectedQuantity) }}
                    </strong>
                    <StatusChip v-else class="position-review-inline-chip" variant="warning">
                      证据不足
                    </StatusChip>
                  </template>
                </el-table-column>
                <el-table-column label="实际成交量" min-width="98" align="right">
                  <template #default="{ row }">
                    <strong class="workbench-code">{{ formatInteger(row.actualQuantity) }}</strong>
                  </template>
                </el-table-column>
                <el-table-column label="数量偏差" min-width="88" align="right">
                  <template #default="{ row }">
                    <span
                      class="workbench-code"
                      :class="{ 'position-review-delta--anomaly': isFiniteNonZero(row.quantityDelta) }"
                    >
                      {{ formatSignedInteger(row.quantityDelta) }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column label="复盘结论" min-width="108">
                  <template #default="{ row }">
                    <StatusChip
                      class="position-review-inline-chip"
                      :variant="row.statusChipVariant"
                    >
                      {{ row.statusLabel }}
                    </StatusChip>
                  </template>
                </el-table-column>
                <el-table-column label="原因" min-width="220">
                  <template #default="{ row }">
                    <span class="position-review-reason" :title="row.reasonText">
                      {{ row.reasonText }}
                    </span>
                  </template>
                </el-table-column>
              </el-table>

              <div v-else class="workbench-empty">
                <el-empty description="当前标的没有策略请求复盘记录" :image-size="72" />
              </div>
            </div>
          </WorkbenchLedgerPanel>
            </el-collapse-item>
          </el-collapse>
        </div>

        <WorkbenchDetailPanel
          class="position-review-evidence-panel"
        >
          <template v-if="activeReview || activeExecution || activeFixedEvent">
            <div class="position-review-evidence-panel__header">
              <div class="position-review-evidence-panel__title">{{ drawerTitle }}</div>
              <el-button size="small" @click="closeEvidence">关闭</el-button>
            </div>
            <div class="position-review-evidence-panel__body">
      <template v-if="activeReview">
        <div class="position-review-drawer__summary">
          <StatusChip :variant="activeReview.statusChipVariant">
            {{ activeReview.statusLabel }}
          </StatusChip>
          <StatusChip :variant="confidenceVariant(activeReview.confidence)">
            证据置信度 <strong>{{ confidenceLabel(activeReview.confidence) }}</strong>
          </StatusChip>
          <StatusChip variant="muted">
            {{ activeReview.sideLabel }} <strong>{{ activeReview.timeLabel }}</strong>
          </StatusChip>
        </div>

        <el-alert
          class="position-review-drawer__alert"
          :type="activeReview.status === 'ANOMALY' ? 'error' : activeReview.status === 'UNVERIFIABLE' ? 'warning' : 'info'"
          :title="activeReview.reasonText"
          :closable="false"
          show-icon
        />

        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="请求数量">
            {{ formatInteger(activeReview.requestQuantity) }} 股
          </el-descriptions-item>
          <el-descriptions-item label="策略应有数量">
            <template v-if="activeReview.expectedQuantity !== null">
              {{ formatInteger(activeReview.expectedQuantity) }} 股
            </template>
            <StatusChip v-else class="position-review-inline-chip" variant="warning">
              证据不足
            </StatusChip>
          </el-descriptions-item>
          <el-descriptions-item label="实际成交数量">
            {{ formatInteger(activeReview.actualQuantity) }} 股
          </el-descriptions-item>
          <el-descriptions-item label="数量偏差">
            {{ formatSignedInteger(activeReview.quantityDelta) }}
            <template v-if="activeReview.quantityDelta !== null"> 股</template>
          </el-descriptions-item>
          <el-descriptions-item label="信号/委托价">
            {{ formatPrice(activeReview.requestPrice) }}
          </el-descriptions-item>
          <el-descriptions-item label="实际成交均价">
            {{ formatPrice(activeReview.actualPrice) }}
          </el-descriptions-item>
          <el-descriptions-item label="策略阈值">
            {{ formatPrice(activeReview.thresholdPrice) }}
          </el-descriptions-item>
          <el-descriptions-item label="最低守护价">
            {{ formatPrice(activeReview.lowestGuardianPrice) }}
          </el-descriptions-item>
        </el-descriptions>

        <section class="position-review-drawer__section">
          <h3>策略计算</h3>
          <p>{{ activeReview.formula || '当前记录未提供可展示的计算公式。' }}</p>
          <div class="position-review-reason-codes">
            <StatusChip
              v-for="(label, index) in activeReview.reasonLabels"
              :key="activeReview.reasonCodes[index]"
              variant="muted"
            >
              {{ label }}
            </StatusChip>
          </div>
        </section>

        <section class="position-review-drawer__section">
          <h3>链路标识</h3>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item
              v-for="item in activeReviewIdentityRows"
              :key="item.label"
              :label="item.label"
            >
              <span class="workbench-code position-review-break-all">{{ item.value }}</span>
            </el-descriptions-item>
          </el-descriptions>
        </section>

        <section class="position-review-drawer__section">
          <h3>来源切片</h3>
          <pre class="position-review-json">{{ prettyJson(activeReview.sourceEntries) }}</pre>
        </section>

        <section class="position-review-drawer__section">
          <h3>成交与账本证据</h3>
          <pre class="position-review-json">{{ prettyJson(activeReview.evidence) }}</pre>
        </section>
      </template>

      <template v-else-if="activeExecution">
        <div class="position-review-drawer__summary">
          <StatusChip :variant="activeExecution.associationChipVariant">
            {{ activeExecution.associationLabel }}
          </StatusChip>
          <StatusChip
            :variant="activeExecution.side === 'buy' ? 'danger' : 'success'"
          >
            {{ activeExecution.sideLabel }}
            <strong>{{ formatInteger(activeExecution.quantity) }} 股</strong>
          </StatusChip>
          <StatusChip variant="muted">
            {{ activeExecution.timeLabel }}
          </StatusChip>
        </div>

        <el-alert
          v-if="!activeExecution.isAssociated"
          class="position-review-drawer__alert"
          type="error"
          title="该笔真实成交尚未关联到策略请求"
          description="系统保留这笔成交用于仓位重建，但不会为它伪造策略结论；可使用下方成交 ID、委托 ID 与证据 ID 继续排查。"
          :closable="false"
          show-icon
        />
        <el-alert
          v-else
          class="position-review-drawer__alert"
          :type="activeExecution.associationQuality === 'high' ? 'success' : 'warning'"
          :title="`已关联请求 ${activeExecution.requestId}`"
          :description="`关联方式：${activeExecution.associationMethod || '未记录'}；关联质量：${activeExecution.associationLabel}`"
          :closable="false"
          show-icon
        />

        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="成交价格">
            {{ formatPrice(activeExecution.price) }}
          </el-descriptions-item>
          <el-descriptions-item label="成交数量">
            {{ formatInteger(activeExecution.quantity) }} 股
          </el-descriptions-item>
          <el-descriptions-item label="方向">
            {{ activeExecution.sideLabel }}
          </el-descriptions-item>
          <el-descriptions-item label="成交真值">
            <span :title="selectedDetail?.dataQuality?.canonicalTradeSource">
              {{ selectedDetail?.dataQuality?.canonicalTradeSourceLabel || 'XT 真实成交' }}
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="成交来源">
            {{ activeExecution.source || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="匿名账户分区">
            {{ activeExecution.accountPartition || '未知' }}
          </el-descriptions-item>
        </el-descriptions>

        <section class="position-review-drawer__section">
          <div class="position-review-drawer__section-head">
            <h3>成交关联链路</h3>
            <el-button
              v-if="associatedReview"
              type="primary"
              link
              @click="openAssociatedReview"
            >
              查看关联请求复盘
            </el-button>
          </div>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item
              v-for="item in activeExecutionIdentityRows"
              :key="item.label"
              :label="item.label"
            >
              <span class="workbench-code position-review-break-all">{{ item.value }}</span>
            </el-descriptions-item>
          </el-descriptions>
        </section>

        <section class="position-review-drawer__section">
          <h3>Canonical 成交原始证据</h3>
          <pre class="position-review-json">{{ prettyJson(activeExecution.raw) }}</pre>
        </section>
      </template>

      <template v-else-if="activeFixedEvent">
        <div class="position-review-drawer__summary">
          <StatusChip :variant="activeFixedEvent.side === 'buy' ? 'danger' : 'success'">
            {{ activeFixedEvent.side === 'buy' ? '买入' : '卖出' }}
            <strong>{{ activeFixedEvent.event_id }}</strong>
          </StatusChip>
          <StatusChip :variant="activeFixedEvent.review?.verdict === 'PASS' ? 'success' : 'warning'">
            复盘结论 <strong>{{ activeFixedEvent.review?.verdict || '未判定' }}</strong>
          </StatusChip>
          <StatusChip variant="muted">
            信号 {{ activeFixedEvent.signal?.label || '未关联信号' }}
          </StatusChip>
        </div>

        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="请求数量">
            {{ activeFixedEvent.order?.request_quantity ?? '—' }} 股
          </el-descriptions-item>
          <el-descriptions-item label="策略应有数量">
            {{ activeFixedEvent.order?.expected_quantity ?? '证据不足' }}
          </el-descriptions-item>
          <el-descriptions-item label="实际成交数量">
            {{ activeFixedEvent.execution?.actual_quantity ?? '—' }} 股
          </el-descriptions-item>
          <el-descriptions-item label="加权成交均价">
            {{ formatPrice(activeFixedEvent.execution?.avg_filled_price) }}
          </el-descriptions-item>
          <el-descriptions-item label="成交笔数 / 跨度">
            {{ activeFixedEvent.execution?.fill_count ?? '—' }} 笔
            <template v-if="activeFixedEvent.execution?.first_fill_time && activeFixedEvent.execution?.last_fill_time">
              / {{ formatTimestamp(activeFixedEvent.execution.first_fill_time) }} ~ {{ formatTimestamp(activeFixedEvent.execution.last_fill_time) }}
            </template>
          </el-descriptions-item>
          <el-descriptions-item label="持仓前后">
            {{ activeFixedEvent.position_impact?.position_before ?? '—' }} → {{ activeFixedEvent.position_impact?.position_after ?? '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="持仓均价前后">
            {{ formatPrice(activeFixedEvent.position_impact?.cost_basis_before) }} → {{ formatPrice(activeFixedEvent.position_impact?.cost_basis_after) }}
          </el-descriptions-item>
          <el-descriptions-item label="已实现盈亏影响">
            {{ formatSignedInteger(activeFixedEvent.position_impact?.realized_pnl_impact) }}
          </el-descriptions-item>
          <el-descriptions-item label="成本口径">
            {{ activeFixedEvent.position_impact?.cost_basis_source || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="费用口径">
            fees_included: {{ activeFixedEvent.position_impact?.fees_included ? 'true' : 'false' }}
          </el-descriptions-item>
        </el-descriptions>

        <section class="position-review-drawer__section">
          <div class="position-review-drawer__section-head">
            <h3>触发信号与关联</h3>
            <el-button type="primary" link @click="closeFixedEvent">关闭</el-button>
          </div>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="信号类型">
              {{ activeFixedEvent.signal?.type || '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="信号族">
              {{ activeFixedEvent.signal?.family || '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="信号时间">
              {{ formatTimestamp(activeFixedEvent.signal?.time) }}
            </el-descriptions-item>
            <el-descriptions-item label="信号价格">
              {{ formatPrice(activeFixedEvent.signal?.price) }}
            </el-descriptions-item>
            <el-descriptions-item label="关联方式">
              {{ activeFixedEvent.signal?.association_method || '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="trace / intent">
              {{ activeFixedEvent.signal?.trace_id || '—' }} / {{ activeFixedEvent.signal?.intent_id || '—' }}
            </el-descriptions-item>
          </el-descriptions>
        </section>

        <section class="position-review-drawer__section">
          <div class="position-review-drawer__section-head">
            <h3>触发条件与全部阈值</h3>
            <el-button
              size="small"
              :loading="fixedEventLoading"
              @click="openFixedEvent(activeFixedEvent)"
            >
              重新加载
            </el-button>
          </div>
          <el-alert
            v-if="fixedEventNormalized.thresholdMissingCount"
            class="position-review-drawer__alert"
            type="warning"
            :title="`${fixedEventNormalized.thresholdMissingCount} 个条件的历史阈值证据缺失（保持 null）`"
            :closable="false"
            show-icon
          />
          <el-table
            v-if="fixedEventNormalized.conditions.length"
            :data="fixedEventNormalized.conditions"
            stripe
            border
            size="small"
            max-height="320"
          >
            <el-table-column label="条件" min-width="150">
              <template #default="{ row }">
                <span class="workbench-code" :title="row.key">{{ row.label }}</span>
              </template>
            </el-table-column>
            <el-table-column label="实际值" min-width="96" align="right">
              <template #default="{ row }">
                <span class="workbench-code">{{ row.actualDisplay || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作符" width="64" align="center">
              <template #default="{ row }">
                {{ row.operator || '—' }}
              </template>
            </el-table-column>
            <el-table-column label="阈值" min-width="96" align="right">
              <template #default="{ row }">
                <template v-if="row.thresholdMissing">
                  <StatusChip class="position-review-inline-chip" variant="warning">缺失</StatusChip>
                </template>
                <span v-else class="workbench-code">{{ row.thresholdDisplay }}</span>
              </template>
            </el-table-column>
            <el-table-column label="通过" width="76" align="center">
              <template #default="{ row }">
                <template v-if="row.passed === null">—</template>
                <StatusChip v-else :variant="row.passed ? 'success' : 'danger'">
                  {{ row.passed ? '是' : '否' }}
                </StatusChip>
              </template>
            </el-table-column>
            <el-table-column label="来源" min-width="120">
              <template #default="{ row }">
                {{ row.source === 'runtime_event' ? '运行事件' : row.source === 'request_snapshot' ? '请求快照' : row.source === 'missing' ? '缺失' : row.source || '—' }}
              </template>
            </el-table-column>
            <el-table-column label="观测时间" min-width="150">
              <template #default="{ row }">
                <span class="workbench-code">{{ formatTimestamp(row.observedAt) }}</span>
              </template>
            </el-table-column>
          </el-table>
          <el-empty
            v-else-if="!fixedEventLoading"
            description="该订单暂无可用条件证据"
            :image-size="64"
          />
        </section>

        <section class="position-review-drawer__section">
          <h3>配置快照与证据</h3>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="表达式">
              {{ fixedEventNormalized.expression || '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="策略版本">
              {{ fixedEventNormalized.strategyVersion || '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="配置快照 hash">
              <span class="workbench-code position-review-break-all">
                {{ fixedEventNormalized.configSnapshotHash || '—' }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="trace_id">
              <span class="workbench-code position-review-break-all">
                {{ fixedEventNormalized.evidence.trace_id || '—' }}
              </span>
            </el-descriptions-item>
          </el-descriptions>
          <pre
            v-if="fixedEventNormalized.triggerSnapshot"
            class="position-review-json"
          >{{ prettyJson(fixedEventNormalized.triggerSnapshot) }}</pre>
        </section>
      </template>
            </div>
          </template>

          <div v-else class="workbench-empty position-review-evidence-panel__empty">
            <el-empty
              description="点击主图 marker 固定订单，或点击账本行查看完整证据"
              :image-size="72"
            />
          </div>
        </WorkbenchDetailPanel>
        </div>
        </section>
      </div>
    </div>

    </div>
  </WorkbenchPage>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import MyHeader from './MyHeader.vue'
import WorkbenchPage from '../components/workbench/WorkbenchPage.vue'
import WorkbenchToolbar from '../components/workbench/WorkbenchToolbar.vue'
import WorkbenchPanel from '../components/workbench/WorkbenchPanel.vue'
import WorkbenchSidebarPanel from '../components/workbench/WorkbenchSidebarPanel.vue'
import WorkbenchLedgerPanel from '../components/workbench/WorkbenchLedgerPanel.vue'
import WorkbenchDetailPanel from '../components/workbench/WorkbenchDetailPanel.vue'
import WorkbenchSummaryRow from '../components/workbench/WorkbenchSummaryRow.vue'
import StatusChip from '../components/workbench/StatusChip.vue'
import PositionReviewChart from '../components/position-review/PositionReviewChart.vue'
import PortfolioOverview from '../components/position-review/PortfolioOverview.vue'
import SymbolReviewChart from '../components/position-review/SymbolReviewChart.vue'
import { positionReviewApi } from '../api/positionReviewApi.js'
import {
  normalizeConditions,
} from './positionReviewRefactor.mjs'
import {
  buildPositionReviewDetailKpis,
  buildPositionReviewSummaryKpis,
  formatPositionReviewInteger,
  formatPositionReviewPrice,
  formatPositionReviewSignedInteger,
  isPositionReviewFiniteNonZero,
  normalizePositionReviewDetail,
  normalizePositionReviewSummary,
  normalizePositionReviewSymbolRows,
  resolvePositionReviewSelectedSymbol,
  runPositionReviewCatalogFilter,
  runPositionReviewRefresh,
} from './positionReview.mjs'
import {
  normalizePositionReviewStatus,
  POSITION_REVIEW_FILTER_OPTIONS,
} from './positionReviewStateMeta.mjs'
import { formatBeijingTimestamp } from '../tool/beijingTime.mjs'

const route = useRoute()
const router = useRouter()

const STATUS_API_VALUES = Object.freeze({
  COMPLIANT: 'PASS',
  ANOMALY: 'FAIL',
  UNVERIFIABLE: 'INSUFFICIENT_EVIDENCE',
  NOT_APPLICABLE: 'NOT_APPLICABLE',
})

const statusFilterOptions = POSITION_REVIEW_FILTER_OPTIONS
const filters = reactive({
  query: '',
  status: '',
})
const loading = reactive({
  summary: false,
  symbols: false,
  detail: false,
})
const loadErrors = reactive({
  summary: '',
  symbols: '',
  detail: '',
})
const summary = ref(normalizePositionReviewSummary({}))
const symbolResult = ref(normalizePositionReviewSymbolRows({ rows: [], total: 0, page: 1, size: 100 }))
const selectedSymbol = ref('')
const selectedDetail = ref(null)
const symbolSectionRef = ref(null)
const activeReview = ref(null)
const activeExecution = ref(null)
const activeFixedEvent = ref(null)
const fixedEventConditions = ref(null)
const fixedEventLoading = ref(false)
const ledgerCollapse = ref(['ledger-executions', 'ledger-reviews'])
const reviewTableRef = ref(null)

let summaryRequestId = 0
let symbolRequestId = 0
let detailRequestId = 0

const summaryKpis = computed(() => buildPositionReviewSummaryKpis(summary.value))
const detailKpis = computed(() => buildPositionReviewDetailKpis(selectedDetail.value || {}))
const summaryDataQualityTitle = computed(() => (
  [
    `source=${summary.value.dataQuality.canonicalTradeSource}`,
    ...summary.value.dataQuality.warningDetails.map((item) => (
      item.code
        ? `${item.code}${item.message ? `: ${item.message}` : ''}`
        : item.text
    )),
  ].filter(Boolean).join('\n')
))
const selectedOutsideCatalog = computed(() => Boolean(
  selectedSymbol.value &&
  !loading.symbols &&
  !symbolResult.value.rows.some((item) => item.symbol === selectedSymbol.value),
))
const activeLoadErrors = computed(() => (
  [
    { scope: 'summary', message: loadErrors.summary },
    { scope: 'symbols', message: loadErrors.symbols },
    { scope: 'detail', message: loadErrors.detail },
  ].filter((item) => item.message)
))
const activeDataQualityWarnings = computed(() => {
  const warnings = [
    ...(summary.value?.dataQuality?.warnings || []),
    ...(selectedDetail.value?.dataQuality?.warnings || []),
  ]
  return [...new Set(warnings.filter(Boolean))]
})
const drawerTitle = computed(() => {
  if (activeFixedEvent.value) {
    const side = activeFixedEvent.value.side === 'buy' ? '买入' : '卖出'
    return `固定订单证据 · ${side} ${activeFixedEvent.value.event_id || ''}`
  }
  if (activeReview.value) {
    return `${activeReview.value.sideLabel}请求复盘 · ${activeReview.value.timeLabel}`
  }
  if (activeExecution.value) {
    return `真实成交详情 · ${activeExecution.value.timeLabel}`
  }
  return '持仓复盘证据详情'
})
const activeReviewIdentityRows = computed(() => {
  if (!activeReview.value) return []
  return [
    { label: 'review_id', value: activeReview.value.reviewId },
    { label: 'trace_id', value: activeReview.value.traceId },
    { label: 'intent_id', value: activeReview.value.intentId },
    { label: 'request_id', value: activeReview.value.requestId },
    { label: 'internal_order_id', value: activeReview.value.internalOrderId },
  ].filter((item) => item.value)
})
const activeExecutionIdentityRows = computed(() => {
  if (!activeExecution.value) return []
  return [
    { label: 'execution_id', value: activeExecution.value.executionId },
    { label: 'broker_trade_id', value: activeExecution.value.brokerTradeId },
    { label: 'broker_order_id', value: activeExecution.value.brokerOrderId },
    { label: 'request_id', value: activeExecution.value.requestId },
    { label: 'internal_order_id', value: activeExecution.value.internalOrderId },
    { label: 'execution_fill_id', value: activeExecution.value.executionFillId },
    { label: 'trade_fact_id', value: activeExecution.value.tradeFactId },
    { label: 'association_method', value: activeExecution.value.associationMethod },
    { label: 'account_partition', value: activeExecution.value.accountPartition },
    { label: 'source', value: activeExecution.value.source },
  ].filter((item) => item.value)
})
const associatedReview = computed(() => {
  const requestId = activeExecution.value?.requestId
  if (!requestId) return null
  return selectedDetail.value?.reviews?.find((item) => item.requestId === requestId) || null
})
const fixedEventNormalized = computed(() => (
  normalizeConditions(fixedEventConditions.value || {})
))

const formatInteger = (value) => formatPositionReviewInteger(value)
const formatPrice = (value) => formatPositionReviewPrice(value)
const formatTimestamp = (value) => formatBeijingTimestamp(value)
const formatSignedInteger = (value) => formatPositionReviewSignedInteger(value)
const isFiniteNonZero = (value) => isPositionReviewFiniteNonZero(value)
const prettyJson = (value) => JSON.stringify(value ?? {}, null, 2)
const confidenceVariant = (value) => {
  const text = String(value || '').toUpperCase()
  if (text === 'HIGH') return 'success'
  if (text === 'MEDIUM') return 'warning'
  return 'muted'
}
const confidenceLabel = (value) => ({
  HIGH: '高',
  MEDIUM: '中',
  LOW: '低',
}[String(value || '').toUpperCase()] || '未知')

const errorMessage = (fallback, error) => {
  const detail = String(
    error?.response?.data?.error ||
    error?.response?.data?.detail ||
    error?.message ||
    '',
  ).trim()
  return detail ? `${fallback}：${detail}` : fallback
}

const drillToSymbol = (symbol) => {
  const normalized = String(symbol || '').trim()
  if (!normalized) return
  selectSymbol(normalized)
  nextTick(() => {
    symbolSectionRef.value?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  })
}

const openFixedEvent = async (event) => {
  const normalized = String(event?.event_id || '').trim()
  if (!normalized) return
  activeReview.value = null
  activeExecution.value = null
  activeFixedEvent.value = event
  fixedEventConditions.value = null
  fixedEventLoading.value = true
  try {
    const response = await positionReviewApi.getEventConditions(normalized)
    fixedEventConditions.value = response || null
  } catch (error) {
    fixedEventConditions.value = null
  } finally {
    fixedEventLoading.value = false
  }
}

const closeFixedEvent = () => {
  activeFixedEvent.value = null
  fixedEventConditions.value = null
}

const closeEvidence = () => {
  activeReview.value = null
  activeExecution.value = null
  activeFixedEvent.value = null
  fixedEventConditions.value = null
}

const buildSymbolParams = () => ({
  page: symbolResult.value.page || 1,
  size: symbolResult.value.size || 100,
  query: filters.query.trim(),
  verdict: filters.status ? STATUS_API_VALUES[filters.status] || filters.status : '',
})

const syncRouteQuery = () => {
  const nextQuery = {
    ...route.query,
    symbol: selectedSymbol.value || undefined,
    status: filters.status || undefined,
    q: filters.query.trim() || undefined,
  }
  router.replace({ query: nextQuery }).catch(() => {})
}

const loadSummary = async ({ refresh = false } = {}) => {
  const requestId = ++summaryRequestId
  loading.summary = true
  loadErrors.summary = ''
  try {
    const response = await positionReviewApi.getSummary({
      refresh: refresh ? 1 : undefined,
    })
    if (requestId !== summaryRequestId) return
    summary.value = normalizePositionReviewSummary(response)
    loadErrors.summary = ''
  } catch (error) {
    if (requestId !== summaryRequestId) return
    loadErrors.summary = errorMessage('加载全局复盘摘要失败', error)
    summary.value = normalizePositionReviewSummary({})
  } finally {
    if (requestId === summaryRequestId) loading.summary = false
  }
}

const loadSymbolDetail = async (symbol) => {
  const normalizedSymbol = String(symbol || '').trim()
  const requestId = ++detailRequestId
  if (!normalizedSymbol) {
    selectedDetail.value = null
    loading.detail = false
    return
  }
  loading.detail = true
  loadErrors.detail = ''
  try {
    const response = await positionReviewApi.getSymbolReview(normalizedSymbol)
    if (requestId !== detailRequestId) return
    selectedDetail.value = normalizePositionReviewDetail(response)
    loadErrors.detail = ''
  } catch (error) {
    if (requestId !== detailRequestId) return
    loadErrors.detail = errorMessage(`加载 ${normalizedSymbol} 复盘详情失败`, error)
    selectedDetail.value = null
  } finally {
    if (requestId === detailRequestId) loading.detail = false
  }
}

const loadSymbols = async ({ forceDetail = false } = {}) => {
  const requestId = ++symbolRequestId
  loading.symbols = true
  loadErrors.symbols = ''
  try {
    const response = await positionReviewApi.listSymbols(buildSymbolParams())
    if (requestId !== symbolRequestId) return
    symbolResult.value = normalizePositionReviewSymbolRows(response)
    loadErrors.symbols = ''

    const routeSymbol = String(route.query.symbol || '').trim()
    const nextSymbol = resolvePositionReviewSelectedSymbol({
      selectedSymbol: selectedSymbol.value,
      routeSymbol,
      rows: symbolResult.value.rows,
    })

    if (forceDetail || nextSymbol !== selectedSymbol.value || !selectedDetail.value) {
      selectedSymbol.value = nextSymbol
      await loadSymbolDetail(nextSymbol)
    }
  } catch (error) {
    if (requestId !== symbolRequestId) return
    loadErrors.symbols = errorMessage('加载历史交易标的失败', error)
  } finally {
    if (requestId === symbolRequestId) loading.symbols = false
  }
}

const refreshData = async () => {
  await runPositionReviewRefresh({
    loadSummary,
    loadSymbols: () => loadSymbols({ forceDetail: true }),
  })
  syncRouteQuery()
}

const loadInitialData = async () => {
  await loadSummary()
  await loadSymbols({ forceDetail: true })
  syncRouteQuery()
}

const selectSymbol = async (symbol) => {
  const normalizedSymbol = String(symbol || '').trim()
  if (!normalizedSymbol || normalizedSymbol === selectedSymbol.value) return
  selectedSymbol.value = normalizedSymbol
  activeReview.value = null
  activeExecution.value = null
  activeFixedEvent.value = null
  fixedEventConditions.value = null
  syncRouteQuery()
  await loadSymbolDetail(normalizedSymbol)
}

const applyCatalogFilters = async () => {
  symbolResult.value = {
    ...symbolResult.value,
    page: 1,
  }
  await runPositionReviewCatalogFilter({
    loadSymbols,
  })
  syncRouteQuery()
}

const resetFilters = async () => {
  filters.query = ''
  filters.status = ''
  await applyCatalogFilters()
}

const changeSymbolPage = async (page) => {
  symbolResult.value = {
    ...symbolResult.value,
    page: Number(page || 1),
  }
  await loadSymbols()
  syncRouteQuery()
}

const openReviewDrawer = (row) => {
  if (!row) return
  activeExecution.value = null
  activeFixedEvent.value = null
  fixedEventConditions.value = null
  activeReview.value = row
  reviewTableRef.value?.setCurrentRow?.(row)
}

const openExecutionDrawer = (row) => {
  if (!row) return
  activeReview.value = null
  activeFixedEvent.value = null
  fixedEventConditions.value = null
  activeExecution.value = row
}

const openAssociatedReview = async () => {
  const review = associatedReview.value
  if (!review) return
  await nextTick()
  openReviewDrawer(review)
}

const reviewRowClassName = ({ row }) => (
  row?.status === 'ANOMALY' ? 'position-review-row--anomaly' : ''
)
const executionRowClassName = ({ row }) => (
  row?.isAssociated === false ? 'position-review-row--unassociated' : ''
)

const retryLoadError = async (scope) => {
  if (scope === 'summary') {
    await loadSummary()
    return
  }
  if (scope === 'symbols') {
    await loadSymbols()
    return
  }
  if (scope === 'detail') {
    await loadSymbolDetail(selectedSymbol.value)
    return
  }
}

onMounted(async () => {
  filters.query = String(route.query.q || '').trim()
  const routeStatus = String(route.query.status || '').trim()
  filters.status = routeStatus ? normalizePositionReviewStatus(routeStatus) : ''
  selectedSymbol.value = String(route.query.symbol || '').trim()
  await loadInitialData()
})
</script>

<style scoped>
.position-review-page {
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
}

.position-review-body {
  gap: var(--fq-space-3);
  overflow: hidden;
  padding: var(--fq-space-3) var(--fq-space-4) var(--fq-space-4);
}

.position-review-toolbar {
  flex: 0 0 auto;
}

.position-review-toolbar__header {
  align-items: flex-start;
}

.position-review-filter-actions {
  flex: 1 1 760px;
}

.position-review-search {
  width: 176px;
}

.position-review-status-filter {
  width: 154px;
}

.position-review-layout {
  display: flex;
  flex: 1 1 auto;
  gap: var(--fq-space-3);
  min-height: 0;
  min-width: 0;
  overflow: hidden;
}

.position-review-main {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: var(--fq-space-3);
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  padding-right: 3px;
  scrollbar-gutter: stable;
}

.position-review-section {
  display: flex;
  flex: 0 0 auto;
  flex-direction: column;
  gap: var(--fq-space-3);
  min-width: 0;
}

.position-review-section__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 2px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.position-review-section__head .workbench-panel__title {
  flex: 0 0 auto;
}

.position-review-section__head p {
  margin: 0;
  color: #9ca3af;
  font-size: 12px;
  line-height: 1.55;
}

.position-review-symbol-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  gap: var(--fq-space-3);
  align-items: stretch;
  min-width: 0;
  min-height: 0;
}

.position-review-error-stack {
  display: flex;
  flex: 0 0 auto;
  flex-direction: column;
  gap: 8px;
}

.position-review-quality-alert {
  flex: 0 0 auto;
}

.position-review-error-row {
  display: flex;
  align-items: stretch;
  gap: 8px;
}

.position-review-error-row .workbench-alert {
  flex: 1 1 auto;
  margin: 0;
}

.position-review-symbol-panel {
  flex: 0 0 280px;
  min-width: 0;
  overflow: hidden;
}

.position-review-symbol-list {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  overflow-y: auto;
  padding-right: 3px;
  scrollbar-gutter: stable;
}

.position-review-symbol-row {
  display: flex;
  flex: 0 0 auto;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--fq-border-soft);
  border-radius: var(--fq-radius-md);
  background: var(--fq-panel-bg);
  color: var(--fq-text-primary);
  text-align: left;
  cursor: pointer;
}

.position-review-symbol-row:hover,
.position-review-symbol-row.active {
  border-color: #93c5fd;
  background: #eff6ff;
}

.position-review-symbol-row:focus-visible {
  outline: 2px solid var(--fq-status-primary);
  outline-offset: 1px;
}

.position-review-symbol-row__head,
.position-review-symbol-row__metrics,
.position-review-symbol-row__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.position-review-symbol-row__identity {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.position-review-symbol-row__identity strong {
  overflow: hidden;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.position-review-symbol-row__identity span,
.position-review-symbol-row__metrics,
.position-review-symbol-row__foot {
  color: var(--fq-text-muted);
  font-size: 11px;
}

.position-review-symbol-row__metrics {
  justify-content: flex-start;
  flex-wrap: wrap;
}

.position-review-symbol-row__foot span:last-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.position-review-inline-chip {
  flex: 0 0 auto;
  padding: 2px 7px;
  font-size: 11px;
}

.position-review-symbol-empty {
  flex: 1 1 auto;
}

.position-review-symbol-pagination {
  display: flex;
  flex: 0 0 auto;
  justify-content: center;
}

.position-review-center {
  display: flex;
  flex-direction: column;
  gap: var(--fq-space-3);
  min-height: 0;
  min-width: 0;
  overflow: hidden;
}

.position-review-subject-panel {
  flex: 0 0 auto;
  padding-top: var(--fq-space-2);
  padding-bottom: var(--fq-space-2);
}

.position-review-scope-meta {
  justify-content: flex-end;
  text-align: right;
}

.position-review-inline-alert {
  margin: 10px 0;
}

.position-review-timeline-panel {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.position-review-timeline-chart {
  flex: 1 1 auto;
  min-height: 0;
}

.position-review-ledger-collapse {
  flex: 0 0 auto;
  max-height: 34%;
  overflow: auto;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
}

.position-review-ledger-collapse :deep(.el-collapse-item__header) {
  background: transparent;
  color: #e5e7eb;
  font-weight: 600;
  padding-left: 12px;
}

.position-review-ledger-collapse :deep(.el-collapse-item__content) {
  padding: 0;
  background: transparent;
}

.position-review-ledger-panel {
  flex: 0 0 auto;
  height: 100%;
  min-height: 260px;
  overflow: hidden;
}

.position-review-table-wrap {
  min-height: 220px;
}

.position-review-evidence-panel {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.position-review-evidence-panel__header {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.position-review-evidence-panel__title {
  overflow: hidden;
  font-size: var(--fq-font-panel-title);
  font-weight: 600;
  color: var(--fq-text-primary);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.position-review-evidence-panel__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding-right: 3px;
  scrollbar-gutter: stable;
}

.position-review-evidence-panel__empty {
  flex: 1 1 auto;
}

.position-review-ledger-counts,
.position-review-drawer__section-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.position-review-drawer__section-head {
  justify-content: space-between;
}

.position-review-drawer__section-head h3 {
  margin-bottom: 0;
}

.position-review-ellipsis {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.position-review-side {
  font-weight: 600;
}

.position-review-side--buy {
  color: var(--fq-status-danger);
}

.position-review-side--sell {
  color: var(--fq-status-success);
}

.position-review-delta--anomaly {
  color: var(--fq-status-danger);
  font-weight: 700;
}

.position-review-reason {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.position-review-row--anomaly td.el-table__cell) {
  background: #fff7f7;
}

:deep(.position-review-row--unassociated td.el-table__cell) {
  background: #fff1f0;
}

.position-review-drawer__summary,
.position-review-reason-codes {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.position-review-drawer__alert {
  margin-top: 14px;
  margin-bottom: 14px;
}

.position-review-drawer__section {
  margin-top: 20px;
}

.position-review-drawer__section h3 {
  margin: 0 0 8px;
  color: var(--fq-text-primary);
  font-size: 14px;
}

.position-review-drawer__section p {
  margin: 0;
  color: var(--fq-text-secondary);
  font-size: 13px;
  line-height: 1.65;
}

.position-review-json {
  max-height: 260px;
  margin: 0;
  overflow: auto;
  padding: 12px;
  border: 1px solid var(--fq-border-soft);
  border-radius: var(--fq-radius-md);
  background: var(--fq-panel-bg-muted);
  color: var(--fq-text-secondary);
  font: 12px/1.55 Consolas, Monaco, 'Courier New', monospace;
  white-space: pre-wrap;
  word-break: break-all;
}

.position-review-break-all {
  word-break: break-all;
}

@media (max-width: 1280px) {
  .position-review-symbol-grid {
    grid-template-columns: minmax(0, 1fr) 340px;
  }

  .position-review-symbol-panel {
    flex-basis: 250px;
  }
}

@media (max-width: 960px) {
  .position-review-page {
    overflow: hidden;
  }

  .position-review-body {
    overflow-y: auto;
  }

  .position-review-filter-actions {
    flex: 0 0 auto;
    justify-content: flex-start;
    width: 100%;
  }

  .position-review-search,
  .position-review-status-filter {
    width: 100%;
  }

  .position-review-layout {
    display: flex;
    flex: 0 0 auto;
    flex-direction: column;
    overflow: visible;
  }

  .position-review-symbol-panel {
    flex: 0 0 auto;
    min-height: 360px;
    max-height: 52vh;
  }

  .position-review-main {
    overflow: visible;
  }

  .position-review-symbol-grid {
    display: flex;
    flex-direction: column;
    overflow: visible;
  }

  .position-review-center {
    overflow: visible;
  }

  .position-review-timeline-panel {
    min-height: 480px;
  }

  .position-review-timeline-chart {
    min-height: 400px;
  }

  .position-review-ledger-panel {
    height: min(520px, 76vh);
  }

  .position-review-evidence-panel {
    min-height: 420px;
    max-height: 60vh;
  }
}

@media (max-width: 760px) {
  :global(.position-review-drawer) {
    width: 100% !important;
  }

  .position-review-ledger-counts {
    align-items: flex-end;
    flex-direction: column;
  }
}
</style>
