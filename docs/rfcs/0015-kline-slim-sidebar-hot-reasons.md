# RFC 0015: KlineSlim 左侧股票池与热门原因历史

- **状态**：Done
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-07
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

RFC 0005 已在目标仓库恢复 `KlineSlim` MVP 主图能力，但当前页面仍是轻量版：

- 左侧股票池列表未迁入，无法在页面内快速切换“持仓 / must_pool / stock_pools / stock_pre_pools”。
- 旧分支中用于 hover 的“标的详情”热门原因列表未迁入。
- 当前目标仓库虽然已有 `plate_reason_daily`、`gantt_stock_daily` 等盘后读模型，但没有为 `KlineSlim` 准备“按股票查询的历史热门原因”专用读模型和查询接口。
- `GET /api/get_stock_pre_pools_list` 在 `category` 为空时，会错误地查询 `category=""`，不符合当前需求中的“全分类合并展示”。

用户要求本轮恢复 `KlineSlim` 的最小左侧工作台，并将 hover 语义改为参考旧分支 `/gantt/shouban30` 的“标的详情”列表：

- 从近到远展示该标的的历史热门记录；
- 每条记录展示 `数据来源 / 热门板块名字 / 板块理由 / 标的理由`；
- 不依赖当天盘中热门标的数据能力；
- 与每日“热门板块 / 热门标的”盘后同步任务一起构建所需读模型。

## 2. 目标（Goals）

- 在目标仓库 `KlineSlim` 页面恢复最小左侧股票池列表。
- 左侧列表顺序固定为：`持仓股 -> must_pool -> stock_pools -> stock_pre_pools`。
- 左侧列表项统一展示 `标的名称 + 代码`。
- 左侧列表默认仅展开 `持仓股`，并保持“同一时刻至多展开一个列表”的 accordion 行为。
- `stock_pre_pools` 在未指定分类时展示全分类合并结果。
- 为 `must_pool / stock_pools / stock_pre_pools` 提供单条删除能力，并直接删除对应数据库记录。
- 为 `KlineSlim` 提供新的热门原因历史接口：`/api/gantt/stocks/reasons`。
- 在 `freshquant_gantt` 分库中新增按股票聚合的热门原因历史读模型，并接入现有 Dagster 盘后链路。
- 为前后端与 Dagster 增加覆盖本次行为的自动化测试。

## 3. 非目标（Non-Goals）

- 不恢复旧分支 `KlineSlim` 的完整工作台、网格模式、搜索抽屉、更多池子或复杂编辑能力。
- 不恢复旧分支基于 `hot_plates / extra_plates / plate_labels` 的“所属板块快照”悬浮框。
- 不新增盘中实时热门标的同步或 WebSocket 推送。
- 不把 `shouban30` 导出集合直接当作 `KlineSlim` 的事实数据源。
- 不修改现有主图 K 线、30m 缠论叠加和默认持仓解析语义。

## 4. 范围（Scope）

**In Scope**

- `KlineSlim` 左侧 4 组列表的最小恢复。
- `KlineSlim` 左侧列表项双行展示、默认 `持仓股` 单展开与 accordion 行为。
- `must_pool / stock_pools / stock_pre_pools` 的单条删除交互。
- `stock_pre_pools` 全分类合并语义修正。
- 新增 `stock_hot_reason_daily` 读模型与对应查询逻辑。
- 新增 `GET /api/gantt/stocks/reasons`。
- 在 `job_gantt_postclose` 中新增构建 `stock_hot_reason_daily` 的步骤。
- 对应前端、后端、Dagster 测试与文档更新。

**Out of Scope**

- `KlineSlim` 页面视觉重设计。
- must_pool 排序编辑、拖拽、批量操作。
- 其它专题页面的 hover 统一改造。
- 任何新的 Mongo 分库、Redis key 或第三方服务依赖。

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- `morningglory/fqwebui` 负责左侧最小列表展示、点击切换标的、hover 懒加载与本地缓存。
- `freshquant/rear/gantt/routes.py` 负责暴露稳定的历史热门原因读取接口。
- `freshquant/data/gantt_readmodel.py` 负责从现有 `gantt_stock_daily + plate_reason_daily` 构建按股票聚合的历史热门原因读模型。
- `morningglory/fqdagster` 负责把该读模型纳入现有盘后同步任务链。

