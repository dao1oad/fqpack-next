<template>
  <div class="workbench-page daily-screening-page">
    <MyHeader />

    <div class="workbench-body daily-screening-body" v-loading="pageLoading">
      <section class="workbench-toolbar">
        <div class="workbench-toolbar__header daily-toolbar-header">
          <div class="workbench-title-group">
            <div class="workbench-page-title">每日选股</div>
            <div class="workbench-page-meta">
              <span>Dagster 预计算</span>
              <span>/</span>
              <span>统一条件池交集</span>
              <span>/</span>
              <span>基础池由 CLS 各模型结果和热门 30/45/60/90 天结果先取并集形成</span>
            </div>
          </div>
          <div class="daily-toolbar-guide">
            <span class="daily-toolbar-guide__title">工作台说明</span>
            <div class="workbench-inline-tags daily-toolbar-guide__tags">
              <span
                v-for="line in workbenchGuideLines"
                :key="line"
                class="workbench-summary-chip workbench-summary-chip--muted daily-toolbar-guide__tag"
              >
                {{ line }}
              </span>
            </div>
          </div>
          <div class="workbench-toolbar__actions">
            <el-button @click="loadScopes">刷新 scopes</el-button>
            <el-button @click="refreshCurrentScope">刷新结果</el-button>
          </div>
        </div>

        <div class="workbench-summary-row">
          <span class="workbench-summary-chip workbench-summary-chip--muted">
            当前 scope <strong>{{ selectedScopeLabel }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--success">
            基础池 <strong>{{ scopeSummary?.stock_count ?? 0 }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--warning">
            当前结果 <strong>{{ resultRows.length }}</strong>
          </span>
          <span class="workbench-summary-chip workbench-summary-chip--muted">
            已选条件 <strong>{{ activeConditionCount }}</strong>
          </span>
        </div>
      </section>

      <el-alert
        v-if="pageError"
        class="workbench-alert"
        type="error"
        :title="pageError"
        :closable="false"
        show-icon
      />

      <div class="daily-screening-grid">
        <section class="workbench-panel daily-filter-panel" v-loading="loadingFilters">
          <div class="workbench-panel__header">
            <div class="workbench-title-group">
              <div class="workbench-panel__title">筛选工作台</div>
              <p class="workbench-panel__desc">前端只做组合查询，不再触发运行，不再展示 SSE。</p>
            </div>
          </div>

          <article class="workbench-block">
            <div class="workbench-panel__title">Scope</div>
            <el-select
              v-model="selectedScopeId"
              class="daily-field-control"
              filterable
              clearable
              placeholder="请选择 scope"
            >
              <el-option
                v-for="item in scopeItems"
                :key="item.scopeId"
                :label="item.isLatest ? `${item.label}（latest）` : item.label"
                :value="item.scopeId"
              />
            </el-select>
          </article>

          <article class="workbench-block">
            <div class="daily-section-header">
              <div class="workbench-panel__title">全市场搜索</div>
              <span class="workbench-muted">输入后直接覆盖中间交集列表，清空后恢复当前筛选结果。</span>
            </div>
            <el-input
              v-model="marketSearchKeyword"
              class="daily-field-control"
              clearable
              placeholder="输入代码或名称，全市场模糊搜索"
              @input="handleMarketSearchInput"
              @clear="handleMarketSearchClear"
            />
          </article>

          <article
            v-for="group in conditionSectionGroups"
            :key="group.key"
            class="workbench-block"
          >
            <div class="daily-filter-group__header">
              <div class="workbench-panel__title">{{ group.title }}</div>
              <span class="workbench-muted">
                {{ group.key === 'base_pool' ? '这组条件先取并集形成基础池' : '这组条件在基础池上继续取交集' }}
              </span>
            </div>
            <div class="daily-filter-group__sections">
              <article
                v-for="section in group.sections"
                :key="section.key"
                class="daily-filter-subsection"
              >
                <div class="daily-section-header">
                  <div class="workbench-panel__title">{{ section.title }}</div>
                  <el-popover
                    trigger="hover"
                    placement="right"
                    :width="360"
                  >
                    <template #reference>
                      <button
                        type="button"
                        class="daily-info-trigger"
                        :aria-label="`查看${section.title}说明`"
                      >
                        i
                      </button>
                    </template>
                    <div class="daily-help-card">
                      <div class="daily-help-card__title">{{ section.title }}</div>
                      <div class="daily-help-card__section">
                        <div class="daily-help-card__label">上游数据来源</div>
                        <p>{{ section.help?.source || '-' }}</p>
                      </div>
                      <div class="daily-help-card__section">
                        <div class="daily-help-card__label">筛选规则</div>
                        <p>{{ section.help?.rule || '-' }}</p>
                      </div>
                      <div class="daily-help-card__section">
                        <div class="daily-help-card__label">结果作用范围</div>
                        <p>{{ section.help?.scopeNote || '-' }}</p>
                      </div>
                    </div>
                  </el-popover>
                </div>
                <div class="daily-chip-grid">
                  <div
                    v-for="item in section.items"
                    :key="item.key"
                    class="daily-condition-chip"
                  >
                    <el-button
                      size="small"
                      :type="isSectionItemSelected(section, item) ? 'primary' : 'default'"
                      :plain="!isSectionItemSelected(section, item)"
                      @click="toggleSectionItem(section, item)"
                    >
                      {{ formatSectionItemLabel(section, item) }}
                    </el-button>
                  </div>
                </div>
              </article>
            </div>
          </article>

          <article class="workbench-block">
            <div class="daily-section-header">
              <div class="workbench-panel__title">日线缠论涨幅</div>
              <el-popover
                trigger="hover"
                placement="right"
                :width="360"
              >
                <template #reference>
                  <button
                    type="button"
                    class="daily-info-trigger"
                    aria-label="查看日线缠论涨幅说明"
                  >
                    i
                  </button>
                </template>
                <div class="daily-help-card">
                  <div class="daily-help-card__title">日线缠论涨幅</div>
                  <div class="daily-help-card__section">
                    <div class="daily-help-card__label">上游数据来源</div>
                    <p>{{ dailyChanlunHelp?.source || '-' }}</p>
                  </div>
                  <div class="daily-help-card__section">
                    <div class="daily-help-card__label">筛选规则</div>
                    <p>{{ dailyChanlunHelp?.rule || '-' }}</p>
                  </div>
                  <div class="daily-help-card__section">
                    <div class="daily-help-card__label">结果作用范围</div>
                    <p>{{ dailyChanlunHelp?.scopeNote || '-' }}</p>
                  </div>
                </div>
              </el-popover>
            </div>
            <div class="daily-metric-toggle-row">
              <el-button
                size="small"
                :type="dayChanlunEnabled ? 'primary' : 'default'"
                :plain="!dayChanlunEnabled"
                @click="toggleDayChanlunFilter"
              >
                {{ dayChanlunEnabled ? '已参与筛选' : '参与筛选' }}
              </el-button>
              <span class="daily-metric-toggle-note">默认值：高级段倍数 3 / 段倍数 2 / 笔涨幅% 20</span>
            </div>
            <div class="daily-metric-grid">
              <el-form-item
                v-for="item in metricFieldConfigs"
                :key="item.key"
              >
                <template #label>
                  <span class="daily-form-label">{{ item.label }}</span>
                </template>
                <el-input-number
                  v-model="metricFilters[item.key]"
                  controls-position="right"
                  :min="0"
                  :step="item.step"
                  class="daily-field-control"
                />
              </el-form-item>
            </div>
          </article>

          <div class="daily-filter-actions">
            <span class="daily-expression">{{ currentExpression }}</span>
            <div class="daily-action-buttons">
              <el-button @click="resetFilters">重置筛选</el-button>
            </div>
          </div>
        </section>

        <div class="daily-center-stack">
          <section class="workbench-panel daily-results-panel" v-loading="queryLoading">
            <div class="workbench-panel__header daily-results-header">
              <div class="daily-results-header__action">
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :disabled="!resultRows.length"
                  :loading="isWorkspaceActionRunning('workspace:append-intersection')"
                  @click="handleAppendIntersectionToPrePool"
                >
                  全部加入pre_pools
                </el-button>
              </div>
              <div class="workbench-title-group">
                <div class="workbench-panel__title">交集列表</div>
                <p class="workbench-panel__desc">
                  {{ isMarketSearchMode ? '当前为全市场搜索覆盖模式，结果直接显示到交集列表。' : '默认勾选融资标的和日线缠论涨幅，其他条件继续取交集。' }}
                </p>
              </div>
              <div class="workbench-panel__meta daily-results-meta">
                <span>{{ resultMetaLabel }}</span>
              </div>
            </div>

            <div v-if="resultRows.length" class="runtime-ledger daily-results-ledger">
              <div class="runtime-ledger__header daily-results-ledger__grid">
                <span>代码</span>
                <span>名称</span>
                <span>操作</span>
                <span>高级段倍数</span>
                <span>段倍数</span>
                <span>笔涨幅%</span>
                <span>缠论原因</span>
              </div>
              <div
                v-for="row in resultRows"
                :key="row.code"
                class="runtime-ledger__row daily-results-ledger__grid"
                :class="{ active: isResultRowActive(row) }"
                @click="handleRowClick(row)"
              >
                <span class="runtime-ledger__cell runtime-ledger__cell--strong">{{ row.code }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--strong runtime-ledger__cell--truncate" :title="row.name || '-'">
                  {{ row.name || '-' }}
                </span>
                <span class="runtime-ledger__cell daily-ledger__actions">
                  <el-button
                    size="small"
                    type="primary"
                    link
                    :loading="isWorkspaceActionRunning(`workspace:append-single:${row.code}`)"
                    @click.stop="handleAppendSingleRowToPrePool(row)"
                  >
                    加入 pre_pools
                  </el-button>
                </span>
                <span class="runtime-ledger__cell runtime-ledger__cell--number">{{ formatNumber(row.higherMultiple) }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--number">{{ formatNumber(row.segmentMultiple) }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--number">{{ formatNumber(row.biGainPercent) }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--truncate" :title="row.chanlunReason || '-'">
                  {{ row.chanlunReason || '-' }}
                </span>
              </div>
            </div>
            <div v-else class="runtime-empty-panel daily-empty-panel">
              <strong>{{ isMarketSearchMode ? '全市场搜索暂无命中结果' : '当前筛选暂无结果' }}</strong>
            </div>
          </section>

          <section class="workbench-panel daily-workspace-panel" v-loading="workspaceLoading">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">工作区</div>
                <p class="workbench-panel__desc">和 /gantt/shouban30 共用同一套 pre_pools / stock_pools / must_pools。</p>
              </div>
              <div class="workbench-panel__meta">
                <span>pre_pools {{ prePoolItems.length }}</span>
                <span>/</span>
                <span>stock_pools {{ stockPoolItems.length }}</span>
                <span>/</span>
                <span>must_pools {{ mustPoolItems.length }}</span>
              </div>
            </div>

            <el-alert
              v-if="workspaceError"
              class="workbench-alert"
              type="error"
              :title="workspaceError"
              :closable="false"
              show-icon
            />

            <el-tabs v-model="activeWorkspaceTab" class="daily-workspace-tabs">
              <el-tab-pane
                v-for="tab in workspaceTabs"
                :key="tab.key"
                :name="tab.key"
              >
                <template #label>
                  <div class="daily-workspace-tab-label">
                    <span>{{ tab.label }}</span>
                    <span>{{ tab.rows.length }}</span>
                  </div>
                </template>

                <div class="daily-workspace-actions">
                  <template v-if="tab.key === 'pre_pool'">
                    <el-button
                      size="small"
                      type="primary"
                      plain
                      :loading="isWorkspaceActionRunning('workspace:pre:sync-stock')"
                      @click="handleSyncPrePoolToStockPool"
                    >
                      {{ tab.batch_action_label }}
                    </el-button>
                    <el-button
                      size="small"
                      type="primary"
                      plain
                      :loading="isWorkspaceActionRunning('workspace:pre:sync-tdx')"
                      @click="handleSyncPrePoolToTdx"
                    >
                      {{ tab.sync_action_label }}
                    </el-button>
                    <el-button
                      size="small"
                      type="danger"
                      plain
                      :loading="isWorkspaceActionRunning('workspace:pre:clear')"
                      @click="handleClearPrePool"
                    >
                      {{ tab.clear_action_label }}
                    </el-button>
                  </template>

                  <template v-else-if="tab.key === 'stockpools'">
                    <el-button
                      size="small"
                      type="primary"
                      plain
                      :loading="isWorkspaceActionRunning('workspace:stock:sync-must')"
                      @click="handleSyncStockPoolToMustPool"
                    >
                      {{ tab.batch_action_label }}
                    </el-button>
                    <el-button
                      size="small"
                      type="primary"
                      plain
                      :loading="isWorkspaceActionRunning('workspace:stock:sync-tdx')"
                      @click="handleSyncStockPoolToTdx"
                    >
                      {{ tab.sync_action_label }}
                    </el-button>
                    <el-button
                      size="small"
                      type="danger"
                      plain
                      :loading="isWorkspaceActionRunning('workspace:stock:clear')"
                      @click="handleClearStockPool"
                    >
                      {{ tab.clear_action_label }}
                    </el-button>
                  </template>
                </div>

                <div v-if="tab.rows.length" class="runtime-ledger daily-workspace-ledger">
                  <div
                    class="runtime-ledger__header"
                    :class="tab.key === 'must_pools' ? 'daily-workspace-ledger__grid--must' : 'daily-workspace-ledger__grid'"
                  >
                    <span>代码</span>
                    <span>名称</span>
                    <span>来源</span>
                    <span>{{ tab.key === 'must_pools' ? '上下文' : '分类 / 上下文' }}</span>
                    <span v-if="tab.key === 'must_pools'">集合</span>
                    <span>操作</span>
                  </div>
                  <div
                    v-for="row in tab.rows"
                    :key="`${tab.key}:${row.code6}:${row.provider}`"
                    class="runtime-ledger__row"
                    :class="[
                      tab.key === 'must_pools' ? 'daily-workspace-ledger__grid--must' : 'daily-workspace-ledger__grid',
                      { active: isWorkspaceRowActive(row) },
                    ]"
                    @click="handleWorkspaceRowClick(row)"
                  >
                    <span class="runtime-ledger__cell runtime-ledger__cell--strong">{{ row.code6 }}</span>
                    <span class="runtime-ledger__cell runtime-ledger__cell--strong runtime-ledger__cell--truncate" :title="row.name || '-'">
                      {{ row.name || '-' }}
                    </span>
                    <span class="runtime-ledger__cell runtime-ledger__cell--truncate" :title="row.source_labels || row.provider || '-'">
                      {{ row.source_labels || row.provider || '-' }}
                    </span>
                    <span class="runtime-ledger__cell daily-workspace-cell">
                      <span
                        class="daily-workspace-cell__main runtime-ledger__cell--truncate"
                        :title="row.category_labels || row.context_label || row.plate_name || '-'"
                      >
                        {{ row.category_labels || row.context_label || row.plate_name || '-' }}
                      </span>
                      <span
                        v-if="row.context_detail"
                        class="daily-workspace-cell__meta runtime-ledger__cell--truncate"
                        :title="row.context_detail"
                      >
                        {{ row.context_detail }}
                      </span>
                    </span>
                    <span
                      v-if="tab.key === 'must_pools'"
                      class="runtime-ledger__cell runtime-ledger__cell--truncate"
                      :title="row.category || '-'"
                    >
                      {{ row.category || '-' }}
                    </span>
                    <span class="runtime-ledger__cell daily-ledger__actions">
                      <div class="daily-workspace-row-actions">
                        <template v-if="tab.key === 'pre_pool'">
                          <el-button
                            size="small"
                            type="primary"
                            link
                            :loading="isWorkspaceActionRunning(`workspace:pre:add:${row.code6}`)"
                            @click.stop="handleAddPrePoolToStockPools(row)"
                          >
                            {{ row.primary_action_label }}
                          </el-button>
                          <el-button
                            size="small"
                            type="danger"
                            link
                            :loading="isWorkspaceActionRunning(`workspace:pre:delete:${row.code6}`)"
                            @click.stop="handleDeletePrePoolRow(row)"
                          >
                            {{ row.secondary_action_label }}
                          </el-button>
                        </template>
                        <template v-else-if="tab.key === 'stockpools'">
                          <el-button
                            size="small"
                            type="primary"
                            link
                            :loading="isWorkspaceActionRunning(`workspace:stock:add-must:${row.code6}`)"
                            @click.stop="handleAddStockPoolToMustPools(row)"
                          >
                            {{ row.primary_action_label }}
                          </el-button>
                          <el-button
                            size="small"
                            type="danger"
                            link
                            :loading="isWorkspaceActionRunning(`workspace:stock:delete:${row.code6}`)"
                            @click.stop="handleDeleteStockPoolRow(row)"
                          >
                            {{ row.secondary_action_label }}
                          </el-button>
                        </template>
                        <template v-else-if="tab.key === 'must_pools'">
                          <el-button
                            size="small"
                            type="danger"
                            link
                            :loading="isWorkspaceActionRunning(`workspace:must:delete:${row.code6}`)"
                            @click.stop="handleDeleteMustPoolRow(row)"
                          >
                            {{ row.secondary_action_label }}
                          </el-button>
                        </template>
                      </div>
                    </span>
                  </div>
                </div>
                <div v-else class="runtime-empty-panel daily-empty-panel">
                  <strong>{{ tab.label }} 暂无记录</strong>
                </div>
              </el-tab-pane>
            </el-tabs>
          </section>
        </div>

        <aside class="daily-detail-stack" v-loading="detailLoading">
          <section class="workbench-panel daily-detail-overview-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">标的详情</div>
                <p class="workbench-panel__desc">工作区和交集列表都复用同一套详情接口。</p>
              </div>
            </div>

            <div v-if="detailSnapshot" class="daily-detail-summary">
              <div class="daily-detail-title">{{ detailSnapshot.name || detailSnapshot.code }}</div>
              <div class="daily-detail-meta">
                <span class="workbench-code">{{ detailSnapshot.code }}</span>
                <span>/</span>
                <span>{{ selectedScopeLabel }}</span>
              </div>
              <div class="daily-detail-metrics">
                <span class="workbench-summary-chip workbench-summary-chip--muted">
                  高级段倍数 {{ formatNumber(detailSnapshot.higherMultiple) }}
                </span>
                <span class="workbench-summary-chip workbench-summary-chip--muted">
                  段倍数 {{ formatNumber(detailSnapshot.segmentMultiple) }}
                </span>
                <span class="workbench-summary-chip workbench-summary-chip--muted">
                  笔涨幅% {{ formatNumber(detailSnapshot.biGainPercent) }}
                </span>
              </div>
            </div>
            <div v-else class="daily-empty">请先选择一只股票。</div>
          </section>

          <section class="workbench-panel daily-detail-condition-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">命中条件</div>
              </div>
            </div>

            <div v-if="detailSnapshot" class="daily-detail-card-grid">
              <article class="workbench-block daily-detail-card">
                <div class="workbench-panel__title">CLS 模型</div>
                <div class="daily-chip-grid">
                  <span
                    v-for="item in detail.clsMemberships"
                    :key="item.conditionKey"
                    class="workbench-summary-chip workbench-summary-chip--muted"
                  >
                    {{ formatDailyScreeningConditionLabel(item.conditionKey) }}
                  </span>
                  <span v-if="detail.clsMemberships.length === 0" class="daily-empty-inline">暂无</span>
                </div>
              </article>

              <article class="workbench-block daily-detail-card">
                <div class="workbench-panel__title">热门窗口</div>
                <div class="daily-chip-grid">
                  <span
                    v-for="item in detail.hotMemberships"
                    :key="item.conditionKey"
                    class="workbench-summary-chip workbench-summary-chip--warning"
                  >
                    {{ formatDailyScreeningConditionLabel(item.conditionKey) }}
                  </span>
                  <span v-if="detail.hotMemberships.length === 0" class="daily-empty-inline">暂无</span>
                </div>
              </article>

              <article class="workbench-block daily-detail-card">
                <div class="workbench-panel__title">市场属性</div>
                <div class="daily-chip-grid">
                  <span
                    v-for="item in detail.marketFlagMemberships"
                    :key="item.conditionKey"
                    class="workbench-summary-chip workbench-summary-chip--success"
                  >
                    {{ formatDailyScreeningConditionLabel(item.conditionKey) }}
                  </span>
                  <span v-if="detail.marketFlagMemberships.length === 0" class="daily-empty-inline">暂无</span>
                </div>
              </article>

              <article class="workbench-block daily-detail-card">
                <div class="workbench-panel__title">chanlun 周期</div>
                <div class="daily-chip-grid">
                  <span
                    v-for="item in detail.chanlunPeriodMemberships"
                    :key="item.conditionKey"
                    class="workbench-summary-chip workbench-summary-chip--muted"
                  >
                    {{ formatDailyScreeningConditionLabel(item.conditionKey) }}
                  </span>
                  <span v-if="detail.chanlunPeriodMemberships.length === 0" class="daily-empty-inline">暂无</span>
                </div>
              </article>

              <article class="workbench-block daily-detail-card">
                <div class="workbench-panel__title">chanlun 信号</div>
                <div class="daily-chip-grid">
                  <span
                    v-for="item in detail.chanlunSignalMemberships"
                    :key="item.conditionKey"
                    class="workbench-summary-chip workbench-summary-chip--muted"
                  >
                    {{ formatDailyScreeningConditionLabel(item.conditionKey) }}
                  </span>
                  <span v-if="detail.chanlunSignalMemberships.length === 0" class="daily-empty-inline">暂无</span>
                </div>
              </article>

              <article class="workbench-block daily-detail-card">
                <div class="workbench-panel__title">缠论原因</div>
                <div class="daily-detail-reason">{{ detailSnapshot.chanlunReason || '-' }}</div>
              </article>

              <article class="workbench-block daily-detail-card">
                <div class="workbench-panel__title">基础池状态</div>
                <div class="daily-base-pool-status">
                  <span
                    class="workbench-summary-chip"
                    :class="detailBasePoolStatus.inBasePool ? 'workbench-summary-chip--success' : 'workbench-summary-chip--warning'"
                  >
                    {{ detailBasePoolStatus.inBasePool ? '当前在基础池' : '当前不在基础池' }}
                  </span>
                  <div class="daily-base-pool-status__meta">
                    最近一次在基础池
                    <strong>{{ detailBasePoolStatus.lastSeenTradeDate || '未找到历史记录' }}</strong>
                  </div>
                </div>
              </article>
            </div>
            <div v-else class="daily-empty">请先选择一只股票。</div>
          </section>

          <section class="workbench-panel daily-detail-history-panel">
            <div class="workbench-panel__header">
              <div class="workbench-title-group">
                <div class="workbench-panel__title">历史热门理由</div>
              </div>
            </div>

            <div v-if="detail.hot_reasons.length" class="runtime-ledger daily-history-ledger">
              <div class="runtime-ledger__header daily-history-ledger__grid">
                <span>日期</span>
                <span>时间</span>
                <span>来源</span>
                <span>板块</span>
                <span>标的理由</span>
                <span>板块理由</span>
              </div>
              <div
                v-for="(row, index) in detail.hot_reasons"
                :key="`${row.date || ''}:${row.time || ''}:${row.provider || ''}:${index}`"
                class="runtime-ledger__row daily-history-ledger__grid"
              >
                <span class="runtime-ledger__cell runtime-ledger__cell--mono">{{ row.date || '-' }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--mono">{{ row.time || '-' }}</span>
                <span class="runtime-ledger__cell">{{ row.provider || '-' }}</span>
                <span class="runtime-ledger__cell runtime-ledger__cell--strong runtime-ledger__cell--truncate" :title="row.plate_name || '-'">
                  {{ row.plate_name || '-' }}
                </span>
                <span class="runtime-ledger__cell runtime-ledger__cell--truncate">
                  <Shouban30ReasonPopover
                    :reference-text="row.stock_reason"
                    :content-text="row.stock_reason"
                    :title="`${detailSnapshot?.code || '-'} ${detailSnapshot?.name || ''}`.trim()"
                    subtitle="历史热门理由"
                    :width="580"
                  />
                </span>
                <span class="runtime-ledger__cell runtime-ledger__cell--truncate">
                  <Shouban30ReasonPopover
                    :reference-text="row.plate_reason"
                    :content-text="row.plate_reason"
                    :title="row.plate_name || '板块理由'"
                    subtitle="历史热门理由"
                    :width="580"
                  />
                </span>
              </div>
            </div>
            <div v-else class="runtime-empty-panel daily-empty-panel">
              <strong>暂无热门理由</strong>
            </div>
          </section>
        </aside>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import MyHeader from './MyHeader.vue'
import Shouban30ReasonPopover from './components/Shouban30ReasonPopover.vue'
import { dailyScreeningApi } from '@/api/dailyScreeningApi.js'
import { stockApi } from '@/api/stockApi.js'
import {
  addShouban30PrePoolToStockPool,
  addShouban30StockPoolToMustPool,
  appendShouban30PrePool,
  clearShouban30PrePool,
  clearShouban30StockPool,
  deleteShouban30PrePoolItem,
  deleteShouban30StockPoolItem,
  getShouban30PrePool,
  getShouban30StockPool,
  syncShouban30PrePoolToStockPool,
  syncShouban30PrePoolToTdx,
  syncShouban30StockPoolToMustPool,
  syncShouban30StockPoolToTdx,
} from '@/api/ganttShouban30.js'
import {
  DEFAULT_DAILY_CHANLUN_METRIC_FILTERS,
  buildDailyScreeningAppendPrePoolPayload,
  buildDailyScreeningAppendSinglePrePoolPayload,
  buildDailyScreeningConditionSectionGroups,
  buildDailyScreeningCurrentExpression,
  buildDailyScreeningDefaultFilterState,
  buildDailyScreeningQueryPayload,
  buildDailyScreeningWorkspaceTabs,
  buildDailyScreeningWorkbenchState,
  formatDailyScreeningConditionLabel,
  normalizeDailyScreeningDetail,
  normalizeDailyScreeningFilterCatalog,
  normalizeDailyScreeningResultRows,
  normalizeDailyScreeningScopeItems,
  readDailyScreeningPayload,
  resolveDailyScreeningClsGroupLabels,
  resolveDailyScreeningClsGroupModels,
  toggleDailyScreeningSelection,
} from './dailyScreeningPage.mjs'

const loadingScopes = ref(false)
const loadingFilters = ref(false)
const queryLoading = ref(false)
const detailLoading = ref(false)
const workspaceLoading = ref(false)
const pageError = ref('')
const workspaceError = ref('')

const scopeItems = ref([])
const selectedScopeId = ref('')
const scopeSummary = ref({})
const filterCatalog = ref(normalizeDailyScreeningFilterCatalog({}))
const resultRows = ref([])
const selectedCode = ref('')
const detail = ref(normalizeDailyScreeningDetail({}))
const prePoolItems = ref([])
const stockPoolItems = ref([])
const mustPoolItems = ref([])
const activeWorkspaceTab = ref('pre_pool')
const workspaceActionKey = ref('')
const marketSearchKeyword = ref('')
const marketSearchTotal = ref(0)

const conditionKeys = ref([])
const clsGroupKeys = ref([])
const dayChanlunEnabled = ref(false)
const metricFilters = reactive({
  ...DEFAULT_DAILY_CHANLUN_METRIC_FILTERS,
})

let queryDebounceTimer = null
let suppressMetricFilterAutoQuery = false

const pageLoading = computed(() => loadingScopes.value || loadingFilters.value)
const detailSnapshot = computed(() => detail.value?.snapshot || null)
const detailBasePoolStatus = computed(() => detail.value?.basePoolStatus || {
  inBasePool: false,
  lastSeenScopeId: '',
  lastSeenTradeDate: '',
})
const sectionHelp = computed(() => filterCatalog.value.sectionHelp || {})
const conditionSectionGroups = computed(() => (
  buildDailyScreeningConditionSectionGroups(filterCatalog.value)
))
const dailyChanlunHelp = computed(() => sectionHelp.value.dailyChanlun || {})
const metricFieldConfigs = computed(() => ([
  {
    key: 'higherMultipleLte',
    label: '高级段倍数 ≤',
    step: 0.1,
  },
  {
    key: 'segmentMultipleLte',
    label: '段倍数 ≤',
    step: 0.1,
  },
  {
    key: 'biGainPercentLte',
    label: '笔涨幅% ≤',
    step: 0.1,
  },
]))
const workbenchGuideLines = [
  '上游：全市场，排除 ST / 北交所',
  '基础池：CLS 分组 + 热门窗口先取并集',
  '交集：其他条件在基础池结果上继续收敛',
  '工作区：结果可加入 pre_pools / stock_pools / must_pools',
]
const selectedScopeLabel = computed(() => {
  const matched = scopeItems.value.find((item) => item.scopeId === selectedScopeId.value)
  return matched?.label || selectedScopeId.value || '-'
})
const normalizedMarketSearchKeyword = computed(() => String(marketSearchKeyword.value || '').trim())
const isMarketSearchMode = computed(() => Boolean(normalizedMarketSearchKeyword.value))
const resultMetaLabel = computed(() => {
  if (isMarketSearchMode.value) {
    return `${resultRows.value.length} / ${marketSearchTotal.value} 条`
  }
  return `${resultRows.value.length} 条`
})
const activeConditionCount = computed(() => {
  return conditionKeys.value.length + clsGroupKeys.value.length + (dayChanlunEnabled.value ? 1 : 0)
})
const currentExpression = computed(() => {
  return buildDailyScreeningCurrentExpression({
    clsGroupKeys: clsGroupKeys.value,
    conditionKeys: conditionKeys.value,
    dayChanlunEnabled: dayChanlunEnabled.value,
    metricFilters,
  })
})
const workspaceTabs = computed(() => {
  return buildDailyScreeningWorkspaceTabs({
    prePoolItems: prePoolItems.value,
    stockPoolItems: stockPoolItems.value,
    mustPoolItems: mustPoolItems.value,
  })
})

const formatNumber = (value) => {
  if (value == null || value === '') return '-'
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric.toFixed(2) : '-'
}

const isResultRowActive = (row) => String(row?.code || '').trim() === selectedCode.value
const isWorkspaceRowActive = (row) => String(row?.code6 || '').trim() === selectedCode.value

const applyDefaultFilterState = () => {
  const defaults = buildDailyScreeningDefaultFilterState()
  conditionKeys.value = [...defaults.conditionKeys]
  clsGroupKeys.value = [...defaults.clsGroupKeys]
  dayChanlunEnabled.value = Boolean(defaults.dayChanlunEnabled)
  metricFilters.higherMultipleLte = defaults.metricFilters.higherMultipleLte
  metricFilters.segmentMultipleLte = defaults.metricFilters.segmentMultipleLte
  metricFilters.biGainPercentLte = defaults.metricFilters.biGainPercentLte
}

const readSharedWorkspacePayload = (response) => {
  if (response && typeof response === 'object') {
    if (response.data && typeof response.data === 'object') {
      return response.data
    }
    return response
  }
  return {}
}

const readWorkspaceItems = (response, itemKey = 'items') => {
  const payload = readSharedWorkspacePayload(response)
  if (Array.isArray(payload)) return payload
  if (Array.isArray(payload?.[itemKey])) return payload[itemKey]
  return []
}

const isWorkspaceActionRunning = (key) => workspaceActionKey.value === key

const buildSelectedFilterKeys = () => {
  const keys = [
    ...clsGroupKeys.value,
    ...conditionKeys.value,
  ]
  if (dayChanlunEnabled.value) {
    keys.push('metric:daily_chanlun')
  }
  return keys
}

const isSectionItemSelected = (section, item) => {
  if (section?.key === 'clsGroups') {
    return clsGroupKeys.value.includes(item?.key)
  }
  return conditionKeys.value.includes(item?.key)
}

const formatSectionItemLabel = (section, item) => {
  return `${item?.label || ''} · ${Number(item?.count || 0)}`
}

const scheduleQueryRows = () => {
  if (queryDebounceTimer) {
    clearTimeout(queryDebounceTimer)
  }
  queryDebounceTimer = setTimeout(() => {
    queryDebounceTimer = null
    void queryRows()
  }, 250)
}

const applyStateDefaults = (latestScope = null) => {
  const state = buildDailyScreeningWorkbenchState(latestScope)
  if (!selectedScopeId.value) {
    selectedScopeId.value = state.scopeId
  }
  suppressMetricFilterAutoQuery = true
  applyDefaultFilterState()
  suppressMetricFilterAutoQuery = false
}

const loadScopes = async () => {
  loadingScopes.value = true
  try {
    const [scopesResponse, latestResponse] = await Promise.all([
      dailyScreeningApi.getScopes(),
      dailyScreeningApi.getLatestScope(),
    ])
    scopeItems.value = normalizeDailyScreeningScopeItems(
      readDailyScreeningPayload(scopesResponse),
    )
    const latestScope = readDailyScreeningPayload(latestResponse)
    if (!selectedScopeId.value) {
      selectedScopeId.value = String(
        latestScope?.scope || latestScope?.run_id || '',
      ).trim()
    }
    if (!conditionKeys.value.length && !clsGroupKeys.value.length && !dayChanlunEnabled.value) {
      applyStateDefaults(latestScope)
    }
    pageError.value = ''
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '加载 scopes 失败'
  } finally {
    loadingScopes.value = false
  }
}

const loadWorkspace = async () => {
  workspaceLoading.value = true
  workspaceError.value = ''
  try {
    const [prePoolResponse, stockPoolResponse, mustPoolResponse] = await Promise.all([
      getShouban30PrePool(),
      getShouban30StockPool(),
      stockApi.getStockMustPoolsList({ page: 1, size: 1000 }),
    ])
    prePoolItems.value = readWorkspaceItems(prePoolResponse)
    stockPoolItems.value = readWorkspaceItems(stockPoolResponse)
    mustPoolItems.value = readWorkspaceItems(mustPoolResponse)
  } catch (error) {
    workspaceError.value = error?.response?.data?.error || error?.message || '加载工作区失败'
  } finally {
    workspaceLoading.value = false
  }
}

const loadScopeSummary = async () => {
  if (!selectedScopeId.value) {
    scopeSummary.value = {}
    return
  }
  const payload = readDailyScreeningPayload(
    await dailyScreeningApi.getScopeSummary(selectedScopeId.value),
  )
  scopeSummary.value = payload || {}
}

const loadFilterCatalog = async () => {
  if (!selectedScopeId.value) {
    filterCatalog.value = normalizeDailyScreeningFilterCatalog({})
    return
  }
  loadingFilters.value = true
  try {
    const payload = readDailyScreeningPayload(
      await dailyScreeningApi.getFilters(selectedScopeId.value),
    )
    filterCatalog.value = normalizeDailyScreeningFilterCatalog(payload)
  } finally {
    loadingFilters.value = false
  }
}

const queryRows = async () => {
  if (!selectedScopeId.value) {
    resultRows.value = []
    marketSearchTotal.value = 0
    return
  }
  queryLoading.value = true
  try {
    const payload = isMarketSearchMode.value
      ? readDailyScreeningPayload(
        await dailyScreeningApi.searchMarketStocks(
          selectedScopeId.value,
          normalizedMarketSearchKeyword.value,
        ),
      )
      : readDailyScreeningPayload(
        await dailyScreeningApi.queryStocks(
          buildDailyScreeningQueryPayload({
            scopeId: selectedScopeId.value,
            conditionKeys: conditionKeys.value,
            clxsModels: resolveDailyScreeningClsGroupModels(clsGroupKeys.value),
            metricFiltersEnabled: dayChanlunEnabled.value,
            metricFilters,
          }),
        ),
      )
    resultRows.value = normalizeDailyScreeningResultRows(payload?.rows)
    marketSearchTotal.value = Number(payload?.total || resultRows.value.length || 0)
    pageError.value = ''
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || (
      isMarketSearchMode.value ? '全市场搜索失败' : '查询交集结果失败'
    )
  } finally {
    queryLoading.value = false
  }
}

const loadDetail = async (code) => {
  if (!selectedScopeId.value || !code) {
    detail.value = normalizeDailyScreeningDetail({})
    return
  }
  detailLoading.value = true
  try {
    const payload = readDailyScreeningPayload(
      await dailyScreeningApi.getStockDetail(selectedScopeId.value, code),
    )
    detail.value = normalizeDailyScreeningDetail(payload)
    pageError.value = ''
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '加载标的详情失败'
  } finally {
    detailLoading.value = false
  }
}

const refreshCurrentScope = async () => {
  if (!selectedScopeId.value) return
  try {
    await Promise.all([loadScopeSummary(), loadFilterCatalog()])
    await queryRows()
    if (selectedCode.value) {
      await loadDetail(selectedCode.value)
    }
  } catch (error) {
    pageError.value = error?.response?.data?.error || error?.message || '刷新 scope 失败'
  }
}

const toggleCondition = async (key) => {
  conditionKeys.value = toggleDailyScreeningSelection(conditionKeys.value, key)
  await queryRows()
}

const resetFilters = async () => {
  suppressMetricFilterAutoQuery = true
  applyDefaultFilterState()
  suppressMetricFilterAutoQuery = false
  await queryRows()
}

const toggleClsGroup = async (key) => {
  clsGroupKeys.value = toggleDailyScreeningSelection(clsGroupKeys.value, key)
  await queryRows()
}

const toggleSectionItem = async (section, item) => {
  if (section?.key === 'clsGroups') {
    await toggleClsGroup(item?.key)
    return
  }
  await toggleCondition(item?.key)
}

const toggleDayChanlunFilter = async () => {
  dayChanlunEnabled.value = !dayChanlunEnabled.value
  await queryRows()
}

const handleMarketSearchInput = () => {
  scheduleQueryRows()
}

const handleMarketSearchClear = () => {
  scheduleQueryRows()
}

const handleRowClick = async (row) => {
  const code = String(row?.code || '').trim()
  if (!code) return
  selectedCode.value = code
  await loadDetail(code)
}

const handleWorkspaceRowClick = async (row) => {
  const code = String(row?.code6 || '').trim()
  if (!code) return
  selectedCode.value = code
  await loadDetail(code)
}

const runWorkspaceAction = async ({
  actionKey,
  action,
  successMessage,
  refreshWorkspace = true,
} = {}) => {
  workspaceActionKey.value = actionKey || ''
  workspaceError.value = ''
  try {
    const response = await action()
    if (refreshWorkspace) {
      await loadWorkspace()
    }
    const resolvedMessage = typeof successMessage === 'function'
      ? successMessage(readSharedWorkspacePayload(response))
      : successMessage
    if (resolvedMessage) {
      ElMessage.success(resolvedMessage)
    }
    return response
  } catch (error) {
    const message = error?.response?.data?.error || error?.message || '工作区操作失败'
    workspaceError.value = message
    ElMessage.error(message)
    return null
  } finally {
    workspaceActionKey.value = ''
  }
}

const handleAppendIntersectionToPrePool = async () => {
  const payload = buildDailyScreeningAppendPrePoolPayload({
    scopeId: selectedScopeId.value,
    rows: resultRows.value,
    conditionKeys: buildSelectedFilterKeys(),
    expression: currentExpression.value,
  })
  if (!payload.items.length) {
    ElMessage.warning('当前交集结果没有可加入的标的')
    return
  }
  await runWorkspaceAction({
    actionKey: 'workspace:append-intersection',
    action: () => appendShouban30PrePool(payload),
    successMessage: `已将当前交集结果 ${payload.items.length} 条加入 pre_pools`,
  })
}

const handleAppendSingleRowToPrePool = async (row) => {
  const code = String(row?.code || '').trim()
  const payload = buildDailyScreeningAppendSinglePrePoolPayload({
    scopeId: selectedScopeId.value,
    row,
    conditionKeys: buildSelectedFilterKeys(),
    expression: currentExpression.value,
  })
  if (!payload.items.length || !code) {
    ElMessage.warning('当前标的没有可加入的记录')
    return
  }
  await runWorkspaceAction({
    actionKey: `workspace:append-single:${code}`,
    action: () => appendShouban30PrePool(payload),
    successMessage: (result) => {
      const appendedCount = Number(result?.appended_count ?? 0)
      const skippedCount = Number(result?.skipped_count ?? 0)
      if (appendedCount > 0 && skippedCount > 0) {
        return `${code} 已加入 pre_pools（追加 ${appendedCount} / 跳过 ${skippedCount}）`
      }
      if (appendedCount > 0) {
        return `${code} 已加入 pre_pools`
      }
      return `${code} 已在 pre_pools 中`
    },
  })
}

const handleAddPrePoolToStockPools = async (row) => {
  await runWorkspaceAction({
    actionKey: `workspace:pre:add:${String(row?.code6 || '').trim()}`,
    action: () => addShouban30PrePoolToStockPool({ code6: row?.code6 }),
    successMessage: `${String(row?.code6 || '').trim()} 已加入 stock_pools`,
  })
}

const handleDeletePrePoolRow = async (row) => {
  await runWorkspaceAction({
    actionKey: `workspace:pre:delete:${String(row?.code6 || '').trim()}`,
    action: () => deleteShouban30PrePoolItem({ code6: row?.code6 }),
    successMessage: `${String(row?.code6 || '').trim()} 已从 pre_pools 删除`,
  })
}

const handleSyncPrePoolToStockPool = async () => {
  await runWorkspaceAction({
    actionKey: 'workspace:pre:sync-stock',
    action: () => syncShouban30PrePoolToStockPool(),
    successMessage: '已将 pre_pools 同步到 stock_pools',
  })
}

const handleSyncPrePoolToTdx = async () => {
  await runWorkspaceAction({
    actionKey: 'workspace:pre:sync-tdx',
    action: () => syncShouban30PrePoolToTdx(),
    successMessage: `已将 pre_pools ${prePoolItems.value.length} 条同步到通达信`,
    refreshWorkspace: false,
  })
}

const handleClearPrePool = async () => {
  await runWorkspaceAction({
    actionKey: 'workspace:pre:clear',
    action: () => clearShouban30PrePool(),
    successMessage: '已清空 pre_pools',
  })
}

const handleAddStockPoolToMustPools = async (row) => {
  await runWorkspaceAction({
    actionKey: `workspace:stock:add-must:${String(row?.code6 || '').trim()}`,
    action: () => addShouban30StockPoolToMustPool({ code6: row?.code6 }),
    successMessage: (payload) => {
      const status = String(payload?.status || '').trim()
      const suffix = status === 'updated' ? '已更新 must_pools' : '已加入 must_pools'
      return `${String(row?.code6 || '').trim()} ${suffix}`
    },
    refreshWorkspace: false,
  })
}

const handleDeleteStockPoolRow = async (row) => {
  await runWorkspaceAction({
    actionKey: `workspace:stock:delete:${String(row?.code6 || '').trim()}`,
    action: () => deleteShouban30StockPoolItem({ code6: row?.code6 }),
    successMessage: `${String(row?.code6 || '').trim()} 已从 stock_pools 删除`,
  })
}

const handleSyncStockPoolToMustPool = async () => {
  await runWorkspaceAction({
    actionKey: 'workspace:stock:sync-must',
    action: () => syncShouban30StockPoolToMustPool(),
    successMessage: (payload) => `已同步 ${payload.total_count ?? 0} 条到 must_pools（created ${payload.created_count ?? 0} / updated ${payload.updated_count ?? 0}）`,
    refreshWorkspace: false,
  })
}

const handleDeleteMustPoolRow = async (row) => {
  await runWorkspaceAction({
    actionKey: `workspace:must:delete:${String(row?.code6 || '').trim()}`,
    action: () => stockApi.deleteFromStockMustPoolsByCode(String(row?.code6 || '').trim()),
    successMessage: `${String(row?.code6 || '').trim()} 已从 must_pools 删除`,
  })
}

const handleSyncStockPoolToTdx = async () => {
  await runWorkspaceAction({
    actionKey: 'workspace:stock:sync-tdx',
    action: () => syncShouban30StockPoolToTdx(),
    successMessage: `已将 stock_pools ${stockPoolItems.value.length} 条同步到通达信`,
    refreshWorkspace: false,
  })
}

const handleClearStockPool = async () => {
  await runWorkspaceAction({
    actionKey: 'workspace:stock:clear',
    action: () => clearShouban30StockPool(),
    successMessage: '已清空 stock_pools',
  })
}

watch(
  () => [
    metricFilters.higherMultipleLte,
    metricFilters.segmentMultipleLte,
    metricFilters.biGainPercentLte,
  ],
  () => {
    if (suppressMetricFilterAutoQuery || !dayChanlunEnabled.value || !selectedScopeId.value) {
      return
    }
    scheduleQueryRows()
  },
)

watch(selectedScopeId, async (scopeId) => {
  if (!scopeId) return
  selectedCode.value = ''
  detail.value = normalizeDailyScreeningDetail({})
  suppressMetricFilterAutoQuery = true
  applyDefaultFilterState()
  suppressMetricFilterAutoQuery = false
  await refreshCurrentScope()
})

onBeforeUnmount(() => {
  if (queryDebounceTimer) {
    clearTimeout(queryDebounceTimer)
    queryDebounceTimer = null
  }
})

onMounted(async () => {
  await loadScopes()
  await Promise.all([
    selectedScopeId.value ? refreshCurrentScope() : Promise.resolve(),
    loadWorkspace(),
  ])
})
</script>

<style scoped>
.daily-screening-body {
  padding: 24px;
}

.daily-toolbar-header {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}

.daily-toolbar-guide {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1 1 720px;
  min-width: 0;
}

.daily-toolbar-guide__title {
  flex: 0 0 auto;
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
}

.daily-toolbar-guide__tags {
  flex: 1 1 auto;
}

.daily-toolbar-guide__tag {
  max-width: 100%;
}

.daily-screening-grid {
  display: grid;
  flex: 1 1 auto;
  grid-template-columns: 312px minmax(0, 1.2fr) minmax(0, 0.98fr);
  gap: 16px;
  min-height: 0;
  overflow: hidden;
  align-items: stretch;
}

.daily-filter-panel,
.daily-center-stack,
.daily-detail-stack {
  min-height: 0;
  max-height: 100%;
}

.daily-filter-panel {
  overflow-y: auto;
  overflow-x: hidden;
}

.daily-center-stack {
  display: grid;
  grid-template-rows: minmax(0, 1.08fr) minmax(0, 0.92fr);
  gap: 16px;
  min-height: 0;
}

.daily-detail-stack {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 16px;
  min-height: 0;
}

.daily-chip-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.daily-filter-group__header {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.daily-filter-group__sections {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 12px;
}

.daily-filter-subsection {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid #eef2f7;
}

.daily-filter-subsection:first-child {
  padding-top: 0;
  border-top: none;
}

.daily-section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.daily-condition-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.daily-metric-toggle-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.daily-metric-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
}

.daily-field-control {
  width: 100%;
}

.daily-filter-actions {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 16px;
}

.daily-action-buttons {
  display: flex;
  gap: 8px;
}

.daily-results-meta {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.daily-results-header {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
}

.daily-results-header__action {
  display: flex;
  align-items: center;
}

.daily-results-panel,
.daily-workspace-panel,
.daily-detail-overview-panel,
.daily-detail-condition-panel,
.daily-detail-history-panel {
  min-height: 0;
}

.daily-expression {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.daily-form-label {
  display: inline-flex;
  align-items: center;
}

.daily-metric-toggle-note {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.daily-info-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  background: #fff;
  color: #475569;
  cursor: pointer;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
}

.daily-help-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.daily-help-card__title {
  font-size: 14px;
  font-weight: 600;
  color: #111827;
}

.daily-help-card__section {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: #374151;
  line-height: 1.5;
}

.daily-help-card__section p {
  margin: 0;
}

.daily-help-card__label {
  font-weight: 600;
  color: #111827;
}

.daily-detail-summary {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.daily-detail-title {
  font-size: 20px;
  font-weight: 600;
}

.daily-detail-meta {
  display: flex;
  gap: 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.daily-detail-card-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  min-height: 0;
}

.daily-detail-card {
  min-height: 0;
}

.daily-detail-reason {
  color: var(--el-text-color-regular);
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.daily-base-pool-status {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.daily-base-pool-status__meta {
  color: #475569;
  font-size: 12px;
  line-height: 1.6;
}

.daily-detail-metrics {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.daily-empty,
.daily-empty-inline {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.daily-empty-panel {
  min-height: 180px;
}

.daily-workspace-tab-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.daily-workspace-tabs {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-height: 0;
}

.daily-workspace-tabs :deep(.el-tabs__content) {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
}

.daily-workspace-tabs :deep(.el-tab-pane) {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-height: 0;
}

.daily-workspace-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.daily-workspace-row-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.runtime-empty-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 220px;
  border: 1px dashed #d8e2ee;
  border-radius: 12px;
  background: #f8fbff;
  color: #5c738c;
  text-align: center;
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
  border-top: 1px solid #eef3f8;
  background: transparent;
}

.runtime-ledger__row:hover,
.runtime-ledger__row.active {
  background: #eef6ff;
}

.runtime-ledger__cell {
  min-width: 0;
  color: #35506c;
}

.runtime-ledger__cell--strong {
  color: #21405e;
  font-weight: 600;
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

.daily-ledger__actions {
  overflow: visible;
}

.daily-workspace-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow: hidden;
}

.daily-workspace-cell__main,
.daily-workspace-cell__meta {
  display: block;
  min-width: 0;
}

.daily-workspace-cell__meta {
  color: #68839d;
  font-size: 11px;
}

.daily-results-ledger__grid {
  grid-template-columns:
    76px
    minmax(132px, 0.95fr)
    112px
    104px
    96px
    96px
    minmax(220px, 1.8fr);
}

.daily-workspace-ledger__grid {
  grid-template-columns:
    76px
    112px
    104px
    minmax(180px, 1.45fr)
    minmax(188px, 1fr);
}

.daily-workspace-ledger__grid--must {
  grid-template-columns:
    76px
    112px
    104px
    minmax(160px, 1.2fr)
    minmax(160px, 1fr)
    minmax(128px, 0.85fr);
}

.daily-history-ledger__grid {
  grid-template-columns:
    108px
    72px
    76px
    108px
    minmax(220px, 1.2fr)
    minmax(220px, 1.2fr);
}

@media (max-width: 1480px) {
  .daily-screening-grid {
    grid-template-columns: 300px minmax(0, 1fr) minmax(340px, 0.9fr);
  }
}

@media (max-width: 1280px) {
  .daily-filter-panel,
  .daily-center-stack,
  .daily-detail-stack {
    grid-column: 1 / -1;
  }

  .daily-detail-card-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 960px) {
  .daily-screening-body {
    padding: 16px;
  }

  .daily-toolbar-guide {
    align-items: flex-start;
    flex-direction: column;
  }

  .daily-screening-grid {
    grid-template-columns: 1fr;
  }

  .daily-center-stack,
  .daily-detail-stack,
  .daily-detail-card-grid {
    grid-template-columns: 1fr;
    grid-template-rows: none;
  }
}
</style>
