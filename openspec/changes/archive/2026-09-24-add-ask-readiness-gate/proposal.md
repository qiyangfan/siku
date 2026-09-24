# 提案：问答就绪门控（未配置模型端点时置灰提交并给中文引导）

## Why

BYOK 语义下问答链路依赖用户自配的模型端点，但当前 UI 在未配置时不做任何前置
拦截：用户输入问题、点击提交，等检索走完才收到一条 503——且 `model_not_available`
文案是 CLI 导向的（config.toml 路径、`--embedding-base-url` 等命令行参数），
对纯桌面用户既晚又难懂。owner 2026-09-24 点名：未配置时应直接置灰提交入口并给
友好提示，而不是点击后报技术错误。

## What Changes

- 内核新增问答就绪判定 `model_supply.ask_readiness`：按 ADR-0009 三层合并口径
  判定「问答就绪 = llm 通道凭证可解析 且 embedding 通道 base_url/model 齐备」；
  rerank 通道可选（reranker=none 一等公民），永不阻塞。缺失项以稳定机器 token
  （`llm.api_key`、`embedding.base_url`、`embedding.model`）表达。
- `GET/PUT /api/settings` 响应新增 `ask_readiness: {ready, missing[]}` 字段
  （additive，OpenAPI 快照显式刷新）；PUT 响应携带保存后的最新就绪状态，UI 保存
  即刷新、免重启生效。
- `/api/ask` 错误映射（HTTP 专属 `map_ask_error`）新增 `ModelNotAvailableError`
  分支：文案改为 UI 导向（引导到「设置」页），不再出现 config.toml 路径与 CLI
  参数；CLI 既有指引文案不变。
- UI 问答视图门控：就绪状态随问答视图可见性刷新；未就绪时提交按钮置灰、提示语
  替换、展示引导卡片（缺失项中文说明 + 「去设置」入口）；设置保存回调刷新就绪
  状态。就绪状态获取失败时不阻塞提交（fail-open，后端错误文案兜底）。

## 受影响决策

- 红线 1 / ADR-0002：就绪判定（问答需要哪些通道、三层如何合并）是内核语义，
  全部位于 model_supply/API 层；UI 只消费 `ready/missing` 并负责中文话术展示，
  不复刻分层合并逻辑。
- 红线 2 / ADR-0009：判定口径与 `resolve_*_channel` 完全一致（含空串归一、
  env 优先、llm 兼容缺省），不引入第二套配置事实源。
- 不新增 ADR：无架构级新决策，属既有 BYOK 供给语义在 UI 面上的前置呈现。

## 与项目路线的关系

Phase 5「桌面无 CLI 上手」链路的体验补齐（装上 → 配模型 → 问 的最后一处断点），
owner 2026-09-24 会话点名立项。不改变发布形态与排序中其它项的优先级。

## Non-goals

- 不做端点真实可达性校验：就绪 ≠ 端点在线，连通性仍走既有 `POST /api/settings/test`
  与请求期错误映射。
- 不覆盖问答的其它前置状态：索引缺失/过期（409 index_unavailable 等）既有路径
  与文案不变。
- 不改 CLI 行为、config.toml 形状与三层优先级语义。
- 不做设置页内的实时连通性自动探测、不做问答前置检查的独立端点。
- 不改 `/api/ask` 请求/响应成功契约与其它错误码语义；OpenAPI 变更仅限
  settings 响应新增字段。

## 边界裁决

- `missing` token 是稳定契约（`<channel>.<field>`），中文话术由 UI 生成——内核
  不承载展示文案，UI 不承载判定逻辑。
- 门控只作用于「提交」动作与其引导：输入不被禁用（用户仍可先写问题），重试、
  健康检查等既有行为不变。
- 就绪状态获取失败（如内核暂不可达之外的解析异常）按 fail-open 处理：不置灰，
  保留既有提交后错误提示路径，避免把用户锁死在未知状态。
