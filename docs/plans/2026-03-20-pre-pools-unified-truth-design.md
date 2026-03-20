# Pre-Pools 单码单记录统一真值设计

## 背景

当前 `stock_pre_pools` 同时承载了多种来源写入：

- `/kline-slim` 通过旧股票服务接口直接读取整张 `stock_pre_pools`
- `/gantt/shouban30` 只读取 `category=三十涨停Pro预选` 的工作区子集
- `/daily-screening` 页面当前复用 `/gantt/shouban30` 的工作区接口，因此看到的也是该子集
- `daily-screening:clxs` 等盘后结果写入时，会把同一个 `code` 以多个模型分类写成多条记录

这导致三个页面的 `pre_pools` 数量不一致，而且旧接口展示的是“记录数”，不是“去重后的标的数”。

## 目标

- 把 `stock_pre_pools` 收敛为“同一池子内同一个 `code` 只保留一条记录”的正式真值
- 三个页面 `/kline-slim`、`/gantt/shouban30`、`/daily-screening` 统一按去重后的 `pre_pool` 展示
- 每条记录清楚展示该标的的 `来源（source）` 和 `分类（category）`
- 写入时仍能对来源和分类做精确区分，并保留来源-分类配对关系
- 删除时按 `code` 删除整条记录，不做局部来源/分类删除

## 非目标

- 不保留“同一个 `code` 多条并存”的旧显示语义
- 不为 `/daily-screening` 再维护一套独立工作区
- 不把“删除某个来源/分类标签”作为当前需求范围
- 不把 `fqscreening` 正式结果真值迁回 `stock_pre_pools`

## 已确认语义

- 同一个池子里同一个 `code` 只保存一条
- 后续来自新来源或新分类时，更新这条记录，而不是新增第二条
- 顶层页面和接口按单条记录展示
- 删除某个 `code` 时，删除该池子里的整条记录
- 三个页面都展示该池子的全量去重结果，而不是各看子集

## 方案比较

### 方案 1：只在前端去重展示

优点：

- 改动最小

缺点：

- 后端仍然保留重复脏数据
- 不同页面继续调用不同接口时，口径仍会漂移
- 写入与删除语义仍不统一

### 方案 2：只在后端读侧聚合，写入继续保留多条

优点：

- 页面数量可以先统一

缺点：

- 存储真值仍是重复行
- 新老接口并存时，后续很容易再次回到“有的地方读明细，有的地方读聚合”
- 删除和 `.blk` 同步仍需要不断补兼容

### 方案 3：把 `stock_pre_pools` 收敛为单码单记录真值

优点：

- 读写口径天然统一
- 三个页面统一展示同一份真值
- 删除语义直接清晰
- 后续 `.blk`、`stock_pools`、`must_pool` 同步都能对齐到统一事实

缺点：

- 需要改写入路径、读取接口和一次性数据迁移

## 结论

采用方案 3。

原因很直接：当前问题的根因不是 UI，而是 `stock_pre_pools` 的真值结构已经失真。只有把存储真值改成“同码单记录”，三页数字一致、来源分类清晰、删除语义统一这三个目标才能同时成立。

## 数据模型

### 顶层记录

`stock_pre_pools` 每个 `code` 只保留一条：

```json
{
  "code": "002123",
  "name": "梦网科技",
  "symbol": "sz002123",
  "created_at": "2026-03-19T23:39:32+08:00",
  "updated_at": "2026-03-20T07:39:32+08:00",
  "datetime": "2026-03-19T23:39:32+08:00",
  "expire_at": "2099-12-31T23:59:59+08:00",
  "sources": [
    "daily-screening",
    "shouban30"
  ],
  "categories": [
    "CLXS_10008",
    "intersection"
  ],
  "memberships": [
    {
      "source": "daily-screening",
      "category": "CLXS_10008",
      "added_at": "2026-03-18T00:00:00+08:00",
      "extra": {
        "screening_run_id": "70da066b9d2b"
      }
    },
    {
      "source": "shouban30",
      "category": "intersection",
      "added_at": "2026-03-20T07:39:32+08:00",
      "extra": {
        "replace_scope": "daily_screening_intersection"
      }
    }
  ],
  "workspace_order": 0
}
```

### 字段语义

- `sources`
  - 去重后的来源列表，只用于读取和展示
- `categories`
  - 去重后的分类列表，只用于读取和展示
- `memberships`
  - 精确来源-分类配对明细，是写入真值
- `workspace_order`
  - 统一工作区顺序真值，取代当前只对 `shouban30` 生效的 `extra.shouban30_order`
- `created_at`
  - 最早进入 `pre_pool` 的时间
- `updated_at`
  - 最近一次新增或补充 membership 的时间
- `expire_at`
  - 整条记录的有效期；若多个 membership 有效期不同，顶层取最晚有效时间

## 写入设计

所有“加入 pre_pools”动作统一走 shared upsert 入口。

### upsert 规则

- 不存在该 `code`
  - 新建整条记录
- 已存在该 `code`
  - 若 `(source, category)` 已存在，则幂等更新该 membership 的元数据
  - 若 `(source, category)` 不存在，则追加新 membership
  - 顶层 `sources/categories/updated_at/expire_at/name/symbol` 同步刷新

