# http-api Specification

## Purpose
把 Phase 1-3 的内核能力（摄取/检索/图谱/wiki）以 localhost HTTP API 暴露并冻结契约，
作为 UI ↔ 内核边界的内核侧落地（ADR-0002 红线），使后续 UI 与内核可并行演进。

## Requirements

### Requirement: 提供 localhost HTTP 内核端点

系统 SHALL 提供 `siku serve` 启动仅绑定 127.0.0.1 的 FastAPI 应用，暴露健康检查与
摄取/检索/图谱/wiki 端点；端点 SHALL 复用既有服务层且 SHALL NOT 包含业务逻辑；
响应字段 SHALL 与 CLI `--json` 输出同构。

#### Scenario: 健康检查

- **GIVEN** 服务已启动
- **WHEN** 客户端请求 `GET /api/health`
- **THEN** 返回 200 与 `{status: "ok", version: <当前版本>}`

#### Scenario: 摄取返回来源级报告

- **GIVEN** 一个存在的本地文档路径
- **WHEN** 客户端请求 `POST /api/ingest` `{source: <路径>}`
- **THEN** 返回 200 与来源级四计数报告（created/updated/skipped/ignored），语义与 `siku ingest` 一致

#### Scenario: 检索返回带来源锚点的结果

- **GIVEN** 已建立检索索引
- **WHEN** 客户端请求 `POST /api/search` `{query: <自然语言>}`
- **THEN** 返回 200 与结果列表，每条携带 chunk 锚点与各段分数，字段与 `siku search --json` 同构

#### Scenario: 图谱构建返回体检报告

- **GIVEN** 一个已摄取的 vault
- **WHEN** 客户端请求 `POST /api/graph` `{vault, data_dir}`
- **THEN** 返回 200 与体检报告（节点/边/社区/同名实体/缓存命中/LLM 调用/告警），字段与 `siku graph --json` 同构

#### Scenario: wiki 生成返回条目统计

- **GIVEN** 图谱与摘要缓存已就绪
- **WHEN** 客户端请求 `POST /api/wiki` `{data_dir}`
- **THEN** 返回 200 与 `{entries, cache_hits, llm_calls, empty_graph}`

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

### Requirement: OpenAPI 契约快照冻结入库

系统 SHALL 把 OpenAPI 契约快照冻结到 `contracts/openapi.json`；契约漂移 SHALL 使
测试失败并要求显式刷新；快照 SHALL 注明生成方式。

#### Scenario: 契约漂移即失败

- **GIVEN** 契约快照已入库
- **WHEN** 端点模型或结构被修改而未刷新快照
- **THEN** 契约测试失败并提示刷新命令

#### Scenario: 显式刷新快照

- **GIVEN** 契约变更经评审确认
- **WHEN** 开发者执行刷新命令
- **THEN** 快照更新且测试恢复通过，diff 进入提交评审

### Requirement: LLM 端点可配置且默认行为不变

`graph`/`wiki` SHALL 支持经参数指定 openai 兼容端点的 base_url 与模型名，使任意
兼容网关（如 muniu、ollama）即插即用；未指定时 SHALL 保持现有默认（DeepSeek）与
全部既有行为（含缺 key 指引、缓存语义）不变。

#### Scenario: 指向自建网关

- **GIVEN** 用户运行 muniu 网关并签发访问 key
- **WHEN** 用户以 `--llm-base-url http://127.0.0.1:8787/v1 --llm-model <别名>
  --api-key-env <变量>` 执行 `siku graph`
- **THEN** 抽取与摘要请求全部经网关完成，图谱产物与直连同构

#### Scenario: 默认行为不变

- **GIVEN** 用户未传任何 LLM 端点参数
- **WHEN** 执行 `siku graph` / `siku wiki`
- **THEN** 行为与既有 DeepSeek 默认完全一致（含缓存键语义，不产生跨端点缓存污染）

#### Scenario: 网关文档明示语义缓存约束

- **GIVEN** 用户经 muniu 网关使用 siku
- **WHEN** 查阅部署文档
- **THEN** 文档明示 siku 租户必须关闭网关语义缓存（模糊命中破坏幂等闸门）与
  换通道需同步摘要身份的注意事项