**不负责（Must Not）**

- 不在 hover 时直接跨集合做实时 join。
- 不把旧分支 `shouban30` 导出页的全部接口与页面一起迁回。
- 不在前端自行推导板块理由或合成历史顺序。

**依赖（Depends On）**

- RFC 0005：`KlineSlim` 页面与主图数据链路。
- RFC 0006：`freshquant_gantt` 分库、`plate_reason_daily`、`gantt_stock_daily`、Dagster 盘后任务。
- 旧分支参考实现：
  - `D:\fqpack\freshquant\morningglory\fqwebui\src\views\KlineSlim.vue`
  - `D:\fqpack\freshquant\morningglory\fqwebui\src\views\js\kline-slim.js`
  - `D:\fqpack\freshquant\freshquant\rear\gantt\shouban30_routes.py`
  - `D:\fqpack\freshquant\freshquant\data\gantt_shouban30_service.py`

**禁止依赖（Must Not Depend On）**

- 旧分支 `stock_plate` 快照链路。
- 旧 `/api/gantt/shouban30/stocks/reasons` 作为目标仓库正式依赖。
- 盘中快照注入与实时热门标的抓取链路。

## 6. 对外接口（Public API）

### 6.1 前端路由与页面行为

- 继续复用 `GET /kline-slim`
- 页面新增左侧固定侧栏：
  - `持仓股`
  - `must_pool`
  - `stock_pools`
  - `stock_pre_pools`
- 默认首次进入页面时仅展开 `持仓股`；展开任一其他列表时自动收起其余列表；点击当前已展开列表时允许全部折叠。
- 每条列表项第一行展示 `标的名称`，第二行展示 `代码`；名称缺失时回退展示代码。
- 点击任意列表项后，切换当前 `symbol` 并保持现有 `period / endDate` 语义。
- `must_pool / stock_pools / stock_pre_pools` 列表项右侧提供删除按钮；点击后先确认，再删除对应数据库记录并刷新受影响列表。

### 6.2 HTTP API

- 现有 `GET /api/get_stock_pre_pools_list`
  - 行为调整：
    - 当 `category` 缺省、为空字符串或仅空白字符时，表示“不按分类过滤”，返回全分类合并结果；
    - 当 `category` 非空时，保持现有按分类过滤行为。
  - 返回结构保持不变。

- 新增 `GET /api/gantt/stocks/reasons`
  - query：
    - `code6`：必填，6 位证券代码
    - `provider`：可选，`all | xgb | jygs`，默认 `all`
    - `limit`：可选，默认 `0`，表示不限制
  - 返回：
    - `data.items`，按 `date desc, time desc` 排序
    - 每条记录包含：
      - `date`
      - `time`
      - `provider`
      - `plate_name`
      - `plate_reason`
      - `stock_reason`
  - 错误语义：
    - `code6` 缺失或格式非法：400
    - `provider` 非法：400

### 6.3 前端 hover 行为

- 鼠标悬浮某个标的时，前端懒加载 `/api/gantt/stocks/reasons?code6=<code6>`
- hover 弹层只读接口返回，不再读取“所属板块快照”
- 前端按 `code6` 做本地缓存，避免重复请求

## 7. 数据与配置（Data / Config）

- 新增集合：`freshquant_gantt.stock_hot_reason_daily`
- 文档结构：
  - `trade_date`
  - `provider`
  - `code6`
  - `name`
  - `plate_key`
  - `plate_name`
  - `plate_reason`
  - `stock_reason`
  - `time`
  - `reason_ref`
  - `updated_at`
- 构建来源：
  - `gantt_stock_daily`
  - `plate_reason_daily`
- 建议索引：
  - 唯一索引：`provider + trade_date + plate_key + code6`
  - 查询索引：`code6 + trade_date desc`
- 不新增新的运行时配置项，继续复用 `FRESHQUANT_MONGODB__GANTT_DB`。

## 8. 破坏性变更（Breaking Changes）

本 RFC 包含一处刻意的现有接口语义调整：

- `GET /api/get_stock_pre_pools_list` 在 `category` 为空时，从“查询 `category=\"\"`”改为“返回全分类合并结果”。

### 影响面

- 依赖 `category` 为空时返回空集或仅匹配空分类的调用方，行为会改变。
- `KlineSlim` 将新增左侧列表和 hover 历史热门弹层。
- `job_gantt_postclose` 增加一段盘后构建步骤，任务耗时会增加。

