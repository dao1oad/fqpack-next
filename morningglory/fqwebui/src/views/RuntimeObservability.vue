<template>
  <div class="workbench-page runtime-page">
    <MyHeader />
    <div class="workbench-body runtime-shell">
      <section class="workbench-toolbar runtime-section runtime-section--workbench">
        <div class="workbench-toolbar__header runtime-title-row">
          <div class="runtime-title-main">
            <div class="workbench-title-group">
              <div class="workbench-page-title">运行观测</div>
              <div class="workbench-page-meta">
                <span>主视图拆为全局 Trace 与组件 Event，分别回答“链路发生了什么”和“组件最近有没有工作”。</span>
              </div>
            </div>
            <div class="runtime-title-actions">
              <el-date-picker
                v-model="timeRange"
                type="datetimerange"
                class="runtime-time-range"
                value-format="YYYY-MM-DDTHH:mm:ssZ"
                range-separator="至"
                start-placeholder="开始时间"
                end-placeholder="结束时间"
                :clearable="false"
                @change="handleTimeRangeChange"
              />
              <el-radio-group v-model="activeView" size="small" class="runtime-view-switch">
                <el-radio-button label="traces">全局 Trace</el-radio-button>
                <el-radio-button label="events">组件 Event</el-radio-button>
              </el-radio-group>
              <el-switch
                v-model="onlyIssues"
                inline-prompt
                active-text="仅异常"
                inactive-text="全部"
              />
              <div v-if="activeView === 'traces'" class="runtime-trace-kind-actions">
                <el-button
                  v-for="option in traceKindOptions"
                  :key="option.value"
                  size="small"
                  :type="selectedTraceKind === option.value ? 'primary' : 'default'"
                  :plain="selectedTraceKind !== option.value"
                  @click="handleTraceKindClick(option.value)"
                >
                  {{ option.label }}
                </el-button>
              </div>
              <el-button @click="openAdvancedFilter">高级筛选</el-button>
              <el-button type="primary" :loading="loading.overview" @click="loadOverview">刷新</el-button>
            </div>
          </div>
        </div>

        <el-alert
          v-if="pageError"
          class="workbench-alert"
          type="error"
          :title="pageError"
          show-icon
          :closable="false"
        />

        <div class="workbench-summary-row runtime-summary-row">
          <span class="workbench-summary-chip">
            可见 Trace <strong>{{ traceListSummary.trace_count }}</strong>
          </span>
          <button
            type="button"
            class="workbench-summary-chip workbench-summary-chip--warning runtime-summary-chip-button"
            :class="{ 'is-disabled': traceListSummary.issue_trace_count === 0 }"
            @click="handleSummaryJump('issue-traces')"
          >
            异常链路 <strong>{{ traceListSummary.issue_trace_count }}</strong>
          </button>
          <button
            type="button"
            class="workbench-summary-chip workbench-summary-chip--danger runtime-summary-chip-button"
            :class="{ 'is-disabled': traceListSummary.issue_step_count === 0 }"
            @click="handleSummaryJump('issue-steps')"
          >
            异常节点 <strong>{{ traceListSummary.issue_step_count }}</strong>
          </button>
          <span v-if="timeRangeDisplayLabel" class="workbench-summary-chip workbench-summary-chip--muted">
            展示范围 <strong>{{ timeRangeDisplayLabel }}</strong>
          </span>
          <div class="runtime-filter-chips">
            <button
              v-for="chip in filterChips"
              :key="chip.key"
              type="button"
              class="runtime-filter-chip"
              @click="clearFilterChip(chip)"
            >
              {{ chip.label }}
            </button>
            <span
              v-if="filterChips.length === 0"
              class="workbench-summary-chip workbench-summary-chip--muted runtime-filter-empty"
            >
              当前无筛选
            </span>
          </div>
        </div>
      </section>

      <div class="runtime-browse-layout">
        <aside class="workbench-panel runtime-browser-panel runtime-browser-panel--components">
          <div class="runtime-home-head">
            <div>
              <h2>组件导航</h2>
              <p>保持和标的列表一致的卡片切换方式，直接按组件查看运行节点、心跳和异常概况。</p>
            </div>
            <span class="runtime-home-meta">核心组件 {{ componentSidebarItems.length }} 个</span>
          </div>

          <div class="component-symbol-list">
            <div
              v-for="item in componentSidebarItems"
              :key="item.component"
              class="component-symbol-card"
              :class="{ active: activeComponent === item.component }"
              @click="handleComponentFilter(item.component)"
            >
              <div class="component-symbol-card__head">
                <div>
                  <strong :title="item.component_label">{{ item.component_label }}</strong>
                  <span :title="item.component">{{ item.component }}</span>
                </div>
                <span class="runtime-inline-status" :class="statusClass(item.status)">
                  {{ item.status }}
                </span>
              </div>

              <div class="component-symbol-card__badges">
                <span class="workbench-summary-chip workbench-summary-chip--muted" :title="item.runtime_summary_title">
                  {{ item.runtime_summary_label || '-' }}
                </span>
                <span class="workbench-summary-chip workbench-summary-chip--muted">
                  Trace {{ item.trace_count }}
                </span>
                <button
                  type="button"
                  class="workbench-summary-chip workbench-summary-chip--warning component-symbol-card__action"
                  :class="{ 'is-disabled': item.issue_trace_count === 0 }"
                  @click.stop="handleComponentIssueTraceJump(item)"
                >
                  异常链路 {{ item.issue_trace_count }}
                </button>
                <button
                  type="button"
                  class="workbench-summary-chip workbench-summary-chip--danger component-symbol-card__action"
                  :class="{ 'is-disabled': item.issue_step_count === 0 }"
                  @click.stop="handleComponentIssueEventJump(item)"
                >
                  异常节点 {{ item.issue_step_count }}
                </button>
              </div>

              <div class="component-symbol-card__foot">
                <span>主心跳 {{ item.heartbeat_label }}</span>
                <span :title="item.runtime_summary_title">
                  {{ item.runtime_details[0]?.runtime_node || '-' }}
                </span>
              </div>
            </div>
          </div>
        </aside>

          <section class="workbench-panel runtime-browser-panel runtime-browser-panel--feed">
            <template v-if="activeView === 'traces'">
              <div class="runtime-home-head">
                <div>
                  <h2>全局 Trace</h2>
                  <p>主表直接展示链路类型、中文节点路径和断裂原因，并支持按类型重新加载最新 Trace。</p>
                </div>
                <div class="runtime-home-actions">
                  <span class="runtime-home-meta">当前显示 {{ traceLedgerRows.length }} 条</span>
                </div>
              </div>

              <article class="runtime-priority-banner" :class="{ 'is-empty': issuePriorityCards.length === 0 }">
                <span>异常优先</span>
                <button
                  v-if="issuePriorityCards.length"
                  type="button"
                  class="runtime-priority-link"
                  @click="handleIssueCardClick(issuePriorityCards[0])"
                >
                  {{ issuePriorityCards[0].headline }} · {{ issuePriorityCards[0].issue_summary }}
                </button>
                <span v-else>当前暂无异常 Trace</span>
              </article>

              <div v-if="traceLedgerRows.length" class="runtime-ledger runtime-trace-ledger">
                <div class="runtime-ledger__header runtime-trace-ledger__grid">
                  <span>最近时间</span>
                  <span>标的</span>
                  <span>链路类型</span>
                  <span>链路状态</span>
                  <span>节点路径</span>
                  <span>节点数</span>
                  <span>总耗时</span>
                  <span>断裂原因</span>
                </div>
                <button
                  v-for="row in traceLedgerRows"
                  :key="row.trace_key || row.trace_id"
                  type="button"
                  class="runtime-ledger__row runtime-trace-ledger__grid"
                  :class="{ active: isActiveTraceRow(row) }"
                  @click="handleRecentTraceClick(row)"
                >
                  <span class="runtime-ledger__cell runtime-ledger__cell--mono">{{ row.last_ts_label || '-' }}</span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--strong runtime-ledger__cell--truncate" :title="row.symbol_display">{{ row.symbol_display }}</span>
                  <span class="runtime-ledger__cell">{{ row.trace_kind_label }}</span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--status">
                    <span class="runtime-inline-status" :class="statusClass(row.trace_status)">
                      {{ row.trace_status_label }}
                    </span>
                  </span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--truncate runtime-ledger__cell--entry-exit" :title="row.entry_exit_label">{{ row.entry_exit_label }}</span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--number">{{ row.step_count }}</span>
                  <span class="runtime-ledger__cell">{{ row.duration_label }}</span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--truncate" :title="row.break_reason || '-'">{{ row.break_reason || '-' }}</span>
                </button>
              </div>
              <div v-if="traceNextCursor" class="runtime-load-more">
                <el-button plain :loading="loading.traces" @click="loadMoreTraces">加载更多 Trace</el-button>
              </div>
              <div v-else class="runtime-empty-panel">
                <strong>暂无最近 Trace</strong>
              </div>
            </template>

          <template v-else>
            <div class="runtime-home-head">
              <div>
                <h2>组件 Event</h2>
                <p>{{ activeComponent ? `${activeComponent} 最近运行事件与心跳` : '先从左侧选择一个组件查看 Event' }}</p>
              </div>
              <div class="runtime-home-actions">
                <span class="runtime-home-meta">当前显示 {{ eventLedgerRows.length }} 条</span>
              </div>
            </div>

            <div v-if="eventLedgerRows.length" class="runtime-ledger runtime-event-ledger">
              <div class="runtime-ledger__header runtime-event-ledger__grid">
                <span>运行时间</span>
                <span>运行节点</span>
                <span>组件</span>
                <span>节点</span>
                <span>状态</span>
                <span>标的</span>
                <span>摘要</span>
                <span>指标</span>
              </div>
              <button
                v-for="(row, rowIndex) in eventLedgerRows"
                :key="row.event_key"
                type="button"
                class="runtime-ledger__row runtime-event-ledger__grid"
                :class="{ active: isActiveEventRow(componentEventFeed[rowIndex]) }"
                @click="handleEventClick(componentEventFeed[rowIndex])"
              >
                <span class="runtime-ledger__cell runtime-ledger__cell--mono">{{ row.ts_label || '-' }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--mono runtime-ledger__cell--truncate" :title="row.runtime_node_label">{{ row.runtime_node_label }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--truncate" :title="row.component_label">{{ row.component_label }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--truncate" :title="row.node_label">{{ row.node_label }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--status">
                  <span class="runtime-inline-status" :class="statusClass(row.status)">
                    {{ row.status }}
                  </span>
                </span>
                <span class="runtime-ledger__cell runtime-ledger__cell--strong runtime-ledger__cell--truncate" :title="row.symbol_display">{{ row.symbol_display }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--truncate" :title="row.summary || '-'">{{ row.summary || '-' }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--truncate" :title="row.metrics_summary || '-'">{{ row.metrics_summary || '-' }}</span>
              </button>
            </div>
            <div v-if="eventNextCursor" class="runtime-load-more">
              <el-button plain :loading="loading.events" @click="loadMoreEvents">加载更多 Event</el-button>
            </div>
            <div v-else class="runtime-empty-panel">
              <strong>{{ activeComponent ? `${activeComponent} 暂无最近事件` : '先选择组件查看 Event' }}</strong>
            </div>
          </template>
          </section>

          <section class="runtime-browser-panel runtime-browser-panel--detail">
            <div v-if="activeView === 'traces'" class="trace-detail trace-detail--embedded">
          <div class="trace-detail-head">
            <div>
              <strong>{{ selectedTraceDetail.trace_id || selectedTrace?.trace_key || '选择一条 Trace' }}</strong>
            </div>
            <div class="trace-detail-actions">
              <el-button :disabled="!selectedStep" @click="openRawBrowser">原始数据</el-button>
            </div>
          </div>
            <div v-if="selectedTrace" class="trace-detail-body trace-detail-body--stacked">
              <div class="trace-detail-tabs-wrap workspace-tabs-wrap">
                <el-tabs v-model="activeTraceDetailTab" class="workspace-tabs trace-detail-tabs">
                  <el-tab-pane name="steps">
                    <template #label>
                      <div class="workspace-tab-label">
                        <span>步骤</span>
                        <span class="tab-meta">{{ traceStepLedgerRows.length }}</span>
                      </div>
                    </template>
                  </el-tab-pane>
                  <el-tab-pane name="summary">
                    <template #label>
                      <div class="workspace-tab-label">
                        <span>摘要</span>
                        <span class="tab-meta">{{ guardianTrace ? 3 : 2 }}</span>
                      </div>
                    </template>
                  </el-tab-pane>
                  <el-tab-pane name="raw">
                    <template #label>
                      <div class="workspace-tab-label">
                        <span>原始数据</span>
                        <span class="tab-meta">{{ embeddedRawLedgerRows.length }}</span>
                      </div>
                    </template>
                  </el-tab-pane>
                </el-tabs>

              <section v-show="activeTraceDetailTab === 'summary'" class="runtime-detail-panel runtime-detail-panel--summary runtime-detail-panel--fill">
                <div class="detail-pane-grid">
                  <section class="detail-ledger-section">
                    <div class="detail-ledger-section__title">链路摘要</div>
                    <table class="detail-kv-table trace-summary-ledger">
                      <tbody>
                        <tr v-for="row in traceSummaryRows" :key="`trace-summary-${row.key}`">
                          <th>{{ row.label }}</th>
                          <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </section>

                  <section class="detail-ledger-section">
                    <div class="detail-ledger-section__title">异常与慢点</div>
                    <table class="detail-kv-table trace-summary-ledger">
                      <tbody>
                        <tr v-for="row in traceIssueRows" :key="`trace-issue-${row.key}`">
                          <th>{{ row.label }}</th>
                          <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </section>

                  <section v-if="guardianTrace" class="detail-ledger-section detail-ledger-section--full">
                    <div class="detail-ledger-section__title">Guardian 结论</div>
                    <div class="detail-pane-grid detail-pane-grid--nested">
                      <table class="detail-kv-table trace-summary-ledger">
                        <tbody>
                          <tr v-for="row in guardianTraceRows" :key="`guardian-summary-${row.key}`">
                            <th>{{ row.label }}</th>
                            <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                          </tr>
                        </tbody>
                      </table>
                      <table v-if="guardianSignalRows.length" class="detail-kv-table trace-summary-ledger">
                        <tbody>
                          <tr v-for="row in guardianSignalRows" :key="`guardian-signal-${row.key}`">
                            <th>{{ row.label }}</th>
                            <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                    <table v-if="guardianDecisionContextRows.length" class="detail-kv-table trace-summary-ledger detail-kv-table--full">
                      <tbody>
                        <tr v-for="row in guardianDecisionContextRows" :key="`guardian-context-${row.key}`">
                          <th>{{ row.label }}</th>
                          <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </section>
                </div>
              </section>

            <section v-show="activeTraceDetailTab === 'steps'" class="runtime-detail-panel runtime-detail-panel--steps">
              <div class="trace-ledger-toolbar">
                <div class="trace-ledger-toolbar__meta">
                  <span>{{ onlyIssues ? '仅显示异常节点' : '显示全部节点' }}</span>
                  <span>可见 {{ traceStepLedgerRows.length }} / {{ selectedTraceDetail.step_count }}</span>
                </div>
                <div class="trace-ledger-toolbar__actions">
                  <el-button text size="small" :disabled="!firstIssueTraceStep" @click="handleTraceAnchorJump('first-issue')">首个异常</el-button>
                  <el-button text size="small" :disabled="!previousIssueTraceStep" @click="handleTraceAnchorJump('previous-issue')">上一个异常</el-button>
                  <el-button text size="small" :disabled="!nextIssueTraceStep" @click="handleTraceAnchorJump('next-issue')">下一个异常</el-button>
                  <el-button text size="small" :disabled="!slowestTraceStep" @click="handleTraceAnchorJump('slowest-step')">最慢节点</el-button>
                </div>
              </div>

              <div v-if="traceStepLedgerRows.length" class="trace-step-ledger">
                <div class="trace-step-ledger__header trace-step-ledger__grid">
                  <span>#</span>
                  <span>时间</span>
                  <span>耗时</span>
                  <span>节点</span>
                  <span>状态</span>
                  <span>分支</span>
                  <span>条件</span>
                  <span>原因</span>
                  <span>结果</span>
                  <span>上下文</span>
                  <span>错误</span>
                </div>
                <button
                  v-for="(row, rowIndex) in traceStepLedgerRows"
                  :key="row.step_key"
                  :ref="(el) => setStepRowRef(el, row.step_key)"
                  type="button"
                  class="trace-step-ledger__row trace-step-ledger__grid"
                  :class="[statusClass(row.status), { active: isActiveStep(filteredSteps[rowIndex]), 'is-issue': row.is_issue }]"
                  @click="handleStepSelect(filteredSteps[rowIndex])"
                >
                  <span class="runtime-ledger__cell runtime-ledger__cell--number">{{ row.index + 1 }}</span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--mono">{{ row.ts_label || '-' }}</span>
                  <span class="runtime-ledger__cell">{{ row.delta_label || '-' }}</span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--strong">{{ row.component_node }}</span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--status">
                    <span class="runtime-inline-status" :class="statusClass(row.status)">
                      {{ row.status }}
                    </span>
                  </span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--truncate">{{ row.branch || '-' }}</span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--truncate">{{ row.expr || '-' }}</span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--truncate">{{ row.reason || '-' }}</span>
                  <span class="runtime-ledger__cell">{{ row.outcome || '-' }}</span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--truncate">{{ row.context_summary || '-' }}</span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--truncate">{{ row.error_summary || '-' }}</span>
                </button>
              </div>
              <div v-if="traceStepsNextCursor" class="runtime-load-more runtime-load-more--detail">
                <el-button plain :loading="loading.traceSteps" @click="loadMoreTraceSteps">加载更早步骤</el-button>
              </div>
              <div v-else class="trace-empty">当前过滤条件下没有节点</div>

              <aside class="step-inspector">
                <template v-if="selectedStep">
                  <div class="step-inspector-head" :class="statusClass(selectedStep.status)">
                    <div>
                      <strong>{{ selectedStep.component }}.{{ selectedStep.node }}</strong>
                      <p>{{ selectedStep.ts_label || '-' }}</p>
                    </div>
                    <span class="trace-step-status">{{ selectedStep.status || 'info' }}</span>
                  </div>

                  <div class="step-inspector-summary">
                    <span>step #{{ selectedStep.index + 1 }}</span>
                    <span v-if="selectedStep.delta_from_prev_label">
                      delta {{ selectedStep.delta_from_prev_label }}
                    </span>
                    <span v-if="selectedStep.offset_ms !== null && selectedStep.offset_ms !== undefined">
                      offset {{ selectedStep.offset_ms }}ms
                    </span>
                    <span v-if="selectedStep.event_type">{{ selectedStep.event_type }}</span>
                  </div>

                  <div class="step-inspector-flags">
                    <span v-if="isFirstIssueStep(selectedStep)" class="inspector-tag">首个异常</span>
                    <span v-if="isSlowestStep(selectedStep)" class="inspector-tag">最长耗时节点</span>
                  </div>

                  <div class="detail-pane-grid detail-pane-grid--step">
                    <section class="detail-ledger-section">
                      <div class="detail-ledger-section__title">Step 摘要</div>

                      <table class="detail-kv-table">
                        <tbody>
                          <tr v-for="row in selectedStepOverviewRows" :key="`selected-step-overview-${row.key}`">
                            <th>{{ row.label }}</th>
                            <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                          </tr>
                        </tbody>
                      </table>
                    </section>

                    <section v-if="selectedStep?.guardian_step && selectedStepGuardianRows.length" class="detail-ledger-section">
                      <div class="detail-ledger-section__title">Guardian 判断</div>
                      <table class="detail-kv-table">
                        <tbody>
                          <tr v-for="row in selectedStepGuardianRows" :key="`selected-step-guardian-${row.key}`">
                            <th>{{ row.label }}</th>
                            <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                          </tr>
                        </tbody>
                      </table>
                    </section>

                    <section v-if="selectedStep?.guardian_step && selectedStepSignalRows.length" class="detail-ledger-section">
                      <div class="detail-ledger-section__title">Guardian 信号</div>
                      <table class="detail-kv-table">
                        <tbody>
                          <tr v-for="row in selectedStepSignalRows" :key="`selected-step-signal-${row.key}`">
                            <th>{{ row.label }}</th>
                            <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                          </tr>
                        </tbody>
                      </table>
                    </section>

                    <section v-if="selectedStepTagRows.length || selectedStepFieldRows.length" class="detail-ledger-section">
                      <div class="detail-ledger-section__title">分支与关联字段</div>
                      <table class="detail-kv-table">
                        <tbody>
                          <tr v-for="row in selectedStepTagRows" :key="`selected-step-tag-${row.key}`">
                            <th>{{ row.label }}</th>
                            <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                          </tr>
                          <tr v-for="row in selectedStepFieldRows" :key="`selected-step-field-${row.key}`">
                            <th>{{ row.label }}</th>
                            <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                          </tr>
                        </tbody>
                      </table>
                    </section>

                    <section v-if="selectedStepContextRows.length" class="detail-ledger-section detail-ledger-section--full">
                      <div class="detail-ledger-section__title">Guardian 上下文</div>
                      <table class="detail-kv-table detail-kv-table--full">
                        <tbody>
                          <tr v-for="row in selectedStepContextRows" :key="`selected-step-context-${row.key}`">
                            <th>{{ row.label }}</th>
                            <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                          </tr>
                        </tbody>
                      </table>
                    </section>

                    <section class="detail-ledger-section detail-ledger-section--full">
                      <div class="detail-ledger-section__title">Payload / Metrics</div>
                      <div class="detail-pane-grid detail-pane-grid--nested">
                        <table class="detail-kv-table">
                          <tbody>
                            <tr v-if="!selectedStepPayloadRows.length">
                              <th>payload</th>
                              <td>-</td>
                            </tr>
                            <tr v-for="row in selectedStepPayloadRows" :key="`selected-step-payload-${row.key}`">
                              <th>{{ row.label }}</th>
                              <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                            </tr>
                          </tbody>
                        </table>
                        <table class="detail-kv-table">
                          <tbody>
                            <tr v-if="!selectedStepMetricsRows.length">
                              <th>metrics</th>
                              <td>-</td>
                            </tr>
                            <tr v-for="row in selectedStepMetricsRows" :key="`selected-step-metrics-${row.key}`">
                              <th>{{ row.label }}</th>
                              <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                      <div class="detail-pane-grid detail-pane-grid--nested detail-pane-grid--raw">
                        <section v-if="selectedStep.payload_text" class="detail-json-section">
                          <div class="detail-ledger-section__title">Payload JSON</div>
                          <pre class="detail-json-view">{{ selectedStep.payload_text }}</pre>
                        </section>
                        <section v-if="selectedStep.metrics_text" class="detail-json-section">
                          <div class="detail-ledger-section__title">Metrics JSON</div>
                          <pre class="detail-json-view">{{ selectedStep.metrics_text }}</pre>
                        </section>
                      </div>
                    </section>
                  </div>

                  <div class="step-inspector-actions">
                    <el-button type="primary" plain @click="openRawFromStep(selectedStep)">查看 Raw</el-button>
                    <el-button text @click="copyText(buildStepCopyText(selectedStep))">复制节点摘要</el-button>
                  </div>
                </template>
                <div v-else class="trace-empty">暂无选中节点</div>
              </aside>
            </section>

            <section v-show="activeTraceDetailTab === 'raw'" class="runtime-detail-panel runtime-detail-panel--fill">
              <div class="runtime-detail-panel__toolbar">
                <span>{{ selectedStep ? `${selectedStep.component}.${selectedStep.node}` : '选择一个 Step 后可直接定位 Raw' }}</span>
                <el-button type="primary" plain :disabled="!selectedStep" @click="openRawBrowser">打开 Raw Browser</el-button>
              </div>
              <div v-if="embeddedRawLedgerRows.length" class="embedded-raw-ledger">
                <div class="embedded-raw-ledger__header">
                  <span>record</span>
                  <span>summary</span>
                  <span>badges</span>
                </div>
                <div
                  v-for="row in embeddedRawLedgerRows"
                  :key="row.key"
                  class="embedded-raw-ledger__entry"
                  :class="{ active: row.active }"
                >
                  <div class="embedded-raw-ledger__row">
                    <span class="runtime-ledger__cell runtime-ledger__cell--strong">{{ row.title }}</span>
                    <span class="runtime-ledger__cell runtime-ledger__cell--mono runtime-ledger__cell--truncate">{{ row.subtitle }}</span>
                    <span class="runtime-ledger__cell runtime-ledger__cell--truncate">{{ row.badges.length ? row.badges.join(' · ') : '-' }}</span>
                  </div>
                  <pre class="detail-json-view">{{ row.body }}</pre>
                </div>
              </div>
              <div v-else class="trace-empty">尚未加载 Raw，点击上方按钮拉取当前节点的原始记录。</div>
            </section>
              </div>
          </div>
          <div v-else class="trace-empty">暂无选中链路</div>
          </div>
            <div v-else class="trace-detail trace-detail--embedded">
              <div class="trace-detail-head">
                <div>
                  <strong>{{ selectedEvent ? `${selectedEvent.component}.${selectedEvent.node}` : '选择一个组件 Event' }}</strong>
                </div>
                <div class="trace-detail-actions">
                  <el-button :disabled="!selectedEvent" @click="openRawBrowser">原始数据</el-button>
                </div>
            </div>
              <div v-if="selectedEvent" class="trace-detail-body trace-detail-body--stacked">
                <div class="trace-detail-tabs-wrap workspace-tabs-wrap">
                  <el-tabs v-model="activeEventDetailTab" class="workspace-tabs event-detail-tabs">
                    <el-tab-pane name="event">
                      <template #label>
                        <div class="workspace-tab-label">
                          <span>事件</span>
                          <span class="tab-meta">{{ eventMetaRows.length + eventSummaryRows.length + eventMetricRows.length }}</span>
                        </div>
                      </template>
                    </el-tab-pane>
                    <el-tab-pane name="payload">
                      <template #label>
                        <div class="workspace-tab-label">
                          <span>载荷</span>
                          <span class="tab-meta">{{ eventPayloadRows.length + eventMetricsRows.length }}</span>
                        </div>
                      </template>
                    </el-tab-pane>
                    <el-tab-pane name="raw">
                      <template #label>
                        <div class="workspace-tab-label">
                          <span>原始数据</span>
                          <span class="tab-meta">{{ embeddedRawLedgerRows.length }}</span>
                        </div>
                      </template>
                    </el-tab-pane>
                  </el-tabs>

                <section v-show="activeEventDetailTab === 'event'" class="runtime-detail-panel runtime-detail-panel--fill event-detail-ledger">
                  <div class="detail-pane-grid detail-pane-grid--step">
                    <section class="detail-ledger-section">
                      <div class="detail-ledger-section__title">事件摘要</div>
                      <table class="detail-kv-table">
                        <tbody>
                          <tr v-for="row in eventMetaRows" :key="`event-meta-${row.key}`">
                            <th>{{ row.label }}</th>
                            <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                          </tr>
                          <tr v-for="row in eventSummaryRows" :key="`event-summary-${row.key}`">
                            <th>{{ row.label }}</th>
                            <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                          </tr>
                          <tr v-for="row in eventMetricRows" :key="`event-metric-${row.key}`">
                            <th>{{ row.label }}</th>
                            <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                          </tr>
                        </tbody>
                      </table>
                    </section>

                    <section v-if="eventDecisionRows.length || eventDetailFieldRows.length" class="detail-ledger-section">
                      <div class="detail-ledger-section__title">判断与关联字段</div>
                      <table class="detail-kv-table">
                        <tbody>
                          <tr v-for="row in eventDecisionRows" :key="`event-decision-${row.key}`">
                            <th>{{ row.label }}</th>
                            <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                          </tr>
                          <tr v-for="row in eventDetailFieldRows" :key="`event-field-${row.key}`">
                            <th>{{ row.label }}</th>
                            <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                          </tr>
                        </tbody>
                      </table>
                    </section>

                    <section v-if="selectedEvent?.guardian_step && eventGuardianRows.length" class="detail-ledger-section">
                      <div class="detail-ledger-section__title">Guardian 判断</div>
                      <table class="detail-kv-table">
                        <tbody>
                          <tr v-for="row in eventGuardianRows" :key="`event-guardian-${row.key}`">
                            <th>{{ row.label }}</th>
                            <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                          </tr>
                        </tbody>
                      </table>
                    </section>

                    <section v-if="selectedEvent?.guardian_step && eventSignalRows.length" class="detail-ledger-section">
                      <div class="detail-ledger-section__title">Guardian 信号</div>
                      <table class="detail-kv-table">
                        <tbody>
                          <tr v-for="row in eventSignalRows" :key="`event-signal-${row.key}`">
                            <th>{{ row.label }}</th>
                            <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                          </tr>
                        </tbody>
                      </table>
                    </section>

                    <section v-if="eventContextRows.length" class="detail-ledger-section detail-ledger-section--full">
                      <div class="detail-ledger-section__title">上下文</div>
                      <table class="detail-kv-table detail-kv-table--full">
                        <tbody>
                          <tr v-for="row in eventContextRows" :key="`event-context-${row.key}`">
                            <th>{{ row.label }}</th>
                            <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                          </tr>
                        </tbody>
                      </table>
                    </section>

                    <section class="detail-ledger-section detail-ledger-section--full">
                      <div class="detail-ledger-section__title">Payload / Metrics</div>
                      <div class="detail-pane-grid detail-pane-grid--nested">
                        <table class="detail-kv-table">
                          <tbody>
                            <tr v-if="!eventPayloadRows.length">
                              <th>payload</th>
                              <td>-</td>
                            </tr>
                            <tr v-for="row in eventPayloadRows" :key="`event-payload-inline-${row.key}`">
                              <th>{{ row.label }}</th>
                              <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                            </tr>
                          </tbody>
                        </table>
                        <table class="detail-kv-table">
                          <tbody>
                            <tr v-if="!eventMetricsRows.length">
                              <th>metrics</th>
                              <td>-</td>
                            </tr>
                            <tr v-for="row in eventMetricsRows" :key="`event-metrics-inline-${row.key}`">
                              <th>{{ row.label }}</th>
                              <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                      <div class="detail-pane-grid detail-pane-grid--nested detail-pane-grid--raw">
                        <section v-if="selectedEvent.payload_text" class="detail-json-section">
                          <div class="detail-ledger-section__title">Payload JSON</div>
                          <pre class="detail-json-view">{{ selectedEvent.payload_text }}</pre>
                        </section>

                        <section v-if="selectedEvent.metrics_text" class="detail-json-section">
                          <div class="detail-ledger-section__title">Metrics JSON</div>
                          <pre class="detail-json-view">{{ selectedEvent.metrics_text }}</pre>
                        </section>
                      </div>
                    </section>
                  </div>
                  <div class="step-inspector-actions">
                    <el-button type="primary" plain @click="openRawFromStep(selectedEvent)">查看 Raw</el-button>
                    <el-button text @click="copyText(buildEventCopyText(selectedEvent))">复制事件摘要</el-button>
                  </div>
                </section>

                <section v-show="activeEventDetailTab === 'payload'" class="runtime-detail-panel runtime-detail-panel--fill event-detail-ledger">
                  <div class="detail-pane-grid">
                    <section class="detail-ledger-section">
                      <div class="detail-ledger-section__title">载荷字段</div>
                      <table class="detail-kv-table">
                        <tbody>
                          <tr v-if="!eventPayloadRows.length">
                            <th>payload</th>
                            <td>-</td>
                          </tr>
                          <tr v-for="row in eventPayloadRows" :key="`event-payload-${row.key}`">
                            <th>{{ row.label }}</th>
                            <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                          </tr>
                        </tbody>
                      </table>
                    </section>

                    <section class="detail-ledger-section">
                      <div class="detail-ledger-section__title">指标字段</div>
                      <table class="detail-kv-table">
                        <tbody>
                          <tr v-if="!eventMetricsRows.length">
                            <th>metrics</th>
                            <td>-</td>
                          </tr>
                          <tr v-for="row in eventMetricsRows" :key="`event-metrics-${row.key}`">
                            <th>{{ row.label }}</th>
                            <td :class="{ 'is-mono': row.mono }">{{ row.value }}</td>
                          </tr>
                        </tbody>
                      </table>
                    </section>
                  </div>
                  <div class="detail-pane-grid detail-pane-grid--nested detail-pane-grid--raw">
                    <section v-if="selectedEvent.payload_text" class="detail-json-section">
                      <div class="detail-ledger-section__title">Payload JSON</div>
                      <pre class="detail-json-view">{{ selectedEvent.payload_text }}</pre>
                    </section>

                    <section v-if="selectedEvent.metrics_text" class="detail-json-section">
                      <div class="detail-ledger-section__title">Metrics JSON</div>
                      <pre class="detail-json-view">{{ selectedEvent.metrics_text }}</pre>
                    </section>
                  </div>
                  <div class="step-inspector-actions">
                    <el-button type="primary" plain @click="openRawFromStep(selectedEvent)">查看 Raw</el-button>
                    <el-button text @click="copyText(buildEventCopyText(selectedEvent))">复制事件摘要</el-button>
                  </div>
                </section>

                <section v-show="activeEventDetailTab === 'raw'" class="runtime-detail-panel runtime-detail-panel--fill event-detail-ledger">
                  <div class="runtime-detail-panel__toolbar">
                    <span>{{ selectedEvent.component }}.{{ selectedEvent.node }}</span>
                    <el-button type="primary" plain @click="openRawBrowser">打开 Raw Browser</el-button>
                  </div>
                  <div v-if="embeddedRawLedgerRows.length" class="embedded-raw-ledger">
                    <div class="embedded-raw-ledger__header">
                      <span>记录</span>
                      <span>摘要</span>
                      <span>标识</span>
                    </div>
                    <div
                      v-for="row in embeddedRawLedgerRows"
                      :key="row.key"
                      class="embedded-raw-ledger__entry"
                      :class="{ active: row.active }"
                    >
                      <div class="embedded-raw-ledger__row">
                        <span class="runtime-ledger__cell runtime-ledger__cell--strong">{{ row.title }}</span>
                        <span class="runtime-ledger__cell runtime-ledger__cell--mono runtime-ledger__cell--truncate">{{ row.subtitle }}</span>
                        <span class="runtime-ledger__cell runtime-ledger__cell--truncate">{{ row.badges.length ? row.badges.join(' · ') : '-' }}</span>
                      </div>
                      <pre class="detail-json-view">{{ row.body }}</pre>
                    </div>
                  </div>
                  <div v-else class="trace-empty">尚未加载 Raw，点击上方按钮拉取当前事件的原始记录。</div>
                </section>
                </div>
              </div>
              <div v-else class="trace-empty">先从左侧选择组件，再从中间选择一个 Event</div>
            </div>
          </section>
        </div>
    </div>

    <el-drawer v-model="advancedFilterVisible" size="420px" title="高级筛选">
      <div class="advanced-filter-grid">
        <el-input v-model="draftQuery.trace_id" clearable placeholder="trace_id" />
        <el-input v-model="draftQuery.intent_id" clearable placeholder="intent_id" />
        <el-input v-model="draftQuery.request_id" clearable placeholder="request_id" />
        <el-input v-model="draftQuery.internal_order_id" clearable placeholder="internal_order_id" />
        <el-input v-model="draftQuery.symbol" clearable placeholder="symbol" />
        <el-input v-model="draftQuery.component" clearable placeholder="component" />
        <el-input v-model="draftQuery.runtime_node" clearable placeholder="runtime_node" />
      </div>
      <div class="advanced-filter-actions">
        <el-button @click="resetAdvancedFilter">清空</el-button>
        <el-button type="primary" :loading="loading.traces" @click="applyAdvancedFilter">应用</el-button>
      </div>
    </el-drawer>

    <el-drawer v-model="rawDrawerVisible" size="55%" title="Raw Records">
      <div class="raw-toolbar">
        <el-input v-model="rawQuery.runtime_node" placeholder="runtime_node" />
        <el-input v-model="rawQuery.component" placeholder="component" />
        <el-input v-model="rawQuery.date" placeholder="YYYY-MM-DD" />
        <el-select v-model="rawQuery.file" placeholder="选择文件" filterable clearable style="width: 280px">
          <el-option v-for="item in rawFiles" :key="item.name" :label="item.name" :value="item.name" />
        </el-select>
        <el-button @click="loadRawFiles">文件</el-button>
        <el-button type="primary" :disabled="!rawQuery.file" @click="loadRawTail()">Tail</el-button>
      </div>
      <div v-if="rawFocusedIndex >= 0" class="raw-focus-banner">
        已定位到第 {{ rawFocusedIndex + 1 }} 条记录
      </div>
      <div v-if="rawRecordCards.length" class="raw-record-list">
        <article
          v-for="(record, index) in rawRecordCards"
          :key="`${record.title}-${record.subtitle}-${index}`"
          :ref="(el) => setRawRecordRef(el, index)"
          class="raw-record-card"
          :class="{ active: rawFocusedIndex === index }"
        >
          <header>
            <strong>{{ record.title }}</strong>
            <span>{{ record.subtitle }}</span>
          </header>
          <div v-if="record.badges.length" class="raw-record-badges">
            <span v-for="badge in record.badges" :key="`${record.title}-${badge}-${index}`">{{ badge }}</span>
          </div>
          <pre class="raw-content">{{ record.body }}</pre>
        </article>
      </div>
      <pre v-else class="raw-content">暂无记录</pre>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import { runtimeObservabilityApi } from '../api/runtimeObservabilityApi'
import MyHeader from './MyHeader.vue'
import {
  buildComponentEventFeed,
  buildEventLedgerRows,
  buildComponentSidebarItems,
  buildTodayTimeRange,
  formatTimeRangeLabel,
  buildTimeRangeQuery,
  buildIssuePriorityCards,
  buildTraceKindOptions,
  buildTraceListSummary,
  buildIssueSummary,
  buildRawRecordSummary,
  buildRawSelectionKey,
  buildTraceLedgerRows,
  buildTraceSummaryMeta,
  buildTraceDetail,
  buildTraceStepLedgerRows,
  buildHealthCards,
  buildRawLookupFromStep,
  buildBoardScopedQuery,
  buildTraceQuery,
  createTraceQueryState,
  filterVisibleTraces,
  findTraceByRow,
  findRawRecordIndex,
  filterTraceSteps,
  pickTraceAnchorStep,
  hasMatchingRawSelection,
  pickDefaultSidebarComponent,
  pickDefaultTraceStep,
  readApiPayload,
  stopPollingTimer,
  TRACE_QUERY_FIELDS,
  TRACE_QUERY_LABELS,
} from './runtimeObservability.mjs'

const loading = reactive({
  overview: false,
  traces: false,
  events: false,
  traceDetail: false,
  traceSteps: false,
  raw: false,
})

const TRACE_PAGE_SIZE = 60
const EVENT_PAGE_SIZE = 120
const TRACE_STEP_PAGE_SIZE = 160

const query = reactive(createTraceQueryState())
const draftQuery = reactive(createTraceQueryState())

const healthSummaryItems = ref([])
const healthCards = ref([])
const traces = ref([])
const traceNextCursor = ref(null)
const events = ref([])
const eventNextCursor = ref(null)
const timeRange = ref(buildTodayTimeRange())
const selectedTrace = ref(null)
const selectedTracePayload = ref(null)
const traceSteps = ref([])
const traceStepsNextCursor = ref(null)
const selectedStep = ref(null)
const selectedEvent = ref(null)
const activeView = ref('traces')
const onlyIssues = ref(false)
const traceOnlyIssues = ref(false)
const autoRefresh = ref(true)
const advancedFilterVisible = ref(false)
const userSelectedComponent = ref(false)
const selectedTraceKind = ref('all')
const activeTraceDetailTab = ref('steps')
const activeEventDetailTab = ref('event')
const rawDrawerVisible = ref(false)
const rawFiles = ref([])
const rawRecords = ref([])
const rawFocusedIndex = ref(-1)
const rawSelectionKey = ref('')
const rawRecordRefs = new Map()
const stepRowRefs = new Map()
const pageError = ref('')
const boardFilter = reactive({
  component: '',
  runtime_node: '',
})
const traceIssueFocus = reactive({
  component: '',
})
const lastLoadedEventQueryKey = ref('')
let eventLoadToken = 0
const rawQuery = reactive({
  runtime_node: '',
  component: '',
  date: '',
  file: '',
})
let overviewTimer = null

const hasDetailValue = (value) => {
  if (value === null || value === undefined) return false
  if (Array.isArray(value)) return value.some((item) => hasDetailValue(item))
  if (typeof value === 'object') return Object.keys(value).length > 0
  return String(value).trim() !== ''
}

const formatDetailValue = (value, fallback = '-') => {
  if (value === null || value === undefined) return fallback
  if (typeof value === 'string') {
    const normalized = value.trim()
    return normalized || fallback
  }
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    const parts = value
      .map((item) => formatDetailValue(item, ''))
      .filter(Boolean)
    return parts.length ? parts.join(' · ') : fallback
  }
  try {
    return JSON.stringify(value)
  } catch {
    return fallback
  }
}

const buildDetailRows = (rows = []) => {
  return rows
    .filter((row) => row && (row.always || hasDetailValue(row.value)))
    .map((row, index) => ({
      key: row.key || `row-${index}`,
      label: row.label || row.key || '-',
      value: formatDetailValue(row.value, row.fallback || '-'),
      copyValue: hasDetailValue(row.copyValue ?? row.value)
        ? formatDetailValue(row.copyValue ?? row.value, '')
        : '',
      mono: Boolean(row.mono),
    }))
}

const buildNodeLabel = (component, node) => {
  const normalizedComponent = String(component || '').trim()
  const normalizedNode = String(node || '').trim()
  const parts = []
  if (normalizedComponent) {
    const matchedComponent = componentSidebarItems.value.find((item) => item.component === normalizedComponent)
    parts.push(matchedComponent?.component_label || normalizedComponent)
  }
  if (normalizedNode) {
    const matchedNode = eventLedgerRows.value.find((item) => item.component === normalizedComponent && item.node === normalizedNode)
    parts.push(matchedNode?.node_label || normalizedNode)
  }
  return parts.length ? parts.join('.') : '-'
}

const flattenDetailEntries = (value, prefix = '') => {
  if (value === null || value === undefined) return []
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return prefix ? [{ key: prefix, value: '[]' }] : []
    }
    return value.flatMap((item, index) =>
      flattenDetailEntries(item, prefix ? `${prefix}[${index}]` : `[${index}]`),
    )
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value)
    if (entries.length === 0) {
      return prefix ? [{ key: prefix, value: '{}' }] : []
    }
    return entries.flatMap(([key, nestedValue]) =>
      flattenDetailEntries(nestedValue, prefix ? `${prefix}.${key}` : key),
    )
  }
  return [
    {
      key: prefix || 'value',
      value: formatDetailValue(value),
    },
  ]
}

