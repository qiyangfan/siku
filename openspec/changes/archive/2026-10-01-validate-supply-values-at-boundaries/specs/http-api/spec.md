## MODIFIED Requirements

### Requirement: 配置文件故障以稳定 code 分道

模型配置文件的两类故障 SHALL 在 HTTP 错误响应的 `code` 字段上可机器判别：
**文件层内容确证无效**（非法 TOML、段结构非法、非 UTF-8、字段类型不符，
以及可解析但字段取值不在允许范围——例如 `[llm] protocol` 越界、embedding/rerank
段多出 `protocol`）SHALL 用 `invalid_config_file`；因权限或 IO 故障读不到
（内容未知）SHALL 用 `config_file_unreadable`。二者 SHALL 与其它供给类错误
（`model_not_available`）区分，且该分道 SHALL 在**所有** HTTP 错误映射点一致生效
（设置读取、设置写入、连通性测试、检索/问答等请求期端点）。状态码与
`{code, message}` 结构 SHALL 不变，`code` 取值集也不 SHALL NOT 因本条扩出新值：
「取值非法」归入 `invalid_config_file` 而不是另立成因码，因为对客户端它是同一条出路
（重新保存覆盖）。

由环境变量或程序传入的 CLI 层提供的协议越界值 SHALL NOT 落入 `invalid_config_file`
（那会承诺页面保存能修好它，而这两层优先级高于文件层），SHALL 由既有
`invalid_settings` 承载，且 message SHALL 点名真正的杠杆。由于文件层的非法取值在载入点
即被拒、`--llm-protocol` 是枚举参数（非法值在解析阶段即被拒），`llm` 通道的该错误只可能
来自 `SIKU_LLM_PROTOCOL` 或程序传入的配置；同理 embedding/rerank 的非空 `protocol`
只可能来自程序传入的配置（其环境变量层没有该字段）。message SHALL NOT 点名这两个来源
之外的杠杆。连通性测试面对同一故障 SHALL 与设置读取面给出同一 `code` 与同一 message。

文案 SHALL 指明到底哪个字段无效及其合法取值名单；该补充说明 SHALL 由服务端自撰，
禁止 (MUST NOT) 回显用户原值（与「凭证不进日志与错误消息」同一纪律）。

分型 SHALL 由异常类决定，禁止 (MUST NOT) 由 message 文本推导；客户端 SHALL NOT 需要靠
「服务是否可达」之类的启发式来判断「一次保存能否修好当前故障」——该判断只有服务端掌握。

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
- **THEN** 返回 503 与 `code=invalid_settings`，message 说明该值来自优先级高于配置文件的
  环境变量或程序传入层、设置页保存覆盖不了它，点名 `SIKU_LLM_PROTOCOL`，
  SHALL NOT 点名 `--llm-protocol`（枚举参数在解析阶段即拒，不可能承载该错误）；
  同一故障下连通性测试给出同一 `code` 与同一 message