### 迁移步骤

1. 审核并通过本 RFC。
2. 为 `stock_hot_reason_daily` 增加构建与查询能力。
3. 修正 `stock_pre_pools` 空分类语义。
4. 恢复 `KlineSlim` 最小左侧工作台并接入 hover。
5. 同提交更新 `docs/migration/progress.md`，落地时同步更新 `docs/migration/breaking-changes.md`。

### 回滚方案

- 回退 `stock_hot_reason_daily` 的构建、查询接口与前端 hover 调用。
- 回退 `get_stock_pre_pools_list` 的空分类语义到旧行为。
- 页面侧移除左侧工作台，仅保留 RFC 0005 的轻量版 `KlineSlim`。

## 9. 迁移映射（From `D:\fqpack\freshquant`）

- `D:\fqpack\freshquant\morningglory\fqwebui\src\views\KlineSlim.vue`
  - 左侧列表与 hover 交互参考
  - 映射到目标仓库同名页面与 `src/views/js/kline-slim.js`
- `D:\fqpack\freshquant\freshquant\rear\gantt\shouban30_routes.py`
  - 旧 `stocks/reasons` 接口参考
  - 映射为目标仓库新接口 `/api/gantt/stocks/reasons`
- `D:\fqpack\freshquant\freshquant\data\gantt_shouban30_service.py:list_stock_reasons`
  - 旧“标的详情”排序与字段语义参考
  - 映射为目标仓库新的 read model query service

## 10. 测试与验收（Acceptance Criteria）

- [ ] 访问 `/kline-slim?symbol=sh510050` 时，左侧可以看到 4 组列表，顺序固定为 `持仓股 -> must_pool -> stock_pools -> stock_pre_pools`
- [ ] 默认首次进入 `/kline-slim` 时仅展开 `持仓股`；任一时刻最多只有 1 个列表展开
- [ ] 左侧每条列表项都能同时看到 `标的名称` 与 `代码`
- [ ] 点击左侧任一标的后，主图区切换到对应标的，且现有 `period / endDate` 语义不变
- [ ] `must_pool / stock_pools / stock_pre_pools` 的删除按钮可以删除对应标的，且删除不会误触发切图
- [ ] 悬浮在任一存在历史热门记录的标的上时，能看到“数据来源 / 热门板块名字 / 板块理由 / 标的理由”列表，且按近到远排序
- [ ] 某标的不存在历史热门记录时，hover 弹层显示空态而非报错
- [ ] `GET /api/get_stock_pre_pools_list` 在未传 `category` 时，返回全分类合并结果
- [ ] `job_gantt_postclose` 执行后，`stock_hot_reason_daily` 写入当日数据
- [ ] `py -3 -m pytest freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py freshquant/tests/test_gantt_dagster_import.py -q` 通过
- [ ] `py -3 -m pytest freshquant/tests/test_stock_pool_service.py -q` 通过
- [ ] `node --test tests/kline-slim-sidebar.test.mjs` 在 `morningglory/fqwebui` 下通过
- [ ] `npm run build` 在 `morningglory/fqwebui` 下通过

## 11. 风险与回滚（Risks / Rollback）

- 风险：当前 `gantt_stock_daily` 与 `plate_reason_daily` 之间的 join 语义若处理不当，可能产生重复记录或理由缺失。
  - 缓解：先以纯函数 + 持久化测试锁定字段与唯一键。
- 风险：`KlineSlim` 当前页面代码已与旧分支严重分叉，直接拷贝旧逻辑容易引入额外功能回归。
  - 缓解：只恢复左侧最小列表与 hover，不回迁其它旧工作台能力。
- 风险：新增 Dagster op 后盘后任务耗时增加。
  - 缓解：读模型构建限定为当日数据，按读模型索引查询，不做全历史重扫。

## 12. 里程碑与拆分（Milestones）

- M1：RFC 0015 评审通过
- M2：后端 `stock_hot_reason_daily` 读模型与 `/api/gantt/stocks/reasons` 完成
- M3：`stock_pre_pools` 空分类语义修正完成
- M4：前端 `KlineSlim` 左侧列表与 hover 完成
- M5：测试、构建验证与迁移进度更新完成
