## RENAMED Requirements

- FROM: ### Requirement: 工具面为六个只读工具加一个幂等摄取工具
- TO: ### Requirement: 工具面为七个只读工具加一个幂等摄取工具

## MODIFIED Requirements

### Requirement: 工具面为七个只读工具加一个幂等摄取工具

服务器 SHALL 暴露八个工具：七个只读（`search` 混合检索、`ask` 单轮有来源问答、
`list_documents` 资料库清单、`read_document` 投影全文读取、`graph_search` 实体搜索、
`graph_neighbors` 有界邻域展开、`entity_evidence` 实体 join 证据检索——查询串确定性
解析种子实体，一跳共现扩展返回带实体溯源的桥接证据，空结果按分型返回定位建议而非
失败）加 `ingest`（文件或目录摄取）。工具语义 SHALL 与既有命令行与 HTTP 面同构；
`read_document` SHALL 施加体积上限并明示截断；图谱类与实体证据类工具 SHALL 沿用
服务端有界查询与截断明示口径；`ask` 的证据不足 SHALL 作为正常结果返回而非失败。

#### Scenario: 检索与问答带可溯源引用

- **GIVEN** 已配置模型供给且索引可用
- **WHEN** 客户端调用 `search` 与 `ask`
- **THEN** 结果携带来源名、锚点与投影路径，`ask` 附引用清单；证据不足时返回
  证据不足标记与说明而非工具失败

#### Scenario: 全文读取超限明示截断

- **GIVEN** 某投影全文超过服务端结果体积上限
- **WHEN** 客户端按来源身份读取该文档
- **THEN** 返回内容在上限内截断，并明示截断标记与总量线索；不存在来源身份则返回
  未找到失败

#### Scenario: 摄取幂等且受限白名单

- **GIVEN** 同一文件已摄取且内容未变，或目标为不支持的格式
- **WHEN** 客户端再次调用 `ingest`
- **THEN** 未变更文件计入跳过而非重复生成；不支持的格式计入 ignored 并如实返回计数，
  不误报成功也不改变既有摄取幂等契约

#### Scenario: 实体证据查询带溯源

- **GIVEN** 图谱与索引已构建
- **WHEN** 客户端调用 `entity_evidence`
- **THEN** 证据结果携带来源名、锚点、投影路径与实体溯源（种子/桥接实体）；无种子
  命中返回分型空结果与定位建议而非工具失败

#### Scenario: 图谱未构建给构建指引

- **GIVEN** 图谱快照不存在
- **WHEN** 客户端调用 `entity_evidence`
- **THEN** 返回未找到失败与"先构建图谱"指引，不出现堆栈或内部异常文本
