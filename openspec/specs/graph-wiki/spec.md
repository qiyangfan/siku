# graph-wiki Specification

## Purpose
从检索 chunk 事实层抽取实体与关系，构建可全量重建的知识图谱与社区，并生成带
来源锚点的 wiki 总目条目。

## Requirements

### Requirement: 从 chunk 事实层抽取实体与关系

系统 SHALL 通过 `GraphExtractor` 协议从检索层检索块抽取实体与关系，并 SHALL 为
每个实体提及与关系携带 `chunk_id`、`source_hash` 与结构锚点，使图谱结论可回链
`vault/attachments/` 原文。

#### Scenario: 抽取产物携带来源锚点

- **GIVEN** 一个带 `source_hash` 与结构锚点的检索块
- **WHEN** 抽取器产出实体与关系
- **THEN** 每条实体提及与关系都携带该块的 `chunk_id`、`source_hash` 与 anchor，
  且 evidence 为块内原文片段

#### Scenario: 抽取输出不合法时报用户可读错误

- **GIVEN** 抽取器返回非 JSON、缺必需字段或关系引用了不存在的实体
- **WHEN** 系统解析抽取产物
- **THEN** 系统抛出用户可读的领域错误并指明 chunk 与问题，不写入半成品图谱

#### Scenario: 空抽取是合法结果

- **GIVEN** 一个不含任何实体的检索块
- **WHEN** 抽取器返回空实体与空关系
- **THEN** 系统正常记录该块的空抽取结果，不报错

### Requirement: 图谱抽取后端可插拔且 LLM 通道可配置

系统 SHALL 以自有协议注入图谱抽取后端，领域层 SHALL NOT 暴露任何第三方 SDK
对象；LLM 通道 SHALL 使用 BYO key 的 openai 兼容 API，未配置 key 时 SHALL 给出
配置指引且不得静默降级。

#### Scenario: 协议注入 fake 抽取器

- **GIVEN** 测试注入可编程 fake 抽取器
- **WHEN** 系统执行图谱构建
- **THEN** 领域层只依赖 `GraphExtractor` 协议与领域模型，测试全程不访问真实 API

#### Scenario: LLM 五剧本不穿透非领域错误

- **GIVEN** fake provider 分别模拟正常、超长输入、空返回、限流与断连
- **WHEN** 系统执行抽取
- **THEN** 全部异常都落在领域错误体系内并携带可定位信息，无裸 SDK 异常穿透

#### Scenario: 未配置 API key 时给出指引

- **GIVEN** 环境中未配置 LLM API key
- **WHEN** 用户执行需要真实抽取的构建
- **THEN** CLI 以非零状态退出并给出中文配置指引，不写入任何图谱产物

### Requirement: 抽取缓存与幂等重建

系统 SHALL 以（chunk_hash, 抽取器/模型标识, prompt 版本）为键缓存抽取产物；
源与配置未变时重建 SHALL NOT 重复调用 LLM，从缓存重建的产物 SHALL 与既有产物
diff 为空。更换模型或 prompt 版本 SHALL 使相关缓存失效并重抽。

#### Scenario: 未变语料零次 LLM 调用

- **GIVEN** 图谱已经构建完成且语料未变化
- **WHEN** 用户再次执行图谱构建
- **THEN** 全部抽取命中缓存，LLM 调用次数为 0，报告与上次一致

#### Scenario: 删除本体重建 diff 为空

- **GIVEN** 缓存与既有图谱产物存在
- **WHEN** 用户删除 parquet 与 wiki 产物后执行全量重建
- **THEN** 重建产物与删除前 diff 为空（社区划分与 wiki 渲染全部确定性）

#### Scenario: 更换模型使缓存失效

- **GIVEN** 用户更换抽取模型标识
- **WHEN** 用户执行图谱构建
- **THEN** 缓存按新键重抽并更新报告中的模型元数据

### Requirement: 社区发现与图谱体检报告

系统 SHALL 在内存图上执行确定性的社区发现并落 parquet；`siku graph` SHALL 输出
节点/边/社区数量、同名实体计数与缓存命中统计的体检报告，量级越界时 SHALL 给出
告警；空语料 SHALL 产出空图谱而非错误。

#### Scenario: 社区划分确定性

- **GIVEN** 相同的实体关系输入
- **WHEN** 重复执行社区发现
- **THEN** 社区划分与编号完全一致（固定随机种子与确定性排序）

#### Scenario: 体检报告暴露量级

- **GIVEN** 图谱构建完成
- **WHEN** 用户查看体检报告
- **THEN** 报告包含节点数、边数、社区数、同名实体数、缓存命中与 LLM 调用次数，
  并对超量级给出告警

#### Scenario: 空语料产出空图谱

- **GIVEN** vault 中没有可抽取的检索块
- **WHEN** 用户执行图谱构建
- **THEN** 系统产出零节点空图谱与空 wiki，成功退出并提示语料为空

### Requirement: wiki 总目条目生成

系统 SHALL 依据社区划分生成带来源锚点的 wiki 总目条目（每社区一篇 Markdown 与
全局索引），条目 SHALL 可从图谱与缓存全量重建；图谱产物缺失时 SHALL 提示先构建
图谱。

#### Scenario: 条目回链来源锚点

- **GIVEN** 一个包含成员实体与关系的社区
- **WHEN** 系统生成该社区的 wiki 条目
- **THEN** 条目包含社区摘要、成员实体、关键关系及其 chunk/原文锚点，可定位
  `vault/attachments/` 原件

#### Scenario: wiki 全量重建幂等

- **GIVEN** 图谱与摘要缓存未变
- **WHEN** 用户删除 wiki 产物后重新生成
- **THEN** 生成结果与删除前 diff 为空

#### Scenario: 图谱缺失时提示构建

