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
错误文案 SHALL 与 CLI 共享同一映射来源。

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

### Requirement: 提供桌面资料库清单与状态

系统 SHALL 提供 `GET /api/library` 返回桌面 vault 的来源级清单：每条 SHALL 含来源
名、相对路径、`source_hash` 与摄取状态（至少区分已摄取/待重抽/已忽略），以及该来源
的索引状态。清单 SHALL 派生自既有摄取元数据，SHALL NOT 复制第二份事实存储。

#### Scenario: 展示来源状态

- **GIVEN** vault 内含一个已摄取文档，且其中之一的原件在摄取后被修改
- **WHEN** 客户端请求 `GET /api/library`
- **THEN** 返回 200，未变更来源标记为已摄取，原件已变更来源标记为待重抽，字段与
  既有摄取元数据同源

#### Scenario: 清单为只读派生

- **WHEN** 客户端重复请求清单
- **THEN** 清单内容随既有摄取元数据变化，系统不因清单查询产生任何写入

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