const buildStructuredRows = (text, fallbackLabel) => {
  const normalized = String(text || '').trim()
  if (!normalized) return []
  try {
    const parsed = JSON.parse(normalized)
    return buildDetailRows(
      flattenDetailEntries(parsed)
        .slice(0, 32)
        .map((entry, index) => ({
          key: `${fallbackLabel}-${index}`,
          label: entry.key || fallbackLabel,
          value: entry.value,
          mono: true,
        })),
    )
  } catch {
    return buildDetailRows([
      {
        key: `${fallbackLabel}-raw`,
        label: fallbackLabel,
        value: normalized,
      },
    ])
  }
}

const buildContextRows = (blocks = []) => {
  return buildDetailRows(
    (Array.isArray(blocks) ? blocks : []).flatMap((block) =>
      (Array.isArray(block?.items) ? block.items : []).map((item) => ({
        key: `${block.key}-${item.key}`,
        label: `${block.label}.${item.key}`,
        value: item.value,
      })),
    ),
  )
}

const normalizeTimeRangeState = (value) => {
  if (Array.isArray(value) && value.length === 2) {
    const [startTime, endTime] = value
    if (String(startTime || '').trim() && String(endTime || '').trim()) {
      return [startTime, endTime]
    }
  }
  return buildTodayTimeRange()
}