### Requirement: 提供带来源引用的单轮问答端点

系统 SHALL 提供 `POST /api/ask` 单轮问答端点。端点 SHALL 复用既有混合检索获取有界上下文，
再调用用户配置的 LLM 生成回答；正常响应 SHALL 返回答案、`request_id`、模型身份和完整
来源引用。问题、`top_k`、`candidate_k` 和打包后的上下文 SHALL 受服务端硬上限约束，超限
不得静默截断证据。端点 SHALL NOT 接受或持久化账号凭证、会话历史或除本次 LLM 瞬时调用
之外的远程状态。

#### Scenario: 基于检索上下文返回回答

- **GIVEN** 检索索引可用，且问题能召回至少一个上下文片段
- **WHEN** 客户端请求 `POST /api/ask` `{question, top_k?, candidate_k?}`
- **THEN** 返回 200，包含非空 `answer`、`request_id`、`model`、检索摘要和至少一条引用；每条
  引用包含本次检索结果的 `citation_id`、source name、note path、anchor、chunk id 与 hash，
  且所有 citation id 均属于本次上下文

#### Scenario: 证据不足时拒答

- **GIVEN** 问题合法但检索没有命中可用上下文
- **WHEN** 客户端请求问答端点
- **THEN** 返回 200，`insufficient_evidence=true`、答案为确定性中文指引、引用为空、
  `model` 为当前配置的模型身份，且不调用 LLM

#### Scenario: 拒绝未授权引用

- **GIVEN** LLM 返回未知 citation id、非 JSON 或字段不完整的回答
- **WHEN** 服务端校验 LLM 输出
- **THEN** 返回 503 与 `code=llm_provider_error`，不返回未经校验的答案或 traceback；不得
  误用图谱抽取的 422 错误，message 使用问答适用的中文文案

### Requirement: 问答请求保持无状态并可追踪

每次问答 SHALL 生成唯一 `request_id` 并写入问答链路日志；成功和确定性无证据响应 SHALL
返回该 id，错误响应继续复用现有 `{code, message}` 结构。服务端 SHALL NOT 保存会话历史。
相同请求不要求服务端复用答案缓存，LLM key SHALL 只从服务进程配置读取。

#### Scenario: 页面刷新不恢复服务端会话

- **GIVEN** 一次问答已经完成
- **WHEN** 客户端重新请求健康检查或发起新问题
- **THEN** 新请求拥有独立 `request_id`，服务端不读取上一轮对话内容

### Requirement: 问答错误复用稳定 HTTP 语义

问答端点 SHALL 复用现有稳定 HTTP 状态/错误码体系：请求无效返回 422，索引或前置状态不
满足返回 409，LLM key 缺失、限流、断连、超长、空返回和结构化输出失败返回 503；错误响应
SHALL 为 `{code, message}` 且不包含英文异常类名或堆栈。问答错误文案可以按问答场景提供，
但不得改变既有 graph/wiki 端点的错误语义。

#### Scenario: LLM 未配置

- **GIVEN** 检索命中上下文但服务进程没有用户自配 LLM key
- **WHEN** 客户端请求问答
- **THEN** 返回 503 与 `code=llm_not_configured`，message 给出中文配置指引

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

### Requirement: 提供桌面资料库清单与状态

系统 SHALL 提供 `GET /api/library` 返回桌面 vault 的来源级清单：每条 SHALL 含来源名、相对路径、`source_hash`、真实 `source_id`、服务端判定的 `removable` 与摄取状态（至少区分已摄取/待重抽/已忽略/原件缺失/已替代），以及该来源的索引状态；由来源目录同步而来的条目 SHALL 附登记的上游路径（`origin_path`），手动导入条目该字段为 null。清单 SHALL 派生自既有摄取元数据与库域登记，SHALL NOT 复制第二份事实存储。未完成的已确认移除 SHALL 如实呈现，不以原件缺失掩盖任务失败。

#### Scenario: 展示来源状态

- **GIVEN** vault 内含已摄取、原件被修改、原件缺失与已替代四类文档
- **WHEN** 客户端请求 `GET /api/library`
- **THEN** 返回 200，四类文档分别标记为已摄取/待重抽/原件缺失/已替代，字段与既有摄取元数据及库域登记同源

