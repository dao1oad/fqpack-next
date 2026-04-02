# Position Management Dense Layout Design

## 背景

当前 `PositionManagement` 已经收敛到三栏工作台，但页面仍保留了较强的卡片化组织方式：

- 左栏“对账检查”使用 audit card 列表，信息密度偏低
- 中栏“标的总览”把配置与 entry 信息纵向堆叠，占用大量高度
- 右栏只有“最近决策与上下文”，缺少与当前选中标的联动的工作区

这导致桌面宽屏环境下，页面扫描效率偏低，空白较多，不符合交易工作台的高密度使用预期。

## 目标

- 将页面改成高密度、表格优先的交易台布局
- 明确中栏主表与右栏明细的主从关系
- 将“对账检查”从卡片流改为 dense ledger
- 让“当前仓位状态 / 对账检查 / 标的总览 / 右侧联动工作区 / 最近决策”都保持固定区域内滚动

## 非目标

- 不改后端 API 结构
- 不新增新的仓位管理写接口
- 不改变“标的总览”现有数据排序语义；继续按持仓优先、仓位市值降序展示
- 不处理 formal deploy；本次仅完成前端实现与测试

## 方案选择

已确认采用方案 A。

### 方案 A

- 左栏上下平分
  - 上：`当前仓位状态`
  - 下：`对账检查`
- 中栏保留 `标的总览`，改造成高密度横向表格
- 右栏上下平分
  - 上：`选中标的工作区`
    - 展示选中标的的 `聚合买入列表 / 按持仓入口止损`
    - 同时展示该标的的 `切片明细`
  - 下：`最近决策与上下文`

### 采用原因

- 与现有三栏工作台骨架最兼容，改动集中在前端视图层
- 可显著提高信息密度，同时保留当前模块边界
- 选中态联动明确，适合桌面交易工作流

## 交互设计

### 中栏与右栏联动

- `标的总览` 支持单行选中
- 页面加载完成后，默认选中当前排序后的首行标的
- 点击中栏任意标的行，右上工作区与右下最近决策都按选中标的联动刷新展示

### 标的总览

- 改为 dense `el-table`
- 每个设置项改为独立列，横向排列，不再纵向堆叠
- 列内优先展示当前值、状态与必要编辑器
- 保留单行保存动作，避免切回独立详情面板

建议列面：

- 标的
- 分类
- 持仓数量
- 持仓市值
- 门禁
- 单标的上限
- 止损价
- 首笔金额
- 常规金额
- 活跃止损
- Open Entry
- 最近触发
- 保存

### 对账检查

- 使用 dense ledger/table 组织，不再按 symbol 渲染卡片
- 每行直接展示：
  - 标的
  - audit status
  - reconciliation state
  - latest resolution
  - signed gap
  - open gap
  - mismatch 摘要
  - 关键 surface/rule 摘要
- 如需保留更多证据，采用行内展开表格，而不是卡片组

### 右栏选中标的工作区

- 上半区拆成两张纵向堆叠的 dense 表格
- 第一张表展示 entry 级聚合买入与止损编辑
- 第二张表展示切片明细
- 两张表都只针对当前选中的单个标的

### 最近决策与上下文

- 继续使用 dense ledger
- 下半区只显示当前选中标的相关决策，减少无关噪音
- 若选中标的暂无决策，显示空态

## 布局设计

- 左栏：`grid-template-rows: 1fr 1fr`
- 中栏：单一主表，占满中栏高度
- 右栏：`grid-template-rows: 1fr 1fr`
- 所有主区域维持 `min-height: 0 + overflow` 约束，避免页面级滚动回归

## 组件改动范围

- `morningglory/fqwebui/src/views/PositionManagement.vue`
  - 调整三栏骨架
  - 增加选中标的状态
  - 右栏拆为“选中标的工作区 + 最近决策”
- `morningglory/fqwebui/src/components/position-management/PositionSubjectOverviewPanel.vue`
  - 改成高密度主表
  - 暴露选中标的联动事件
- `morningglory/fqwebui/src/components/position-management/PositionReconciliationPanel.vue`
  - 从卡片列表改为 dense ledger/table
- `morningglory/fqwebui/src/views/*.test.mjs`
  - 更新视图结构与布局约束测试

## 测试策略

- 先写失败测试，锁定：
  - 左栏上下平分
  - 右栏上下平分
  - 中栏主表单选联动
  - `对账检查` 已切换为 dense ledger
  - `标的总览` 采用横向列式设置项
- 再实现最小改动使测试通过
- 最后运行 position/workbench 相关 Node tests

## 风险与控制

- 风险：中栏列过多导致横向拥挤
  - 控制：对数值列缩宽、文本列截断、保留 tooltip
- 风险：右栏联动需要复用现有 detail 数据
  - 控制：继续依赖现有 `detailMap`，只做选中态切换
- 风险：布局改动引发桌面滚动回退
  - 控制：保留并扩展 `workbenchViewportLayout` 测试
