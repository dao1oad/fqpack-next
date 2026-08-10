# must_pool 买入信号口径对齐 + TDX 导入边界修复方案

> 落盘日期：2026-08-10
> 关联 GitHub Issue：[#547](https://github.com/dao1oad/fqpack-next/issues/547)
> 状态：待评审 / 待实施

## 0. 背景与问题清单（讨论结论汇总）

| # | 问题 | 证据 | 性质 |
|---|------|------|------|
| P1 | 前端「must_pool 买入信号」面板是宽口径（任意周期/类型/无 tag 的 BUY_LONG），与当前 5 分钟监控窄口径（5m + `must_pool_5m_new_open` tag + enabled 池）不一致 | `freshquant\stock_service.py:545-580` vs `freshquant\signal\astock\job\monitor_stock_zh_a_min.py` | 代码 bug（口径分叉） |
| P2 | 面板 must_pool 读取不过滤 `disabled`/`instrument_type`，会把禁用或非股票/ETF 代码混入 | `stock_service.py:558-560` vs `freshquant\pool\general.py:14-25` | 代码 bug |
| P3 | TDX 导入遇标的库查不到的代码，`import_pool` 直接 `instrument["name"]` 抛 TypeError，整次同步失败；`failed_codes` 恒为空；失败代码旧记录会被覆盖删除误删 | `freshquant\data\astock\must_pool.py:270,326,349`、`stock_service.py:459-478` | 代码 bug（边界） |
| P4 | 测试固化了旧宽口径，阻碍回归 | `freshquant\tests\test_stock_pool_service.py:542` | 测试待更新 |
| P5 | 本机 `trading_mode=False` → 5m 线未启用（idle standby）；池内 18 只全部满足监控口径（stock_cn / disabled=False） | 本机 Mongo `params.monitor` + `D:\fqdata\log\fqnext_guardian_event_err.log` | 运维配置（非代码） |
| P6 | 15s/30s 持仓口径容易混淆（数据落库 15s / scope 刷新 30s / 读缓存 15s TTL） | `freshquant\xt_account_sync\worker.py`、`monitor_stock_zh_a_min.py`、`freshquant\data\astock\holding.py` | 文档澄清 |

## 1. 修复目标

1. 面板「must_pool 买入信号」= 当前 5 分钟监控逻辑的真实产出（5m + `must_pool_5m_new_open` tag + enabled must_pool + 非持仓 BUY_LONG）。
2. TDX 导入对未知代码不再整次失败：跳过并计入失败统计，保留旧记录。
3. 测试与 `docs/current/**` 同步到新口径。

## 2. 改动范围（全部在本仓库）

### F1（核心）：面板查询口径对齐

**文件**：`freshquant\stock_service.py` `get_stock_signal_list` 的 `must_pool_buys` 分支（约 551-572 行）

```python
elif category == "must_pool_buys":
    # 与 queryMustPoolCodes() 同口径：enabled + 股票/ETF
    must_pool_codes = sorted(
        str(doc.get("code") or "")
        for doc in DBfreshquant["must_pool"].find(
            {
                "instrument_type": {"$in": ["stock_cn", "etf_cn"]},
                "disabled": {"$ne": True},
            }
        )
        if doc.get("code")
    )
    if not must_pool_codes:
        data = []
    else:
        data = list(
            DBfreshquant["stock_signals"]
            .find(
                {
                    **cond,
                    "period": "5m",                      # 前端格式，与 save_a_stock_signal 写入一致
                    "tags": "must_pool_5m_new_open",     # Mongo 数组包含匹配
                    "code": {"$in": must_pool_codes},
                }
            )
            .sort("fire_time", pymongo.DESCENDING)
            .skip((page - 1) * size)
            .limit(size)
        )
```

要点：
- `period="5m"`：监控写入的是 `to_frontend_period("5min")="5m"`（`freshquant\util\period.py:30`），历史 custom/screening 信号周期格式相同，可直接过滤；
- `tags: "must_pool_5m_new_open"`：Mongo 数组字段用字符串匹配即“包含该元素”；
- 建议把 `"must_pool_5m_new_open"` 提取为模块级常量（与 `freshquant\strategy\guardian.py:48` 的 `MUST_POOL_5M_NEW_OPEN_TAG` 同值，注释互指）；
- `queryMustPoolCodes()` 有 60s 进程缓存（`pool\general.py:14`），这里直接用 Mongo 查询避免引入缓存与跨模块依赖，但**过滤条件保持一致**（若想严格复用，可改为 `from freshquant.pool.general import queryMustPoolCodes` 并 `{"$in": queryMustPoolCodes()}`，二选一，建议直接复用函数保证永不分叉）。

### F2：import_pool 未知标的边界修复

**文件**：`freshquant\data\astock\must_pool.py` `import_pool`（约 270-366 行）

1. `instrument = query_instrument_info(code)` 后加 None 分支：

```python
instrument = query_instrument_info(code)
if instrument is None:
    logger.warning("must_pool import skipped: instrument not found for %s", code)
    return False
```

2. 正常路径末尾 `return True`（保持现有调用方兼容——`add_to_must_pool`、CLI 均可忽略返回值）。

**文件**：`freshquant\stock_service.py` `sync_must_pool_from_tdx_self_select` 循环（约 459-469 行）

```python
try:
    ok = must_pool.import_pool(...)
    if not ok:
        failed_codes.append(code)
        continue
except Exception as exc:                      # 兜底：单条失败不整批失败
    logger.warning("must_pool import failed for %s: %s", code, exc)
    failed_codes.append(code)
    continue
synced_codes.append(code)
```

3. 覆盖删除阶段（约 471-479 行）改为**失败代码保留旧记录**：

```python
target_code_set = set(synced_codes) | set(failed_codes)
```

4. `add_to_must_pool`（约 915 行）同步处理返回值：`if not must_pool.import_pool(...): return False`。

### F3：测试更新

**文件**：`freshquant\tests\test_stock_pool_service.py`

1. 更新 `test_get_stock_signal_list_for_must_pool_buys_filters_current_non_holding_must_pool`（542 行）：
   - must_pool fixture 增加 `disabled=True` / `instrument_type="fund_cn"` 的反例，断言被排除；
   - stock_signals fixture 增加 `period="1m"` 无 tag、`period="5m"` 无 tag、`period="5m"` 带 tag 三类，断言只返回“5m + 带 tag”那条；
   - 断言 `last_query` 含 `period`/`tags`/`code $in` 条件。
2. 新增 `test_import_pool_skips_unknown_instrument`：monkeypatch `query_instrument_info` 返回 None，断言返回 False 且集合无写入。
3. 新增 `test_sync_must_pool_from_tdx_keeps_failed_existing_record`：池中已有 code A，本次同步 A 失败（instrument None），断言 A 的旧记录未被删除、`failed_count=1`。
4. `freshquant\tests\test_must_pool_data.py` 若断言 import_pool 无返回值，保持兼容（返回值不影响既有断言）。

### F4：前端最小调整（可选，低优先）

**文件**：`morningglory\fqwebui\src\views\StockControl.vue`
- 第三栏描述改为“5 分钟买点（must_pool_5m_new_open）监控信号”，与后端口径一致；
- 不改变接口契约，前端测试 `morningglory\fqwebui\tests\stock-control-signal-lists.test.mjs` 无需改动（除非断言文案，改则同步）。

### F5：文档同步（必须，同一 PR）

- `docs\current\reference\stock-pools-and-positions.md:63-65`：把「`/stock-control` 的 `must_pools买入信号`」口径更新为：
  > 条件为 `position=BUY_LONG`、`is_holding=False`、`period=5m`、带 `must_pool_5m_new_open` tag，且 code 当前在 enabled `must_pool`（`instrument_type∈{stock_cn,etf_cn}`、`disabled≠True`）。
- `docs\current\modules\strategy-guardian.md`：在 32-37 行后补一句“面板口径与监控产出一致”的说明，避免再次分叉。
- `docs\current\runtime.md:37`：明确 15s/30s 分层（数据落库 15s、Guardian scope 刷新 30s、读缓存 15s TTL + 同步后版本失效），消除歧义。

## 3. 非目标

- 不改监控逻辑本身（5m 只接受 `buy_v_reverse`/`macd_bullish_divergence`、`buy_zs_huila` 禁用——这是已确认的设计，不是 bug）；
- 不自动把本机 `trading_mode` 置为 true（属于配置变更，需单独走变更流程后再重启 `fqnext_guardian_event`）；
- 不改 15s/30s 周期本身（分层设计合理，只做文档澄清）；
- 不做历史信号回填 tag（历史 5m 信号本就不是当前监控产出；如确需保留展示，可另开维护脚本按 `period=5m + BUY_LONG + 非持仓 + 当时在池` 补 tag，本次不做）。

## 4. 验收标准

1. `pytest freshquant/tests/test_stock_pool_service.py freshquant/tests/test_must_pool_data.py` 全绿；
2. 接口验证：`GET /api/get_stock_signal_list?category=must_pool_buys` 返回记录全部满足 `period=5m` 且 `tags` 含 `must_pool_5m_new_open`；无 tag/非 5m/禁用池代码的信号不再出现；
3. TDX 同步验证：构造含未知代码的临时待买组，同步返回 `failed_count≥1`，未知代码旧记录保留，其余代码正常覆盖；
4. 前端页面刷新后第三栏只显示 5 分钟买点信号；
5. `docs/current/**` 已同步（`docs-current-guard` CI 通过）。

## 5. 部署与流程（GitHub-first）

1. **分支**：`codex/fix-must-pool-signal-panel-alignment`（禁止直推 main）；
2. **PR 正文**：写清背景、目标、范围、非目标、验收标准、部署影响（上述 1-4 节）；
3. **CI 三绿**：`docs-current-guard` / `pre-commit` / `pytest`；
4. **合并后部署**：按部署矩阵，改动涉及 `freshquant/stock_service.py`（rear 依赖）与 `freshquant/data/astock/must_pool.py`（API 与 subject_management 依赖）：
   - 重部署 API server（`fq_apiserver`，镜像 `fqnext_rear:2026.2.23`）；
   - `fqnext_guardian_event` 不直接依赖 `import_pool`，无需重启；如稳妥起见可随 trading 链一并重启；
5. **健康检查**：API 存活 + `/api/get_stock_signal_list?category=must_pool_buys` 口径抽查 + TDX 同步一次成功；
6. **清理**：删除已合并远端分支、临时测试分组文件与临时脚本。

## 6. 残余风险与恢复

- **历史信号展示变化**：面板将不再显示 2026-08-06 之前无 tag 的 5m 信号——这是本次修复的预期行为（它们不属于当前监控产出）；如业务需要历史回看，另行评估 backfill；
- **未知代码同步行为变化**：从“整批失败”变为“跳过并保留旧记录”——更接近覆盖契约本意，但需确认业务接受“部分成功”；
- 恢复方式：PR revert 后重部署即可回到当前行为；配置类（trading_mode）不在本 PR 内，互不影响。
