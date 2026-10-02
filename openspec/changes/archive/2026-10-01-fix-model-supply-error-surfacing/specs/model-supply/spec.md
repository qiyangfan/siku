# model-supply Specification（delta）

## ADDED Requirements

### Requirement: 模型端点错误按语义分型

系统 SHALL 把「凭证被端点拒绝」（HTTP 401/403）与「通道未配置」「端点不可用」分为
不同的领域错误类：embedding/rerank 端点的 401/403 SHALL 抛「凭证被拒」类错误并携带
结构化的通道标识（`llm`/`embedding`/`rerank`），LLM 端点的 401/403 SHALL 抛 LLM
侧的「凭证被拒」类错误。分型 SHALL 以既有错误类的**子类**实现，使所有按基类捕获的
处理器行为零回退；错误映射层 SHALL 按新类先于通用类给出各自文案，SHALL NOT 依赖
异常消息文本做分型。配置文件的「内容不可解析」与「文件读不到（权限/IO 故障）」
SHALL NOT 归为同一类。

#### Scenario: 端点拒绝凭证时报凭证被拒

- **GIVEN** embedding 端点已配置且可达，但对当前 api_key 返回 HTTP 401 或 403
- **WHEN** 系统调用该端点
- **THEN** 抛出的错误按基类捕获仍属「模型端点不可用」体系，同时携带通道标识供
  文案层区分，用户面文案说明凭证被拒并指引核对 key 与端点是否成套

#### Scenario: 凭证被拒文案不得等同于未配置

- **GIVEN** 一次因 401/403 失败、但 base_url 与 model 均已正确配置的调用
- **WHEN** 系统向用户呈现错误文案
- **THEN** 文案不得要求用户「补全 base_url 与 model」，而应说明凭证被拒及
  api_key/api_key_env 与端点须属同一厂商同一账号

#### Scenario: 未配置仍按未配置分型

- **GIVEN** embedding 通道在所有层级都没有 `base_url`/`model`
- **WHEN** 系统解析该通道
- **THEN** 抛「未配置」类错误并给出配置模板指引，不与凭证被拒混淆

#### Scenario: LLM 端点拒绝凭证按同类分型

- **GIVEN** LLM 端点对当前 key 返回 HTTP 401 或 403
- **WHEN** 系统执行抽取、wiki 生成或问答调用
- **THEN** 错误按 LLM 凭证被拒分型（仍可被 LLM 服务失败的基类捕获），文案指引核对
  LLM 通道的凭证与端点

### Requirement: 配置文件不可解析时用户可自救

配置文件内容不可解析（非法 TOML 或段结构非法）时，系统 SHALL 仍允许用户以显式保存
覆盖该文件以恢复可用状态：设置写入 SHALL 以空的配置层为基底合并本次提交并原子替换
坏文件，SHALL 在响应中显式告知「原配置文件不可解析、已被本次保存覆盖」；
SHALL NOT 在仅因权限或 IO 故障读不到文件时走覆盖路径（该情形内容未知，必须保持
报错）。设置读取与命令行入口面对同型错误 SHALL 给出可行动指引而非「去补全
base_url/model」。

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

- **GIVEN** 配置文件不可解析导致 `GET /api/settings` 返回错误，但本地服务可达
- **WHEN** 用户在设置页确认「以空配置覆盖本机配置文件并重新填写」
- **THEN** 表单以空配置出图（不沿用服务端读数、不伪造 `config_path`），
  提交走覆盖写并得到「原文件不可解析已被覆盖」告知；服务不可达时不提供该入口
  （保存同样无处可去）

#### Scenario: 读取面给出恢复指引

- **GIVEN** 配置文件不可解析
- **WHEN** 客户端读取设置
- **THEN** 返回可行动中文指引：重新保存即可覆盖坏文件（免重启生效），或删除该
  配置文件后重配——删除只影响模型配置，不影响已摄取语料与索引

#### Scenario: 命令行服务面对坏文件明示后继续启动

- **GIVEN** 配置文件不可解析
- **WHEN** 用户启动本地服务（含桌面壳的 sidecar 启动路径）
- **THEN** 服务在用户面明示「配置文件不可解析」并继续启动，请求期按各自指引报错或
  接受设置页保存的覆盖

## MODIFIED Requirements

### Requirement: 分层解析模型供给配置

系统 SHALL 按 CLI 参数 > 环境变量 > 配置文件的优先级解析 LLM、embedding、rerank 三类
端点配置（`base_url`、`model`、凭证）；任一必需项在所有层级均缺失时，SHALL 返回
可行动的配置指引而非静默使用默认端点。配置文件路径 SHALL 使用平台应用配置目录下的
`config.toml`，与桌面数据根目录决策一致。「所有层级」SHALL 包含命令行层：由服务
入口（如 `siku serve`）传入的端点参数与文件层、环境变量层同权参与必需项判定，
就绪判定与实际请求 SHALL 依据同一合并结果。

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

#### Scenario: 服务入口的命令行层计入必需项判定

- **GIVEN** config.toml 与环境变量层均未提供 embedding 端点，而服务启动命令传入了
  embedding 的 base_url 与 model
- **WHEN** 系统解析 embedding 通道或判定问答就绪
- **THEN** 判定结果为已就绪（与请求期同一合并口径），不得报「未配置」
