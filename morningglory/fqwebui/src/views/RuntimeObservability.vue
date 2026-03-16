<template>
  <div class="workbench-page runtime-page">
    <MyHeader />
    <div class="workbench-body runtime-shell">
      <section class="workbench-toolbar runtime-section runtime-section--workbench">
        <div class="workbench-toolbar__header runtime-title-row">
          <div class="workbench-title-group">
            <div class="workbench-page-title">运行观测</div>
            <div class="workbench-page-meta">
              <span>主视图拆为全局 Trace 与组件 Event，分别回答“链路发生了什么”和“组件最近有没有工作”。</span>
            </div>
          </div>
          <div class="workbench-toolbar__actions runtime-title-actions">
            <el-radio-group v-model="activeView" size="small" class="runtime-view-switch">
              <el-radio-button label="traces">全局 Trace</el-radio-button>
              <el-radio-button label="events">组件 Event</el-radio-button>
            </el-radio-group>
            <el-switch
              v-model="autoRefresh"
              inline-prompt
              active-text="自动刷新"
              inactive-text="手动"
            />
            <el-switch
              v-model="onlyIssues"
              inline-prompt
              active-text="仅异常"
              inactive-text="全部"
            />
            <el-button @click="openAdvancedFilter">高级筛选</el-button>
            <el-button type="primary" :loading="loading.overview" @click="loadOverview">刷新</el-button>
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
          <span class="workbench-summary-chip workbench-summary-chip--warning">
            异常链路 <strong>{{ traceListSummary.issue_trace_count }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--danger">
            异常节点 <strong>{{ traceListSummary.issue_step_count }}</strong>
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
              <p>组件筛选和运行健康统一压成台账，展开后直接看 runtime node 明细。</p>
            </div>
            <span class="runtime-home-meta">核心组件 {{ componentSidebarItems.length }} 个</span>
          </div>

          <div class="component-ledger">
            <div class="component-ledger__header">
              <span>组件</span>
              <span>状态</span>
              <span>心跳</span>
              <span>异常链路</span>
              <span>异常节点</span>
            </div>
            <div
              v-for="item in componentSidebarItems"
              :key="item.component"
              class="component-ledger__entry"
            >
              <button
                type="button"
                class="component-ledger__row"
                :class="[statusClass(item.status), { active: activeComponent === item.component }]"
                @click="handleComponentFilter(item.component)"
              >
                <span class="component-ledger__component">{{ item.component }}</span>
                <span class="component-ledger__status">{{ item.status }}</span>
                <span class="component-ledger__heartbeat">{{ item.heartbeat_label }}</span>
                <span>{{ item.issue_trace_count }}</span>
                <span>{{ item.issue_step_count }}</span>
              </button>

              <div v-if="activeComponent === item.component" class="component-ledger__detail">
                <div class="component-ledger__runtime-header">
                  <span>runtime node</span>
                  <span>状态</span>
                  <span>心跳</span>
                  <span>异常</span>
                  <span>highlights</span>
                </div>
                <div
                  v-for="detail in item.runtime_details"
                  :key="`${item.component}-${detail.runtime_node}`"
                  class="component-ledger__runtime-row"
                >
                  <span class="component-ledger__runtime-node">{{ detail.runtime_node }}</span>
                  <span class="component-ledger__runtime-status" :class="statusClass(detail.status)">
                    {{ detail.status }}
                  </span>
                  <span>{{ detail.heartbeat_label }}</span>
                  <span>{{ detail.issue_trace_count }}/{{ detail.issue_step_count }}</span>
                  <span class="component-ledger__runtime-highlights">
                    <template v-if="detail.highlights.length">
                      <span
                        v-for="highlight in detail.highlights"
                        :key="`${item.component}-${detail.runtime_node}-${highlight.key}`"
                      >
                        {{ highlight.label }} {{ highlight.display }}
                      </span>
                    </template>
                    <span v-else>no data</span>
                  </span>
                </div>
              </div>
            </div>
          </div>
        </aside>

          <section class="workbench-panel runtime-browser-panel runtime-browser-panel--feed">
            <template v-if="activeView === 'traces'">
              <div class="runtime-home-head">
                <div>
                  <h2>全局 Trace</h2>
                  <p>主表直接给出最近链路的入口、出口、断裂原因和慢点，右侧默认看完整 Step 台账。</p>
                </div>
                <div class="runtime-home-actions">
                  <span class="runtime-home-meta">当前显示 {{ traceLedgerRows.length }} 条</span>
                  <el-button v-if="recentTraceLimit < 50" text @click="showMoreRecentTraces">查看更多</el-button>
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
                  <span>last_ts</span>
                  <span>symbol</span>
                  <span>identity</span>
                  <span>kind</span>
                  <span>status</span>
                  <span>entry -> exit</span>
                  <span>steps</span>
                  <span>duration</span>
                  <span>break_reason</span>
                  <span>slowest</span>
                </div>
                <button
                  v-for="row in traceLedgerRows"
                  :key="row.trace_key || row.trace_id"
                  type="button"
                  class="runtime-ledger__row runtime-trace-ledger__grid"
                  :class="{ active: isActiveTraceRow(row) }"
                  @click="handleRecentTraceClick(row)"
                >
                  <span class="runtime-ledger__cell runtime-ledger__cell--mono">{{ row.last_ts || '-' }}</span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--strong">{{ row.symbol || '-' }}</span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--mono">{{ row.identity || '-' }}</span>
                  <span class="runtime-ledger__cell">{{ row.trace_kind_label }}</span>
                  <span class="runtime-ledger__cell">
                    <span class="runtime-inline-status" :class="statusClass(row.trace_status)">
                      {{ row.trace_status_label }}
                    </span>
                  </span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--truncate">{{ row.entry_exit_label }}</span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--number">{{ row.step_count }}</span>
                  <span class="runtime-ledger__cell">{{ row.duration_label }}</span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--truncate">{{ row.break_reason || '-' }}</span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--truncate">{{ row.slowest_step_label }}</span>
                </button>
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
                <span>ts</span>
                <span>runtime_node</span>
                <span>component</span>
                <span>node</span>
                <span>status</span>
                <span>symbol</span>
                <span>identity</span>
                <span>summary</span>
                <span>metrics</span>
              </div>
              <button
                v-for="(row, rowIndex) in eventLedgerRows"
                :key="row.event_key"
                type="button"
                class="runtime-ledger__row runtime-event-ledger__grid"
                :class="{ active: isActiveEventRow(componentEventFeed[rowIndex]) }"
                @click="handleEventClick(componentEventFeed[rowIndex])"
              >
                <span class="runtime-ledger__cell runtime-ledger__cell--mono">{{ row.ts || '-' }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--mono">{{ row.runtime_node }}</span>
                <span class="runtime-ledger__cell">{{ row.component }}</span>
                <span class="runtime-ledger__cell">{{ row.node }}</span>
                <span class="runtime-ledger__cell">
                  <span class="runtime-inline-status" :class="statusClass(row.status)">
                    {{ row.status }}
                  </span>
                </span>
                <span class="runtime-ledger__cell runtime-ledger__cell--strong">{{ row.symbol || '-' }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--mono">{{ row.identity || '-' }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--truncate">{{ row.summary || '-' }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--truncate">{{ row.metrics_summary || '-' }}</span>
              </button>
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
              <div v-if="selectedTrace" class="trace-summary-chips">
                <span class="trace-summary-chip">{{ selectedTraceDetail.trace_kind || 'unknown' }}</span>
                <span class="trace-summary-chip">{{ selectedTraceDetail.trace_status || 'open' }}</span>
                <span class="trace-summary-chip">steps {{ selectedTraceDetail.step_count }}</span>
                <span class="trace-summary-chip" :class="{ 'is-issue': selectedTraceDetail.issue_count > 0 }">
                  issues {{ selectedTraceDetail.issue_count }}
                </span>
                <span class="trace-summary-chip">duration {{ selectedTraceDetail.duration_label || selectedTraceDetail.total_duration_label }}</span>
                <span v-if="selectedTraceDetail.break_reason" class="trace-summary-chip is-issue">
                  {{ selectedTraceDetail.break_reason }}
                </span>
              </div>
            </div>
            <div class="trace-detail-actions">
              <el-button :disabled="!selectedStep" @click="openRawBrowser">Raw</el-button>
            </div>
          </div>
            <div v-if="selectedTrace" class="trace-detail-body trace-detail-body--stacked">
              <div v-if="traceIdentityStrip.items.length" class="trace-identity-strip">
                <button
                  v-for="item in traceIdentityStrip.items"
                  :key="item.key"
                  type="button"
                  class="trace-identity-strip__item"
                  @click="copyText(item.value)"
                >
                  <span>{{ item.label }}</span>
                  <code>{{ item.value }}</code>
                </button>
              </div>

              <div class="runtime-detail-tabs">
                <button
                  type="button"
                  class="runtime-detail-tabs__tab"
                  :class="{ active: activeTraceDetailTab === 'steps' }"
                  @click="activeTraceDetailTab = 'steps'"
                >
                  Steps
                </button>
                <button
                  type="button"
                  class="runtime-detail-tabs__tab"
                  :class="{ active: activeTraceDetailTab === 'summary' }"
                  @click="activeTraceDetailTab = 'summary'"
                >
                  Summary
                </button>
                <button
                  type="button"
                  class="runtime-detail-tabs__tab"
                  :class="{ active: activeTraceDetailTab === 'raw' }"
                  @click="activeTraceDetailTab = 'raw'"
                >
                  Raw
                </button>
              </div>

              <section v-show="activeTraceDetailTab === 'summary'" class="runtime-detail-panel runtime-detail-panel--summary">
                <div class="trace-timeline-panel">
                <section v-if="guardianTrace" class="guardian-trace-panel">
                  <div class="guardian-trace-head">
                    <div>
                      <h3>Guardian 视角</h3>
                      <p>直接展示当前信号、最终结论和关键原因。</p>
                    </div>
                    <span class="guardian-status-badge" :class="statusClass(guardianTrace.conclusion?.status)">
                      {{ guardianTrace.conclusion?.label || '-' }}
                    </span>
                  </div>
                  <div class="guardian-trace-grid">
                    <article class="guardian-trace-card">
                      <span>信号摘要</span>
                      <strong>{{ guardianTrace.signal?.title || '-' }}</strong>
                      <p>{{ guardianTrace.signal?.subtitle || '无结构化信号摘要' }}</p>
                      <div class="guardian-chip-list">
                        <span v-for="tag in guardianTrace.signal?.tags || []" :key="`guardian-trace-tag-${tag}`">
                          {{ tag }}
                        </span>
                      </div>
                    </article>
                    <article class="guardian-trace-card">
                      <span>最终结论</span>
                      <strong>{{ guardianTrace.conclusion?.label || '-' }}</strong>
                      <p>{{ guardianTrace.conclusion?.node_label || '-' }}</p>
                      <div class="guardian-chip-list">
                        <span v-if="guardianTrace.conclusion?.reason_code">
                          原因 {{ guardianTrace.conclusion.reason_code }}
                        </span>
                        <span v-if="guardianTrace.conclusion?.branch">
                          分支 {{ guardianTrace.conclusion.branch }}
                        </span>
                        <span v-if="guardianTrace.conclusion?.expr">
                          条件 {{ guardianTrace.conclusion.expr }}
                        </span>
                      </div>
                    </article>
                  </div>
                </section>

                <div class="trace-summary-grid">
                  <article class="trace-summary-card">
                    <span>开始时间</span>
                    <strong>{{ selectedTraceDetail.first_ts || '-' }}</strong>
                  </article>
                  <article class="trace-summary-card">
                    <span>结束时间</span>
                    <strong>{{ selectedTraceDetail.last_ts || '-' }}</strong>
                  </article>
                  <article class="trace-summary-card">
                    <span>入口 -> 出口</span>
                    <strong>{{ `${selectedTraceDetail.entry_component}.${selectedTraceDetail.entry_node}` }}</strong>
                    <em>{{ `${selectedTraceDetail.exit_component}.${selectedTraceDetail.exit_node}` }}</em>
                  </article>
                  <article class="trace-summary-card">
                    <span>最长耗时</span>
                    <strong>{{ traceSummaryMeta.slowest_step ? `${traceSummaryMeta.slowest_step.component}.${traceSummaryMeta.slowest_step.node}` : '-' }}</strong>
                    <em>{{ traceSummaryMeta.slowest_step?.delta_from_prev_label || '-' }}</em>
                  </article>
                </div>

                <div class="trace-issue-banner" :class="{ 'is-empty': issueSummary.items.length === 0 }">
                  {{ issueSummary.headline }}
                </div>

                <div class="trace-affected-row">
                  <span>涉及组件</span>
                  <div class="trace-affected-list">
                    <span v-for="component in traceSummaryMeta.affected_components" :key="component">{{ component }}</span>
                    <span v-if="traceSummaryMeta.affected_components.length === 0">-</span>
                  </div>
                </div>

              </div>
            </section>

            <section v-show="activeTraceDetailTab === 'steps'" class="runtime-detail-panel">
              <div class="trace-ledger-toolbar">
                <span>{{ onlyIssues ? '仅显示异常节点' : '显示全部节点' }}</span>
                <span>可见 {{ traceStepLedgerRows.length }} / {{ selectedTraceDetail.step_count }}</span>
              </div>

              <div v-if="traceStepLedgerRows.length" class="trace-step-ledger">
                <div class="trace-step-ledger__header trace-step-ledger__grid">
                  <span>#</span>
                  <span>ts</span>
                  <span>delta</span>
                  <span>component.node</span>
                  <span>status</span>
                  <span>branch</span>
                  <span>expr</span>
                  <span>reason</span>
                  <span>outcome</span>
                  <span>context</span>
                  <span>error</span>
                </div>
                <button
                  v-for="(row, rowIndex) in traceStepLedgerRows"
                  :key="row.step_key"
                  type="button"
                  class="trace-step-ledger__row trace-step-ledger__grid"
                  :class="[statusClass(row.status), { active: isActiveStep(filteredSteps[rowIndex]), 'is-issue': row.is_issue }]"
                  @click="handleStepSelect(filteredSteps[rowIndex])"
                >
                  <span class="runtime-ledger__cell runtime-ledger__cell--number">{{ row.index + 1 }}</span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--mono">{{ row.ts || '-' }}</span>
                  <span class="runtime-ledger__cell">{{ row.delta_label || '-' }}</span>
                  <span class="runtime-ledger__cell runtime-ledger__cell--strong">{{ row.component_node }}</span>
                  <span class="runtime-ledger__cell">
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
              <div v-else class="trace-empty">当前过滤条件下没有节点</div>

              <aside class="step-inspector">
                <template v-if="selectedStep">
                  <div class="step-inspector-head" :class="statusClass(selectedStep.status)">
                    <div>
                      <strong>{{ selectedStep.component }}.{{ selectedStep.node }}</strong>
                      <p>{{ selectedStep.ts || '-' }}</p>
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

                  <section v-if="selectedStep.guardian_step?.signal" class="step-inspector-section">
                    <h4>Guardian 信号</h4>
                    <div class="guardian-signal-card">
                      <strong>{{ selectedStep.guardian_step.signal.title }}</strong>
                      <p>{{ selectedStep.guardian_step.signal.subtitle || '无附加摘要' }}</p>
                      <div class="guardian-chip-list">
                        <span v-for="tag in selectedStep.guardian_step.signal.tags" :key="`${stepKey(selectedStep)}-signal-tag-${tag}`">
                          {{ tag }}
                        </span>
                      </div>
                    </div>
                    <div
                      v-for="item in selectedStep.guardian_step.signal.items"
                      :key="`${stepKey(selectedStep)}-signal-${item.key}`"
                      class="inspector-field-row"
                    >
                      <span>{{ item.label }}</span>
                      <code>{{ item.value }}</code>
                      <button type="button" class="trace-copy-link" @click.stop="copyText(item.value)">复制</button>
                    </div>
                  </section>

                  <section v-if="selectedStep.guardian_step" class="step-inspector-section">
                    <h4>Guardian 判断</h4>
                    <div class="guardian-chip-list">
                      <span>节点 {{ selectedStep.guardian_step.node_label }}</span>
                      <span>结果 {{ selectedStep.guardian_step.outcome.label }}</span>
                      <span v-if="selectedStep.guardian_step.outcome.branch">
                        分支 {{ selectedStep.guardian_step.outcome.branch }}
                      </span>
                      <span v-if="selectedStep.guardian_step.outcome.reason_code">
                        原因 {{ selectedStep.guardian_step.outcome.reason_code }}
                      </span>
                    </div>
                    <p v-if="selectedStep.guardian_step.outcome.expr" class="guardian-step-expr">
                      条件：{{ selectedStep.guardian_step.outcome.expr }}
                    </p>
                  </section>

                  <section v-if="selectedStep.guardian_step?.context_blocks?.length" class="step-inspector-section">
                    <h4>Guardian 上下文</h4>
                    <div v-for="block in selectedStep.guardian_step.context_blocks" :key="`${stepKey(selectedStep)}-${block.key}`" class="guardian-context-block">
                      <strong>{{ block.label }}</strong>
                      <div class="guardian-context-grid">
                        <div v-for="item in block.items" :key="`${stepKey(selectedStep)}-${block.key}-${item.key}`" class="guardian-context-item">
                          <span>{{ item.key }}</span>
                          <code>{{ item.value }}</code>
                        </div>
                      </div>
                    </div>
                  </section>

                  <section class="step-inspector-section">
                    <h4>关联字段</h4>
                    <div v-for="field in selectedStep.detail_fields" :key="`${stepKey(selectedStep)}-${field.key}`" class="inspector-field-row">
                      <span>{{ field.key }}</span>
                      <code>{{ field.value }}</code>
                      <button type="button" class="trace-copy-link" @click.stop="copyText(field.value)">复制</button>
                    </div>
                  </section>

                  <section v-if="selectedStep.tags.length" class="step-inspector-section">
                    <h4>分支判断</h4>
                    <div class="inspector-tag-list">
                      <span v-for="tag in selectedStep.tags" :key="`${stepKey(selectedStep)}-detail-${tag.key}`" class="inspector-tag">
                        {{ tag.label }}: {{ tag.value }}
                      </span>
                    </div>
                  </section>

                  <section v-if="selectedStep.payload_text" class="step-inspector-section">
                    <h4>Payload</h4>
                    <pre>{{ selectedStep.payload_text }}</pre>
                  </section>

                  <section v-if="selectedStep.metrics_text" class="step-inspector-section">
                    <h4>Metrics</h4>
                    <pre>{{ selectedStep.metrics_text }}</pre>
                  </section>

                  <div class="step-inspector-actions">
                    <el-button type="primary" plain @click="openRawFromStep(selectedStep)">查看 Raw</el-button>
                    <el-button text @click="copyText(buildStepCopyText(selectedStep))">复制节点摘要</el-button>
                  </div>
                </template>
                <div v-else class="trace-empty">暂无选中节点</div>
              </aside>
            </section>

            <section v-show="activeTraceDetailTab === 'raw'" class="runtime-detail-panel">
              <div class="runtime-detail-panel__toolbar">
                <span>{{ selectedStep ? `${selectedStep.component}.${selectedStep.node}` : '选择一个 Step 后可直接定位 Raw' }}</span>
                <el-button type="primary" plain :disabled="!selectedStep" @click="openRawBrowser">打开 Raw Browser</el-button>
              </div>
              <div v-if="rawRecordCards.length" class="raw-record-list raw-record-list--embedded">
                <article
                  v-for="(record, index) in rawRecordCards"
                  :key="`${record.title}-${record.subtitle}-${index}`"
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
              <div v-else class="trace-empty">尚未加载 Raw，点击上方按钮拉取当前节点的原始记录。</div>
            </section>
          </div>
          <div v-else class="trace-empty">暂无选中链路</div>
          </div>
            <div v-else class="trace-detail trace-detail--embedded">
              <div class="trace-detail-head">
                <div>
                  <strong>{{ selectedEvent ? `${selectedEvent.component}.${selectedEvent.node}` : '选择一个组件 Event' }}</strong>
                  <div v-if="selectedEvent" class="trace-summary-chips">
                    <span class="trace-summary-chip">{{ selectedEvent.event_type || 'trace_step' }}</span>
                    <span class="trace-summary-chip">{{ selectedEvent.status || 'info' }}</span>
                    <span class="trace-summary-chip">{{ selectedEvent.runtime_node || '-' }}</span>
                  </div>
                </div>
                <div class="trace-detail-actions">
                  <el-button :disabled="!selectedEvent" @click="openRawBrowser">Raw</el-button>
                </div>
              </div>
              <div v-if="selectedEvent" class="trace-detail-body trace-detail-body--stacked">
                <div v-if="eventIdentityStrip.items.length" class="trace-identity-strip">
                  <button
                    v-for="item in eventIdentityStrip.items"
                    :key="item.key"
                    type="button"
                    class="trace-identity-strip__item"
                    @click="copyText(item.value)"
                  >
                    <span>{{ item.label }}</span>
                    <code>{{ item.value }}</code>
                  </button>
                </div>

                <div class="runtime-detail-tabs event-detail-tabs">
                  <button
                    type="button"
                    class="runtime-detail-tabs__tab"
                    :class="{ active: activeEventDetailTab === 'event' }"
                    @click="activeEventDetailTab = 'event'"
                  >
                    Event
                  </button>
                  <button
                    type="button"
                    class="runtime-detail-tabs__tab"
                    :class="{ active: activeEventDetailTab === 'payload' }"
                    @click="activeEventDetailTab = 'payload'"
                  >
                    Payload
                  </button>
                  <button
                    type="button"
                    class="runtime-detail-tabs__tab"
                    :class="{ active: activeEventDetailTab === 'raw' }"
                    @click="activeEventDetailTab = 'raw'"
                  >
                    Raw
                  </button>
                </div>

                <section v-show="activeEventDetailTab === 'event'" class="step-inspector">
                  <div class="step-inspector-head" :class="statusClass(selectedEvent.status)">
                    <div>
                      <strong>{{ selectedEvent.component }}.{{ selectedEvent.node }}</strong>
                      <p>{{ selectedEvent.ts || '-' }}</p>
                    </div>
                    <span class="trace-step-status">{{ selectedEvent.status || 'info' }}</span>
                  </div>

                  <div class="step-inspector-summary">
                    <span>{{ selectedEvent.event_type || 'trace_step' }}</span>
                    <span>{{ selectedEvent.runtime_node || '-' }}</span>
                  </div>

                  <div v-if="selectedEvent.badges.length" class="inspector-tag-list">
                    <span v-for="badge in selectedEvent.badges" :key="`${selectedEvent.key}-${badge}`" class="inspector-tag">
                      {{ badge }}
                    </span>
                  </div>

                  <section v-if="selectedEvent.summary_metrics.length" class="step-inspector-section">
                    <h4>Metrics 摘要</h4>
                    <div class="guardian-chip-list">
                      <span v-for="metric in selectedEvent.summary_metrics" :key="`${selectedEvent.key}-${metric.key}`">
                        {{ metric.label }} {{ metric.display }}
                      </span>
                    </div>
                  </section>

                  <section v-if="selectedEvent.summary" class="step-inspector-section">
                    <h4>摘要</h4>
                    <p class="recent-feed-path">{{ selectedEvent.summary }}</p>
                  </section>
                </section>

                <section v-show="activeEventDetailTab === 'payload'" class="runtime-detail-panel">
                  <section v-if="selectedEvent.payload_text" class="step-inspector-section">
                    <h4>Payload</h4>
                    <pre>{{ selectedEvent.payload_text }}</pre>
                  </section>

                  <section v-if="selectedEvent.metrics_text" class="step-inspector-section">
                    <h4>Metrics</h4>
                    <pre>{{ selectedEvent.metrics_text }}</pre>
                  </section>

                  <div class="step-inspector-actions">
                    <el-button type="primary" plain @click="openRawFromStep(selectedEvent)">查看 Raw</el-button>
                    <el-button text @click="copyText(buildEventCopyText(selectedEvent))">复制事件摘要</el-button>
                  </div>
                </section>

                <section v-show="activeEventDetailTab === 'raw'" class="runtime-detail-panel">
                  <div class="runtime-detail-panel__toolbar">
                    <span>{{ selectedEvent.component }}.{{ selectedEvent.node }}</span>
                    <el-button type="primary" plain @click="openRawBrowser">打开 Raw Browser</el-button>
                  </div>
                  <div v-if="rawRecordCards.length" class="raw-record-list raw-record-list--embedded">
                    <article
                      v-for="(record, index) in rawRecordCards"
                      :key="`${record.title}-${record.subtitle}-${index}`"
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
                  <div v-else class="trace-empty">尚未加载 Raw，点击上方按钮拉取当前事件的原始记录。</div>
                </section>
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
  buildIdentityStrip,
  buildIssuePriorityCards,
  buildTraceListSummary,
  buildIssueSummary,
  buildRawRecordSummary,
  buildTraceLedgerRows,
  buildTraceSummaryMeta,
  buildTraceDetail,
  buildTraceStepLedgerRows,
  buildHealthCards,
  buildRawLookupFromStep,
  buildTraceQuery,
  createTraceQueryState,
  findTraceByRow,
  findRawRecordIndex,
  filterTraceSteps,
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
  raw: false,
})

const query = reactive(createTraceQueryState())
const draftQuery = reactive(createTraceQueryState())

const healthCards = ref([])
const traces = ref([])
const events = ref([])
const selectedTrace = ref(null)
const selectedStep = ref(null)
const selectedEvent = ref(null)
const activeView = ref('traces')
const onlyIssues = ref(false)
const autoRefresh = ref(false)
const advancedFilterVisible = ref(false)
const recentTraceLimit = ref(20)
const activeTraceDetailTab = ref('steps')
const activeEventDetailTab = ref('event')
const rawDrawerVisible = ref(false)
const rawFiles = ref([])
const rawRecords = ref([])
const rawFocusedIndex = ref(-1)
const rawRecordRefs = ref({})
const pageError = ref('')
const boardFilter = reactive({
  component: '',
  runtime_node: '',
})
const rawQuery = reactive({
  runtime_node: '',
  component: '',
  date: '',
  file: '',
})
let overviewTimer = null

const visibleTraces = computed(() => {
  if (!onlyIssues.value) return traces.value
  return traces.value.filter((trace) => buildTraceDetail(trace).issue_count > 0)
})
const traceListSummary = computed(() => buildTraceListSummary(visibleTraces.value))
const issuePriorityCards = computed(() => buildIssuePriorityCards(visibleTraces.value))
const traceLedgerRows = computed(() =>
  buildTraceLedgerRows(visibleTraces.value, { limit: recentTraceLimit.value }),
)
const componentSidebarItems = computed(() => buildComponentSidebarItems(traces.value, healthCards.value))
const activeComponent = computed(() => String(boardFilter.component || '').trim())
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
  return chips
})

