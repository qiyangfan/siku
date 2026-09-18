# 提案：完成 Phase 3 图谱与 wiki 纵切面

## Why

Phase 2 已经交付了带 `source_hash` 与结构锚点的稳定 chunk 与混合检索，但知识还没被
结构化：实体、关系、社区与 wiki 总目仍不存在，产品核心亮点（知识图谱 + LLM wiki）
尚未落地。本阶段把 chunk 事实层加工为可重建的知识图谱与总目条目，为 Phase 4 的
图谱 API 与对话检索提供结构底座。

## What Changes

- 新增 `src/siku/graph/` 与 `src/siku/wiki/` 两个领域包：从检索 chunk 事实层抽取
  实体/关系，构建内存图并落 parquet，社区发现后生成 wiki 总目条目。
- 定义项目自有的图谱抽取器协议 `GraphExtractor`，LLM 强模型经可插拔后端接入
  （默认 DeepSeek 兼容端点，BYO key），graphify 的方法复用而不绑定其实现（ADR-0005）。
- 抽取缓存：以（chunk_hash, 抽取器/模型标识, prompt 版本）为键缓存 LLM 抽取产物，
  源与模型未变不重抽——保证「全量重跑幂等（重建结果 diff 为空）」闸门可达成
  （宪法红线 3）。
- 图谱本体落 parquet（entities/relations/communities 三件），内存图用 NetworkX
  （ADR-0003，10⁵ 边级才换 igraph）；不引入任何 server 形态图数据库。
- 社区发现 + 社区摘要 + wiki 总目条目生成，全部产物带 chunk/来源锚点可回链。
- 新增 CLI：`siku graph`（构建图谱并输出量级体检报告）与 `siku wiki`（生成总目
  条目），支持 `--json` 稳定输出。
- 图谱体检报告：节点/边/社区数量与量级告警，作为 Phase 3 闸门证据之一。

## 受影响决策

- ADR-0003：图谱为内存图（NetworkX）+ parquet 落盘，不引入独立图数据库。
- ADR-0005：chunk/entity/edge/community 持久化 schema 由本项目定义（SQLite 缓存 +
  parquet 本体）；抽取引擎一律经 `GraphExtractor` 协议作可插拔后端；AGPL 引擎若
  出现只准子进程隔离。
- ADR-0006：图谱抽取用 API 强模型（BYO key，graphify + DeepSeek 已验证）；问答
  LLM 与图谱抽取共用的 provider 通道在本阶段定型为 openai 兼容协议。

## 与项目亮点的关系

图谱与 wiki 是 siku 的核心产品亮点，本 change 正是其落地阶段；Phase 2 已备好的
稳定 chunk、`source_hash` 溯源与来源锚点被完整复用。检索主通道不因图谱引入而
改变（图谱检索通道按 ADR-0006 属按需叠加，非本阶段范围）。

以下能力为明确延期或后续路线，不是从项目中删除：

| 能力 | 本 change | 后续归属 |
|---|---|---|
| 图谱检索通道（按图遍历召回） | 不实现 | Phase 4 按需叠加，主检索通道仍是混合召回 |
| HTTP API 与 WebUI 图视图 | 不实现 | Phase 4：先冻结契约再接 UI |
| 实体消歧/融合（跨文档同名实体合并策略） | 仅做同名合并的基础版 | 质量问题沉淀后按需另开 change |
| 多语言抽取、增量图谱更新 | 不实现 | Backlog（当前全量重建已够快） |

## 本 change 不实现（Deferred，不是产品删项）

- 不实现图谱检索/图遍历问答通道，不改动 Phase 2 已定档的混合召回行为与
  retrieval spec；golden set 回归门禁继续约束检索侧。
- 不实现 HTTP API、WebUI、Tauri 壳与对话编排（Phase 4 及以后）。
- 不引入任何图数据库、向量库之外的新存储形态；图谱本体只用 parquet，缓存只用
  SQLite（ADR-0003 三件套边界内）。
- 不做实体消歧的语义级融合（嵌入相似度合并、跨语言对齐等），同名合并仅做
  大小写/空白归一的基础版并在体检报告中暴露同名实体数量。
- 不做模型训练/微调；LLM 只经 API 调用（BYO key），CI 永不调用真实 API，测试
  只使用可编程 fake provider（正常/超长/空返回/限流/断连五剧本）。
- 不修改 `vault/` 中的原件与 Markdown 事实层；图谱/wiki/缓存皆为派生物，支持
  全量删除后重建。
