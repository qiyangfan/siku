# http-api Specification（delta）

## ADDED Requirements

### Requirement: 提供模型供给设置的读写端点

系统 SHALL 提供 `GET /api/settings` 返回 LLM/embedding/rerank 三通道配置的掩码视图
（`base_url`、`model`、`api_key_env`、key 是否已设置的布尔标记），SHALL NOT 在响应中
回显任何 key 明文；当通道的有效值来自环境变量层时 SHALL 予以标注。系统 SHALL 提供
`PUT /api/settings`，校验后把提交的三通道配置合并写入 config.toml 并保持 0600 权限，
返回写入后的掩码视图；校验失败 SHALL 返回 422 与既有 `{code, message}` 结构且不改写
配置文件。设置读写 SHALL NOT 使 key 进入日志或错误消息。

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

#### Scenario: 校验失败返回 422

- **GIVEN** 提交的通道配置含非法形状（如 base_url 非合法 URL）
- **WHEN** 客户端请求 `PUT /api/settings`
- **THEN** 返回 422 与 `{code, message}` 中文指引，config.toml 未被改写

#### Scenario: 写入保持权限与掩码

- **GIVEN** 一次合法的三通道设置提交
- **WHEN** 服务端合并写入 config.toml
- **THEN** 文件权限保持 0600，响应为写入后的掩码视图，日志与响应均无 key 明文

### Requirement: 设置写入后无需重启生效

serve 进程 SHALL 在设置写入后使缓存的三通道 provider 失效，下一次检索或问答按新
配置重建 provider；既有端点行为、健康检查语义与 OpenAPI 既有部分 SHALL 保持不变。
当提交的 embedding 模型身份相对索引元数据发生变更时，写入响应 SHALL 附带需全量重建
索引的中文告警；系统 SHALL NOT 自动触发重建。

#### Scenario: 保存后直接问答

- **GIVEN** serve 已按旧配置启动并完成过一次问答
- **WHEN** 用户经 `PUT /api/settings` 更新 LLM 端点后立即发起新问答
- **THEN** 新问答按新端点执行，无需重启 serve

#### Scenario: embedding 变更返回重建告警

- **GIVEN** 索引元数据记录的 embedding 模型身份为 A
- **WHEN** 用户经 `PUT /api/settings` 把 embedding 模型改为 B
- **THEN** 写入成功且响应含「需全量重建索引」的中文告警，系统不自动触发重建

### Requirement: 提供端点连通性测试

系统 SHALL 提供 `POST /api/settings/test`，对提交或当前生效的单通道配置发起最小
探测调用（不携带任何语料内容）；成功 SHALL 返回可达结果与耗时，失败 SHALL 按既有
provider 错误映射返回 503 与 `{code, message}` 中文指引。测试 SHALL NOT 持久化任何
状态或凭证，SHALL NOT 在错误中回显上游端点的原始错误体。

#### Scenario: 测试可达端点

- **GIVEN** 一个可达的 embedding 端点配置
- **WHEN** 客户端请求 `POST /api/settings/test`
- **THEN** 返回 200 与成功标记及耗时，未写入任何配置或索引产物

#### Scenario: 测试失败映射既有错误语义

- **GIVEN** 提交的端点返回 401
- **WHEN** 客户端请求 `POST /api/settings/test`
- **THEN** 返回 503 与 `{code, message}`，message 为中文凭证/配置指引，响应不含
  上游错误体回显与任何 key
