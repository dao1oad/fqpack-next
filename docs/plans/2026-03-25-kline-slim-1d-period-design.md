# Kline Slim 1D Period Design

**背景**

`kline-slim` 当前周期上限是 `30m`。前端周期枚举没有 `1d`，后端 `/api/stock_data` 的 `realtimeCache` 只覆盖分钟级 Redis 读取路径，因此用户无法直接查看 `1d`，也没有一个和现有周期使用方式一致的日线缓存入口。

**目标**

- 在 `kline-slim` 中增加 `1d` 周期
- 保持和现有 `1m/5m/15m/30m` 一致的接口使用方式
- 不改变现有分钟级缓存行为
- 在 `1d` 场景下支持 Redis 读取缓存，缓存按“当天有效”失效

**非目标**

- 不重写现有分钟级 Redis 缓存模型
- 不给分钟级周期新增 miss 后回写
- 不新增新的前端接口或单独的 `1d` API

**方案选择**

采用“统一读路径、受控扩展”的方案：

- 前端把 `1d` 纳入 `kline-slim` 支持周期列表
- 后端把 `1d` 纳入 `realtimeCache` 的可读取周期集合
- `/api/stock_data` 继续保持“先读 Redis，miss 后 fallback 到 `get_data_v2()`”的行为
- 不给分钟级周期新增 miss 后回写，避免改变它们当前的新鲜度语义
- `1d` 的 Redis key 复用现有 `get_redis_cache_key()` 规范
- `1d` 的 Redis 缓存 TTL 设置为到本地次日 `00:00`

**一致性策略**

- 对外接口保持一致：
  - 仍然使用 `/api/stock_data`
  - 仍然通过 `period` 指定周期
  - 仍然通过 `realtimeCache=1` 控制是否启用 Redis
  - 仍然在 `endDate` 存在时绕过 Redis
- 对内缓存模型保持克制：
  - 分钟周期继续沿用当前“只读 Redis + fallback”模型
  - `1d` 只是接入同一读取入口和同一 key 规范，不额外改变分钟周期的 miss 行为

**实现范围**

- 前端：
  - `morningglory/fqwebui/src/views/js/kline-slim-chanlun-periods.mjs`
  - 必要的前端测试
- 后端：
  - `freshquant/util/period.py`
  - `freshquant/rear/stock/routes.py`
  - `freshquant/tests/test_stock_data_route_cache.py`
- 文档：
  - `docs/current/modules/kline-webui.md`

**测试策略**

- 前端测试验证 `1d` 周期会被识别、不会被归一化回 `5m`
- 后端测试验证：
  - `1d` 在 `realtimeCache=1` 时会读 Redis
  - `1d` miss 时仍然 fallback 到 `get_data_v2()`
  - `endDate` 请求绕过 Redis
  - `1d` 使用现有 key 规范

**风险与控制**

- 风险：把 `1d` 直接并入实时缓存支持集后，误伤现有分钟级逻辑
- 控制：只扩展可读周期，不新增分钟级回写逻辑；测试覆盖分钟级现有行为不回退
