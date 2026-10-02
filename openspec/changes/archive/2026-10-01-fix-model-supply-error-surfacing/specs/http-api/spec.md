# http-api Specification（delta）

## MODIFIED Requirements

### Requirement: 领域错误归一为 HTTP 状态与稳定错误码

API 层 SHALL 把领域错误体系映射为稳定的三类状态码（状态前置 409 / 输入不可处理 422 /
外部依赖不可用 503）与稳定英文错误码、简体中文文案；SHALL NOT 泄漏堆栈或裸异常信息；
错误文案 SHALL 与 CLI 共享同一映射来源（同一函数），并 SHALL 按调用面（命令行 / HTTP）
分别成文：HTTP 面（含 localhost API 与桌面壳）的指引 MUST NOT 出现配置文件路径或
命令行参数教程，SHALL 指向「设置」页并说明保存后免重启生效；命令行面 SHALL 保留
配置文件与参数级指引。同一错误码在两面的文案差异 SHALL NOT 改变状态码与错误码本身。
「凭证被端点拒绝」「通道未配置」「配置文件不可解析」三种语义 SHALL 各有独立文案，
SHALL NOT 相互顶替。

#### Scenario: 无裸异常穿透

- **GIVEN** 任一领域错误被端点触发（如缺索引、缺 LLM key、限流）
- **WHEN** API 返回错误响应
- **THEN** 响应为 `{code, message}` 结构，message 为简体中文指引，响应中无堆栈与英文异常类名

#### Scenario: 状态前置类错误返回 409

- **GIVEN** 未建立检索索引
- **WHEN** 客户端请求 `POST /api/search`
- **THEN** 返回 409 与 `code=index_unavailable`，message 提示先执行索引

#### Scenario: 依赖不可用类错误返回 503

- **GIVEN** 未配置 LLM API key
- **WHEN** 客户端请求 `POST /api/graph` 且语料需要真实抽取
- **THEN** 返回 503 与 `code=llm_not_configured`，message 给出中文配置指引

#### Scenario: HTTP 面文案不含命令行语境指引

- **GIVEN** 检索或问答请求因模型端点未配置而失败
- **WHEN** 客户端经 HTTP API 读取错误响应
- **THEN** 返回 503 与既有错误码，message 指向「设置」页并说明保存后免重启生效，
  不出现配置文件路径与命令行参数示例

#### Scenario: 凭证被拒与未配置文案分道

- **GIVEN** 端点已正确配置 base_url 与 model，但对当前凭证返回 401/403
- **WHEN** 客户端经 HTTP API 读取错误响应
- **THEN** message 说明凭证被拒并指引核对该通道的 api_key 与 base_url 是否属同一
  厂商同一账号，不再要求「补全 base_url 与 model」

### Requirement: 暴露问答就绪状态

`GET /api/settings` 与 `PUT /api/settings` 响应 SHALL 附带 `ask_readiness`
（`ready` 布尔与 `missing` 字符串列表）：就绪 SHALL 按 ADR-0009 三层合并口径判定
——llm 通道凭证可解析且 embedding 通道 base_url/model 齐备；「三层」SHALL 计入
服务入口（`siku serve`）传入的命令行层，与请求期通道解析共用同一合并路径，
SHALL NOT 引入第二套判定逻辑；rerank 通道 SHALL NOT 阻塞就绪。`missing` SHALL
使用稳定的 `<channel>.<field>` 机器 token，SHALL NOT 包含任何凭证明文。判定 SHALL
与问答请求期的通道解析同源，不得出现「判定未就绪而请求实际可用」或反向的分裂。

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

#### Scenario: 命令行层补齐即就绪

- **GIVEN** 文件层与环境变量层的 embedding 通道为空，但服务以
  `siku serve --embedding-base-url … --embedding-model …` 启动
- **WHEN** 客户端请求 `GET /api/settings`
- **THEN** `ask_readiness.ready=true` 且 `missing` 为空——判定与请求期实际可用一致

#### Scenario: 保存后响应携带最新就绪状态

