# 提案：LLM 通道多协议接入（OpenAI Chat / Anthropic Messages / OpenAI Responses）

## Why

owner 2026-09-26 插话两连：①国内几乎所有主流厂商都有 Anthropic 分支（
`/v1/messages` 协议，cc-switch 名单多为其 Claude/Coding 分支）；②「我希望你支持
Anthropic 格式、completions 格式、response 格式等所有主流格式」。当前内核只说
OpenAI Chat Completions 一种协议（`/chat/completions`），用户拿着 Kimi/智谱/
千问的 Anthropic 分支 key 无法直连，只能找 OpenAI 兼容端点或中转。同时 owner
定调：自建网关反代（muniu/one-api 等）不作为强制路径，而是与官方端点平级的
用户自选端点（地位同 Ollama）。

## What Changes

- **通道配置**：`ChannelValues` 新增 `protocol` 字段（枚举 `openai-chat` /
  `anthropic` / `openai-responses`，缺省 `openai-chat` 完全兼容现状），随
  config.toml `[llm]`、`SIKU_LLM_PROTOCOL`、CLI `--llm-protocol` 三层同构解析；
  embedding/rerank 通道对非空 `protocol` 报配置指引错误（不静默忽略）。
- **Provider**：`HttpxLlmProvider` 按协议分发请求构造与响应解析（端点路径、
  凭证头、请求体、响应抽取），幂等语义不变（temperature=0、非流式）；五剧本
  错误映射复用。
- **契约**：`GET/PUT /api/settings` 掩码视图与提交值增 `protocol` 字段（枚举
  校验，非法 422）；连通性探测按协议发起；OpenAPI 快照再生成。
- **UI**：LLM 通道表单新增「接口协议」选择；厂商预设按「厂商 × 协议分支」
  提供（新增 Kimi/智谱/千问的 Anthropic 分支预设），选预设联动协议；
  embedding/rerank 不提供协议选择（内核拒绝）。UI hint 说明：自建网关反代与
  官方端点平级，手填即可，无特殊路径。
- **ADR-0012**：多协议 LLM 接入的决策记录。

## 受影响决策

- ADR-0009（BYOK 分层供给）：`protocol` 是通道的第 5 个可配置维度，随既有
  三层合并；凭证保护语义不变（anthropic 协议用 `x-api-key` 头承载同一凭证值）。
- ADR-0012（新增）：协议是通道属性而非全局开关——不同通道可各异；缺省
  `openai-chat` 保证既有 config.toml 与 CLI 行为零漂移。
- 红线 2（UI↔内核边界）：协议协商全部住内核 provider，前端只提交字段值。

## 与项目路线的关系

Phase 5「桌面无 CLI 上手」的模型接入面扩展；owner 点名批次。

## Non-goals

- 不做协议自动探测/试错回退：协议由用户显式配置，配错由请求期错误映射给中文
  指引（自动探测会把「端点配错」变成「慢」，且五剧本错误语义会被吞）。
- 不接 Google Gemini 原生协议与 AWS Bedrock 原生协议：二者已有 OpenAI 兼容
  端点（预设已覆盖），原生协议收益低、认证链复杂（SIGv4）。
- 不改 DashScope 环境变量回退的协议（恒 `openai-chat`，回退端点本就是兼容
  模式）。
- 不支持 legacy `/v1/completions`（无 chat 语义，图谱/wiki/问答全依赖 chat）。
- 不提供「协议 × 模型」合法性校验：模型名由厂商侧决定，测连接即可验证。