### 写入来源约定

- `daily-screening`
  - source 固定写 `daily-screening`
  - category 使用当前业务分类，如 `CLXS_10008`、`CLXS_10004`、`chanlun:buy_zs_huila`、`intersection`
- `shouban30`
  - source 固定写 `shouban30`
  - category 使用板块或场景分类，如 `plate:<plate_key>`、`intersection`
- 手工或旧链路
  - source 固定写 `manual` 或兼容来源名
  - category 使用用户输入或兼容旧值

### 删除规则

- 删除按 `code` 执行
- 删掉整条记录以及其所有 memberships
- 不支持仅删某个来源或分类

## 读取设计

三个页面统一读取同一份“去重后的 pre_pool”。

### canonical 读接口

新增或统一一个 shared pre-pool list 接口，返回：

- `items`
  - 每个 `code` 一条
- `meta`
  - `total`
  - `source_options`
  - `category_options`

每条 `item` 返回：

- `code`
- `name`
- `symbol`
- `sources`
- `categories`
- `memberships`
- `created_at`
- `updated_at`
- `expire_at`
- `workspace_order`

### 页面读口径

- `/kline-slim`
  - 改为展示全量去重的 `pre_pool`
- `/gantt/shouban30`
  - 不再只看 `三十涨停Pro预选` 子集，而是展示全量去重池子
  - 允许前端按 `source=shouban30` 或指定 `category` 进行筛选
- `/daily-screening`
  - 同样展示全量去重池子
  - 默认可以提供 `source=daily-screening` 的筛选入口，但总数应与其他页面一致

## 前端展示设计

三个页面都展示统一字段：

- 标的代码
- 标的名称
- 来源
- 分类
- 最近更新时间

### 来源与分类显示

- `sources` 以 tag 列表展示
- `categories` 以 tag 列表展示
- 当页面需要看某个来源或某个分类时，使用前端筛选，不再靠读不同后端接口分流

### 计数口径

- 页面头部 `pre_pools N`
  - 一律表示“去重后的标的数量”
- 不再展示“原始记录条数”作为页面池子数量

## 旧数据迁移

需要提供一次性收敛脚本或服务迁移方法：

- 读取现有 `stock_pre_pools`
- 按 `code` 分组
- 从旧记录推导 membership：
  - 旧 `remark=daily-screening:clxs`
    - 推导 `source=daily-screening`
    - `category` 优先取旧 `category`
  - 旧 `category=三十涨停Pro预选` 或 `extra.shouban30_*`
    - 推导 `source=shouban30`
    - `category` 取 `intersection` 或 `plate:<plate_key>`
- 合并出单条记录并回写

### 迁移冲突处理

- `name/symbol`
  - 取最近一次非空值
- `created_at`
  - 取最早时间
- `updated_at`
  - 取最晚时间
- `expire_at`
  - 取最晚有效时间
- `workspace_order`
  - 优先沿用已有 `shouban30_order`
  - 无顺序时按稳定排序回填

## 接口兼容策略

- 旧接口可以短期保留 URL
- 但内部都转向 shared pre-pool service
- 对仍依赖旧单值字段的页面，兼容返回：
  - `primary_source`
  - `primary_category`
- 新页面应改为使用：
  - `sources`
  - `categories`
  - `memberships`

## 测试策略

### 后端单元测试

- shared pre-pool service
  - 新 code 插入
  - 相同 `(source, category)` 幂等 upsert
  - 新 `(source, category)` 追加 membership
  - 删除整条记录
  - 统一列表按 `code` 去重返回

### 现有写入链回归

- `daily_screening`
  - 多模型重复写入同一 `code` 时，只保留一条记录
- `shouban30`
  - append 同一 `code` 时不新增第二条
  - 只更新 memberships 和顺序

### 路由测试

- `/api/get_stock_pre_pools_list`
  - 返回去重结果
- `/api/gantt/shouban30/pre-pool`
  - 返回统一结果
- `/api/daily-screening/pre-pools`
  - 返回统一结果

### 前端测试

- `/kline-slim` 侧边栏计数按去重结果展示
- `/gantt/shouban30` 工作区展示来源与分类标签
- `/daily-screening` 工作区展示来源与分类标签
- 三页用同一批 mock 数据时，`pre_pools` 数量一致

## 部署影响

- `freshquant/**`
  - 重建 API Server
- `morningglory/fqwebui/**`
  - 重建 Web UI
- 若增加迁移脚本
  - 需在部署窗口执行一次数据收敛

## 风险与注意点

- 当前部分代码默认 `category` 是单值字符串，必须系统性排查
- `.blk` 同步、`stock_pools` 同步若仍依赖旧顺序字段，需要同时切换到统一 `workspace_order`
- 旧页面若直接读 Mongo 明细结构，会和新真值冲突，必须统一通过 shared service 读取

## 验收标准

- 三个页面同一时点下的 `pre_pools` 数量完全一致
- 同一 `code` 从多个来源写入时，池子总数不增加
- 每行能清楚展示所有来源和分类
- 按 `code` 删除后，该标的从池子彻底消失
- `.blk` 输出基于去重后的池子，不再受重复明细影响
