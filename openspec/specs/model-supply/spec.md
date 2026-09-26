# model-supply Specification

## Purpose
统一管理 LLM、embedding、rerank 三类模型端点的供给配置：分层解析（CLI > 环境变量 >
配置文件 > 报错）、凭证保护、以及与桌面应用一致的本机配置文件位置。模型一律经
用户配置的端点（云或自部署）供给，内核不内置任何模型。

## Requirements

### Requirement: 分层解析模型供给配置

系统 SHALL 按 CLI 参数 > 环境变量 > 配置文件的优先级解析 LLM、embedding、rerank 三类
端点配置（`base_url`、`model`、凭证）；任一必需项在所有层级均缺失时，SHALL 返回
可行动的配置指引而非静默使用默认端点。配置文件路径 SHALL 使用平台应用配置目录下的
`config.toml`，与桌面数据根目录决策一致。

#### Scenario: 高层级覆盖低层级

- **GIVEN** config.toml 与 CLI 参数同时提供了 embedding 端点的 `model`
- **WHEN** 用户以 CLI 参数执行索引
- **THEN** 系统使用 CLI 参数值，config.toml 值仅在 CLI 未提供时生效

#### Scenario: 缺失必需配置时报错

- **GIVEN** 用户未以任何层级配置 embedding 端点
- **WHEN** 用户执行需要 embedding 的命令
- **THEN** 系统报错并给出 config.toml 模板位置或 CLI 参数示例，不回退到任何内置默认端点

#### Scenario: 配置文件三平台定位一致

- **GIVEN** 用户分别在 macOS、Windows、Linux 上安装
- **WHEN** 系统读取模型供给配置
- **THEN** 配置文件位于各自平台应用配置目录下的 `config.toml`，且解析行为在三平台一致

### Requirement: 保护模型凭证

系统 SHALL 支持两种凭证提供方式：配置文件内的 `api_key` 明文（文件创建时 SHALL 为
0600 权限）或 `api_key_env` 环境变量间接引用；系统 MUST NOT 将任何凭证写入日志、
索引元数据、评测基线、错误消息或 OpenAPI 契约。

#### Scenario: 明文 key 的文件权限

- **GIVEN** 用户在 config.toml 中直接写入 `api_key`
- **WHEN** 系统创建或重写该配置文件
- **THEN** 文件权限为 0600，非本用户不可读

#### Scenario: 凭证不泄漏

- **GIVEN** 一次使用明文 `api_key` 的端点调用因 401 失败
- **WHEN** 系统记录日志或返回错误
- **THEN** 日志、错误消息与任何持久化产物中均不包含该 key 的值

### Requirement: LLM 通道支持厂商环境变量回退

系统 SHALL 在 LLM 通道三层（CLI 参数、环境变量、config.toml）合并结果的所有字段
（`base_url`、`model`、`api_key`、`api_key_env`、`protocol`）均未设置，且运行环境中
`DASHSCOPE_API_KEY` 非空时，将该通道回退为通义千问 OpenAI 兼容端点（固定
`base_url` 与默认模型，`api_key_env` 指向 `DASHSCOPE_API_KEY`）。任一 LLM 字段
被任何层级显式设置时系统 SHALL NOT 回退；embedding 与 rerank 通道 SHALL NOT
适用任何厂商回退。回退 SHALL 与请求期通道解析同源：问答就绪判定、生成链路与
连通性测试 SHALL 依据同一回退结果。

#### Scenario: 三层缺省且环境变量存在时回退生效

- **GIVEN** config.toml、`SIKU_LLM_*` 环境变量与 CLI 参数均未提供任何 LLM 通道
  字段，且环境中 `DASHSCOPE_API_KEY` 非空
- **WHEN** 系统解析 LLM 通道或判定问答就绪
- **THEN** 解析结果为通义千问兼容端点（固定 base_url 与默认模型、
  `api_key_env=DASHSCOPE_API_KEY`），就绪判定不再因 llm 凭证缺失而阻塞

#### Scenario: 任一字段显式配置时不回退

- **GIVEN** config.toml 为 LLM 通道设置了 `api_key_env`（其余字段为空）且
  `DASHSCOPE_API_KEY` 存在
- **WHEN** 系统解析 LLM 通道
- **THEN** 按显式配置解析（base_url/model 沿用既有缺省语义），不切换到通义端点

#### Scenario: 环境变量缺失时保持既有缺省

- **GIVEN** LLM 通道三层均未配置且环境中无 `DASHSCOPE_API_KEY`
- **WHEN** 系统解析 LLM 通道或判定问答就绪
- **THEN** 行为与本需求生效前完全一致（DeepSeek 缺省端点，缺失
  `llm.api_key` 进入就绪缺项清单）

#### Scenario: embedding 通道不享受回退

- **GIVEN** embedding 通道三层均未配置且环境中 `DASHSCOPE_API_KEY` 非空
- **WHEN** 系统解析 embedding 通道或判定问答就绪
- **THEN** 仍报配置指引缺项（`embedding.base_url`、`embedding.model`），
  不回退到任何内置端点

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
