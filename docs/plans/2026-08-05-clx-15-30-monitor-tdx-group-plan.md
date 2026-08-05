# CLX 15/30 监控结果自动去重追加到通达信新自选股分组

日期：2026-08-05
状态：待与 Devin 评审后定稿
关联需求：clx_15_30 监控结果自动去重追加到通达信新增自选股分组

## 目标

- 通达信中新增一个自选股分组 `clx_15_30`（文件 `T0002/blocknew/CLX_15_30.blk`）。
- `strategy_consumer` 的 CLX 15/30 监控命中（写 `realtime_screen_multi_period` 的正信号）自动去重追加到该分组。
- 复用现有通达信实现：`freshquant/clx_daily_selection/tdx_export.py` 的编码与原子写模式。

## 现状事实（本机核实）

- 监控命中写入点：`freshquant/market_data/xtdata/strategy_consumer.py::_process_clx_signals`
  - 正信号 docs 写入 `realtime_screen_multi_period`，随后 DingTalk 聚合通知。
  - `meta["code"]` 为带前缀代码（如 `sh600000`），`_base_code()` 可还原 6 位代码。
- 可复用实现：`freshquant/clx_daily_selection/tdx_export.py`
  - `encode_tdx_blk_code()`：6 位/带前缀代码 → TDX `.blk` 行（`1/0/2` + 6 位）。
  - `write_clx_tdx_group()`：全量覆盖 `CLX_18.blk`，GBK + CRLF + temp/fsync/os.replace 原子写。
- 消费进程可写 TDX：supervisord `[program-default] envFiles=D:/fqpack/config/envs.conf` 已含
  `TDX_HOME=D:/new_tdx` 与 `FRESHQUANT_TDX__HOME=D:/new_tdx`，`bootstrap_config.tdx.home` 在 consumer 进程可解析。

## 方案（最小化，复用现有实现）

1. `freshquant/clx_daily_selection/tdx_export.py`
   - 新增常量：`CLX_15_30_TDX_GROUP_DISPLAY_NAME="clx_15_30"`、`CLX_15_30_TDX_BLOCK_KEY="CLX_15_30"`、`CLX_15_30_TDX_BLK_FILENAME="CLX_15_30.blk"`。
   - `write_clx_tdx_group` 增加可选参数 `block_key/display_name`（默认保持 `CLX_18`，向后兼容）。
   - 新增 `read_tdx_blk_codes(tdx_home=None, filename=...)`：读回现有分组行并解码为 6 位代码（顺序保留、去重）。
   - 新增 `append_clx_15_30_tdx_group(codes, *, tdx_home=None)`：
     - 现有行 + 新命中代码合并，按首见顺序去重；
     - 无新代码时不写文件，返回 `appended_count=0`；
     - 有新增时复用原子写（GBK、CRLF、temp+fsync+replace），失败保留旧分组并抛错。
2. `freshquant/market_data/xtdata/strategy_consumer.py::_process_clx_signals`
   - `insert_many` 成功后，收集 docs 的 `_base_code(code)` 去重集合，best-effort 调用
     `append_clx_15_30_tdx_group(codes)`；异常仅记 warning，不影响信号主链。
3. 测试
   - `freshquant/tests/test_clx_daily_selection_tdx_export.py`：append 去重/顺序/无新增不写/原子失败保留旧文件/泛化参数兼容。
   - consumer 侧：新增对 docs→base codes 去重的纯函数测试。
4. 文档：`docs/current/modules/market-data-xtdata.md` 补充“正信号写库后去重追加通达信 `CLX_15_30.blk` 分组”。

## 非目标

- 不改变 `CLX_18.blk` 每日选股导出行为。
- 不改变 `stock_pools` / `must_pool` 语义。
- 不触发下单、不写 `must_pool`。

## 部署面

- `freshquant/market_data/**` → 重启 consumer（`fqnext_realtime_xtdata_consumer`）。
- `freshquant/clx_daily_selection/**` → 重部署 API（`fq_apiserver`），因 clx_daily_selection 路由由 API 提供。

## 验收

- pytest：`test_clx_daily_selection_tdx_export.py` 新增用例全绿；相关既有用例全绿。
- consumer 进程重启后运行验证通过；TDX 分组文件在无命中时不创建、有命中时去重追加。

## Devin 评审结论（2026-08-05，已达成一致）

Devin 单轮评审（只读，基于 GitHub main 克隆核对）方向同意，3 个必改点：

1. 不泛化 `write_clx_tdx_group`（保持其签名与 CLX_18 行为不变），新增独立 `append_tdx_group_members`，并抽取共用原子写 `_atomic_write_blk`。
2. 去重按“编码后 7 字符行”直接比对，禁止解码回 6 位再编码（LOF 如 160512 裸 6 位会 fail-closed）；consumer 侧直接传带前缀的 `meta["code"]`（如 sh600000）给编码函数。
3. `_process_clx_signals` 挂载点正确；但回调来自线程池并发，读-合并-重写需模块级 `threading.Lock`；空追加（无新成员）应为 no-op，不抛错、不触碰旧文件。

最终文件级改动清单：
- `freshquant/clx_daily_selection/tdx_export.py`：新增 `CLX_15_30_*` 常量、`_TDX_BLK_WRITE_LOCK`、`_atomic_write_blk`、`read_tdx_blk_lines`、`append_tdx_group_members`；`write_clx_tdx_group` 改为复用 `_atomic_write_blk`（行为与错误文案不变）。
- `freshquant/market_data/xtdata/strategy_consumer.py::_process_clx_signals`：insert_many 之后 best-effort 调用 `append_tdx_group_members([d.get("code") for d in docs])`，异常仅 warning。
- 测试：`freshquant/tests/test_clx_daily_selection_tdx_export.py` 新增 append/read 用例；新增 `freshquant/tests/test_xtdata_consumer_clx_tdx_group.py` 验证挂载与 best-effort。
- 文档：`docs/current/modules/market-data-xtdata.md` 补充分组写入说明。
