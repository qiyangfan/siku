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
