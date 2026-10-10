## MODIFIED Requirements

### Requirement: 提供模型供给设置的读写端点

系统 SHALL 提供 `GET /api/settings` 返回三通道配置掩码视图，SHALL NOT 回显任何 key
明文，通道有效值来自环境变量层时 SHALL 标注；响应 SHALL 附带与请求期同源的
`ask_readiness`（含 `missing` 与 `invalid` 两族稳定 token）与 `llm_env_fallback`。
只要配置文件层可读，读取 SHALL 成功返回视图——环境变量或程序层携带的非法取值 SHALL
以 `invalid` token 呈现而非使读取整体失败。系统 SHALL 提供 `PUT /api/settings`：
校验合并写入 config.toml 并保持 0600，返回写入后的掩码视图；`protocol` SHALL 按枚举
校验，embedding/rerank 提交非空 `protocol` 与非法枚举值均 SHALL 返回 422 且不改写
配置文件。设置读写 SHALL NOT 使 key 进日志或错误消息；单次设置请求 SHALL 只读取一次
配置文件，写面响应的回退判定 SHALL 复用本次合并结果。

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

#### Scenario: 环境层协议越界时读取成功且不谎报就绪

- **GIVEN** config.toml 有效，但环境变量 `SIKU_LLM_PROTOCOL` 取值越界
- **WHEN** 客户端请求 `GET /api/settings`
- **THEN** 返回 200 与完整视图；`ask_readiness.ready=false` 且 `invalid` 含稳定 token
  （如 `llm.protocol`），该 token 由与请求期相同的解析路径产出——随后对问答端点的
  真实请求确会失败，视图不谎报就绪

#### Scenario: 落盘后装配失败不得谎报保存失败

- **GIVEN** 文件层配置合法，但环境变量层的 `protocol` 取值越界（就绪判定含该层）
- **WHEN** 客户端请求 `PUT /api/settings` 提交合法配置
- **THEN** 返回 200 成功响应而非错误形状：写入事实（含覆盖告知与 embedding 重建
  告警等既有字段）如实携带，视图 `ask_readiness.ready=false` 且 `invalid` 含稳定
  token；文件已写入却谎报保存失败的情形 SHALL NOT 发生

### Requirement: 配置文件故障以稳定 code 分道

模型配置文件的两类故障 SHALL 在 HTTP 错误响应 `code` 上可机器判别：文件层内容确证
无效（非法 TOML、段结构非法、非 UTF-8、类型不符、取值越界）SHALL 用
`invalid_config_file`；权限或 IO 读不到（内容未知）SHALL 用 `config_file_unreadable`。
二者 SHALL 与 `model_not_available` 区分，分道 SHALL 在所有 HTTP 错误映射点一致
生效；状态码与 `{code, message}` 结构 SHALL 不变，`code` 取值集 SHALL NOT 扩新值。
环境变量或程序层的协议越界 SHALL NOT 落入 `invalid_config_file`，SHALL 由
`invalid_settings` 承载并点名真正杠杆（读取面呈现见设置读写端点条）。文案 SHALL
指明无效字段与合法名单，SHALL NOT 回显用户原值。分型 SHALL 由异常类决定，SHALL NOT
由 message 文本推导。

#### Scenario: 可覆盖与不可覆盖在 code 上可辨

- **GIVEN** 本机配置文件分别处于「内容不可解析」与「权限读不到」两种状态
- **WHEN** 客户端请求 `GET /api/settings`
- **THEN** 两者均为 503，`code` 分别为 `invalid_config_file` 与 `config_file_unreadable`；
  设置页据前者给出覆盖自救入口，据后者只给重试

#### Scenario: 请求期端点同一分道

- **GIVEN** 配置文件不可解析
- **WHEN** 客户端调用检索或问答端点，触发同一异常
- **THEN** 响应 `code` 仍为 `invalid_config_file`（不与「通道未配置」共用 `model_not_available`），
  message 仍为可行动中文且不含配置文件路径与命令行参数教程

#### Scenario: 坏取值与坏语法同码同出路

- **GIVEN** config.toml 可解析但 `[llm] protocol` 取值不在枚举内
- **WHEN** 客户端请求 `GET /api/settings`
- **THEN** 返回 503 与 `code=invalid_config_file`（与不可解析同码），message 点出
  `[llm] protocol` 及三个合法值、不回显该越界值本身；随后一次合法保存以覆盖方式修复它

#### Scenario: 上层协议越界不承诺页面可修

- **GIVEN** `SIKU_LLM_PROTOCOL`（或程序传入的 CLI 层）取值越界，而 config.toml 本身有效
- **WHEN** 客户端请求 `GET /api/settings` 或调用问答端点
- **THEN** 设置读取面返回 200 视图，`ask_readiness` 以稳定 token 呈现无效并给出点名
  `SIKU_LLM_PROTOCOL` 的指引，SHALL NOT 承诺页面保存可修；问答与连通性测试面返回
  503 `invalid_settings`，message 同样点名该环境变量、SHALL NOT 点名 `--llm-protocol`
  （枚举参数在解析阶段即拒，不可能承载该错误），连通性测试与问答面同码同 message
