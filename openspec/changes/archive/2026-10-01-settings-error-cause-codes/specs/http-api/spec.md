## ADDED Requirements

### Requirement: 配置文件故障以稳定 code 分道

模型配置文件的两类故障 SHALL 在 HTTP 错误响应的 `code` 字段上可机器判别：内容确证不可解析
（非法 TOML、段结构非法、非 UTF-8、字段类型不符）SHALL 用 `invalid_config_file`，因权限或 IO
故障读不到（内容未知）SHALL 用 `config_file_unreadable`；协议取值越界不属本条，由既有
`invalid_settings` 承载；两者 SHALL 与其它供给类错误
（`model_not_available`）区分，且该分道 SHALL 在**所有** HTTP 错误映射点一致生效（设置读取、
设置写入、连通性测试、检索/问答等请求期端点）。状态码与 `{code, message}` 结构 SHALL 不变。

分型 SHALL 由异常类决定，禁止 (MUST NOT) 由 message 文本推导；客户端 SHALL NOT 需要靠
「服务是否可达」之类的启发式来判断「一次保存能否修好当前故障」——该判断只有服务端掌握。

#### Scenario: 可覆盖与不可覆盖在 code 上可辨

- **GIVEN** 本机配置文件分别处于「内容不可解析」与「权限读不到」两种状态
- **WHEN** 客户端请求 `GET /api/settings`
- **THEN** 两者均为 503，`code` 分别为 `invalid_config_file` 与 `config_file_unreadable`；
  设置页据前者给出覆盖自救入口，据后者只给重试。协议取值越界不落在本条两码上：该文件可解析、
  只是值不在枚举内，由既有 `invalid_settings` 承载（保存可覆盖修正）

#### Scenario: 请求期端点同一分道

- **GIVEN** 配置文件不可解析
- **WHEN** 客户端调用检索或问答端点，触发同一异常
- **THEN** 响应 `code` 仍为 `invalid_config_file`（不与「通道未配置」共用 `model_not_available`），
  message 仍为可行动中文且不含配置文件路径与命令行参数教程

## MODIFIED Requirements

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
日志或错误消息；遇配置文件故障时日志 SHALL 只记异常类名与文件路径，SHALL NOT 再记
解码器详情文本（成因与处置已由响应面完整承载，详情文本对排障无增量，且路径本已单列）。
防凭证值泄漏由既有的「`ValidationError` 只保留字段路径与错误类型」保证，与本条无关。

单次设置请求 SHALL 只读取一次配置文件：写面响应里的回退判定 SHALL 复用本次合并结果，
SHALL NOT 再读一次文件（同请求两套事实源会让视图与回退标注不一致）。

写入已落盘之后的响应装配若抛领域错误（如环境变量层的协议越界——写入前的校验只管文件层），
`PUT /api/settings` SHALL NOT 返回 `internal_error` 类 5xx，SHALL 按 `GET` 面同一映射给出状态码、
`code` 与指引，并在文案中声明「本次提交的配置已写入本机配置文件」这一既成事实——写成功是事实，
谎报保存失败会把「重新保存覆盖坏文件」这条自救路径变成反复重试的迷宫。该分支 SHALL NOT 静默丢弃
成功响应本该携带的事实（写入与覆盖告知、重建告警），错误体结构不变；兜底映射 SHALL 覆盖任何
供给类领域错误，使装配失败在任何成因下都不退化为 500。

配置文件内容不可解析时，`PUT /api/settings` SHALL NOT 因此拒绝保存：系统 SHALL 以
空的文件层为基底合并本次提交并原子替换坏文件，响应 SHALL 携带布尔字段
`invalid_config_file_overwritten`（缺省 `false`）明示该次保存覆盖了不可解析的文件；
仅因权限/IO 故障读不到文件时 SHALL NOT 走覆盖路径。`GET /api/settings` 遇同型错误
SHALL 返回可行动指引（重新保存即可覆盖，或删除该配置文件后重配且删除不影响已摄取
语料）并按成因给 `code`，SHALL NOT 输出「补全 base_url 与 model」这类与实际成因不符
的文案；读面 SHALL NOT 为「让表单出图」而改成成功响应——请求期每请求现读该文件，
容忍会让就绪状态与真实请求结果分叉（误就绪比死路更难排查）。

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
- **THEN** 返回 503 与 `code=invalid_config_file`，message 说明配置文件不可解析并给出
  「重新保存覆盖 / 删除该文件后重配」两条出路，不出现命令行参数教程；设置页据该 code
  提供覆盖自救入口，保存成功后再次读取返回 200

#### Scenario: 落盘后装配失败不得谎报保存失败

- **GIVEN** 文件层配置合法，但环境变量层的 `protocol` 取值越界（就绪判定含该层）
- **WHEN** 客户端请求 `PUT /api/settings` 提交合法配置
- **THEN** 返回 503 且 `code` 与 `GET` 面对同一故障一致（`invalid_settings`），而非 500
  `internal_error`；message 声明本次提交已写入本机配置文件并给出协议取值指引，且成功响应本该
  携带的覆盖告知与重建告警一并写入该文案；再次读取仍为同一码（两面同源）
