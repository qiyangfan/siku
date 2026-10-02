# model-supply Specification（delta）

## ADDED Requirements

### Requirement: LLM 通道支持厂商环境变量回退

系统 SHALL 在 LLM 通道三层（CLI 参数、环境变量、config.toml）合并结果的所有字段
（`base_url`、`model`、`api_key`、`api_key_env`）均未设置，且运行环境中
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