- **GIVEN** `data/graph/` 下没有图谱产物
- **WHEN** 用户执行 `siku wiki`
- **THEN** CLI 以非零状态退出并提示先执行 `siku graph`

### Requirement: 提供 graph 与 wiki CLI

系统 SHALL 提供 `siku graph` 与 `siku wiki` 命令，均 SHALL 支持 `--json` 稳定
输出；CLI 用户文案为简体中文，错误经领域错误体系归一化。

#### Scenario: 构建图谱并报告

- **GIVEN** 一个已摄取并建立检索索引的 vault
- **WHEN** 用户执行 `siku graph`
- **THEN** 系统完成抽取、构建与社区发现，报告统计与体检结果；`--json` 输出
  稳定字段

#### Scenario: 生成 wiki 总目

- **GIVEN** 图谱与摘要缓存已就绪
- **WHEN** 用户执行 `siku wiki`
- **THEN** 系统生成每社区条目与 `index.md`，并报告条目数量

#### Scenario: 命令错误路径为中文

- **GIVEN** 缺索引产物、未配置 key 或 LLM 故障
- **WHEN** 用户执行 `siku graph` 或 `siku wiki`
- **THEN** CLI 以非零状态退出，输出简体中文指引，技术细节不进用户面

### Requirement: 资料移除后旧可读派生物失效

手动资料移除完整成功前，系统 SHALL 使包含旧语料的可读图谱与 Wiki 快照失效，保留可复用的抽取缓存，SHALL NOT 自动调用模型重建。后续读取 SHALL 沿未构建语义给出重建提示；图谱显式重建 SHALL 仅使用当前剩余 Markdown 事实层及其派生块，Wiki SHALL 使用当前重建图谱，SHALL NOT 从旧缓存恢复已移除资料，也 SHALL NOT 新增检索索引或向量端点的前置条件。

#### Scenario: 移除后已有快照不能继续读取

- **GIVEN** 一个已构建图谱/Wiki 的手动来源被完整移除
- **WHEN** 新请求读取图谱或 Wiki
- **THEN** 不返回旧可读产物，提示需重新构建，移除本身没有自动模型调用

#### Scenario: 缓存复用不能复活删除块

- **GIVEN** 抽取缓存仍包含已移除来源的历史条目
- **WHEN** 用户显式重建图谱与 Wiki
- **THEN** 只按当前 Markdown 事实层来源和 chunk 集合复用缓存，移除内容不进入新实体、关系、社区或条目

#### Scenario: 无检索索引仍按剩余事实层构建

- **GIVEN** 资料已移除，剩余 Markdown 投影存在但检索索引不存在，图谱模型前提已满足
- **WHEN** 用户显式构建图谱并生成 Wiki
- **THEN** 图谱使用剩余事实层，Wiki 使用当前图谱，不因缺少检索索引遗漏语料

### Requirement: 内容变更后图谱可增量自动维护

系统 SHALL 提供库级开关（默认关闭）控制内容变更任务成功后是否自动增量刷新**已存在**的图谱。开启时，自动刷新 SHALL 同时满足以下前提：图谱快照已存在；抽取身份（抽取器标识、模型、prompt 版本）与上次成功构建一致；LLM 通道可用。任一前提不满足时 SHALL 跳过刷新，并在任务通知中说明原因。自动刷新 SHALL 走与显式更新相同的构建路径，产物 SHALL 与显式更新一致；SHALL NOT 自动创建图谱、SHALL NOT 自动重建已被移除或清理失效的快照、SHALL NOT 触发全量重抽。被取消的任务 SHALL NOT 触发自动刷新。刷新失败 SHALL NOT 改变内容变更任务的成功终态，旧图谱快照 SHALL 保持可读，后续内容变更 SHALL 复用既有抽取缓存续传。

#### Scenario: 开启后只增量抽取新内容

- **GIVEN** 开关已开启，图谱已构建且此后仅新增一个文档
- **WHEN** 摄取或扫描任务成功结束
- **THEN** 任务收尾自动刷新图谱，仅新文档的 chunk 发生 LLM 抽取，旧 chunk 全部命中缓存，任务通知如实报告新增抽取数与缓存命中数

#### Scenario: 图谱不存在时跳过且不创建

- **GIVEN** 开关已开启但图谱从未构建，或图谱快照已被移除/清理失效
- **WHEN** 内容变更任务成功结束
- **THEN** 不发生任何图谱模型调用，图谱维持未构建语义，首建仍由用户显式触发

#### Scenario: 抽取身份变化时跳过并指引显式更新

- **GIVEN** 开关已开启，且上次成功构建后抽取模型或 prompt 版本已变更
- **WHEN** 内容变更任务成功结束
- **THEN** 跳过自动刷新，通知说明模型/prompt 已变更、需显式更新且将全量重抽，不产生静默的全量重抽

#### Scenario: 刷新失败不改变任务终态

- **GIVEN** 开关已开启且前提满足，但抽取端点限流、返回不可解析内容或通道不可用
- **WHEN** 内容变更任务成功结束而图谱刷新失败
- **THEN** 任务终态为 succeeded 并附失败通知，旧图谱保持可读，下次内容变更复用缓存续传而非全量重抽

#### Scenario: 取消不触发刷新

- **GIVEN** 开关已开启且用户在内容变更任务执行中取消
- **WHEN** 任务以取消终态结束
- **THEN** 不发生图谱刷新，图谱保持任务前快照，已入库内容仍发布检索索引

#### Scenario: 自动与显式产物一致

- **GIVEN** 同一语料分别经自动刷新与用户显式更新两条路径构建
- **WHEN** 比较两次图谱产物
- **THEN** 实体、关系与社区产物 diff 为空（自动路径未引入独立的增量算法）