const buildTraceRequestParams = () => ({
  ...buildTraceQuery(query, timeRange.value),
  ...(selectedTraceKind.value && selectedTraceKind.value !== 'all'
    ? { trace_kind: selectedTraceKind.value }
    : {}),
  include_symbol_name: 1,
  limit: TRACE_PAGE_SIZE,
})
const buildEventRequestParams = () => ({
  ...buildBoardScopedQuery(query, boardFilter, timeRange.value),
  include_symbol_name: 1,
  limit: EVENT_PAGE_SIZE,
})
const buildEventRequestKey = () => JSON.stringify({
  ...buildEventRequestParams(),
})
const timeRangeDisplayLabel = computed(() => formatTimeRangeLabel(timeRange.value))

const hydratedTraces = computed(() => traces.value.map((trace) => buildTraceDetail(trace)))
const visibleTraces = computed(() =>
  filterVisibleTraces(hydratedTraces.value, {
    issueComponent: traceIssueFocus.component,
    onlyIssueTraces: traceOnlyIssues.value,
  }),
)
const traceKindOptions = computed(() => buildTraceKindOptions(hydratedTraces.value))
const traceListSummary = computed(() => buildTraceListSummary(visibleTraces.value))
const issuePriorityCards = computed(() => buildIssuePriorityCards(visibleTraces.value))
const traceLedgerRows = computed(() => buildTraceLedgerRows(visibleTraces.value))
const componentSidebarItems = computed(() => buildComponentSidebarItems(hydratedTraces.value, healthSummaryItems.value))
const activeComponent = computed(() => String(boardFilter.component || '').trim())
const traceIssueFocusLabel = computed(() => {
  const component = String(traceIssueFocus.component || '').trim()
  if (!component) return ''
  return componentSidebarItems.value.find((item) => item.component === component)?.component_label || component
})
const componentEventFeed = computed(() => {
  if (!activeComponent.value) return []
  return buildComponentEventFeed(events.value, {
    component: activeComponent.value,
    runtime_node: boardFilter.runtime_node,
    onlyIssues: onlyIssues.value,
  })
})
const eventLedgerRows = computed(() => buildEventLedgerRows(componentEventFeed.value))
const filterChips = computed(() => {
  const chips = []
  if (traceOnlyIssues.value) {
    chips.push({
      key: 'trace-only-issues',
      label: '异常链路',
      kind: 'trace-only-issues',
    })
  }
  if (onlyIssues.value) {
    chips.push({
      key: 'only-issues',
      label: '仅异常',
      kind: 'toggle',
    })
  }
  for (const [field, label] of Object.entries(TRACE_QUERY_LABELS)) {
    const value = String(query[field] || '').trim()
    if (!value) continue
    chips.push({
      key: `query-${field}`,
      label: `${label}: ${value}`,
      kind: 'query',
      field,
    })
  }
  if (selectedTraceKind.value && selectedTraceKind.value !== 'all') {
    const activeOption = traceKindOptions.value.find((item) => item.value === selectedTraceKind.value)
    chips.push({
      key: 'trace-kind',
      label: activeOption?.label || selectedTraceKind.value,
      kind: 'trace-kind',
    })
  }
  if (traceIssueFocusLabel.value) {
    chips.push({
      key: 'trace-issue-focus',
      label: `异常组件: ${traceIssueFocusLabel.value}`,
      kind: 'trace-issue-focus',
    })
  }
  return chips
})

