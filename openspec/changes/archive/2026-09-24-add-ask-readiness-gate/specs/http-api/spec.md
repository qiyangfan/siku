# http-api Specification（delta）

## ADDED Requirements

### Requirement: 暴露问答就绪状态

`GET /api/settings` 与 `PUT /api/settings` 响应 SHALL 附带 `ask_readiness`
（`ready` 布尔与 `missing` 字符串列表）：就绪 SHALL 按 ADR-0009 三层合并口径判定
——llm 通道凭证可解析且 embedding 通道 base_url/model 齐备；rerank 通道 SHALL NOT
阻塞就绪。`missing` SHALL 使用稳定的 `<channel>.<field>` 机器 token，SHALL NOT
包含任何凭证明文。判定 SHALL 与问答请求期的通道解析同源，不得引入第二套配置
事实源。

#### Scenario: 未配置时返回缺失明细

- **GIVEN** config.toml 与环境变量层均未提供任何通道配置
- **WHEN** 客户端请求 `GET /api/settings`
- **THEN** 返回 200，`ask_readiness.ready=false`，`missing` 含 `llm.api_key`、
  `embedding.base_url`、`embedding.model`，且不含 rerank 通道条目与任何凭证

#### Scenario: 环境变量层补齐即就绪

- **GIVEN** 文件层为空但 `SIKU_LLM_API_KEY`、`SIKU_EMBEDDING_BASE_URL`、
  `SIKU_EMBEDDING_MODEL` 均已设置
- **WHEN** 客户端请求 `GET /api/settings`
- **THEN** `ask_readiness.ready=true` 且 `missing` 为空——判定覆盖环境变量层

#### Scenario: 保存后响应携带最新就绪状态

- **GIVEN** 客户端经 `PUT /api/settings` 提交了齐备的 llm 与 embedding 配置
- **WHEN** 写入成功返回
- **THEN** 响应的 `ask_readiness.ready=true`，UI 可免二次请求直接刷新门控状态

#### Scenario: 问答未配置错误的 UI 导向文案

- **GIVEN** embedding 通道未配置且客户端请求 `/api/ask`
- **WHEN** 服务返回错误
- **THEN** 返回 503 与 `code=model_not_available`，message 为引导「设置」页的
  中文文案，不出现 config.toml 路径或命令行参数
