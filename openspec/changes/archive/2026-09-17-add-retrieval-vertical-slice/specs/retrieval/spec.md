# 检索纵切面

## Purpose

从本地 Markdown 事实层生成可重建的混合检索索引，并返回带来源锚点的高质量候选结果。

## ADDED Requirements

### Requirement: 从 Markdown 事实层建立可重建索引

系统 SHALL 只读取 `vault/notes/` 中的 Markdown 投影建立派生索引，并 SHALL 保存每个文档
与检索块的 `source_id`、`source_hash`、来源名称、相对路径、结构锚点和正文。

#### Scenario: 建立结构化检索块

- **GIVEN** 一个包含 frontmatter 和多个二级结构区块的 Markdown 投影
- **WHEN** 用户执行索引同步
- **THEN** 系统为每个非空结构区块建立稳定的检索块，并保留对应 anchor、ordinal 和
  `source_hash`

#### Scenario: 相同来源 hash 不变

- **GIVEN** 某来源已经建立索引且其 `source_hash` 未变化
- **WHEN** 用户再次执行索引同步
- **THEN** 系统跳过该来源的解析、分词和 embedding，不产生重复检索块

#### Scenario: 单来源 hash 变化

- **GIVEN** 某来源的 Markdown 投影 `source_hash` 发生变化
- **WHEN** 用户执行索引同步
- **THEN** 系统只替换该来源的旧块、全文条目和向量，旧块不得继续出现在查询结果中

#### Scenario: 全量重建

- **GIVEN** 现有派生索引可能损坏或模型配置发生变化
- **WHEN** 用户执行显式全量重建
- **THEN** 系统忽略旧派生数据，按当前 `vault/notes/` 生成新索引，失败时旧索引仍可查询

### Requirement: 提供中文安全的全文检索

系统 SHALL 对 Markdown 正文和查询使用同一套确定性预分词规则，并 SHALL 通过参数化查询
在 SQLite FTS5 中执行 BM25 全文召回；系统 MUST NOT 将连续中文原文直接交给裸 FTS5。

#### Scenario: 中文短语命中

- **GIVEN** 索引中存在包含中文术语的检索块
- **WHEN** 用户以该术语或短语查询
- **THEN** 全文召回返回包含该检索块的候选，并保留其来源名称、路径、hash 和 anchor

#### Scenario: 英文数字型号保留

- **GIVEN** 检索块同时包含中文、英文、数字或连字符型号
- **WHEN** 用户查询英文词、数字或完整型号
- **THEN** 预分词不会丢失这些 token，全文召回可以返回对应检索块

#### Scenario: 合法查询无全文命中

- **GIVEN** 查询语句合法但没有任何全文匹配
- **WHEN** 系统执行全文召回
- **THEN** 系统返回空候选而不是抛出内部错误

### Requirement: 提供本地向量召回与模型配置校验

系统 SHALL 通过可替换的 embedding provider 建立向量索引，并 SHALL 在查询时执行向量召回；
系统 SHALL 保存模型标识、revision 和向量维度，并在配置不匹配时拒绝混用。

#### Scenario: 向量索引使用可替换 provider

- **GIVEN** 一个可用的 embedding provider 和若干检索块
- **WHEN** 用户执行索引同步
- **THEN** 系统为每个新增或变化的检索块保存向量及其模型元数据，且不暴露 provider
  的第三方对象

#### Scenario: 模型元数据不一致

- **GIVEN** 已有向量索引的模型标识或维度与当前配置不一致
- **WHEN** 用户执行查询或增量索引
- **THEN** 系统拒绝混用并提示执行显式全量重建

#### Scenario: 向量 provider 不可用

- **GIVEN** 本地模型依赖、模型文件或 provider 不可用
- **WHEN** 用户执行需要向量的索引或查询
- **THEN** 系统返回明确的用户可读错误，不写入可用索引半成品

### Requirement: 执行混合召回与重排

系统 SHALL 将 BM25 候选与向量候选合并后进行确定性的候选融合，并 SHALL 使用可替换的
reranker 对融合候选重排；最终结果 SHALL 按稳定规则排序并包含可追溯来源信息。

#### Scenario: 两路候选合并

- **GIVEN** BM25 与向量召回分别返回候选，且两路候选存在交集或差集
- **WHEN** 用户执行检索
- **THEN** 系统对候选去重、融合两路排名、执行重排，并返回不超过 `top_k` 条结果

#### Scenario: 排名相同的稳定顺序

- **GIVEN** 两个结果的重排分数和融合分数均相同
- **WHEN** 系统生成最终结果
- **THEN** 系统使用稳定的 chunk 标识作次级排序，使相同输入得到相同顺序

#### Scenario: 返回结构锚点

- **GIVEN** 命中的检索块来自带页码、slide 或 sheet 锚点的投影
- **WHEN** 系统返回搜索结果
- **THEN** 结果包含该 anchor、source_hash、相对 note 路径与正文，使调用者可以定位原件

### Requirement: 提供检索 CLI

系统 SHALL 提供 `siku index`、`siku search QUERY` 和 `siku evaluate-retrieval` 命令；CLI SHALL
使用简体中文用户文案，并 SHALL 支持稳定的 JSON 输出供后续 HTTP 层复用。

#### Scenario: 同步索引并报告统计

- **GIVEN** 一个包含有效投影和未知/无关文件的 vault
- **WHEN** 用户执行 `siku index`
- **THEN** 系统完成索引同步并报告 created、updated、skipped、removed 统计，未知文件不
  进入索引

#### Scenario: 查询并返回结果

- **GIVEN** 当前存在模型配置匹配的可用索引
- **WHEN** 用户执行 `siku search QUERY`
- **THEN** CLI 返回按最终分数排序的结果、来源元数据和结构锚点；无命中时成功返回空结果

#### Scenario: 索引不可用

- **GIVEN** 用户尚未建立索引、索引版本损坏或模型配置不一致
- **WHEN** 用户执行 `siku search QUERY`
- **THEN** CLI 以非零状态退出并给出执行索引或重建的明确提示

### Requirement: 以 golden set 作为检索回归门禁

系统 SHALL 提供版本化的 golden set、评测指标和基线快照；检索评测分数低于已提交基线时
SHALL 失败，分数相同或提升时 SHALL 通过。

#### Scenario: 运行 golden set 评测

- **GIVEN** 一个版本化的问题-期望来源集合和可用检索索引
- **WHEN** 用户执行 `siku evaluate-retrieval`
- **THEN** 系统报告 Recall@5、MRR@10、逐题命中情况以及模型/参数元数据

#### Scenario: 评测分数不低于基线

- **GIVEN** 当前评测分数不低于已提交基线
- **WHEN** 回归门禁比较当前结果与基线
- **THEN** 命令成功退出并保留可审计的比较结果

#### Scenario: 评测分数低于基线

- **GIVEN** 当前评测分数低于已提交基线
- **WHEN** 回归门禁比较当前结果与基线
- **THEN** 命令以非零状态退出并指出下降的指标，不得自动覆盖旧基线
