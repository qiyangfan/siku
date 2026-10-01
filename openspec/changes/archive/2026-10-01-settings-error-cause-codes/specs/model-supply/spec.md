## MODIFIED Requirements

### Requirement: 配置文件不可解析时用户可自救

配置文件内容不可解析（非法 TOML 或段结构非法）时，系统 SHALL 仍允许用户以显式保存
覆盖该文件以恢复可用状态：设置写入 SHALL 以空的配置层为基底合并本次提交并原子替换
坏文件，SHALL 在响应中显式告知「原配置文件不可解析、已被本次保存覆盖」；
SHALL NOT 在仅因权限或 IO 故障读不到文件时走覆盖路径（该情形内容未知，必须保持
报错）。设置读取与命令行入口面对同型错误 SHALL 给出可行动指引而非「去补全
base_url/model」，且 SHALL 以稳定 `code` 区分「保存可修」（`invalid_config_file`）与
「保存不可修」（`config_file_unreadable`）——设置页的覆盖自救入口 SHALL 只由前者驱动，
禁止 (MUST NOT) 靠「服务可达与否」之类的客户端启发式推断。

启动面忽略文件层之后 SHALL NOT 因此放弃对其余层校验：文件层坏、而 env/CLI 层的
`protocol` 取值越界时，`siku serve` SHALL 归一化失败（先明示文件层不可解析，再给出协议
取值指引并以非零码退出），禁止 (MUST NOT) 把该异常漏成未捕获的 traceback——`except` 块内
再抛出的异常不会被同一 `try` 的后续分支接住，这是一条真实崩溃路径。

#### Scenario: 坏文件下保存即恢复

- **GIVEN** 配置文件内容为非法 TOML（用户手改坏）
- **WHEN** 客户端提交一次合法的设置保存
- **THEN** 写入成功、文件被原子替换为本次提交的内容，响应携带「已覆盖不可解析的
  配置文件」标记

#### Scenario: 读不到文件不得当作可解析覆盖

- **GIVEN** 配置文件存在但进程无权读取
- **WHEN** 客户端提交设置保存
- **THEN** 返回错误且不覆盖原文件（原内容未知，静默替换会丢用户配置）

#### Scenario: 读不到文件不等于通道未配置

- **GIVEN** 配置文件因权限或 IO 故障读不出内容（通道可能其实配好了）
- **WHEN** 系统向用户呈现错误（读取面、连通探测面或命令行面）
- **THEN** 文案说明「文件当前无法读取」，不要求用户补全 base_url/model，
  也不与被播报为「通道未配置」混为一谈；`siku serve` 在该情形下快速失败退出并给出
  同一条指引（内容未知时不带病继续启动）

#### Scenario: 读取失败后设置页仍能进入覆盖自救

- **GIVEN** 配置文件不可解析导致 `GET /api/settings` 返回 503 且 `code=invalid_config_file`
- **WHEN** 用户在设置页确认「以空配置覆盖本机配置文件并重新填写」
- **THEN** 表单以空配置出图（不沿用服务端读数、不伪造 `config_path`），
  提交走覆盖写并得到「原文件不可解析已被覆盖」告知；服务不可达或
  `code=config_file_unreadable` 时不提供该入口（前者保存无处可去，后者覆盖会丢配置）

#### Scenario: 读取面给出恢复指引

- **GIVEN** 配置文件不可解析
- **WHEN** 客户端读取设置
- **THEN** 返回可行动中文指引：重新保存即可覆盖坏文件（免重启生效），或删除该
  配置文件后重配——删除只影响模型配置，不影响已摄取语料与索引；响应 `code` 为
  `invalid_config_file`，设置页据此判断「这条指引是可以被执行自救的」

#### Scenario: 命令行服务面对坏文件明示后继续启动

- **GIVEN** 配置文件不可解析
- **WHEN** 用户启动本地服务（含桌面壳的 sidecar 启动路径）
- **THEN** 服务在用户面明示「配置文件不可解析」并继续启动，请求期按各自指引报错或
  接受设置页保存的覆盖

#### Scenario: 坏文件叠加上层协议越界时归一化失败

- **GIVEN** 配置文件不可解析，且环境中 `SIKU_LLM_PROTOCOL`（或 `--llm-protocol`）取值越界
- **WHEN** 用户启动 `siku serve`
- **THEN** 先明示文件层不可解析，再给出「LLM 线协议非法，仅支持 openai-chat / anthropic /
  openai-responses，请修正 --llm-protocol、SIKU_LLM_PROTOCOL 或 [llm] protocol」并以非零码退出；
  用户面不出现未捕获异常的 traceback
