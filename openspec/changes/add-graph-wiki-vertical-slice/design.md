# 设计：Phase 3 图谱与 wiki 纵切面

## 边界与事实源

`src/siku/graph/` 负责抽取、缓存、图谱构建与体检；`src/siku/wiki/` 负责社区摘要
与总目条目生成。两者只读取 `vault/notes/` 投影与检索层已固化的 chunk 元数据
（`chunk_id`/`source_hash`/`anchor`），复用 `retrieve.notes_reader` 的解析器，不
重复实现投影解析。`vault/` 不写入任何图谱或 wiki 数据；`data/graph/` 与
`data/wiki/` 均为可删除、可全量重建的派生物（宪法红线 3）。

## 数据布局

默认派生目录 `data/` 下新增（CLI 可 `--data-dir` 覆盖）：

```text
data/
  graph/
    cache.sqlite3          # LLM 抽取缓存（键：chunk_hash+抽取器/模型+prompt 版本）
    entities.parquet       # 实体表：entity_id/name/type/source 锚点列表
    relations.parquet      # 关系表：source_entity/target_entity/type/chunk 锚点
    communities.parquet    # 社区表：community_id/成员实体/层级/摘要缓存键
  wiki/
    entries/               # 总目条目（每社区一篇 Markdown，含锚点回链）
    index.md               # 总目索引
```

图谱本体只用 parquet，缓存只用 SQLite（ADR-0003 三件套边界内）。parquet 读写用
pyarrow（已随 lancedb 进入依赖树，作为 graph 包的显式声明依赖）。

## 抽取管线与 GraphExtractor 协议

```python
class GraphExtractor(Protocol):
    extractor_id: str          # 如 "llm-deepseek-chat"
    prompt_version: str        # 进入缓存键，prompt 变更即失效旧缓存
    def extract(self, chunk: ChunkRecord) -> GraphExtraction: ...
```

`GraphExtraction` 为项目自有领域模型：`entities: tuple[EntityMention, ...]`、
`relations: tuple[RelationMention, ...]`，每个 mention 携带 `name/type/evidence`
（evidence 为 chunk 内原文片段），**不暴露任何第三方 SDK 对象**（ADR-0005 红线）。

默认实现 `LlmGraphExtractor`：openai 兼容 chat completions 协议（httpx 直连，不引
入 openpy SDK），默认 DeepSeek 端点；key 从环境变量读取（`SIKU_LLM_API_KEY`，可
`--api-key-env` 覆盖变量名），缺失/为空时抛 `LlmNotConfiguredError`，CLI 给出中文
配置指引，绝不静默降级为规则抽取。prompt 复用 graphify 验证过的结构（实体+关系
一次抽取、严格 JSON 输出），但不绑定其代码。

LLM 输出校验：非法 JSON、缺字段、实体/关系引用越界一律转 `GraphExtractionError`
（用户可读），空抽取（无实体）是合法结果而非错误。

## 抽取缓存与幂等

缓存键：`sha256(chunk_hash + extractor_id + model_id + prompt_version)`。命中缓存
则不调用 LLM；未命中则调用并写缓存。由此实现：

- 同一语料 + 同一抽取配置下，第二次构建**零次 LLM 调用**；
- 「全量重跑幂等（重建结果 diff 为空）」闸门：删除 parquet 本体后从缓存重建，
  产物字节级一致（社区发现固定随机种子、排序全部确定性化；wiki 渲染无时间戳等
  非稳定字段，环境元数据只入体检报告不入产物）。

换模型/换 prompt 版本 → 缓存键变化 → 相关 chunk 全部重抽（显式语义，与检索层
「换模型显式重建」一致）。

## 图谱构建、社区发现与 wiki

1. 合并：全部 mention 按归一化名称（NFKC + 大小写折叠 + 空白折叠）合并为实体；
   同名实体数量进入体检报告（基础版同名合并，语义消歧明确延期）。
2. 关系：mention 对去重后成边，边携带证据 chunk 锚点列表（chunk_id + anchor +
   source_hash），保证任何图谱结论可回链原文。
3. 内存图用 `networkx.Graph`；社区发现用 `networkx.community.louvain_communities`
   固定 seed。图规模超过 10⁵ 边属 ADR-0003 复核信号，体检报告负责暴露量级。
4. 社区摘要：每社区取成员实体与关系证据交 LLM 生成摘要（走同一缓存机制，键含
   summarizer prompt 版本）；摘要失败按五剧本语义转领域错误，不允许空摘要落盘。
5. wiki 条目：每社区一篇 Markdown（标题、摘要、成员实体、关键关系及原文锚点），
   `index.md` 汇总总目；渲染为纯确定性字符串拼接，无时间戳等非稳定字段。

## CLI 与错误处理

```text
siku graph  [--vault VAULT] [--data-dir DATA_DIR] [--rebuild] [--json]
siku wiki   [--data-dir DATA_DIR] [--json]
```

`siku graph` 构建图谱并输出体检报告（节点/边/社区计数、同名实体数、量级告警、
缓存命中与 LLM 调用次数）；`--rebuild` 忽略缓存强制重抽。`siku wiki` 生成总目；
图谱产物缺失时报错并提示先执行 `siku graph`。`--json` 输出稳定字段（计数、缓存
命中、告警列表），人类可读文案简体中文，日志英文。

## 测试策略

- 先写失败测试再分层实现：领域模型 → LLM provider 五剧本（正常/超长/空返回/
  限流/断连，可编程 fake，CI 永不打真实 API）→ 抽取输出解析 → 缓存跳过逻辑 →
  图构建/parquet 往返 → 社区确定性 → wiki 渲染 → CLI。
- 幂等闸门测试：同语料二次构建断言 LLM 调用为 0；删本体重建断言 parquet 与
  wiki 产物 diff 为空。
- 本地质量验证（BYO key，显式命令，不入 CI）：对小语料跑真实抽取并人工复核
  实体/关系质量，记录抽取调用成本。