- **GIVEN** 客户端经 `PUT /api/settings` 提交了齐备的 llm 与 embedding 配置
- **WHEN** 写入成功返回
- **THEN** 响应的 `ask_readiness.ready=true`，UI 可免二次请求直接刷新门控状态

#### Scenario: 问答未配置错误的 UI 导向文案

- **GIVEN** embedding 通道未配置且客户端请求 `/api/ask`
- **WHEN** 服务返回错误
- **THEN** 返回 503 与 `code=model_not_available`，message 为引导「设置」页的
  中文文案，不出现 config.toml 路径或命令行参数

### Requirement: 提供模型供给设置的读写端点

系统 SHALL 提供 `GET /api/settings` 返回 LLM/embedding/rerank 三通道配置的掩码视图
（`base_url`、`model`、`api_key_env`、`protocol`、key 是否已设置的布尔标记），
SHALL NOT 在响应中回显任何 key 明文；当通道的有效值来自环境变量层时 SHALL 予以
标注。响应 SHALL 附带 `llm_env_fallback`：LLM 通道厂商环境变量回退生效时为其端点
描述（`vendor`、`base_url`、`model`、`api_key_env`，不含凭证明文），未生效时为
`null`；该字段 SHALL 与请求期通道解析同源（计入 serve 的 CLI 层）。系统 SHALL
提供 `PUT /api/settings`，校验后把提交的三通道配置合并写入 config.toml 并保持
0600 权限，返回写入后的掩码视图；`protocol` SHALL 按枚举校验（`openai-chat`/
`anthropic`/`openai-responses`），embedding/rerank 通道提交非空 `protocol` 与
非法枚举值均 SHALL 返回 422 与既有 `{code, message}` 结构且不改写配置文件。
连通性测试 SHALL 按通道当前协议发起最小调用。设置读写 SHALL NOT 使 key 进入
日志或错误消息。

配置文件内容不可解析时，`PUT /api/settings` SHALL NOT 因此拒绝保存：系统 SHALL 以
空的文件层为基底合并本次提交并原子替换坏文件，响应 SHALL 携带布尔字段
`invalid_config_file_overwritten`（缺省 `false`）明示该次保存覆盖了不可解析的文件；
仅因权限/IO 故障读不到文件时 SHALL NOT 走覆盖路径。`GET /api/settings` 遇同型错误
SHALL 返回可行动指引（重新保存即可覆盖，或删除该配置文件后重配且删除不影响已摄取
语料），SHALL NOT 输出「补全 base_url 与 model」这类与实际成因不符的文案。

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

#### Scenario: 协议随视图返回并按枚举校验

- **GIVEN** config.toml 为 llm 通道配置 `protocol = "anthropic"`
- **WHEN** 客户端读取设置或以该值提交
- **THEN** 视图返回 `protocol = "anthropic"`；提交非法枚举值或给 embedding
  通道提交非空 protocol 时返回 422 中文指引且不改写配置文件

#### Scenario: 校验失败返回 422

- **GIVEN** 提交的通道配置含非法形状（如 base_url 非合法 URL）
- **WHEN** 客户端请求 `PUT /api/settings`
- **THEN** 返回 422 与 `{code, message}` 中文指引，config.toml 未被改写

#### Scenario: 写入保持权限与掩码

- **GIVEN** 一次合法的三通道设置提交
- **WHEN** 服务端合并写入 config.toml
- **THEN** 文件权限保持 0600，响应为写入后的掩码视图，日志与响应均无 key 明文

#### Scenario: 不可解析的配置文件被保存覆盖并告知

- **GIVEN** config.toml 内容已损坏到无法解析
- **WHEN** 客户端请求 `PUT /api/settings` 提交合法配置
- **THEN** 返回 200，文件被替换为本次提交的内容，响应
  `invalid_config_file_overwritten=true` 且不含英文异常信息；正常保存路径下该字段
  为 `false`

#### Scenario: 读取损坏配置文件给出恢复指引

- **GIVEN** config.toml 内容无法解析
- **WHEN** 客户端请求 `GET /api/settings`
- **THEN** 返回 503 与 `{code, message}`，message 说明配置文件不可解析并给出
  「重新保存覆盖 / 删除该文件后重配」两条出路，不出现命令行参数教程