const selectedTraceDetail = computed(() => buildTraceDetail(selectedTrace.value || {}))
const guardianTrace = computed(() => selectedTraceDetail.value.guardian_trace || null)
const traceSummaryMeta = computed(() => buildTraceSummaryMeta(selectedTraceDetail.value))
const issueSummary = computed(() => buildIssueSummary(selectedTraceDetail.value))
const filteredSteps = computed(() => {
  return filterTraceSteps(selectedTraceDetail.value.steps, { onlyIssues: onlyIssues.value })
})
const traceStepLedgerRows = computed(() =>
  buildTraceStepLedgerRows({
    ...selectedTraceDetail.value,
    steps: filteredSteps.value,
  }),
)
const traceIdentityStrip = computed(() => buildIdentityStrip(selectedTraceDetail.value))
const eventIdentityStrip = computed(() => buildIdentityStrip(selectedEvent.value || {}))
const rawRecordCards = computed(() => rawRecords.value.map((record) => buildRawRecordSummary(record)))

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

const loadOverview = async () => {
  loading.overview = true
  try {
    pageError.value = ''
    const [healthResult, traceResult, eventResult] = await Promise.allSettled([
      runtimeObservabilityApi.getHealthSummary(),
      loadTraces({ suppressError: true }),
      loadEvents({ suppressError: true }),
    ])
    const errors = []
    if (healthResult.status === 'fulfilled') {
      healthCards.value = buildHealthCards(
        readApiPayload(healthResult.value, 'components', []),
      )
    } else {
      errors.push(summarizeRequestError('健康摘要加载失败', healthResult.reason))
    }
    if (traceResult.status === 'rejected') {
      errors.push(summarizeRequestError('Trace 列表加载失败', traceResult.reason))
    }
    if (eventResult.status === 'rejected') {
      errors.push(summarizeRequestError('Event 列表加载失败', eventResult.reason))
    }
    pageError.value = errors.join('；')
  } finally {
    loading.overview = false
  }
}

