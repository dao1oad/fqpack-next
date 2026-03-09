# Gantt Shouban30 排除北交所标的 Design

## 目标

将北交所标的彻底排除出 `/gantt/shouban30` 的盘后快照，而不是在页面展示层隐藏。

## 方案

- 过滤层级放在 `freshquant/data/gantt_readmodel.py` 的 `persist_shouban30_for_date()`。
- 板块黑名单过滤保持不变。
- 在进入缠论计算前，按 `code6` 过滤北交所代码段：
  - `43****`
  - `83****`
  - `87****`
  - `92****`
- 只对剩余 A 股候选股执行：
  - `chanlun_*` 计算
  - `shouban30_stocks` 落库
  - `shouban30_plates` 计数聚合
- 过滤后没有剩余候选股的板块，直接不进入 `shouban30_plates`。

## 数据语义

- `candidate_stocks_count`：过滤板块黑名单和北交所标的后的候选数。
- `stocks_count`：上述候选中的缠论通过数。
- `failed_stocks_count`：上述候选中的缠论未通过/不可用数。

## Dagster 与验证

- Dagster graph 不改，只需重建 `shouban30` 四档窗口快照。
- 验证口径：
  - `920xxx` 不再出现在 `shouban30_stocks`
  - 仅由北交所构成的板块不再出现在 `shouban30_plates`
  - `/api/gantt/shouban30/*` 返回与页面统计同步变化
