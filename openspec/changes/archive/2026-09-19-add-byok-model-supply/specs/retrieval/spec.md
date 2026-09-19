# retrieval Specification（delta）

## REMOVED Requirements

### Requirement: 提供本地向量召回与模型配置校验

**Reason**: 模型供给全面端点化（BYOK），进程内本地模型（bge-m3/bge-reranker +
sentence-transformers/torch）整体删除，"本地"语义不复存在。

**Migration**: 行为由下方 ADDED 的「提供向量召回与模型配置校验」承接；golden set
参照基准改由用户自部署端点通道承担（见 ADR-0009）。

## ADDED Requirements

### Requirement: 提供向量召回与模型配置校验

系统 SHALL 通过用户配置的 embedding 端点（openai 兼容 `POST /embeddings`）建立向量
索引，并 SHALL 在查询时执行向量召回；系统 SHALL 保存模型标识、端点通道标识与向量
维度，并在配置不匹配时拒绝混用。系统 MUST NOT 在索引元数据、日志或评测基线中记录
API 凭证。

#### Scenario: 向量索引使用端点 provider

- **GIVEN** 一个已配置且可达的 embedding 端点和若干检索块
- **WHEN** 用户执行索引同步
- **THEN** 系统分批调用端点为每个新增或变化的检索块保存向量及其模型元数据，且不暴露
  provider 的第三方对象

#### Scenario: 模型元数据不一致

- **GIVEN** 已有向量索引的模型标识或维度与当前配置不一致
- **WHEN** 用户执行查询或增量索引
- **THEN** 系统拒绝混用并提示执行显式全量重建

#### Scenario: 端点不可达或凭证无效

- **GIVEN** embedding 端点不可达、返回 401/429/5xx 或未配置
- **WHEN** 用户执行需要向量的索引或查询
- **THEN** 系统返回明确的用户可读错误与配置指引，不写入可用索引半成品

## MODIFIED Requirements

### Requirement: 执行混合召回与重排

系统 SHALL 将 BM25 候选与向量候选合并后进行确定性的候选融合，并 SHALL 使用用户配置
的 rerank 端点对融合候选重排；用户显式选择 `reranker=none` 时，系统 SHALL 按融合
分数直接排序。最终结果 SHALL 按稳定规则排序并包含可追溯来源信息。

#### Scenario: 两路候选合并

- **GIVEN** BM25 与向量召回分别返回候选，且两路候选存在交集或差集
- **WHEN** 用户执行检索
- **THEN** 系统对候选去重、融合两路排名、执行重排（或按 none 配置跳过），并返回不
  超过 `top_k` 条结果

#### Scenario: 排名相同的稳定顺序

- **GIVEN** 两个结果的重排分数和融合分数均相同
- **WHEN** 系统生成最终结果
- **THEN** 系统使用稳定的 chunk 标识作次级排序，使相同输入得到相同顺序

#### Scenario: 返回结构锚点

- **GIVEN** 命中的检索块来自带页码、slide 或 sheet 锚点的投影
- **WHEN** 系统返回搜索结果
- **THEN** 结果包含该 anchor、source_hash、相对 note 路径与正文，使调用者可以定位原件

#### Scenario: 重排器未配置

- **GIVEN** 用户显式配置 `reranker=none`（如自部署端点不提供 rerank API）
- **WHEN** 用户执行检索
- **THEN** 系统按 RRF 融合分数排序返回结果，行为确定性与其他配置一致

### Requirement: 提供检索 CLI

系统 SHALL 提供 `siku index`、`siku search QUERY` 和 `siku evaluate-retrieval` 命令；
三类命令 SHALL 支持模型供给参数（embedding/rerank 端点与凭证，或来自分层配置）；
CLI SHALL 使用简体中文用户文案，并 SHALL 支持稳定的 JSON 输出供后续 HTTP 层复用。

#### Scenario: 同步索引并报告统计

- **GIVEN** 一个包含有效投影和未知/无关文件的 vault 以及已配置的 embedding 端点
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

#### Scenario: 模型端点未配置

- **GIVEN** 用户未以任何层级配置 embedding（或必需的 rerank）端点
- **WHEN** 用户执行需要模型调用的 `siku index` 或 `siku search QUERY`
- **THEN** CLI 以非零状态退出并给出可行动的配置指引（config.toml 模板或参数示例），
  不产生半成品数据

### Requirement: 以 golden set 作为检索回归门禁

系统 SHALL 提供版本化的 golden set、评测指标和**按模型通道**保存的基线快照；同一
通道的检索评测分数低于该通道已提交基线时 SHALL 失败，分数相同或提升时 SHALL 通过。

#### Scenario: 运行 golden set 评测

- **GIVEN** 一个版本化的问题-期望来源集合、已配置的模型通道和可用检索索引
- **WHEN** 用户执行 `siku evaluate-retrieval`
- **THEN** 系统报告 Recall@5、MRR@10、逐题命中情况以及通道/模型/参数元数据

#### Scenario: 评测分数不低于基线

- **GIVEN** 当前评测分数不低于所属通道的已提交基线
- **WHEN** 回归门禁比较当前结果与基线
- **THEN** 命令成功退出并保留可审计的比较结果

#### Scenario: 评测分数低于基线

- **GIVEN** 当前评测分数低于所属通道的已提交基线
- **WHEN** 回归门禁比较当前结果与基线
- **THEN** 命令以非零状态退出并指出下降的指标，不得自动覆盖旧基线

#### Scenario: 通道基线缺失

- **GIVEN** 用户首次以某个新的模型通道执行评测
- **WHEN** 所属通道不存在基线快照且未提供 `--save-baseline`
- **THEN** 命令以非零状态退出并提示显式建立该通道基线，不得静默跳过比较
