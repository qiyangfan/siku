## MODIFIED Requirements

### Requirement: LLM 通道支持多协议接入

LLM 通道 SHALL 支持三种线协议：`openai-chat`（缺省，既有 `/chat/completions` 行为）、
`anthropic`（Messages API：`{base_url}/v1/messages`、`x-api-key` 凭证头、顶层
`system`、`max_tokens` 必填）、`openai-responses`（`{base_url}/responses`、顶层
`instructions`）。`protocol` SHALL 经既有三层（CLI > 环境变量 > config.toml）合并
解析，缺省行为零漂移；三协议 SHALL 同等幂等并复用既有五剧本错误映射。协议取值
SHALL 在每个输入边界被拒：文件层在载入点拒（归文件无效），`--llm-protocol` 枚举
参数在命令行解析阶段拒，环境变量与程序层在通道解析时拒且指引 SHALL 点名真正杠杆、
SHALL NOT 让用户去「设置」页保存。embedding 与 rerank 通道 SHALL NOT 消费
`protocol` 字段，文件层出现即视为文件无效。

#### Scenario: 缺省协议行为零漂移

- **GIVEN** 用户未在任何层级配置 `protocol`
- **WHEN** 执行图谱抽取或问答
- **THEN** 请求发往 `{base_url}/chat/completions`，行为与协议字段引入前完全一致

#### Scenario: Anthropic 分支直连

- **GIVEN** 用户配置 `protocol = "anthropic"` 与某厂商 Anthropic 分支端点
- **WHEN** 系统发起一次抽取调用
- **THEN** 请求发往 `{base_url}/v1/messages`，凭证经 `x-api-key` 头承载，
  system 以顶层字段传递，响应按 `content[]` 文本块抽取

#### Scenario: OpenAI Responses 协议直连

- **GIVEN** 用户配置 `protocol = "openai-responses"`
- **WHEN** 系统发起一次抽取调用
- **THEN** 请求发往 `{base_url}/responses`，system 经 `instructions` 传递，
  响应按 `output[]` 消息项的 `output_text` 抽取

#### Scenario: embedding 通道拒绝 protocol 字段

- **GIVEN** 用户在 embedding 通道设置了非空 `protocol`（手改 config.toml 的该段）
- **WHEN** 系统载入配置或解析 embedding 通道
- **THEN** 该文件被判定为无效并指明「[embedding] protocol 是多余字段，仅 LLM 通道
  使用它」，不静默忽略、也不把它当成合法配置继续用

#### Scenario: 非法协议值报可行动指引

- **GIVEN** 用户提交或配置了枚举之外的 `protocol` 值
- **WHEN** 系统处理设置提交、载入配置文件、解析通道或读取设置
- **THEN** 指引按取值来源分面且列出三个合法值：提交值 → 422 校验错误；文件层 →
  503 `invalid_config_file`（重新保存即可覆盖）；环境变量/程序层 → 请求面与连通
  探测面 503 `invalid_settings` 并点名该变量或参数，设置读取面 SHALL 返回 200 视图
  并以 `ask_readiness.invalid` 稳定 token 呈现，指引同样点名该变量且 SHALL NOT
  承诺页面保存可修

#### Scenario: 文件层坏协议归入文件无效并可被保存修复

- **GIVEN** config.toml 含 `[llm] protocol = "gemini-native"`
- **WHEN** 客户端读取设置，随后提交一次把该值改回合法枚举的保存
- **THEN** 读取返回 503 `invalid_config_file` 且文案点出 `[llm] protocol` 与合法名单
  （不回显用户原值）；保存返回 200 并告知已覆盖该文件；再次读取返回 200

#### Scenario: 命令行坏协议在解析阶段即拒

- **GIVEN** 用户执行 `siku serve --llm-protocol bogus`
- **WHEN** 命令行解析该参数
- **THEN** 以用法错误退出（不进入服务启动、不监听端口），错误信息列出三个合法值，
  且不出现未捕获异常

### Requirement: 配置文件不可解析时用户可自救

配置文件对模型供给无效时，系统 SHALL 仍允许用户以显式保存覆盖恢复可用：「无效」涵盖
内容不可解析（非法 TOML、段结构非法、非 UTF-8）与可解析但取值不在允许范围（如
`[llm] protocol` 越界）——后者 SHALL 在载入点即被拒，禁止非法取值进入运行期。设置
写入 SHALL 以空配置层为基底合并本次提交并原子替换坏文件，SHALL 显式告知覆盖事实；
仅权限/IO 读不到时 SHALL NOT 走覆盖（内容未知必须保持报错）。读取与命令行面对同型
错误 SHALL 给可行动指引（指明无效字段与合法名单），SHALL 以稳定 `code` 区分「保存
可修」（`invalid_config_file`）与「保存不可修」（`config_file_unreadable`），设置页
覆盖自救入口 SHALL 只由前者驱动，SHALL NOT 靠客户端启发式推断。启动面忽略文件层后
SHALL 继续校验其余层：`siku serve` 遇文件层无效或上层协议越界 SHALL 在用户面明示后
继续启动，SHALL NOT 把异常漏成未捕获的 traceback。

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

- **GIVEN** 配置文件无效（不可解析，或字段取值不在允许范围）导致
  `GET /api/settings` 返回 503 且 `code=invalid_config_file`
- **WHEN** 用户在设置页确认「以空配置覆盖本机配置文件并重新填写」
- **THEN** 表单以空配置出图（不沿用服务端读数、不伪造 `config_path`），
  提交走覆盖写并得到「原文件无效已被覆盖」告知；服务不可达或
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

- **GIVEN** 配置文件无效（不可解析，或字段取值非法），且 env/CLI 层的 `protocol`
  取值越界
- **WHEN** 用户启动 `siku serve`
- **THEN** 先在用户面明示文件层无效，再告警协议越界（点名该环境变量或程序传入层，
  `--llm-protocol` 作为枚举参数不再是这条错误的来源）并继续启动：LLM 通道按无效
  呈现、其余通道照常可用，用户面不出现未捕获异常的 traceback（场景名沿旧约保留，
  「归一化」语义不变——从归一化失败收敛为归一化明示后继续）

#### Scenario: 坏取值文件不产生运行期非法状态

- **GIVEN** config.toml 含越界的 `[llm] protocol` 值
- **WHEN** 任何消费模型供给配置的路径被调用（设置读写、连通探测、问答、检索、
  就绪判定）
- **THEN** 它们一律在同一处（载入点）得到同一异常与同一成因码
  `invalid_config_file`，系统不存在「带着该非法值继续工作」的中间状态
