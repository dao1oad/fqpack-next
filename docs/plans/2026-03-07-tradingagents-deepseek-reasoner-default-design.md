# TradingAgents-CN `deepseek-reasoner` 默认深度模型设计

**日期**：2026-03-07

## 背景

当前 FreshQuant 中接入的 `TradingAgents-CN` 已经把默认分析模型切到 `DeepSeek`，但实际运行配置仍是：

- `quick_analysis_model=deepseek-chat`
- `deep_analysis_model=deepseek-chat`

同时，当前代码和运行配置仍存在三个缺口：

1. 前端模型目录没有 `deepseek-reasoner`
2. 后端按模型名反查 provider 的映射里没有 `deepseek-reasoner`
3. 当前 Mongo 中已存在活动系统配置，重启后会继续沿用旧的 `deepseek-chat` 深度模型默认值

用户要求：

- 将 `deepseek-reasoner` 正式接入 `TradingAgents-CN`
- 配置为默认 `deep_analysis_model`
- 保持 `quick_analysis_model=deepseek-chat`
- 使用 `002682` 做真实股票分析回归，确认深度思考模型可正常使用

## 目标

- 在 `TradingAgents-CN` 内正式支持 `deepseek-reasoner`
- 让前端可见、后端可识别、能力校验可通过、默认系统设置可写入
- 对当前 Docker 运行实例里的活动系统配置做一次安全迁移，使新默认值立即生效
- 在真实分析流程中优先使用 `deepseek-reasoner`
- 当 `deepseek-reasoner` 在工具调用链路失败时，自动回退到 `deepseek-chat`，保证股票分析流程仍可完成

## 非目标

- 不改 `TradingAgentsGraph` 的分析图结构
- 不替换 `TradingAgents-CN` 当前的数据获取逻辑
- 不把 `deepseek-reasoner` 配成快速分析模型
- 不引入新的外部模型供应商
- 不重构整套模型选择系统

## 方案比较

### 方案 A：完整接入 `deepseek-reasoner` 并增加运行时回退（采用）

- 修改模型能力表、默认模型目录、provider 映射、默认系统设置
- 增加一个仅针对 `deepseek-reasoner` 工具调用失败的回退逻辑
- 启动后将当前活动配置迁移到 `deep_analysis_model=deepseek-reasoner`

优点：

- 前后端、默认值、运行态一致
- 真实任务优先用深度思考模型
- 工具调用兼容性不足时不会直接把整条分析链打挂

缺点：

- 需要同时覆盖代码默认值和运行态配置迁移
- 回退逻辑需要精确控制触发条件，避免吞掉无关异常

### 方案 B：只把默认值改成 `deepseek-reasoner`

优点：

- 改动面最小

缺点：

- 当前模型目录和 provider 映射不完整，界面和运行态会不一致
- 若 `reasoner` 在工具调用链失败，会直接导致分析任务失败

### 方案 C：保留 `deepseek-chat` 默认，只允许单次请求指定 `deepseek-reasoner`

优点：

- 风险更低

缺点：

- 不满足“配置为默认深度模型”的要求

## 设计

### 1. 模型注册与能力声明

需要同步补齐以下位置：

- `app/constants/model_capabilities.py`
  - 新增 `deepseek-reasoner`
  - 标记为适合 `DEEP_ANALYSIS`
  - 特性至少包含 `tool_calling` 和 `reasoning`
- `app/services/config_service.py`
  - 默认 `llm_configs` 补 `deepseek-reasoner`
  - 默认 `model_catalog` 的 DeepSeek 列表补 `deepseek-reasoner`

这样做的原因是：

- 前端模型下拉来自模型目录
- 后端推荐和校验依赖能力表
- 默认系统配置初始化依赖 `_create_default_config()`

### 2. 默认值策略

默认值统一为：

- `quick_analysis_model=deepseek-chat`
- `deep_analysis_model=deepseek-reasoner`
- `default_provider=deepseek`
- `default_model=deepseek-chat`

说明：

- `default_model` 在当前系统里更接近“通用默认模型”或“快速模型”语义，保留为 `deepseek-chat` 更稳妥
- 只把深度模型切到 `deepseek-reasoner`，避免快速阶段也被重推理模型拖慢

### 3. 运行态迁移

仅改代码默认值还不够，因为当前 `tradingagents_cn` 中已存在活动系统配置。

需要在 FreshQuant 的 `ta_backend` 启动链路里增加一个 repo 侧 bootstrap 步骤：

- 确保默认管理员继续存在
- 确保当前活动 `system_configs` 的 `system_settings.deep_analysis_model` 被更新为 `deepseek-reasoner`
- 若活动配置中缺少 `deepseek-reasoner` 的 `llm_configs`/目录项，则补齐

迁移范围只限当前接入实例使用的 `tradingagents_cn` 库，不触碰 FreshQuant 其他业务库。

### 4. 回退逻辑

回退只对以下场景生效：

- 当前深度模型是 `deepseek-reasoner`
- 异常发生在多智能体分析执行阶段
- 异常内容明确指向工具调用链不兼容，例如 `tool_calls`、`tool_calling`、`function call`、`tool use`、`unsupported tools`

回退行为：

1. 记录一次 warning，明确说明 `deepseek-reasoner -> deepseek-chat`
2. 保持同一任务重新执行分析，不改变股票代码、日期、研究深度、分析师集合
3. 仅替换深度模型，快速模型仍为 `deepseek-chat`

不回退的情况：

- 鉴权失败
- 网络连接失败
- 数据准备失败
- Mongo/Redis 故障
- 用户输入不合法

### 5. 验收

自动化验收：

- `deepseek-reasoner` 出现在默认模型目录
- `deepseek-reasoner` 可被映射为 `deepseek` provider
- 默认系统配置中 `deep_analysis_model=deepseek-reasoner`
- 当命中工具调用不兼容异常时，回退目标为 `deepseek-chat`

真实验收：

- 使用 `002682` 发起真实单股分析任务
- 任务能完成，不处于 failed
- 结果中能看到本次任务实际使用的模型信息
- 若 `reasoner` 直接成功，记录成功结果
- 若命中回退，也必须记录“原因 + 已回退并完成”的证据

## 落地文件范围

- 修改 `third_party/tradingagents-cn/app/constants/model_capabilities.py`
- 修改 `third_party/tradingagents-cn/app/services/config_service.py`
- 修改 `third_party/tradingagents-cn/app/services/simple_analysis_service.py`
- 修改 `third_party/tradingagents-cn/app/core/unified_config.py`（如需补默认回退值）
- 视迁移实现方式修改 `docker/compose.parallel.yaml` 或新增 `docker/tradingagents/` bootstrap 脚本
- 修改 `third_party/tradingagents-cn/tests/test_tushare_deepseek_defaults.py`
- 更新 `docs/agent/TradingAgents-CN接入与运行说明.md`
- 更新 `docs/migration/progress.md`

## 风险

- `deepseek-reasoner` 是否对当前 LangGraph 工具调用语义完全兼容，必须以真实任务验证为准
- 若回退条件写得过宽，可能掩盖真实缺陷；写得过窄，则无法保护任务完成率
- 当前运行实例使用共享 Mongo/Redis，配置迁移必须只作用于 `tradingagents_cn`