#### Scenario: 清单为只读派生

- **WHEN** 客户端重复请求清单
- **THEN** 清单内容随既有摄取元数据与库域登记变化，系统不因清单查询产生任何写入

#### Scenario: 展示喂养来源

- **GIVEN** 某文档由来源目录同步入库，另一文档由手动导入
- **WHEN** 客户端请求 `GET /api/library`
- **THEN** 前者条目附来源目录中的上游路径，后者该字段为 null

#### Scenario: 移除资格由服务端给出

- **GIVEN** 库中存在手动导入与同步登记管理的来源
- **WHEN** 客户端获取清单
- **THEN** 条目携带真实 `source_id`，仅服务端确认的手动来源可标记 `removable=true`，客户端不从路径推断

### Requirement: 提供导入摄取任务与进度查询

系统 SHALL 提供 `POST /api/library/ingest` 触发对 vault 的增量摄取后台任务（复用
既有幂等管线，同 `source_hash` 不重抽），SHALL 提供 `GET /api/library/jobs/{id}`
返回任务进度（已完成/失败/总数与当前文件）。同一时刻 SHALL 最多存在一个摄取任务，
重复触发 SHALL 返回 409 与稳定错误码的中文提示。进度 SHALL 经 HTTP 轮询获取，系统
不建立长连接推送。任务状态 SHALL 只存进程内存；进程重启后按幂等语义重跑恢复。

#### Scenario: 导入触发摄取并推进度

- **GIVEN** 用户导入两个新文档后触发摄取
- **WHEN** 客户端轮询 job 进度
- **THEN** 进度从 0/2 推进到 2/2，任务结束后清单中两个来源标记为已摄取

#### Scenario: 重复触发返回 409

- **GIVEN** 一个摄取任务正在执行
- **WHEN** 客户端再次请求 `POST /api/library/ingest`
- **THEN** 返回 409 与 `{code, message}` 中文提示，原任务不受影响

#### Scenario: 进程重启后幂等恢复

- **GIVEN** 摄取任务进行到一半时 serve 进程重启
- **WHEN** 用户重新触发摄取
- **THEN** 管线按 `source_hash` 跳过已完成文件并完成剩余部分，无重复产物

#### Scenario: 取消运行中的任务

- **GIVEN** 一个逐文件摄取任务正在执行
- **WHEN** 客户端请求取消该任务
- **THEN** 当前文件处理完毕后任务停止，已完成部分保留；对已结束或未知任务取消
  分别返回 409 与 404 稳定错误码

### Requirement: 提供索引同步与全量重建入口

摄取任务完成后系统 SHALL 自动执行增量索引同步（复用既有管线）；当索引模型身份与
当前 embedding 配置不匹配时，增量同步 SHALL 拒绝并返回既有「需全量重建」中文指引
（与设置中心告警同一出口）。系统 SHALL 提供显式全量重建端点，未携带确认标记时
SHALL 返回 422；重建进度 SHALL 复用任务进度机制反馈。

#### Scenario: 摄取后自动增量索引

- **GIVEN** 索引已存在且 embedding 配置未变
- **WHEN** 一次摄取任务成功结束
- **THEN** 新增/变更来源的块进入索引，无需用户单独操作

#### Scenario: 全量重建需确认

- **WHEN** 客户端请求全量重建且未携带确认标记
- **THEN** 返回 422；携带确认标记后执行重建并以任务进度反馈

### Requirement: 提供浏览只读端点

系统 SHALL 提供浏览读取端点：返回 vault 笔记投影的分页清单（稳定排序、含来源名与
元数据）与单篇 Markdown 内容（含来源锚点信息）；请求不存在的条目 SHALL 返回 404。
端点为只读，SHALL NOT 提供任何写回路径。

#### Scenario: 清单与单篇读取

- **GIVEN** vault 已摄取若干文档并生成笔记投影
- **WHEN** 客户端请求清单后请求其中一篇
- **THEN** 清单含稳定排序的分页与总数，单篇返回 Markdown 内容与来源锚点信息

#### Scenario: 读取不存在的条目

