# model-supply Specification

## Purpose
统一管理 LLM、embedding、rerank 三类模型端点的供给配置：分层解析（CLI > 环境变量 >
配置文件 > 报错）、凭证保护、以及与桌面应用一致的本机配置文件位置。模型一律经
用户配置的端点（云或自部署）供给，内核不内置任何模型。

## Requirements

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

### Requirement: 保护模型凭证

系统 SHALL 支持两种凭证提供方式：配置文件内的 `api_key` 明文（文件创建时 SHALL 为
0600 权限）或 `api_key_env` 环境变量间接引用；系统 MUST NOT 将任何凭证写入日志、
索引元数据、评测基线、错误消息或 OpenAPI 契约。

#### Scenario: 明文 key 的文件权限

- **GIVEN** 用户在 config.toml 中直接写入 `api_key`
- **WHEN** 系统创建或重写该配置文件
- **THEN** 文件权限为 0600，非本用户不可读

#### Scenario: 凭证不泄漏

- **GIVEN** 一次使用明文 `api_key` 的端点调用因 401 失败
- **WHEN** 系统记录日志或返回错误
- **THEN** 日志、错误消息与任何持久化产物中均不包含该 key 的值

### Requirement: LLM 通道支持厂商环境变量回退

系统 SHALL 在 LLM 通道三层（CLI 参数、环境变量、config.toml）合并结果的所有字段
（`base_url`、`model`、`api_key`、`api_key_env`、`protocol`）均未设置，且运行环境中
`DASHSCOPE_API_KEY` 非空时，将该通道回退为通义千问 OpenAI 兼容端点（固定
`base_url` 与默认模型，`api_key_env` 指向 `DASHSCOPE_API_KEY`）。任一 LLM 字段
被任何层级显式设置时系统 SHALL NOT 回退；embedding 与 rerank 通道 SHALL NOT
适用任何厂商回退。回退 SHALL 与请求期通道解析同源：问答就绪判定、生成链路与
连通性测试 SHALL 依据同一回退结果。

#### Scenario: 三层缺省且环境变量存在时回退生效

- **GIVEN** config.toml、`SIKU_LLM_*` 环境变量与 CLI 参数均未提供任何 LLM 通道
  字段，且环境中 `DASHSCOPE_API_KEY` 非空
- **WHEN** 系统解析 LLM 通道或判定问答就绪
- **THEN** 解析结果为通义千问兼容端点（固定 base_url 与默认模型、
  `api_key_env=DASHSCOPE_API_KEY`），就绪判定不再因 llm 凭证缺失而阻塞

#### Scenario: 任一字段显式配置时不回退

- **GIVEN** config.toml 为 LLM 通道设置了 `api_key_env`（其余字段为空）且
  `DASHSCOPE_API_KEY` 存在
- **WHEN** 系统解析 LLM 通道
- **THEN** 按显式配置解析（base_url/model 沿用既有缺省语义），不切换到通义端点

#### Scenario: 环境变量缺失时保持既有缺省

- **GIVEN** LLM 通道三层均未配置且环境中无 `DASHSCOPE_API_KEY`
- **WHEN** 系统解析 LLM 通道或判定问答就绪
- **THEN** 行为与本需求生效前完全一致（DeepSeek 缺省端点，缺失
  `llm.api_key` 进入就绪缺项清单）

#### Scenario: embedding 通道不享受回退

- **GIVEN** embedding 通道三层均未配置且环境中 `DASHSCOPE_API_KEY` 非空
- **WHEN** 系统解析 embedding 通道或判定问答就绪
- **THEN** 仍报配置指引缺项（`embedding.base_url`、`embedding.model`），
  不回退到任何内置端点

### Requirement: LLM 通道支持多协议接入

LLM 通道 SHALL 支持三种线协议：`openai-chat`（缺省，既有 `/chat/completions`
行为）、`anthropic`（Messages API：`{base_url}/v1/messages`、`x-api-key` 与
`anthropic-version` 凭证头、顶层 `system` 字段、`max_tokens` 必填）、
`openai-responses`（`{base_url}/responses`、顶层 `instructions` 字段）。
`protocol` SHALL 作为通道配置字段随既有三层（CLI > 环境变量 > config.toml）
合并解析，缺省 `openai-chat` 且缺省行为与既有完全一致。三协议 SHALL 保持同等
幂等语义（temperature=0、非流式），并 SHALL 复用既有五剧本错误映射。embedding
与 rerank 通道遇到非空 `protocol` SHALL 返回配置指引错误而非静默忽略；非法
枚举值 SHALL 在解析与提交校验时报可行动的中文指引。

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

- **GIVEN** 用户在 embedding 通道设置了非空 `protocol`
- **WHEN** 系统解析 embedding 通道
- **THEN** 返回配置指引错误，说明该字段仅 LLM 通道支持，不静默忽略

#### Scenario: 非法协议值报可行动指引

- **GIVEN** 用户提交或配置了枚举之外的 `protocol` 值
- **WHEN** 系统解析通道或处理设置提交
- **THEN** 返回 422/解析错误与中文指引，列出三个合法值

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
