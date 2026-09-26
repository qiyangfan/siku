# model-supply Specification（delta）

## ADDED Requirements

### Requirement: LLM 通道支持多协议接入

LLM 通道 SHALL 支持三种线协议：`openai-chat`（缺省，既有 `/chat/completions`
行为）、`anthropic`（Messages API：`{base_url}/v1/messages`、`x-api-key` 与
`anthropic-version` 凭证头、顶层 `system` 字段、`max_tokens` 必填）、
`openai-responses`（`{base_url}/responses`、顶层 `instructions` 字段）。
`protocol` SHALL 作为通道配置字段随既有三层（CLI > 环境变量 > config.toml）
合并解析，缺省 `openai-chat` 且缺省行为与既有完全一致。三协议 SHALL 保持同等
幂等语义（temperature=0、非流式），并 SHALL 复用既有五剧本错误映射。embedding
与 rerank 通道遇到非空 `protocol` SHALL 返回配置指引错误而非静默忽略；非法
枚举值 SHALL 在解析与提交校验时报可行动的中文指引。

#### Scenario: 缺省协议行为零漂移

- **GIVEN** 用户未在任何层级配置 `protocol`
- **WHEN** 执行图谱抽取或问答
- **THEN** 请求发往 `{base_url}/chat/completions`，行为与协议字段引入前完全一致

#### Scenario: Anthropic 分支直连

- **GIVEN** 用户配置 `protocol = "anthropic"` 与某厂商 Anthropic 分支端点
- **WHEN** 系统发起一次抽取调用
- **THEN** 请求发往 `{base_url}/v1/messages`，凭证经 `x-api-key` 头承载，
  system 以顶层字段传递，响应按 `content[]` 文本块抽取

#### Scenario: OpenAI Responses 协议直连

- **GIVEN** 用户配置 `protocol = "openai-responses"`
- **WHEN** 系统发起一次抽取调用
- **THEN** 请求发往 `{base_url}/responses`，system 经 `instructions` 传递，
  响应按 `output[]` 消息项的 `output_text` 抽取

#### Scenario: embedding 通道拒绝 protocol 字段

- **GIVEN** 用户在 embedding 通道设置了非空 `protocol`
- **WHEN** 系统解析 embedding 通道
- **THEN** 返回配置指引错误，说明该字段仅 LLM 通道支持，不静默忽略

#### Scenario: 非法协议值报可行动指引

- **GIVEN** 用户提交或配置了枚举之外的 `protocol` 值
- **WHEN** 系统解析通道或处理设置提交
- **THEN** 返回 422/解析错误与中文指引，列出三个合法值