- **GIVEN** 客户端请求的笔记标识不存在
- **WHEN** 客户端请求单篇内容
- **THEN** 返回 404 与 `{code, message}` 中文提示，无其他副作用

### Requirement: 提供图谱有界只读查询

系统 SHALL 提供图谱读取端点：返回实体/边/社区的聚合统计，以及有界子图查询（度数
top-N、实体搜索、邻域展开，请求含返回上限）。候选结果超过上限时系统 SHALL 按既定
优先级裁剪并在响应中明示「已截断」与总数。端点 SHALL NOT 暴露存储文件路径或一次性
推送全图。

#### Scenario: 聚合统计

- **GIVEN** 图谱已构建
- **WHEN** 客户端请求统计
- **THEN** 返回节点数、边数、社区数等聚合指标

#### Scenario: 大图截断明示

- **GIVEN** 子图查询的候选结果超过返回上限
- **WHEN** 客户端请求邻域展开
- **THEN** 返回不超过上限的结果集，并携带「已截断」标记与候选总数

### Requirement: 提供 wiki 只读端点

系统 SHALL 提供 wiki 条目清单与单条内容读取端点，内容派生自 `data/wiki/entries/`；
响应 SHALL 携带生成时间等时效元数据。端点为只读，读取 SHALL NOT 触发生成或重建。

#### Scenario: 条目阅读

- **GIVEN** wiki 已生成
- **WHEN** 客户端请求条目清单与其中一条
- **THEN** 清单返回条目列表，单条返回内容与生成时间元数据，且未触发重新生成

### Requirement: 提供来源目录管理端点

系统 SHALL 提供来源目录的列举、注册、启停与移除端点。注册 SHALL 校验路径存在且
为目录（否则 422），同一真实路径 SHALL NOT 重复登记（否则 409）；移除 SHALL 仅
删除登记与检测缓存，SHALL NOT 影响已入库文档与既有 tombstone。

#### Scenario: 注册、启停与移除不触及语料

- **GIVEN** 某来源目录已登记且其文档已入库
- **WHEN** 客户端将该源停用后移除登记
- **THEN** 端点返回成功，已入库文档与清单状态保持不变，后续扫描不再遍历该目录

### Requirement: 提供扫描与清理端点

系统 SHALL 提供 `POST /api/library/scan` 立即执行一轮扫描（复用既有任务进度机制，
支持全量哈希校验选项）；任务槽被占用时 SHALL 返回 409 `library_job_busy`。系统
SHALL 提供自动扫描间隔与图谱自动刷新开关的读写端点（间隔 0 表示关闭自动扫描，
负值 SHALL 拒绝为 422；开关缺省为关闭），二者更新 SHALL 免重启生效。系统 SHALL
提供 `POST /api/library/purge` 确认式清理端点：未携带确认标记 SHALL 返回 422
`purge_confirm_required`；携带后 SHALL 以任务进度反馈清理过程。

#### Scenario: 手动扫描无变更时瞬时完成

- **GIVEN** 来源目录与登记内容一致
- **WHEN** 客户端请求 `POST /api/library/scan`
- **THEN** 返回 succeeded 任务快照且条目为空，无摄取与索引动作发生

#### Scenario: 间隔更新写入注册表

- **GIVEN** 自动扫描间隔为缺省值
- **WHEN** 客户端请求 `PUT` 更新间隔为 60 秒
- **THEN** 返回 200 与新值，后续读取与调度均按 60 秒执行；负值更新返回 422

#### Scenario: 图谱自动刷新开关读写

- **GIVEN** 图谱自动刷新开关为缺省关闭
- **WHEN** 客户端请求 `PUT` 开启该开关并重新读取
- **THEN** 返回 200 与新值，后续内容变更任务按开关语义执行；再次关闭后行为回到
  只同步索引

#### Scenario: 清理需确认

- **WHEN** 客户端请求 `POST /api/library/purge` 且未携带确认标记
- **THEN** 返回 422 与 `{code, message}` 中文提示，任何文件未被删除

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

### Requirement: 提供确认的单来源移除任务