const selectedTraceDetail = computed(() => buildTraceDetail({
  ...(selectedTrace.value || {}),
  ...(selectedTracePayload.value?.trace || {}),
  steps: traceSteps.value,
}))
const guardianTrace = computed(() => selectedTraceDetail.value.guardian_trace || null)
const traceSummaryMeta = computed(() => buildTraceSummaryMeta(selectedTraceDetail.value))
const issueSummary = computed(() => buildIssueSummary(selectedTraceDetail.value))
const filteredSteps = computed(() => {
  return filterTraceSteps(selectedTraceDetail.value.steps, { onlyIssues: onlyIssues.value })
})
const firstIssueTraceStep = computed(() => pickTraceAnchorStep(selectedTraceDetail.value, null, 'first-issue'))
const previousIssueTraceStep = computed(() => pickTraceAnchorStep(selectedTraceDetail.value, selectedStep.value, 'previous-issue'))
const nextIssueTraceStep = computed(() => pickTraceAnchorStep(selectedTraceDetail.value, selectedStep.value, 'next-issue'))
const slowestTraceStep = computed(() => pickTraceAnchorStep(selectedTraceDetail.value, selectedStep.value, 'slowest-step'))
const traceStepLedgerRows = computed(() =>
  buildTraceStepLedgerRows({
    ...selectedTraceDetail.value,
    steps: filteredSteps.value,
  }),
)
const rawRecordCards = computed(() => rawRecords.value.map((record) => buildRawRecordSummary(record)))
const activeEmbeddedRawTarget = computed(() => (activeView.value === 'events' ? selectedEvent.value : selectedStep.value))
const embeddedRawRecordCards = computed(() => {
  return hasMatchingRawSelection(rawSelectionKey.value, activeEmbeddedRawTarget.value, activeView.value)
    ? rawRecordCards.value
    : []
})
const embeddedRawFocusedIndex = computed(() => (embeddedRawRecordCards.value.length > 0 ? rawFocusedIndex.value : -1))
const traceSummaryRows = computed(() =>
  buildDetailRows([
    {
      key: 'trace',
      label: 'Trace',
      value: selectedTraceDetail.value.trace_id || selectedTrace.value?.trace_key,
      mono: true,
      always: true,
    },
    {
      key: 'symbol',
      label: '标的',
      value: selectedTraceDetail.value.symbol_display,
      always: true,
    },
    {
      key: 'kind',
      label: '链路类型',
      value: traceLedgerRows.value.find((item) => item.trace_id === selectedTraceDetail.value.trace_id)?.trace_kind_label || selectedTraceDetail.value.trace_kind,
      always: true,
    },
    {
      key: 'status',
      label: '链路状态',
      value: traceLedgerRows.value.find((item) => item.trace_id === selectedTraceDetail.value.trace_id)?.trace_status_label || selectedTraceDetail.value.trace_status,
      always: true,
    },
    {
      key: 'first_ts',
      label: '开始',
      value: selectedTraceDetail.value.first_ts_label,
      mono: true,
      always: true,
    },
    {
      key: 'last_ts',
      label: '结束',
      value: selectedTraceDetail.value.last_ts_label,
      mono: true,
      always: true,
    },
    {
      key: 'duration',
      label: '总耗时',
      value: selectedTraceDetail.value.duration_label || selectedTraceDetail.value.total_duration_label,
      always: true,
    },
    {
      key: 'step_count',
      label: '节点数',
      value: selectedTraceDetail.value.step_count,
      mono: true,
      always: true,
    },
    {
      key: 'issue_count',
      label: '异常节点数',
      value: selectedTraceDetail.value.issue_count,
      mono: true,
      always: true,
    },
    {
      key: 'entry',
      label: '入口',
      value: buildNodeLabel(selectedTraceDetail.value.entry_component, selectedTraceDetail.value.entry_node),
      mono: true,
      always: true,
    },
    {
      key: 'exit',
      label: '出口',
      value: buildNodeLabel(selectedTraceDetail.value.exit_component, selectedTraceDetail.value.exit_node),
      mono: true,
      always: true,
    },
  ]),
)
const traceIssueRows = computed(() =>
  buildDetailRows([
    {
      key: 'issue_headline',
      label: '异常概览',
      value: issueSummary.value.headline,
      always: true,
    },
    {
      key: 'issue_nodes',
      label: '异常阶段',
      value: selectedTraceDetail.value.steps
        .filter((step) => step?.is_issue)
        .map((step) => buildNodeLabel(step.component, step.node)),
      always: true,
    },
    {
      key: 'break_reason',
      label: '断裂原因',
      value: selectedTraceDetail.value.break_reason,
      always: true,
    },
    {
      key: 'first_issue',
      label: '首个异常',
      value: traceSummaryMeta.value.first_issue
        ? buildNodeLabel(traceSummaryMeta.value.first_issue.component, traceSummaryMeta.value.first_issue.node)
        : '-',
      mono: true,
      always: true,
    },
    {
      key: 'last_issue',
      label: '最后异常',
      value: traceSummaryMeta.value.last_issue
        ? buildNodeLabel(traceSummaryMeta.value.last_issue.component, traceSummaryMeta.value.last_issue.node)
        : '-',
      mono: true,
      always: true,
    },
    {
      key: 'slowest',
      label: '慢点',
      value: traceSummaryMeta.value.slowest_step
        ? `${buildNodeLabel(traceSummaryMeta.value.slowest_step.component, traceSummaryMeta.value.slowest_step.node)} · ${traceSummaryMeta.value.slowest_step.delta_from_prev_label || '-'}`
        : '-',
      always: true,
    },
    {
      key: 'affected_components',
      label: '涉及组件',
      value: traceSummaryMeta.value.affected_components,
      always: true,
    },
    {
      key: 'issue_reasons',
      label: '异常原因',
      value: issueSummary.value.items.map((item) => `${item.label} x${item.count}`),
      always: true,
    },
  ]),
)
const guardianTraceRows = computed(() =>
  buildDetailRows([
    {
      key: 'guardian_signal',
      label: '信号',
      value: guardianTrace.value?.signal?.title,
      always: true,
    },
    {
      key: 'guardian_signal_subtitle',
      label: '摘要',
      value: guardianTrace.value?.signal?.subtitle,
      always: true,
    },
    {
      key: 'guardian_tags',
      label: '标签',
      value: guardianTrace.value?.signal?.tags || [],
      always: true,
    },
    {
      key: 'guardian_conclusion',
      label: '结论',
      value: guardianTrace.value?.conclusion?.label,
      always: true,
    },
    {
      key: 'guardian_node',
      label: '节点',
      value: guardianTrace.value?.conclusion?.node_label,
      always: true,
    },
    {
      key: 'guardian_reason',
      label: '原因',
      value: guardianTrace.value?.conclusion?.reason_code,
      always: true,
    },
    {
      key: 'guardian_branch',
      label: '分支',
      value: guardianTrace.value?.conclusion?.branch,
      always: true,
    },
    {
      key: 'guardian_expr',
      label: '条件',
      value: guardianTrace.value?.conclusion?.expr,
      always: true,
    },
  ]),
)
const guardianSignalRows = computed(() =>
  buildDetailRows(
    (guardianTrace.value?.signal?.items || []).map((item) => ({
      key: item.key,
      label: item.label,
      value: item.value,
    })),
  ),
)
const guardianDecisionContextRows = computed(() =>
  buildContextRows(guardianTrace.value?.latest_decision?.context_blocks || []),
)
const selectedStepOverviewRows = computed(() =>
  buildDetailRows([
    {
      key: 'step_index',
      label: 'Step',
      value: selectedStep.value ? `#${selectedStep.value.index + 1}` : '-',
      mono: true,
      always: true,
    },
    {
      key: 'component_node',
      label: '节点',
      value: selectedStep.value ? buildNodeLabel(selectedStep.value.component, selectedStep.value.node) : '-',
      mono: true,
      always: true,
    },
    {
      key: 'status',
      label: 'Status',
      value: selectedStep.value?.status,
      always: true,
    },
    {
      key: 'ts',
      label: '时间',
      value: selectedStep.value?.ts_label,
      mono: true,
      always: true,
    },
    {
      key: 'delta',
      label: 'Delta',
      value: selectedStep.value?.delta_from_prev_label,
      always: true,
    },
    {
      key: 'offset',
      label: 'Offset',
      value:
        selectedStep.value?.offset_ms !== null && selectedStep.value?.offset_ms !== undefined
          ? `${selectedStep.value.offset_ms}ms`
          : '-',
      mono: true,
      always: true,
    },
    {
      key: 'event_type',
      label: 'Event',
      value: selectedStep.value?.event_type,
      always: true,
    },
    {
      key: 'flags',
      label: '标记',
      value: [
        isFirstIssueStep(selectedStep.value) ? '首个异常' : '',
        isSlowestStep(selectedStep.value) ? '最长耗时节点' : '',
      ].filter(Boolean),
      always: true,
    },
  ]),
)
const selectedStepGuardianRows = computed(() =>
  buildDetailRows([
    {
      key: 'guardian_node',
      label: 'Guardian 节点',
      value: selectedStep.value?.guardian_step?.node_label,
      always: true,
    },
    {
      key: 'guardian_outcome',
      label: '判断结果',
      value: selectedStep.value?.guardian_step?.outcome?.label,
      always: true,
    },
    {
      key: 'guardian_branch',
      label: '分支',
      value: selectedStep.value?.guardian_step?.outcome?.branch,
      always: true,
    },
    {
      key: 'guardian_reason',
      label: '原因',
      value: selectedStep.value?.guardian_step?.outcome?.reason_code,
      always: true,
    },
    {
      key: 'guardian_expr',
      label: '条件',
      value: selectedStep.value?.guardian_step?.outcome?.expr,
      always: true,
    },
  ]),
)
const selectedStepSignalRows = computed(() =>
  buildDetailRows([
    {
      key: 'signal_title',
      label: '信号',
      value: selectedStep.value?.guardian_step?.signal?.title,
      always: true,
    },
    {
      key: 'signal_subtitle',
      label: '摘要',
      value: selectedStep.value?.guardian_step?.signal?.subtitle,
      always: true,
    },
    {
      key: 'signal_tags',
      label: '标签',
      value: selectedStep.value?.guardian_step?.signal?.tags || [],
      always: true,
    },
    ...((selectedStep.value?.guardian_step?.signal?.items || []).map((item) => ({
      key: `signal-${item.key}`,
      label: item.label,
      value: item.value,
    }))),
  ]),
)
const selectedStepContextRows = computed(() =>
  buildContextRows(selectedStep.value?.guardian_step?.context_blocks || []),
)
const selectedStepFieldRows = computed(() =>
  buildDetailRows(
    (selectedStep.value?.detail_fields || []).map((field) => ({
      key: field.key,
      label: field.key,
      value: field.value,
      mono: true,
    })),
  ),
)
const selectedStepTagRows = computed(() =>
  buildDetailRows(
    (selectedStep.value?.tags || []).map((tag) => ({
      key: tag.key,
      label: tag.label,
      value: tag.value,
    })),
  ),
)
const selectedStepPayloadRows = computed(() => buildStructuredRows(selectedStep.value?.payload_text, 'payload'))
const selectedStepMetricsRows = computed(() => buildStructuredRows(selectedStep.value?.metrics_text, 'metrics'))
const eventMetaRows = computed(() =>
  buildDetailRows([
    {
      key: 'event_node',
      label: '事件',
      value: selectedEvent.value ? buildNodeLabel(selectedEvent.value.component, selectedEvent.value.node) : '-',
      mono: true,
      always: true,
    },
    {
      key: 'event_type',
      label: 'Type',
      value: selectedEvent.value?.event_type,
      always: true,
    },
    {
      key: 'status',
      label: 'Status',
      value: selectedEvent.value?.status,
      always: true,
    },
    {
      key: 'runtime_node',
      label: 'Runtime Node',
      value: selectedEvent.value?.runtime_node,
      mono: true,
      always: true,
    },
    {
      key: 'ts',
      label: '时间',
      value: selectedEvent.value?.ts_label,
      mono: true,
      always: true,
    },
    {
      key: 'symbol',
      label: 'Symbol',
      value: selectedEvent.value?.symbol_display,
      always: true,
    },
    {
      key: 'identity',
      label: 'Identity',
      value: selectedEvent.value?.identity,
      mono: true,
      always: true,
    },
    {
      key: 'is_issue',
      label: '异常',
      value: selectedEvent.value?.is_issue ? 'yes' : 'no',
      always: true,
    },
  ]),
)
const eventSummaryRows = computed(() =>
  buildDetailRows([
    {
      key: 'summary',
      label: '摘要',
      value: selectedEvent.value?.summary,
      always: true,
    },
    {
      key: 'badges',
      label: 'Badges',
      value: selectedEvent.value?.badges || [],
      always: true,
    },
    {
      key: 'message',
      label: '消息',
      value: selectedEvent.value?.message,
      always: true,
    },
    {
      key: 'metrics_summary',
      label: 'Metrics',
      value: (selectedEvent.value?.summary_metrics || []).map((metric) => `${metric.label} ${metric.display}`),
      always: true,
    },
  ]),
)
const eventMetricRows = computed(() =>
  buildDetailRows(
    (selectedEvent.value?.summary_metrics || []).map((metric) => ({
      key: metric.key,
      label: metric.label,
      value: metric.display,
    })),
  ),
)
const eventDecisionRows = computed(() =>
  buildDetailRows([
    {
      key: 'decision_outcome',
      label: '判断结果',
      value:
        selectedEvent.value?.guardian_step?.outcome?.label ||
        selectedEvent.value?.decision_outcome?.label ||
        selectedEvent.value?.decision_outcome?.outcome,
      always: true,
    },
    ...((selectedEvent.value?.tags || []).map((tag) => ({
      key: `decision-${tag.key}`,
      label: tag.label,
      value: tag.value,
    }))),
  ]),
)
const eventDetailFieldRows = computed(() =>
  buildDetailRows(
    (selectedEvent.value?.detail_fields || []).map((field) => ({
      key: field.key,
      label: field.key,
      value: field.value,
      mono: true,
    })),
  ),
)
const eventGuardianRows = computed(() =>
  buildDetailRows([
    {
      key: 'guardian_node',
      label: 'Guardian 节点',
      value: selectedEvent.value?.guardian_step?.node_label,
      always: true,
    },
    {
      key: 'guardian_outcome',
      label: '判断结果',
      value: selectedEvent.value?.guardian_step?.outcome?.label,
      always: true,
    },
    {
      key: 'guardian_branch',
      label: '分支',
      value: selectedEvent.value?.guardian_step?.outcome?.branch,
      always: true,
    },
    {
      key: 'guardian_reason',
      label: '原因',
      value: selectedEvent.value?.guardian_step?.outcome?.reason_code,
      always: true,
    },
    {
      key: 'guardian_expr',
      label: '条件',
      value: selectedEvent.value?.guardian_step?.outcome?.expr,
      always: true,
    },
  ]),
)
const eventSignalRows = computed(() =>
  buildDetailRows([
    {
      key: 'signal_title',
      label: '信号',
      value: selectedEvent.value?.guardian_step?.signal?.title,
      always: true,
    },
    {
      key: 'signal_subtitle',
      label: '摘要',
      value: selectedEvent.value?.guardian_step?.signal?.subtitle,
      always: true,
    },
    {
      key: 'signal_tags',
      label: '标签',
      value: selectedEvent.value?.guardian_step?.signal?.tags || [],
      always: true,
    },
    ...((selectedEvent.value?.guardian_step?.signal?.items || []).map((item) => ({
      key: `signal-${item.key}`,
      label: item.label,
      value: item.value,
    }))),
  ]),
)
const eventContextRows = computed(() => {
  if (selectedEvent.value?.guardian_step?.context_blocks?.length) {
    return buildContextRows(selectedEvent.value.guardian_step.context_blocks)
  }
  return buildStructuredRows(selectedEvent.value?.decision_context_text, 'context')
})
const eventPayloadRows = computed(() => buildStructuredRows(selectedEvent.value?.payload_text, 'payload'))
const eventMetricsRows = computed(() => buildStructuredRows(selectedEvent.value?.metrics_text, 'metrics'))
const embeddedRawLedgerRows = computed(() =>
  embeddedRawRecordCards.value.map((record, index) => ({
    key: `${record.title}-${index}`,
    title: record.title || '-',
    subtitle: record.subtitle || '-',
    badges: Array.isArray(record.badges) ? record.badges : [],
    body: record.body || '',
    active: embeddedRawFocusedIndex.value === index,
  })),
)

