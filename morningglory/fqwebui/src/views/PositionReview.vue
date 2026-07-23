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

      <div class="position-review-main-grid">
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

        <div class="position-review-detail-stack">
          <div class="position-review-overview-grid">
            <WorkbenchPanel class="position-review-overview-panel">
              <div class="workbench-panel__header">
                <div class="workbench-title-group">
                  <div class="workbench-panel__title">全局复盘结论</div>
                  <p class="workbench-panel__desc">
                    “证据不足”不会被计入符合率，也不会被默认为符合。
                  </p>
                </div>
              </div>
              <PositionReviewChart
                class="position-review-overview-chart"
                :option="statusDonutOption"
                :loading="loading.summary"
                :empty="summaryStatusTotal === 0"
                empty-text="暂无可复盘请求"
              />
            </WorkbenchPanel>

            <WorkbenchPanel class="position-review-overview-panel">
              <div class="workbench-panel__header">
                <div class="workbench-title-group">
                  <div class="workbench-panel__title">月度成交额</div>
                  <p class="workbench-panel__desc">
                    {{ selectedDetail?.displayName || '选择标的后展示' }}，按成交日聚合。
                  </p>
                </div>
              </div>
              <PositionReviewChart
                class="position-review-overview-chart"
                :option="monthlyTradeOption"
                :loading="loading.detail"
                :empty="!selectedDetail?.monthlyActivity?.length"
                empty-text="选择有成交记录的标的后展示"
              />
            </WorkbenchPanel>
          </div>

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
                <div class="workbench-panel__title">价格 · 策略应有量 · 实际成交量 · 持仓联动</div>
                <p class="workbench-panel__desc">
                  同一时间轴查看信号/委托价、策略阈值、成交点、数量偏差与仓位重建；持仓线从“期初仓（推导）”起点开始。
                </p>
              </div>
            </div>
            <PositionReviewChart
              class="position-review-timeline-chart"
              :option="timelineOption"
              :loading="loading.detail"
              :empty="!hasTimelineData"
              empty-text="当前标的暂无可绘制的交易时间轴"
              @chart-click="handleChartClick"
            />
          </WorkbenchPanel>

          <WorkbenchLedgerPanel
            v-if="selectedDetail"
            class="position-review-ledger-panel"
          >
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">成交明细（真实成交）</div>
                <p class="workbench-panel__desc">
                  完整展示 {{ selectedDetail.dataQuality.canonicalTradeSourceLabel }} 成交真值；关联状态仅描述证据链质量，不伪造策略结论。
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
                <el-empty description="当前标的没有真实成交记录" :image-size="72" />
              </div>
            </div>
          </WorkbenchLedgerPanel>

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
        </div>
      </div>
    </div>

    <el-drawer
      v-model="drawerVisible"
      class="position-review-drawer"
      :title="drawerTitle"
      size="720px"
      destroy-on-close
    >
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
    </el-drawer>
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
import { positionReviewApi } from '../api/positionReviewApi.js'
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
  buildPositionReviewMonthlyTradeOption,
  buildPositionReviewStatusDonutOption,
  buildPositionReviewTimelineOption,
} from './positionReviewCharts.mjs'
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
const activeReview = ref(null)
const activeExecution = ref(null)
const drawerVisible = ref(false)
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
const summaryStatusTotal = computed(() => (
  summary.value.statusDistribution.reduce((sum, item) => sum + Number(item.value || 0), 0)
))
const statusDonutOption = computed(() => (
  buildPositionReviewStatusDonutOption(summary.value.statusDistribution)
))
const monthlyTradeOption = computed(() => (
  buildPositionReviewMonthlyTradeOption(selectedDetail.value?.monthlyActivity || [])
))
const timelineOption = computed(() => (
  buildPositionReviewTimelineOption(selectedDetail.value || {})
))
const hasTimelineData = computed(() => Boolean(
  selectedDetail.value?.reviews?.length ||
  selectedDetail.value?.pricePoints?.length ||
  selectedDetail.value?.positionPoints?.length,
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
  drawerVisible.value = false
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
  activeReview.value = row
  drawerVisible.value = true
  reviewTableRef.value?.setCurrentRow?.(row)
}

const openExecutionDrawer = (row) => {
  if (!row) return
  activeReview.value = null
  activeExecution.value = row
  drawerVisible.value = true
}

const openAssociatedReview = async () => {
  const review = associatedReview.value
  if (!review) return
  await nextTick()
  openReviewDrawer(review)
}

const handleChartClick = async (params) => {
  const eventId = String(
    params?.data?.eventId ||
    params?.data?.requestId ||
    '',
  ).trim()
  if (!eventId || !selectedDetail.value) return
  const row = selectedDetail.value.reviews.find((item) => (
    item.id === eventId ||
    item.reviewId === eventId ||
    item.requestId === eventId
  ))
  if (!row) return
  await nextTick()
  openReviewDrawer(row)
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

.position-review-main-grid {
  display: grid;
  flex: 1 1 auto;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: var(--fq-space-3);
  min-height: 0;
  min-width: 0;
  overflow: hidden;
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

.position-review-detail-stack {
  display: flex;
  flex-direction: column;
  gap: var(--fq-space-3);
  min-height: 0;
  min-width: 0;
  overflow-y: auto;
  padding-right: 3px;
  scrollbar-gutter: stable;
}

.position-review-overview-grid {
  display: grid;
  grid-template-columns: minmax(280px, 0.72fr) minmax(420px, 1.28fr);
  gap: var(--fq-space-3);
}

.position-review-overview-panel {
  min-height: 330px;
}

.position-review-overview-chart {
  flex: 1 1 auto;
  min-height: 240px;
}

.position-review-subject-panel {
  flex: 0 0 auto;
}

.position-review-scope-meta {
  justify-content: flex-end;
  text-align: right;
}

.position-review-inline-alert {
  margin: 10px 0;
}

.position-review-timeline-panel {
  flex: 0 0 auto;
  min-height: 620px;
}

.position-review-timeline-chart {
  flex: 1 1 auto;
  min-height: 520px;
}

.position-review-ledger-panel {
  flex: 0 0 auto;
  height: min(680px, 68vh);
  min-height: 420px;
  overflow: hidden;
}

.position-review-table-wrap {
  min-height: 320px;
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
  .position-review-main-grid {
    grid-template-columns: 280px minmax(0, 1fr);
  }

  .position-review-overview-grid {
    grid-template-columns: 1fr;
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

  .position-review-main-grid {
    display: flex;
    flex: 0 0 auto;
    flex-direction: column;
    overflow: visible;
  }

  .position-review-symbol-panel {
    min-height: 360px;
    max-height: 52vh;
  }

  .position-review-detail-stack {
    overflow: visible;
  }

  .position-review-overview-grid {
    grid-template-columns: 1fr;
  }

  .position-review-timeline-panel {
    min-height: 560px;
  }

  .position-review-timeline-chart {
    min-height: 470px;
  }

  .position-review-ledger-panel {
    height: min(620px, 76vh);
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