系统 SHALL 提供 `POST /api/library/remove`，按 `source_id` 和显式 `confirmed=true` 移除一个手动来源，复用既有任务与进度查询契约。请求 SHALL NOT 接受任意文件路径。未确认 SHALL 返回 422，不存在 SHALL 返回 404，同步管理来源或同库写入冲突 SHALL 返回 409 与稳定错误码；已经确认但尚未完成的来源 SHALL 可按原 ID 重试。

#### Scenario: 确认后使用既有进度

- **GIVEN** 目标是可移除的手动来源且库空闲
- **WHEN** 请求包含有效 source_id 与 confirmed=true
- **THEN** 接收一个移除任务，返回既有任务响应，客户端经原进度接口获知实际完成或失败

#### Scenario: 未确认没有副作用

- **GIVEN** 目标来源存在
- **WHEN** 移除请求省略确认或确认不为 true
- **THEN** 返回 422，不标记、不修改文件或派生物

#### Scenario: 不能提交任意路径

- **GIVEN** 请求试图把外部路径或越界目标当成来源 ID
- **WHEN** 系统验证目标
- **THEN** 明确拒绝，不删除任意本机文件

### Requirement: 同库写入任务互斥

同一受管库的导入、原始摄取、扫描写入、清理、索引、图谱和 Wiki 构建，以及影响同步归属的来源启停/解除登记 SHALL 共享写入互斥，覆盖 HTTP、CLI 与不同进程，并持续至任务写入及发布完成。手动冲突 SHALL 明确反馈忙态，HTTP 保持 409 `library_job_busy`；自动扫描写入冲突 SHALL 顺延，并在重新取得写入权后重验来源及计划，SHALL NOT 执行已失效的槽外计划。只读查询 SHALL 保持既有快照读取，不因本规则新增模型调用。

#### Scenario: 构建与移除不能交错发布

- **GIVEN** 一个图谱或 Wiki 构建正在使用同库来源
- **WHEN** 另一个进程请求移除
- **THEN** 手动请求明确反馈忙态，待构建结束后可重试，不在移除完成后发布旧来源的构建结果

#### Scenario: 原始摄取也遵守互斥

- **GIVEN** 单项移除任务正在执行
- **WHEN** 同库原始摄取接口或 CLI 索引命令尝试写入
- **THEN** 明确反馈忙态，不能绕过资料库任务槽改写正在移除的来源

#### Scenario: 自动扫描写入顺延

- **GIVEN** 库写入被手动任务占用，自动扫描检测到文件变更
- **WHEN** 扫描准备写入
- **THEN** 本轮写入顺延，无用户可见失败，来源文件保持只读

#### Scenario: 来源解除登记后旧计划不喂回

- **GIVEN** 扫描在锁外形成计划，随后来源在同库锁内被停用或解除登记
- **WHEN** 扫描稍后取得写入权
- **THEN** 重验来源与当前计划，放弃该陈旧计划，不重新导入失效来源，不复活已移除内容

### Requirement: 资料库任务通知派生维护结果

资料库任务（摄取/扫描/清理）的终态快照 SHALL 可携带中文通知字段，说明收尾阶段
派生维护的结果或跳过原因（含图谱自动刷新的抽取与缓存命中计数、因抽取身份变更
跳过的原因、因端点失败跳过的事实）。通知 SHALL NOT 改变任务终态语义（成功/失败/
取消）；通知字段缺失 SHALL 按无附加信息处理，既有客户端解析不受影响。

#### Scenario: 自动刷新计数进通知

- **GIVEN** 开关已开启且自动刷新实际执行
- **WHEN** 客户端轮询该任务快照
- **THEN** 响应携带通知字段，说明本次新增抽取数与缓存命中数

#### Scenario: 跳过与失败同样可见

- **GIVEN** 开关已开启但抽取身份不符，或抽取端点失败
- **WHEN** 客户端轮询该任务快照
- **THEN** 通知分别说明跳过原因或失败事实，任务终态分别为 succeeded（摄取成功）
  与既有终态语义，不因图谱刷新失败改写

#### Scenario: 无通知时保持兼容

- **GIVEN** 开关为关闭，或任务未发生任何可通知的派生维护
- **WHEN** 客户端轮询任务快照
- **THEN** 通知字段缺失或为空，旧客户端按既有契约正常解析