const syncQueryState = (target, source = {}) => {
  for (const field of TRACE_QUERY_FIELDS) {
    target[field] = String(source?.[field] || '').trim()
  }
}

const summarizeRequestError = (fallback, error) => {
  const detail = String(
    error?.response?.data?.detail ||
      error?.response?.data?.message ||
      error?.message ||
      '',
  ).trim()
  return detail ? `${fallback}：${detail}` : fallback
}

const mergeByKey = (items = [], keyField = 'trace_key') => {
  const merged = []
  const seen = new Set()
  for (const item of items) {
    const key = String(item?.[keyField] || item?.trace_id || item?.event_id || '').trim()
    if (!key || seen.has(key)) continue
    seen.add(key)
    merged.push(item)
  }
  return merged
}

const resetSelectedTraceDetailState = () => {
  selectedTracePayload.value = null
  traceSteps.value = []
  traceStepsNextCursor.value = null
  selectedStep.value = null
}

const loadOverview = async () => {
  loading.overview = true
  try {
    pageError.value = ''
    const currentTimeRange = normalizeTimeRangeState(timeRange.value)
    timeRange.value = currentTimeRange
    const [healthResult, traceResult, eventResult] = await Promise.allSettled([
      runtimeObservabilityApi.getHealthSummary(buildTimeRangeQuery(currentTimeRange)),
      loadTraces({ suppressError: true }),
      ...(activeView.value === 'events' ? [loadEvents({ suppressError: true })] : []),
    ])
    const errors = []
    if (healthResult.status === 'fulfilled') {
      healthSummaryItems.value = readApiPayload(healthResult.value, 'components', [])
      healthCards.value = buildHealthCards(healthSummaryItems.value)
    } else {
      errors.push(summarizeRequestError('健康摘要加载失败', healthResult.reason))
    }
    if (traceResult.status === 'rejected') {
      errors.push(summarizeRequestError('Trace 列表加载失败', traceResult.reason))
    }
    if (eventResult?.status === 'rejected') {
      errors.push(summarizeRequestError('Event 列表加载失败', eventResult.reason))
    }
    pageError.value = errors.join('；')
  } finally {
    loading.overview = false
  }
}

const loadTraces = async (options = {}) => {
  const suppressError = Boolean(options?.suppressError)
  const append = Boolean(options?.append)
  loading.traces = true
  try {
    if (!suppressError) pageError.value = ''
    const cursor = append ? traceNextCursor.value : null
    const response = await runtimeObservabilityApi.listTraces({
      ...buildTraceRequestParams(),
      ...(cursor?.ts ? { cursor_ts: cursor.ts } : {}),
      ...(cursor?.trace_key ? { cursor_trace_key: cursor.trace_key } : {}),
    })
    const items = readApiPayload(response, 'items', [])
    const nextCursor = readApiPayload(response, 'next_cursor', null)
    traces.value = append
      ? mergeByKey([...traces.value, ...items], 'trace_key')
      : items
    traceNextCursor.value = nextCursor
    if (!append) {
      const currentTraceRow = {
        trace_key: selectedTrace.value?.trace_key,
        trace_id: selectedTrace.value?.trace_id,
      }
      const nextSelected = findTraceByRow(traces.value, currentTraceRow) || traces.value[0] || null
      if ((nextSelected?.trace_key || '') !== (selectedTrace.value?.trace_key || '')) {
        resetSelectedTraceDetailState()
      }
      selectedTrace.value = nextSelected
    }
  } catch (error) {
    if (!suppressError) {
      pageError.value = summarizeRequestError('Trace 列表加载失败', error)
    }
    throw error
  } finally {
    loading.traces = false
  }
}

const loadMoreTraces = async () => {
  if (!traceNextCursor.value || loading.traces) return
  await loadTraces({ append: true })
}

const loadEvents = async (options = {}) => {
  const suppressError = Boolean(options?.suppressError)
  const append = Boolean(options?.append)
  const loadToken = eventLoadToken + 1
  const cursor = append ? eventNextCursor.value : null
  const params = {
    ...buildEventRequestParams(),
    ...(cursor?.ts ? { cursor_ts: cursor.ts } : {}),
    ...(cursor?.event_id ? { cursor_event_id: cursor.event_id } : {}),
  }
  const requestKey = JSON.stringify(buildEventRequestParams())
  eventLoadToken = loadToken
  loading.events = true
  try {
    if (!suppressError) pageError.value = ''
    const response = await runtimeObservabilityApi.listEvents(params)
    if (loadToken !== eventLoadToken) return
    const items = readApiPayload(response, 'items', [])
    events.value = append
      ? mergeByKey([...events.value, ...items], 'event_id')
      : items
    eventNextCursor.value = readApiPayload(response, 'next_cursor', null)
    lastLoadedEventQueryKey.value = requestKey
  } catch (error) {
    if (loadToken !== eventLoadToken) return
    if (!suppressError) {
      pageError.value = summarizeRequestError('Event 列表加载失败', error)
    }
    throw error
  } finally {
    if (loadToken === eventLoadToken) {
      loading.events = false
    }
  }
}

const loadMoreEvents = async () => {
  if (!eventNextCursor.value || loading.events) return
  await loadEvents({ append: true })
}

const loadTraceDetail = async (traceRow, options = {}) => {
  const suppressError = Boolean(options?.suppressError)
  const targetTrace = traceRow || selectedTrace.value
  const traceKey = String(targetTrace?.trace_key || targetTrace?.trace_id || '').trim()
  if (!traceKey) {
    resetSelectedTraceDetailState()
    return
  }
  loading.traceDetail = true
  try {
    if (!suppressError) pageError.value = ''
    const response = await runtimeObservabilityApi.getTraceDetail(traceKey, {
      ...buildTimeRangeQuery(timeRange.value),
      step_limit: TRACE_STEP_PAGE_SIZE,
    })
    const trace = readApiPayload(response, 'trace', null)
    const steps = readApiPayload(response, 'steps', [])
    selectedTracePayload.value = { trace }
    traceSteps.value = Array.isArray(steps) ? steps : []
    traceStepsNextCursor.value = readApiPayload(response, 'steps_next_cursor', null)
  } catch (error) {
    resetSelectedTraceDetailState()
    if (!suppressError) {
      pageError.value = summarizeRequestError('Trace 详情加载失败', error)
    }
    throw error
  } finally {
    loading.traceDetail = false
  }
}

const loadMoreTraceSteps = async () => {
  const targetTraceKey = String(selectedTrace.value?.trace_key || selectedTrace.value?.trace_id || '').trim()
  if (!targetTraceKey || !traceStepsNextCursor.value || loading.traceSteps) return
  loading.traceSteps = true
  try {
    const response = await runtimeObservabilityApi.listTraceSteps(targetTraceKey, {
      ...buildTimeRangeQuery(timeRange.value),
      limit: TRACE_STEP_PAGE_SIZE,
      cursor_ts: traceStepsNextCursor.value?.ts,
      cursor_event_id: traceStepsNextCursor.value?.event_id,
    })
    const items = readApiPayload(response, 'items', [])
    traceSteps.value = [...items, ...traceSteps.value]
    traceStepsNextCursor.value = readApiPayload(response, 'next_cursor', null)
  } catch (error) {
    pageError.value = summarizeRequestError('Trace 步骤加载失败', error)
    throw error
  } finally {
    loading.traceSteps = false
  }
}

