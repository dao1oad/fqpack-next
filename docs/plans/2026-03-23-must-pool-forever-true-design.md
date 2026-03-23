# must_pool forever 固定为 true 设计

## 背景

当前 `must_pool.forever` 在不同入口的默认值不一致：

- `daily-screening` / `gantt shouban30` 默认写 `true`
- 老 `stock_pools` 弹窗默认写 `false`
- `kline-slim` / `subject-management` 保存草稿时也会把该字段作为可编辑配置写回

实际运行里，页面的“加入 must_pool”和“从 must_pool 删除”都是显式操作，`forever` 已经不再承担必要的产品语义。继续保留可编辑状态只会制造口径分裂，并让旧自动清理逻辑和 UI 摘要继续暴露无意义配置。

## 目标

- 所有 `must_pool` 写入口统一固定写入 `forever=true`
- 所有页面不再显示或编辑 `forever`
- 自动清理逻辑不再依赖 `forever`
- 历史 `must_pool` 文档统一回填为 `forever=true`

## 非目标

- 本次不彻底删除 Mongo 文档中的 `forever` 字段
- 本次不重做 `must_pool` 集合结构
- 本次不改动显式删除接口语义，删除仍然只按 `code` 删除

## 方案

### 1. 写路径统一

- `freshquant/rear/stock/routes.py` 的 `/api/add_to_must_pool_by_code` 不再从请求读取 `forever`
- `freshquant/stock_service.py` 的 `add_to_must_pool(...)` 内部固定写 `True`
- `freshquant/subject_management/write_service.py` 的 `update_must_pool(...)` 固定写 `True`
- `freshquant/data/astock/must_pool.py` 保留兼容参数，但内部对外部工作流统一走 `true`

### 2. 清理逻辑降级

- `freshquant/pool/general.py` 的 `cleanMustPool()` 改成不再按 `forever=False` 过滤
- 这样后续即使有人误开清理任务，也不会再存在“某些 must_pool 因 forever=false 被特殊删除”的旧语义

### 3. 前端设置项删除

- `StockPools.vue` 删除“是否永久”开关
- `KlineSlim.vue` / `kline-slim-subject-panel.mjs` 删除“永久跟踪”编辑项和相关说明文字
- `SubjectManagement.vue` / `subjectManagement.mjs` / `subjectManagementPage.mjs` 删除该字段的摘要、状态标签和编辑行
- 相关 API 不再携带 `forever` 参数

### 4. 数据回填

- 增加一个一次性数据修复脚本，把 `must_pool` 中缺失或为 `false` 的文档统一更新为 `true`
- 脚本纳入 PR，并在部署后执行一次，保证历史数据与新代码口径一致

### 5. 文档同步

- 更新 `docs/current/reference/stock-pools-and-positions.md`
- 更新受影响模块文档，明确 `must_pool` 当前为显式增删，`forever` 不再是用户可见配置

## 风险与控制

- 风险：旧 CLI 或脚本仍传 `forever=false`
  - 控制：服务端写入口忽略该值并统一写 `true`
- 风险：前端测试仍断言 `forever` 字段存在于编辑草稿
  - 控制：先改测试，再改实现
- 风险：历史数据仍残留 `false`
  - 控制：提供明确的数据修复脚本并在正式部署后执行

## 验证

- 前端单测：确认页面不再暴露 `forever` 行、开关和摘要
- 后端单测：确认 `must_pool` 写入统一为 `true`
- 行为验证：显式添加 / 删除单只标的不受影响
- 构建与 formal deploy 后，再核对生产运行口径
