# Gantt Shouban30 聚合视图设计

## 背景

当前 `/gantt/shouban30` 页面只支持按单一来源 `xgb` 或 `jygs` 展示 30 天首板板块、板块内热点标的和标的详情。页面顶部的来源/窗口切换器占用横向空间，左栏板块列表仍以连续段展示，且没有“跨来源聚合”的统一视图。

这次需求不引入新的后端聚合接口。聚合语义仍由前端基于现有 `xgb/jygs` 两份查询结果完成；为支持精确并集统计，读模型会在原有 `shouban30_plates / shouban30_stocks` 文档上附加命中交易日数组字段，但不新增新的查询路由。

## 目标

- 将来源标签和窗口选择器移动到左栏“首板板块”区域上方。
- 左栏按“最后一次上板时间（`seg_to`）从近到远”排序，并把“连续段”列改为“最后上板”。
- 新增“聚合”标签，合并 `xgb` 与 `jygs` 的热门板块和热门标的。
- 在标签区域展示当前视图的统计信息：热门板块数、热门个股数。

## 非目标

- 不新增新的 Flask API 或 Mongo 聚合快照。
- 不修改 Dagster `shouban30_*` 的构建逻辑。
- 不改变右栏“历史全量热门理由”的查询接口和语义。

## 聚合规则

### 板块聚合

- 聚合视图会并行拉取当前窗口下的 `xgb` 与 `jygs` 两份板块列表。
- 以 `plate_name` 完全同名作为同一聚合板块的判定条件。
- 不同名板块保持各自独立。
- 同名板块的字段合并规则：
  - `last_up_date`：取两边 `seg_to` 的最大值。
  - `appear_days_30`：取两边命中交易日的并集去重计数。
  - `reason_text`：取 `last_up_date` 对应来源的理由。
  - `stocks_count`：取聚合后去重的 `code6` 数量。
  - `providers`：记录该聚合板块来自哪些原始来源，供后续下钻。

### 标的聚合

- 当聚合视图选中某个板块时，前端并行拉取其对应来源的原始标的列表。
- 以 `code6` 去重，同一标的命中多个来源时合并为一条。
- 同名聚合板块下的标的字段合并规则：
  - `hit_count_window`：按两边命中交易日并集去重计数。
  - `latest_trade_date`：取更晚日期。
  - `latest_reason`：取 `latest_trade_date` 对应来源的理由。
  - `providers`：记录命中来源集合。

### 统计信息

- `xgb` / `jygs` 标签：直接显示该来源下板块数、按去重 `code6` 统计的个股数。
- `聚合` 标签：显示聚合后板块数、按去重 `code6` 统计的个股数。

## 页面布局

- 页面顶栏保留标题、`as_of_date`、窗口日期范围。
- 左栏卡片内部新增一个控制区：
  - 第一行：`XGB / JYGS / 聚合`
  - 第二行：`30 / 45 / 60 / 90`
  - 第三行：`N 个热门板块 / M 个热门个股`
- 中栏和右栏结构保持不变。

## 排序与默认选中

- 左栏按 `last_up_date desc -> appear_days_30 desc -> plate_name asc` 排序。
- 单源视图中 `last_up_date` 即 `seg_to`。
- 聚合视图中 `last_up_date` 为合并后的最大日期。
- 中栏按 `latest_trade_date desc -> hit_count_window desc -> code6 asc` 排序。
- 切换标签或窗口时，仍维持“左栏默认选第一条 -> 中栏默认选第一条 -> 右栏自动加载详情”的交互。

## 技术方案

- 前端新增一个纯 helper 模块，封装：
  - 单源板块排序
  - 聚合板块构建
  - 聚合标的构建
  - 统计信息计算
- 后端在现有读模型上追加：
  - `shouban30_plates.hit_trade_dates_30`
  - `shouban30_stocks.hit_trade_dates_30`
  - `shouban30_stocks.hit_trade_dates_window`
  这些字段只用于精确聚合，不改变既有接口入参与路由结构。
- Vue 页面只负责：
  - 并行拉取 `xgb/jygs`
  - 根据当前标签切换计算后的视图
  - 触发下钻
- 后端仍只保留现有 `/api/gantt/shouban30/plates|stocks` 与 `/api/gantt/stocks/reasons`。

## 测试策略

- 新增前端纯函数测试，覆盖：
  - 单源板块按最后上板时间排序
  - 同名板块聚合与理由选择
  - 聚合标的按 `code6` 去重
  - 聚合统计按去重 `code6` 计算
- 保留并复用后端现有 `gantt` 相关测试。
- 页面级验证使用：
  - `npm run build`
  - Docker 重建 `fq_webui`
  - Edge headless 打开目标 URL 检查关键 DOM 文本

## 风险

- 前端聚合依赖两次 API 请求，切换标签时请求数量会增加，需要用请求序号防止旧响应覆盖新状态。
- `plate_name` 完全同名去重是业务约定，若来源间同义不同名仍会保留为两条，这是本次明确接受的边界。