const openAdvancedFilter = () => {
  syncQueryState(draftQuery, query)
  advancedFilterVisible.value = true
}

const applyAdvancedFilter = async () => {
  syncQueryState(query, draftQuery)
  const tasks = [loadTraces()]
  if (activeView.value === 'events') {
    tasks.push(loadEvents())
  }
  await Promise.all(tasks)
  advancedFilterVisible.value = false
}

const resetAdvancedFilter = () => {
  syncQueryState(draftQuery)
}

const handleTraceClick = async (row) => {
  const selected = findTraceByRow(hydratedTraces.value, row)
  if (!selected) return
  const previousTraceKey = selectedTrace.value?.trace_key || selectedTrace.value?.trace_id || ''
  selectedTrace.value = selected
  activeTraceDetailTab.value = 'steps'
  const nextTraceKey = selected.trace_key || selected.trace_id || ''
  if (previousTraceKey === nextTraceKey && !selectedTracePayload.value?.trace?.trace_key) {
    await loadTraceDetail(selected, { suppressError: true })
  }
}

const handleIssueCardClick = async (card) => {
  await handleTraceClick(card)
}

const handleRecentTraceClick = async (row) => {
  await handleTraceClick(row)
}

const handleEventClick = (event) => {
  selectedEvent.value = event || null
  activeEventDetailTab.value = 'event'
}

const handleTimeRangeChange = async (value) => {
  timeRange.value = normalizeTimeRangeState(value)
  await loadOverview()
}

const handleTraceKindClick = async (kind) => {
  const normalizedKind = String(kind || '').trim() || 'all'
  selectedTraceKind.value = normalizedKind
  await loadTraces()
}

const switchToComponentEvents = async (component, options = {}) => {
  const normalizedComponent = String(component || '').trim()
  if (!normalizedComponent) return
  const nextOnlyIssues = Object.prototype.hasOwnProperty.call(options, 'onlyIssues')
    ? Boolean(options.onlyIssues)
    : onlyIssues.value
  traceIssueFocus.component = ''
  traceOnlyIssues.value = false
  userSelectedComponent.value = true
  boardFilter.component = normalizedComponent
  boardFilter.runtime_node = ''
  onlyIssues.value = nextOnlyIssues
  activeView.value = 'events'
  if (lastLoadedEventQueryKey.value === buildEventRequestKey()) return
  await loadEvents({ suppressError: true })
}

const handleComponentFilter = async (target) => {
  const normalizedComponent =
    typeof target === 'string'
      ? String(target || '').trim()
      : String(target?.component || '').trim()
  if (!normalizedComponent) return
  await switchToComponentEvents(normalizedComponent, { onlyIssues: false })
}

const handleSummaryJump = async (target) => {
  if (target === 'issue-traces' && traceListSummary.value.issue_trace_count <= 0) return
  if (target === 'issue-steps' && traceListSummary.value.issue_step_count <= 0) return
  traceIssueFocus.component = ''
  traceOnlyIssues.value = true
  onlyIssues.value = target === 'issue-steps'
  activeView.value = 'traces'
  activeTraceDetailTab.value = 'steps'
  if (selectedTraceKind.value !== 'all') {
    await handleTraceKindClick('all')
  }
}

const handleComponentIssueTraceJump = async (item) => {
  const normalizedComponent = String(item?.component || '').trim()
  if (!normalizedComponent || Number(item?.issue_trace_count || 0) <= 0) return
  traceIssueFocus.component = normalizedComponent
  traceOnlyIssues.value = true
  onlyIssues.value = false
  activeView.value = 'traces'
  activeTraceDetailTab.value = 'steps'
  if (selectedTraceKind.value !== 'all') {
    await handleTraceKindClick('all')
  }
}

const handleComponentIssueEventJump = async (item) => {
  const normalizedComponent = String(item?.component || '').trim()
  if (!normalizedComponent || Number(item?.issue_step_count || 0) <= 0) return
  await switchToComponentEvents(normalizedComponent, { onlyIssues: true })
}

const clearFilterChip = async (chip) => {
  if (!chip) return
  if (chip.kind === 'trace-only-issues') {
    traceOnlyIssues.value = false
    return
  }
  if (chip.kind === 'toggle') {
    onlyIssues.value = false
    return
  }
  if (chip.kind === 'trace-kind') {
    await handleTraceKindClick('all')
    return
  }
  if (chip.kind === 'trace-issue-focus') {
    traceIssueFocus.component = ''
    return
  }
  if (chip.kind === 'query' && chip.field) {
    query[chip.field] = ''
    draftQuery[chip.field] = ''
    const tasks = [loadTraces()]
    if (activeView.value === 'events') {
      tasks.push(loadEvents())
    }
    await Promise.all(tasks)
  }
}

const handleStepSelect = (step) => {
  selectedStep.value = step || null
}

const handleTraceAnchorJump = async (mode) => {
  const target = pickTraceAnchorStep(selectedTraceDetail.value, selectedStep.value, mode)
  if (!target) return
  if (mode === 'slowest-step') {
    onlyIssues.value = false
  }
  activeTraceDetailTab.value = 'steps'
  selectedStep.value = target
  await scrollToSelectedStep()
}

const buildIdentityCopyValue = (item = {}) => {
  return Array.isArray(item?.values) && item.values.length > 0
    ? item.values.join('\n')
    : String(item?.value || '').trim()
}

const openRawBrowser = async () => {
  const target = activeView.value === 'events' ? selectedEvent.value : selectedStep.value
  if (target) {
    await openRawFromStep(target)
    return
  }
  if (selectedStep.value) {
    await openRawFromStep(selectedStep.value)
    return
  }
  rawDrawerVisible.value = true
}

const openRawFromStep = async (step) => {
  const lookup = buildRawLookupFromStep(step)
  if (!lookup) return
  const selectionKey = buildRawSelectionKey(step, activeView.value)
  rawSelectionKey.value = selectionKey
  rawQuery.runtime_node = lookup.runtime_node
  rawQuery.component = lookup.component
  rawQuery.date = lookup.date
  rawQuery.file = ''
  rawDrawerVisible.value = true
  await loadRawFiles()
  if (rawFiles.value.length > 0) {
    rawQuery.file = rawFiles.value[0].name
    await loadRawTail(step, selectionKey)
  }
}

const loadRawFiles = async () => {
  loading.raw = true
  try {
    const response = await runtimeObservabilityApi.listRawFiles({
      runtime_node: rawQuery.runtime_node,
      component: rawQuery.component,
      date: rawQuery.date,
    })
    rawFiles.value = readApiPayload(response, 'files', [])
  } finally {
    loading.raw = false
  }
}

const loadRawTail = async (
  targetStep = activeView.value === 'events' ? selectedEvent.value : selectedStep.value,
  targetSelectionKey = buildRawSelectionKey(targetStep, activeView.value),
) => {
  if (!rawQuery.file) return
  rawSelectionKey.value = targetSelectionKey || ''
  loading.raw = true
  try {
    const response = await runtimeObservabilityApi.tailRawFile({
      runtime_node: rawQuery.runtime_node,
      component: rawQuery.component,
      date: rawQuery.date,
      file: rawQuery.file,
      lines: 120,
    })
    const records = readApiPayload(response, 'records', [])
    if (targetSelectionKey && targetSelectionKey !== rawSelectionKey.value) return
    rawRecords.value = records
    rawFocusedIndex.value = findRawRecordIndex(records, targetStep)
    await scrollToFocusedRawRecord()
  } finally {
    loading.raw = false
  }
}

const stepKey = (step) => {
  return [
    step?.component || '',
    step?.node || '',
    step?.ts || '',
    step?.index ?? '',
  ].join('|')
}

const isActiveStep = (step) => {
  return stepKey(selectedStep.value) === stepKey(step)
}

const isFirstIssueStep = (step) => {
  return stepKey(traceSummaryMeta.value.first_issue) === stepKey(step)
}

const isSlowestStep = (step) => {
  return stepKey(traceSummaryMeta.value.slowest_step) === stepKey(step)
}

const setStepRowRef = (element, key) => {
  if (!key) return
  stepRowRefs.set(key, element || null)
}

const scrollToSelectedStep = async () => {
  const key = stepKey(selectedStep.value)
  if (!key) return
  await nextTick()
  stepRowRefs.get(key)?.scrollIntoView({
    block: 'nearest',
    behavior: 'smooth',
  })
}

const statusClass = (status) => {
  const normalized = String(status || 'info').trim()
  if (normalized === 'success') return 'is-success'
  if (normalized === 'warning') return 'is-warning'
  if (normalized === 'failed' || normalized === 'error') return 'is-failed'
  if (normalized === 'skipped') return 'is-skipped'
  return 'is-info'
}

const buildStepCopyText = (step) => {
  if (!step) return ''
  const lines = [
    `${step.component}.${step.node}`,
    `status: ${step.status || 'info'}`,
    step.ts ? `ts: ${step.ts}` : '',
    ...(step.detail_fields || []).map((field) => `${field.key}: ${field.value}`),
    ...(step.tags || []).map((tag) => `${tag.label}: ${tag.value}`),
  ].filter(Boolean)
  return lines.join('\n')
}

const isActiveTraceRow = (row) => {
  const selectedKey = selectedTrace.value?.trace_key || ''
  const selectedId = selectedTrace.value?.trace_id || ''
  return (
    (row?.trace_key && row.trace_key === selectedKey) ||
    (row?.trace_id && row.trace_id === selectedId)
  )
}

const isActiveEventRow = (row) => {
  return [
    row?.key || '',
    row?.component || '',
    row?.runtime_node || '',
    row?.node || '',
    row?.ts || '',
  ].join('|') === [
    selectedEvent.value?.key || '',
    selectedEvent.value?.component || '',
    selectedEvent.value?.runtime_node || '',
    selectedEvent.value?.node || '',
    selectedEvent.value?.ts || '',
  ].join('|')
}

const copyText = async (value) => {
  const text = String(value || '').trim()
  if (!text) return
  try {
    if (window?.navigator?.clipboard?.writeText) {
      await window.navigator.clipboard.writeText(text)
    }
  } catch {
    return
  }
}

const buildEventCopyText = (event) => {
  if (!event) return ''
  return [
    `${event.component}.${event.node}`,
    `event_type: ${event.event_type || 'trace_step'}`,
    `status: ${event.status || 'info'}`,
    event.runtime_node ? `runtime_node: ${event.runtime_node}` : '',
    event.ts ? `ts: ${event.ts}` : '',
    ...(event.badges || []),
  ].filter(Boolean).join('\n')
}

const resetOverviewTimer = () => {
  overviewTimer = stopPollingTimer(overviewTimer, { clearInterval: window.clearInterval.bind(window) })
  if (!autoRefresh.value) return
  overviewTimer = window.setInterval(() => {
    loadOverview()
  }, 15000)
}

const syncSelectedStep = () => {
  const steps = filteredSteps.value
  if (!steps.length) {
    selectedStep.value = null
    return
  }
  const currentKey = stepKey(selectedStep.value)
  selectedStep.value = steps.find((step) => stepKey(step) === currentKey) || pickDefaultTraceStep(steps)
}

const setRawRecordRef = (element, index) => {
  rawRecordRefs.set(index, element || null)
}

const scrollToFocusedRawRecord = async () => {
  if (rawFocusedIndex.value < 0) return
  await nextTick()
  rawRecordRefs.get(rawFocusedIndex.value)?.scrollIntoView({
    block: 'nearest',
    behavior: 'smooth',
  })
}

watch([selectedTraceDetail, onlyIssues], () => {
  syncSelectedStep()
})

watch(componentEventFeed, (items) => {
  const currentKey = selectedEvent.value?.key || ''
  selectedEvent.value = items.find((item) => item.key === currentKey) || items[0] || null
}, { immediate: true })

watch(componentSidebarItems, (items) => {
  if (items.length === 0) {
    userSelectedComponent.value = false
    boardFilter.component = ''
    boardFilter.runtime_node = ''
    return
  }
  if (userSelectedComponent.value && boardFilter.component) return
  const fallback = pickDefaultSidebarComponent(items, boardFilter.component)
  if (fallback === boardFilter.component) return
  boardFilter.component = fallback
  boardFilter.runtime_node = ''
}, { immediate: true })

watch(
  () => [boardFilter.component, boardFilter.runtime_node],
  async ([component, runtimeNode], [prevComponent, prevRuntimeNode] = []) => {
    if (component === prevComponent && runtimeNode === prevRuntimeNode) return
    if (!component && !runtimeNode) return
    if (activeView.value !== 'events') return
    if (lastLoadedEventQueryKey.value === buildEventRequestKey()) return
    await loadEvents({ suppressError: true })
  },
)

watch(activeView, async (view, previousView) => {
  if (view !== 'events' || view === previousView) return
  if (lastLoadedEventQueryKey.value === buildEventRequestKey()) return
  await loadEvents({ suppressError: true })
})

watch(visibleTraces, (items) => {
  if (items.length === 0) {
    selectedTrace.value = null
    resetSelectedTraceDetailState()
    return
  }
  const currentRow = {
    trace_key: selectedTrace.value?.trace_key,
    trace_id: selectedTrace.value?.trace_id,
  }
  selectedTrace.value = findTraceByRow(items, currentRow) || items[0] || null
}, { immediate: true })

watch(
  () => [
    selectedTrace.value?.trace_key || selectedTrace.value?.trace_id || '',
    ...normalizeTimeRangeState(timeRange.value),
  ],
  async ([traceKey], [previousTraceKey] = []) => {
    activeTraceDetailTab.value = 'steps'
    if (!traceKey) {
      resetSelectedTraceDetailState()
      return
    }
    if (traceKey === previousTraceKey && selectedTracePayload.value?.trace?.trace_key === traceKey) {
      return
    }
    await loadTraceDetail(selectedTrace.value, { suppressError: true })
  },
  { immediate: true },
)

watch(rawRecords, () => {
  rawRecordRefs.clear()
})

watch(traceStepLedgerRows, () => {
  stepRowRefs.clear()
})