const loadTraces = async (options = {}) => {
  const suppressError = Boolean(options?.suppressError)
  loading.traces = true
  try {
    if (!suppressError) pageError.value = ''
    const response = await runtimeObservabilityApi.listTraces(buildTraceQuery(query))
    traces.value = readApiPayload(response, 'traces', [])
    const currentTraceRow = {
      trace_key: selectedTrace.value?.trace_key,
      trace_id: selectedTrace.value?.trace_id,
    }
    selectedTrace.value = findTraceByRow(traces.value, currentTraceRow) || traces.value[0] || null
  } catch (error) {
    if (!suppressError) {
      pageError.value = summarizeRequestError('Trace 列表加载失败', error)
    }
    throw error
  } finally {
    loading.traces = false
  }
}

const loadEvents = async (options = {}) => {
  const suppressError = Boolean(options?.suppressError)
  try {
    if (!suppressError) pageError.value = ''
    const response = await runtimeObservabilityApi.listEvents(buildTraceQuery(query))
    events.value = readApiPayload(response, 'events', [])
  } catch (error) {
    if (!suppressError) {
      pageError.value = summarizeRequestError('Event 列表加载失败', error)
    }
    throw error
  }
}

const openAdvancedFilter = () => {
  syncQueryState(draftQuery, query)
  advancedFilterVisible.value = true
}

