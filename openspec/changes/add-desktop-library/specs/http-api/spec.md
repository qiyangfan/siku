# http-api Specification（delta）

## ADDED Requirements

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
