# ADR-0012：LLM 通道多协议接入

- 状态：已接受（2026-09-26）
- 关联：ADR-0009（BYOK 模型供给分层）

## 背景

内核 LLM provider 原本只说 OpenAI Chat Completions 一种线协议。国内主流厂商
（Kimi、智谱、通义千问等）普遍同时提供 OpenAI 兼容分支与 Anthropic 分支
（`/v1/messages`），OpenAI 自家又推出了 Responses API；用户持有哪类 key 不由
siku 决定。同时 owner 定调：自建网关反代（muniu/one-api 等）不作为强制路径，
而是与官方端点平级的用户自选端点（地位同 Ollama）。

## 决策

1. **协议是 LLM 通道的第 5 个配置字段**（`protocol`），随既有三层
   （CLI > 环境变量 > config.toml）合并，枚举 `openai-chat`（缺省）/
   `anthropic` / `openai-responses`。缺省值保证既有配置与 CLI 行为零漂移。
2. **协议差异收敛在 provider 的请求/响应两端**：端点路径、凭证头、system 位置、
   必填参数与文本抽取方式按协议分发；幂等语义三协议一致（temperature=0、
   非流式），不破坏「重建产物 diff 为空」闸门；五剧本错误映射复用。
3. **embedding/rerank 不开放协议字段**：二者线协议事实上单一，遇到非空
   `protocol` 报配置指引错误（fail loud）。
4. **不做协议自动探测**：配错由请求期错误映射给中文指引；自动探测把「配错」
   变成「慢」，且会吞掉五剧本的确定性语义。
5. **自建网关平级**：不内置、不默认、不强制任何中转；官方直连与自建反代都是
   「用户自配端点」，协议字段同样适用于 Anthropic 协议反代。

## 后果

- 用户可直接使用厂商 Anthropic 分支 key 与 OpenAI Responses 端点，无需中转。
- 设置契约、连通性探测与 CLI 旗标同步携带协议；预设按「厂商 × 协议分支」组织。
- 换协议不换凭证体系：anthropic 用 `x-api-key` 头承载同一凭证值，凭证保护
  （SecretStr、0600、不进日志）语义不变。
- 新增协议（如 Gemini 原生、Bedrock SIGv4）时在 provider 内增加分发分支并扩展
  枚举，调用方与契约形状不变。