watch(selectedStep, () => {
  scrollToSelectedStep()
})

watch(activeTraceDetailTab, (tab) => {
  if (tab === 'steps') {
    scrollToSelectedStep()
  }
})

watch(autoRefresh, () => {
  resetOverviewTimer()
})

onMounted(() => {
  resetOverviewTimer()
  loadOverview()
})

onBeforeUnmount(() => {
  overviewTimer = stopPollingTimer(overviewTimer, { clearInterval: window.clearInterval.bind(window) })
})
</script>

<style scoped>
.runtime-page {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  min-height: 100dvh;
  background: #f5f7fa;
}

.runtime-shell {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.runtime-section {
  background: transparent;
  border: 0;
  border-radius: 0;
  padding: 0;
  box-shadow: none;
}

.runtime-title-row {
  display: flex;
  justify-content: flex-start;
  gap: 12px;
  align-items: flex-start;
  margin: 0;
}

.runtime-title-main {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 12px;
}

.runtime-title-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.runtime-time-range {
  width: min(100%, 340px);
  min-width: 0;
}

.runtime-view-switch {
  margin-right: 4px;
}

.runtime-trace-kind-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.runtime-summary-row {
  justify-content: space-between;
}

.runtime-summary-chip-button,
.component-symbol-card__action {
  border: 0;
  cursor: pointer;
  font: inherit;
}

.runtime-summary-chip-button.is-disabled,
.component-symbol-card__action.is-disabled {
  cursor: default;
  opacity: 0.58;
  pointer-events: none;
}

.runtime-filter-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-left: auto;
}

.runtime-filter-chip {
  border: 1px solid #d9ecff;
  border-radius: 999px;
  padding: 4px 10px;
  background: #f4f9ff;
  color: #409eff;
  cursor: pointer;
  font-size: 12px;
  font: inherit;
}

.runtime-filter-chip:hover {
  background: #ecf5ff;
}

.runtime-filter-empty {
  color: #64748b;
}

.runtime-home-section {
  border: 1px solid #d8e2ee;
  border-radius: 16px;
  background: linear-gradient(180deg, #ffffff 0%, #f7faff 100%);
  padding: 16px;
}

.runtime-home-section + .runtime-home-section {
  margin-top: 14px;
}

.runtime-home-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 10px;
}

.runtime-home-head h2 {
  margin: 0;
  color: #303133;
  font-size: 15px;
}

.runtime-home-head p {
  margin: 4px 0 0;
  color: #909399;
  font-size: 12px;
}

.runtime-home-meta {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  background: #f8fafc;
  color: #64748b;
  font-size: 12px;
}

.runtime-home-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.runtime-browse-layout {
  display: grid;
  grid-template-columns: minmax(200px, 0.58fr) minmax(820px, 2.42fr) minmax(400px, 1.08fr);
  gap: 14px;
  flex: 1 1 auto;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
  align-items: stretch;
}

.runtime-browser-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  min-width: 0;
  border-color: #ebeef5;
  border-radius: 8px;
  background: #fff;
  padding: 12px;
}

.runtime-browser-panel--detail {
  min-height: 0;
  padding: 0;
  background: transparent;
  border: 0;
  box-shadow: none;
  overflow: hidden;
}

.component-symbol-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding-right: 4px;
  scrollbar-gutter: stable;
}