const applyAdvancedFilter = async () => {
  syncQueryState(query, draftQuery)
  recentTraceLimit.value = 20
  await Promise.all([loadTraces(), loadEvents()])
  advancedFilterVisible.value = false
}

const resetAdvancedFilter = () => {
  syncQueryState(draftQuery)
}

const handleTraceClick = async (row) => {
  const selected = findTraceByRow(traces.value, row)
  if (!selected) return
  if (selected.trace_id) {
    const response = await runtimeObservabilityApi.getTraceDetail(selected.trace_id)
    selectedTrace.value = readApiPayload(response, 'trace', selected)
  } else {
    selectedTrace.value = selected
  }
  activeTraceDetailTab.value = 'steps'
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

const handleComponentFilter = (target) => {
  const normalizedComponent =
    typeof target === 'string'
      ? String(target || '').trim()
      : String(target?.component || '').trim()
  if (!normalizedComponent) return
  boardFilter.component = normalizedComponent
  boardFilter.runtime_node = ''
  recentTraceLimit.value = 20
}

const clearFilterChip = async (chip) => {
  if (!chip) return
  if (chip.kind === 'toggle') {
    onlyIssues.value = false
    return
  }
  if (chip.kind === 'query' && chip.field) {
    query[chip.field] = ''
    draftQuery[chip.field] = ''
    await loadTraces()
  }
}

const showMoreRecentTraces = () => {
  recentTraceLimit.value = 50
}

const handleStepSelect = (step) => {
  selectedStep.value = step || null
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
  rawQuery.runtime_node = lookup.runtime_node
  rawQuery.component = lookup.component
  rawQuery.date = lookup.date
  rawQuery.file = ''
  rawDrawerVisible.value = true
  await loadRawFiles()
  if (rawFiles.value.length > 0) {
    rawQuery.file = rawFiles.value[0].name
    await loadRawTail(step)
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

const loadRawTail = async (targetStep = activeView.value === 'events' ? selectedEvent.value : selectedStep.value) => {
  if (!rawQuery.file) return
  loading.raw = true
  try {
    const response = await runtimeObservabilityApi.tailRawFile({
      runtime_node: rawQuery.runtime_node,
      component: rawQuery.component,
      date: rawQuery.date,
      file: rawQuery.file,
      lines: 120,
    })
    rawRecords.value = readApiPayload(response, 'records', [])
    rawFocusedIndex.value = findRawRecordIndex(rawRecords.value, targetStep)
    await scrollToFocusedRawRecord()
  } finally {
    loading.raw = false
  }
}

const stepKey = (step) => {
  return [
    step?.ts || '',
    step?.component || '',
    step?.node || '',
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
  rawRecordRefs.value = {
    ...rawRecordRefs.value,
    [index]: element || null,
  }
}

const scrollToFocusedRawRecord = async () => {
  if (rawFocusedIndex.value < 0) return
  await nextTick()
  rawRecordRefs.value[rawFocusedIndex.value]?.scrollIntoView({
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
    boardFilter.component = ''
    boardFilter.runtime_node = ''
    return
  }
  const fallback = pickDefaultSidebarComponent(items, boardFilter.component)
  if (fallback === boardFilter.component) return
  boardFilter.component = fallback
  boardFilter.runtime_node = ''
}, { immediate: true })

watch(visibleTraces, (items) => {
  const currentRow = {
    trace_key: selectedTrace.value?.trace_key,
    trace_id: selectedTrace.value?.trace_id,
  }
  selectedTrace.value = findTraceByRow(items, currentRow) || items[0] || null
}, { immediate: true })

watch(() => selectedTrace.value?.trace_id || selectedTrace.value?.trace_key || '', () => {
  activeTraceDetailTab.value = 'steps'
})

watch(rawRecords, () => {
  rawRecordRefs.value = {}
})

watch(autoRefresh, () => {
  resetOverviewTimer()
})

onMounted(() => {
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
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
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
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin: 0;
}

.runtime-title-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.runtime-view-switch {
  margin-right: 4px;
}

.runtime-summary-row {
  justify-content: space-between;
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
  grid-template-columns: 260px minmax(360px, 1.2fr) minmax(420px, 1.1fr);
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
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
}

.component-sidebar-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}

.component-sidebar-item {
  width: 100%;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fff;
  padding: 10px;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.component-sidebar-item:hover,
.component-sidebar-item.active {
  border-color: #409eff;
  box-shadow: 0 0 0 1px rgba(64, 158, 255, 0.12);
  transform: none;
}

.component-sidebar-item.is-warning {
  background: linear-gradient(180deg, #ffffff 0%, #fff8ec 100%);
}

.component-sidebar-item.is-failed {
  background: linear-gradient(180deg, #ffffff 0%, #fff1f0 100%);
}

.component-sidebar-item.is-skipped {
  background: linear-gradient(180deg, #ffffff 0%, #f5f2ff 100%);
}

.component-sidebar-main,
.component-sidebar-meta,
.component-sidebar-popover-stats,
.component-sidebar-popover-highlights,
.trace-flow-popover-item {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.component-sidebar-main {
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
}

.component-sidebar-main strong {
  color: #21405e;
}

.component-sidebar-heartbeat,
.component-sidebar-meta,
.component-sidebar-popover p,
.component-sidebar-popover-stats,
.recent-feed-identity {
  color: #69829b;
  font-size: 12px;
}

.component-sidebar-meta {
  margin-top: 10px;
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
.guardian-step-expr,
.guardian-trace-head p,
.guardian-trace-card p,
.guardian-signal-card p {
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
  grid-template-columns: minmax(0, 1.6fr) 80px 84px 72px 72px;
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
  grid-template-columns: minmax(0, 1.4fr) 72px 72px 72px minmax(0, 1.8fr);
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
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  color: #45627f;
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
  grid-template-columns: 152px 76px 132px 76px 88px minmax(180px, 1.4fr) 52px 72px minmax(150px, 1fr) minmax(150px, 1fr);
}

.runtime-event-ledger__grid {
  grid-template-columns: 152px 128px 104px 104px 88px 76px 132px minmax(170px, 1.3fr) minmax(150px, 1fr);
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

.runtime-inline-status,
.component-ledger__status,
.component-ledger__runtime-status {
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

.trace-summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.trace-summary-card {
  border: 1px solid #d8e2ee;
  border-radius: 12px;
  background: #fff;
  padding: 12px;
}

.trace-summary-card span {
  display: block;
  color: #68829b;
  font-size: 12px;
  margin-bottom: 8px;
}

.trace-summary-card strong {
  display: block;
  color: #21405e;
}

.trace-summary-card em {
  display: inline-block;
  margin-top: 6px;
  color: #56718d;
  font-size: 12px;
  font-style: normal;
}

.trace-issue-banner {
  margin-bottom: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  background: #fff4f2;
  color: #8f342b;
  border: 1px solid #f5d2ce;
  font-size: 13px;
}

.trace-issue-banner.is-empty {
  background: #eef7f1;
  color: #2f6a48;
  border-color: #cde8d7;
}

.trace-affected-row {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 12px;
}

.trace-affected-row > span {
  min-width: 72px;
  color: #68829b;
  font-size: 12px;
}

.trace-affected-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.trace-affected-list span {
  padding: 4px 8px;
  border-radius: 999px;
  background: #edf4fb;
  color: #35506c;
  font-size: 12px;
}

.trace-timeline-panel,
.step-inspector {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.guardian-trace-panel {
  border: 1px solid #d8e2ee;
  border-radius: 14px;
  background: linear-gradient(180deg, #ffffff 0%, #f4f8fc 100%);
  padding: 14px;
  margin-bottom: 12px;
}

.guardian-trace-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 12px;
}

.guardian-trace-head h3,
.guardian-signal-card strong,
.guardian-trace-card strong {
  margin: 0;
  color: #21405e;
}

.guardian-trace-grid,
.guardian-context-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.guardian-trace-card,
.guardian-signal-card,
.guardian-context-block {
  border: 1px solid #d8e2ee;
  border-radius: 12px;
  background: #fff;
  padding: 12px;
}

.guardian-trace-card > span,
.guardian-context-block > strong {
  display: block;
  color: #68829b;
  font-size: 12px;
}

.guardian-status-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 72px;
  padding: 6px 10px;
  border-radius: 999px;
  background: #edf4fb;
  color: #35506c;
  font-size: 12px;
}

.guardian-status-badge.is-success {
  background: #1e9b61;
  color: #fff;
}

.guardian-status-badge.is-warning {
  background: #de8f1f;
  color: #fff;
}

.guardian-status-badge.is-failed {
  background: #cf4a3c;
  color: #fff;
}

.guardian-status-badge.is-skipped {
  background: #7d74b6;
  color: #fff;
}

.trace-detail-body--stacked {
  display: grid;
  gap: 12px;
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
  gap: 8px;
}

.runtime-detail-tabs__tab {
  border: 1px solid #d8e2ee;
  border-radius: 999px;
  background: #fff;
  padding: 6px 12px;
  color: #5e7690;
  cursor: pointer;
  font: inherit;
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

.trace-ledger-toolbar {
  margin-bottom: 10px;
}

.trace-step-ledger {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: auto;
  border: 1px solid #e5edf5;
  border-radius: 12px;
  background: #fff;
  margin-bottom: 12px;
}

.trace-step-ledger__header,
.trace-step-ledger__row {
  display: grid;
  grid-template-columns: 40px 152px 72px minmax(160px, 1.2fr) 88px 112px 140px 120px 72px minmax(150px, 1fr) minmax(150px, 1fr);
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
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
  border: 1px solid #d8e2ee;
  border-radius: 12px;
  background: #fff;
  padding: 12px;
  min-height: 320px;
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

.step-inspector pre {
  margin: 0;
  padding: 12px;
  border-radius: 10px;
  background: #0f2034;
  color: #dff0ff;
  font-size: 12px;
  line-height: 1.55;
  overflow: auto;
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
