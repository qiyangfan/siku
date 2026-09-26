# http-api Specification（delta）

## MODIFIED Requirements

### Requirement: 提供模型供给设置的读写端点

系统 SHALL 提供 `GET /api/settings` 返回 LLM/embedding/rerank 三通道配置的掩码视图
（`base_url`、`model`、`api_key_env`、key 是否已设置的布尔标记），SHALL NOT 在响应中
回显任何 key 明文；当通道的有效值来自环境变量层时 SHALL 予以标注。响应 SHALL 附带
`llm_env_fallback`：LLM 通道厂商环境变量回退生效时为其端点描述（`vendor`、
`base_url`、`model`、`api_key_env`，不含凭证明文），未生效时为 `null`；该字段 SHALL
与请求期通道解析同源（计入 serve 的 CLI 层）。系统 SHALL 提供 `PUT /api/settings`，
校验后把提交的三通道配置合并写入 config.toml 并保持 0600 权限，返回写入后的掩码视图；
校验失败 SHALL 返回 422 与既有 `{code, message}` 结构且不改写配置文件。设置读写
SHALL NOT 使 key 进入日志或错误消息。

#### Scenario: 读取返回掩码视图

- **GIVEN** config.toml 已为 llm 通道配置 base_url/model 与明文 api_key
- **WHEN** 客户端请求 `GET /api/settings`
- **THEN** 返回 200，llm 通道含 base_url 与 model，key 仅以「已设置」布尔标记表示，
  响应任何字段不含 key 明文

#### Scenario: 环境变量层覆盖标注

- **GIVEN** `SIKU_LLM_API_KEY` 环境变量存在且 config.toml 另有 api_key
- **WHEN** 客户端请求 `GET /api/settings`
- **THEN** llm 通道标注凭证生效于环境变量层，用户可据知表单保存的文件层值在该变量
  移除前不生效

#### Scenario: 回退生效时响应携带端点描述

- **GIVEN** LLM 通道各层均未配置且环境中 `DASHSCOPE_API_KEY` 非空
- **WHEN** 客户端请求 `GET /api/settings`
- **THEN** `llm_env_fallback` 为非空对象（`vendor`、`base_url`、`model`、
  `api_key_env`），不含凭证明文；显式配置 LLM 通道并保存后再次读取，
  `llm_env_fallback` 为 `null`

#### Scenario: 校验失败返回 422

- **GIVEN** 提交的通道配置含非法形状（如 base_url 非合法 URL）
- **WHEN** 客户端请求 `PUT /api/settings`
- **THEN** 返回 422 与 `{code, message}` 中文指引，config.toml 未被改写

#### Scenario: 写入保持权限与掩码

- **GIVEN** 一次合法的三通道设置提交
- **WHEN** 服务端合并写入 config.toml
- **THEN** 文件权限保持 0600，响应为写入后的掩码视图，日志与响应均无 key 明文