.component-symbol-card {
  width: 100%;
  padding: 12px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.component-symbol-card:hover,
.component-symbol-card.active {
  border-color: #409eff;
  box-shadow: 0 0 0 1px rgba(64, 158, 255, 0.12);
}

.component-symbol-card__head,
.component-symbol-card__foot,
.component-symbol-card__badges {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.component-symbol-card__head,
.component-symbol-card__foot {
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.component-symbol-card__head strong {
  display: block;
  color: #21405e;
}

.component-symbol-card__head span,
.component-symbol-card__foot {
  color: #69829b;
  font-size: 12px;
}

.component-symbol-card__badges {
  margin-top: 10px;
}

.component-symbol-card__action {
  text-align: left;
}

.component-sidebar-highlights,
.component-sidebar-popover-highlights {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.component-sidebar-highlights span,
.component-sidebar-popover-highlights span {
  padding: 4px 8px;
  border-radius: 999px;
  background: #edf4fb;
  color: #35506c;
  font-size: 12px;
}

.component-sidebar-popover {
  display: grid;
  gap: 10px;
}

.component-sidebar-popover strong {
  color: #21405e;
}

.component-sidebar-popover p {
  margin: 0;
}

.component-sidebar-popover-list {
  display: grid;
  gap: 10px;
}

.component-sidebar-popover-card {
  border: 1px solid #d8e2ee;
  border-radius: 12px;
  background: #fff;
  padding: 12px;
}

.component-sidebar-popover-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.component-detail-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 64px;
  padding: 4px 8px;
  border-radius: 999px;
  background: #edf4fb;
  color: #35506c;
  font-size: 12px;
  text-transform: lowercase;
}

.component-detail-status.is-success {
  background: #1e9b61;
  color: #fff;
}

.component-detail-status.is-warning {
  background: #de8f1f;
  color: #fff;
}

.component-detail-status.is-failed {
  background: #cf4a3c;
  color: #fff;
}

.component-detail-status.is-skipped {
  background: #7d74b6;
  color: #fff;
}

.runtime-priority-banner {
  margin-bottom: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid #d8e2ee;
  background: linear-gradient(180deg, #fffdf7 0%, #fff6e4 100%);
  display: grid;
  gap: 8px;
}

.runtime-priority-banner.is-empty {
  background: linear-gradient(180deg, #f8fbff 0%, #eef4fb 100%);
}

.runtime-priority-banner > span {
  color: #5a728c;
  font-size: 12px;
}

.runtime-priority-link {
  border: 0;
  background: none;
  padding: 0;
  color: #21405e;
  text-align: left;
  cursor: pointer;
  font: inherit;
}

.runtime-priority-link:hover {
  color: #0f5ba7;
}

.runtime-empty-panel {
  min-height: 120px;
  display: grid;
  place-items: center;
  gap: 8px;
  color: #69829b;
  text-align: center;
}

.runtime-empty-panel strong {
  color: #21405e;
}

.issue-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}

.issue-card {
  border: 1px solid #d8e2ee;
  border-radius: 14px;
  padding: 14px;
  background: #fff;
  cursor: pointer;
  text-align: left;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}

.issue-card:hover {
  transform: translateY(-1px);
  border-color: #5d8fbd;
  box-shadow: 0 10px 24px rgba(35, 73, 115, 0.1);
}

.issue-card-top,
.issue-card-metrics,
.issue-card-identities,
.recent-feed-meta,
.component-board-stats,
.component-board-footer {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  color: #69829b;
  font-size: 12px;
}

.component-board-highlights {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.component-board-highlights span {
  border-radius: 999px;
  padding: 4px 8px;
  background: #edf4fb;
  color: #45627f;
  font-size: 12px;
}

.issue-card-top {
  justify-content: space-between;
  margin-bottom: 10px;
}

.issue-card strong,
.recent-feed-item strong,
.component-board-card strong {
  display: block;
  color: #21405e;
}

.issue-card-headline,
.issue-card-subline,
.issue-card-summary,
.recent-feed-path {
  margin: 8px 0 0;
  color: #35506c;
}

.recent-feed-guardian-subtitle,
.guardian-step-expr {
  margin: 8px 0 0;
  color: #56718d;
  font-size: 13px;
}

.issue-card-subline,
.issue-card-summary,
.recent-feed-path {
  font-size: 13px;
}

.issue-card-metrics,
.issue-card-identities {
  margin-top: 10px;
}

.issue-card.is-failed {
  background: linear-gradient(180deg, #ffffff 0%, #fff1f0 100%);
}

.issue-card.is-warning {
  background: linear-gradient(180deg, #ffffff 0%, #fff8ec 100%);
}

.issue-card.is-skipped {
  background: linear-gradient(180deg, #ffffff 0%, #f5f2ff 100%);
}

.component-ledger {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  border: 1px solid #e5edf5;
  border-radius: 12px;
  background: #fff;
}

.component-ledger__header,
.component-ledger__row {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) 96px 84px 72px 72px;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  font-size: 12px;
}

.component-ledger__header {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #f6f9fc;
  color: #68839d;
  border-bottom: 1px solid #e5edf5;
}

.component-ledger__row {
  width: 100%;
  border: 0;
  border-bottom: 1px solid #e5edf5;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.component-ledger__row:hover,
.component-ledger__row.active {
  background: #eef6ff;
}

.component-ledger__component,
.component-ledger__runtime-node {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.component-ledger__component,
.component-ledger__runtime-node,
.runtime-ledger__cell--strong {
  color: #21405e;
  font-weight: 600;
}

.component-ledger__detail {
  padding: 8px 10px 12px;
  border-bottom: 1px solid #e5edf5;
  background: #f8fbff;
}

.component-ledger__runtime-header,
.component-ledger__runtime-row {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) 96px 78px 72px minmax(0, 1.9fr);
  align-items: start;
  gap: 8px;
  font-size: 12px;
}

.component-ledger__runtime-header {
  color: #68839d;
  margin-bottom: 8px;
}

.component-ledger__runtime-row + .component-ledger__runtime-row {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #dbe5ef;
}

.component-ledger__runtime-highlights {
  display: block;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  color: #45627f;
}

.component-ledger__runtime-highlights span + span {
  margin-left: 8px;
}

.runtime-ledger {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  border: 1px solid #e5edf5;
  border-radius: 12px;
  background: #fff;
}

.runtime-ledger__header,
.runtime-ledger__row {
  display: grid;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  font-size: 12px;
}

.runtime-ledger__header {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #f6f9fc;
  color: #68839d;
  border-bottom: 1px solid #e5edf5;
}

.runtime-ledger__row {
  width: 100%;
  border: 0;
  border-top: 1px solid #eef3f8;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.runtime-ledger__row:hover,
.runtime-ledger__row.active {
  background: #eef6ff;
}

.runtime-trace-ledger__grid {
  grid-template-columns:
    152px
    minmax(220px, 1.15fr)
    104px
    102px
    minmax(480px, 3.6fr)
    54px
    84px
    minmax(160px, 0.9fr);
}

.runtime-event-ledger__grid {
  grid-template-columns:
    152px
    144px
    140px
    140px
    112px
    180px
    minmax(260px, 1.45fr)
    minmax(220px, 1.15fr);
}

.runtime-ledger__cell {
  min-width: 0;
  color: #35506c;
}

.runtime-ledger__cell--truncate {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.runtime-ledger__cell--mono {
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12px;
}

.runtime-ledger__cell--number {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.runtime-ledger__cell--status {
  overflow: visible;
}

.runtime-ledger__cell--entry-exit {
  color: #21405e;
  font-weight: 600;
}

.runtime-inline-status,
.component-ledger__status,
.component-ledger__runtime-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 88px;
  box-sizing: border-box;
  padding: 4px 8px;
  border-radius: 999px;
  background: #edf4fb;
  color: #35506c;
  font-size: 12px;
  line-height: 1;
  text-transform: lowercase;
  white-space: nowrap;
}

.runtime-inline-status.is-success,
.component-ledger__runtime-status.is-success {
  background: #1e9b61;
  color: #fff;
}

.runtime-inline-status.is-warning,
.component-ledger__runtime-status.is-warning {
  background: #de8f1f;
  color: #fff;
}

.runtime-inline-status.is-failed,
.component-ledger__runtime-status.is-failed {
  background: #cf4a3c;
  color: #fff;
}

.runtime-inline-status.is-skipped,
.component-ledger__runtime-status.is-skipped {
  background: #7d74b6;
  color: #fff;
}

.recent-feed-tags,
.component-distribution {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.guardian-chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.recent-feed-tags span,
.component-distribution-chip,
.guardian-chip-list span {
  padding: 4px 8px;
  border-radius: 999px;
  background: #edf4fb;
  color: #35506c;
  font-size: 12px;
}

.component-distribution {
  margin-top: 14px;
}

.component-distribution-chip {
  border: 0;
  cursor: pointer;
  font: inherit;
}

.component-distribution-chip.active {
  background: #21405e;
  color: #fff;
}

.component-board-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.component-board-card {
  border: 1px solid #d8e2ee;
  border-radius: 14px;
  background: #fff;
  padding: 14px;
  cursor: pointer;
  text-align: left;
}

.component-board-card.active {
  border-color: #21405e;
  box-shadow: 0 10px 24px rgba(35, 73, 115, 0.1);
}

.component-board-card.is-warning {
  background: linear-gradient(180deg, #ffffff 0%, #fff8ec 100%);
}

.component-board-card.is-failed {
  background: linear-gradient(180deg, #ffffff 0%, #fff1f0 100%);
}

.component-board-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.component-board-head span {
  color: #69829b;
  font-size: 12px;
}

.component-board-stats {
  margin-bottom: 8px;
}

.advanced-filter-grid {
  display: grid;
  gap: 12px;
}

.advanced-filter-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 16px;
}

.health-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
}

.health-card {
  border-radius: 14px;
  padding: 14px;
  background: linear-gradient(180deg, #ffffff 0%, #f4f8fc 100%);
  border: 1px solid #dbe5ef;
}

.health-card-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  color: #1f3c5b;
}

.health-card-head span {
  color: #6a8198;
  font-size: 12px;
}

.health-card-body p,
.health-card-body li {
  margin: 6px 0;
  color: #39546f;
}

.health-card-body ul {
  padding-left: 16px;
  margin: 0;
}

.trace-toolbar {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr)) auto;
  gap: 10px;
  margin-bottom: 14px;
}

.trace-list-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr)) minmax(280px, 1.6fr);
  gap: 10px;
  margin-bottom: 14px;
}

.trace-list-summary-card {
  border: 1px solid #d8e2ee;
  border-radius: 12px;
  background: linear-gradient(180deg, #ffffff 0%, #f5f8fc 100%);
  padding: 12px;
}

.trace-list-summary-card > span {
  display: block;
  margin-bottom: 8px;
  color: #69829b;
  font-size: 12px;
}

.trace-list-summary-card strong {
  display: block;
  color: #21405e;
  font-size: 24px;
  line-height: 1;
}

.trace-list-summary-card--wide strong {
  font-size: 18px;
}

.trace-list-summary-components {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.trace-list-summary-components span {
  padding: 4px 8px;
  border-radius: 999px;
  background: #edf4fb;
  color: #35506c;
  font-size: 12px;
}

.trace-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(320px, 0.9fr);
  gap: 16px;
}

.trace-list,
.trace-detail {
  min-width: 0;
}

.trace-detail {
  display: flex;
  flex-direction: column;
  border: 1px solid #dfe7f3;
  border-radius: 14px;
  background: linear-gradient(180deg, #fbfdff 0%, #f4f8fc 100%);
  padding: 14px;
  min-height: 0;
  overflow: hidden;
}

.trace-detail--embedded {
  height: 100%;
}

.trace-detail-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.trace-detail-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.trace-summary-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.trace-summary-chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  background: #edf4fb;
  color: #31506e;
  font-size: 12px;
}

.trace-summary-chip.is-issue {
  background: #fff1f0;
  color: #9f2d24;
}

.trace-detail-body {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(280px, 0.9fr);
  gap: 14px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.trace-timeline-panel,
.step-inspector {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.trace-detail-body--stacked {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);
  gap: 12px;
}

.trace-detail-tabs-wrap,
.trace-detail-tabs {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.trace-detail-tabs-wrap > .runtime-detail-panel {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
}

.workspace-tab-label {
  display: flex;
  gap: 6px;
  align-items: center;
}

.tab-meta {
  font-size: 11px;
  font-weight: 400;
}

:deep(.workspace-tabs .el-tabs__header) {
  margin-bottom: 8px;
}

:deep(.workspace-tabs .el-tabs__content) {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

:deep(.workspace-tabs .el-tab-pane) {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.detail-pane-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  min-height: 0;
  align-items: stretch;
}

.detail-pane-grid--nested,
.detail-pane-grid--step,
.detail-pane-grid--raw {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.detail-ledger-section,
.detail-json-section {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border: 1px solid #e2eaf4;
  border-radius: 10px;
  background: #fbfdff;
  overflow: hidden;
}

.detail-ledger-section--full {
  grid-column: 1 / -1;
}

.detail-ledger-section__title {
  padding: 8px 10px;
  border-bottom: 1px solid #e6eef7;
  background: #f6f9fc;
  color: #66829c;
  font-size: 12px;
  font-weight: 600;
}

.detail-kv-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 12px;
}

.detail-kv-table th,
.detail-kv-table td {
  padding: 7px 10px;
  border-top: 1px solid #edf2f7;
  vertical-align: top;
}

.detail-kv-table tr:first-child th,
.detail-kv-table tr:first-child td {
  border-top: 0;
}

.detail-kv-table th {
  width: 118px;
  color: #68829b;
  text-align: left;
  font-weight: 500;
  background: #fbfdff;
}

.detail-kv-table td {
  color: #21405e;
  word-break: break-word;
}

.detail-kv-table td.is-mono {
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12px;
}

.detail-kv-table--full th {
  width: 156px;
}

.trace-summary-ledger,
.event-detail-ledger {
  flex: 1 1 auto;
}

.detail-json-section {
  background: #fff;
}

.detail-json-view {
  margin: 0;
  padding: 10px 12px;
  background: #0f2034;
  color: #dff0ff;
  font-size: 12px;
  line-height: 1.55;
  min-height: 160px;
  overflow: auto;
  flex: 1 1 auto;
}

.trace-identity-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.trace-identity-strip__item,
.trace-copy-chip,
.trace-copy-link {
  border: 0;
  background: none;
  padding: 0;
  color: inherit;
  cursor: pointer;
  font: inherit;
}

.trace-identity-strip__item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 999px;
  background: #edf4fb;
  color: #35506c;
  font-size: 12px;
}

.trace-identity-strip__item code {
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12px;
}

.trace-copy-chip {
  padding: 4px 10px;
  border-radius: 999px;
  background: #edf4fb;
}

.trace-copy-chip:hover,
.trace-copy-link:hover,
.trace-identity-strip__item:hover {
  color: #0f5ba7;
}

.runtime-detail-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.runtime-detail-tabs__tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  min-width: 84px;
  min-height: 30px;
  box-sizing: border-box;
  border: 1px solid #d8e2ee;
  border-radius: 10px;
  background: #fff;
  padding: 4px 12px;
  color: #5e7690;
  cursor: pointer;
  font: inherit;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
}

.runtime-detail-tabs__tab.active {
  border-color: #5d8fbd;
  background: #eef6ff;
  color: #21405e;
}

.runtime-detail-panel {
  border: 1px solid #d8e2ee;
  border-radius: 12px;
  background: #fff;
  padding: 12px;
  min-height: 0;
}

.runtime-detail-panel--fill {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  scrollbar-gutter: stable;
}

.runtime-detail-panel--steps {
  --trace-step-ledger-row-height: 40px;
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.runtime-detail-panel__toolbar,
.trace-ledger-toolbar,
.step-inspector-summary {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  color: #66829c;
  font-size: 12px;
}

.runtime-detail-panel__toolbar {
  margin-bottom: 10px;
}

.runtime-load-more {
  display: flex;
  justify-content: center;
  margin-top: 12px;
}

.runtime-load-more--detail {
  margin-top: 0;
  margin-bottom: 12px;
}

.trace-ledger-toolbar {
  margin-bottom: 10px;
}

.trace-ledger-toolbar__meta,
.trace-ledger-toolbar__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.trace-step-ledger {
  display: flex;
  flex-direction: column;
  flex: 0 0 auto;
  min-height: 0;
  max-height: calc(var(--trace-step-ledger-row-height) * 9 + 2px);
  overflow: auto;
  border: 1px solid #e5edf5;
  border-radius: 12px;
  background: #fff;
  margin-bottom: 12px;
}

.trace-step-ledger__header,
.trace-step-ledger__row {
  display: grid;
  grid-template-columns:
    40px
    152px
    72px
    minmax(200px, 1.25fr)
    112px
    112px
    160px
    128px
    72px
    minmax(190px, 1fr)
    minmax(190px, 1fr);
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  min-height: var(--trace-step-ledger-row-height);
  font-size: 12px;
}

.trace-step-ledger__header {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #f6f9fc;
  color: #68839d;
  border-bottom: 1px solid #e5edf5;
}

.trace-step-ledger__row {
  width: 100%;
  border: 0;
  border-top: 1px solid #eef3f8;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.trace-step-ledger__row:hover,
.trace-step-ledger__row.active {
  background: #eef6ff;
}

.trace-step-ledger__row.is-issue {
  background: #fff9f2;
}

.trace-definition-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.trace-definition-card {
  border: 1px solid #e5edf5;
  border-radius: 12px;
  background: #fff;
  padding: 12px;
}

.trace-definition-card h4 {
  margin: 0 0 10px;
  color: #21405e;
}

.trace-definition-list {
  display: grid;
  gap: 8px;
}

.trace-definition-row {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  align-items: start;
  gap: 10px;
  color: #66829c;
  font-size: 12px;
}

.trace-definition-row code {
  color: #2e4d69;
  white-space: normal;
  word-break: break-word;
}

.trace-step-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 66px;
  padding: 4px 8px;
  border-radius: 999px;
  background: #edf4fb;
  color: #35506c;
  font-size: 12px;
  text-transform: lowercase;
}

.trace-step-tags,
.inspector-tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 8px 0 0;
}

.trace-step-tags span,
.inspector-tag {
  padding: 4px 8px;
  border-radius: 999px;
  background: #f1f5fa;
  color: #4b6580;
  font-size: 12px;
}

.trace-step-card p {
  margin: 4px 0;
  color: #46607a;
}

.trace-step-card.is-success .trace-step-marker,
.trace-step-card.is-success .trace-step-status,
.step-inspector-head.is-success .trace-step-status {
  background: #1e9b61;
  color: #fff;
}

.trace-step-card.is-warning .trace-step-marker,
.trace-step-card.is-warning .trace-step-status,
.step-inspector-head.is-warning .trace-step-status {
  background: #de8f1f;
  color: #fff;
}

.trace-step-card.is-failed .trace-step-marker,
.trace-step-card.is-failed .trace-step-status,
.step-inspector-head.is-failed .trace-step-status {
  background: #cf4a3c;
  color: #fff;
}

.trace-step-card.is-skipped .trace-step-marker,
.trace-step-card.is-skipped .trace-step-status,
.step-inspector-head.is-skipped .trace-step-status {
  background: #7d74b6;
  color: #fff;
}

.trace-step-card.is-success {
  background: linear-gradient(180deg, #ffffff 0%, #f2fbf6 100%);
}

.trace-step-card.is-warning {
  background: linear-gradient(180deg, #ffffff 0%, #fff8ec 100%);
}

.trace-step-card.is-failed {
  background: linear-gradient(180deg, #ffffff 0%, #fff1f0 100%);
}

.trace-step-card.is-skipped {
  background: linear-gradient(180deg, #ffffff 0%, #f5f2ff 100%);
}

.step-inspector {
  flex: 1 1 auto;
  border: 1px solid #d8e2ee;
  border-radius: 12px;
  background: #fff;
  padding: 12px;
  min-height: 0;
  overflow: auto;
}

.step-inspector-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  padding: 12px;
  border-radius: 12px;
  margin-bottom: 10px;
  background: #f4f8fc;
}

.step-inspector-head strong {
  display: block;
  color: #1d3b58;
}

.step-inspector-head p {
  margin: 6px 0 0;
  color: #6b859e;
  font-size: 12px;
}

.step-inspector-head.is-success {
  background: #eefaf3;
}

.step-inspector-head.is-warning {
  background: #fff6e6;
}

.step-inspector-head.is-failed {
  background: #fff0ef;
}

.step-inspector-head.is-skipped {
  background: #f4f1ff;
}

.step-inspector-section {
  margin-top: 14px;
}

.step-inspector-flags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.step-inspector-section h4 {
  margin: 0 0 8px;
  color: #274564;
}

.inspector-field-row {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 8px 0;
  border-top: 1px solid #edf2f7;
}

.inspector-field-row:first-of-type {
  border-top: 0;
}

.inspector-field-row span {
  color: #68829b;
  font-size: 12px;
}

.inspector-field-row code {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #2e4d69;
}

.guardian-context-item {
  display: grid;
  gap: 6px;
  padding: 8px 0;
  border-top: 1px solid #edf2f7;
}

.guardian-context-item:first-child {
  border-top: 0;
}

.guardian-context-item span {
  color: #68829b;
  font-size: 12px;
}

.guardian-context-item code {
  color: #2e4d69;
  white-space: normal;
  word-break: break-word;
}

.step-inspector-actions {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-top: 16px;
}

.trace-empty {
  min-height: 200px;
  display: grid;
  place-items: center;
  color: #6a8198;
}

.raw-toolbar {
  display: grid;
  grid-template-columns: 1fr 1fr 160px 280px auto auto;
  gap: 10px;
  margin-bottom: 14px;
}

.raw-focus-banner {
  margin-bottom: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #eef4fb;
  color: #35506c;
  font-size: 12px;
}

.raw-record-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1 1 auto;
  max-height: none;
  min-height: 0;
  overflow: auto;
}

.raw-record-card {
  border: 1px solid #d8e2ee;
  border-radius: 12px;
  background: #fff;
  padding: 12px;
}

.raw-record-card.active {
  border-color: #5d8fbd;
  box-shadow: 0 10px 24px rgba(35, 73, 115, 0.1);
}

.raw-record-card header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.raw-record-card header strong {
  color: #20405e;
}

.raw-record-card header span {
  color: #6a8198;
  font-size: 12px;
}

.raw-record-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.raw-record-badges span {
  padding: 4px 8px;
  border-radius: 999px;
  background: #edf4fb;
  color: #35506c;
  font-size: 12px;
}

.embedded-raw-ledger {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: auto;
  border: 1px solid #e5edf5;
  border-radius: 12px;
  background: #fff;
}

.embedded-raw-ledger__header,
.embedded-raw-ledger__row {
  display: grid;
  grid-template-columns: minmax(180px, 0.9fr) minmax(280px, 1.45fr) minmax(180px, 0.75fr);
  gap: 8px;
  padding: 8px 10px;
  font-size: 12px;
  align-items: center;
}

.embedded-raw-ledger__header {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #f6f9fc;
  color: #68839d;
  border-bottom: 1px solid #e5edf5;
}

.embedded-raw-ledger__entry {
  border-top: 1px solid #eef3f8;
  background: #fff;
}

.embedded-raw-ledger__entry:first-of-type {
  border-top: 0;
}

.embedded-raw-ledger__entry.active {
  background: #eef6ff;
}

.embedded-raw-ledger__row {
  background: transparent;
}

.embedded-raw-ledger__entry .detail-json-view {
  min-height: 140px;
  border-top: 1px solid #edf2f7;
}

.raw-content {
  margin: 0;
  min-height: 120px;
  max-height: 48vh;
  overflow: auto;
  padding: 16px;
  border-radius: 12px;
  background: #102033;
  color: #dff0ff;
  font-size: 12px;
  line-height: 1.55;
}

:deep(.runtime-trace-row--issue) td {
  background: #fff7f5 !important;
}

@media (max-width: 1600px) {
  .runtime-browse-layout {
    grid-template-columns: minmax(220px, 0.72fr) minmax(0, 1.28fr);
  }

  .runtime-browser-panel--detail {
    grid-column: 1 / -1;
    min-height: 520px;
  }
}

@media (max-width: 1080px) {
  .runtime-title-row,
  .runtime-browse-layout,
  .runtime-home-head,
  .runtime-home-actions,
  .recent-feed-item,
  .recent-feed-topline,
  .recent-feed-heading,
  .component-sidebar-main,
  .component-sidebar-popover-head,
  .component-board-head,
  .trace-toolbar,
  .trace-list-summary,
  .raw-toolbar,
  .trace-layout,
  .trace-detail-body,
  .trace-identity-grid,
  .trace-summary-grid,
  .guardian-trace-grid,
  .guardian-context-grid {
    grid-template-columns: 1fr;
  }

  .trace-detail-head,
  .step-inspector-actions,
  .trace-timeline-hint,
  .trace-affected-row,
  .raw-record-card header,
  .issue-card-top,
  .guardian-trace-head {
    flex-direction: column;
    align-items: stretch;
  }

  .inspector-field-row {
    grid-template-columns: 1fr;
  }

  .trace-flow-popover-item {
    grid-template-columns: 1fr;
  }
}
</style>
