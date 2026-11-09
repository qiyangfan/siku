## Why

混合召回（向量 + BM25 + 重排）存在结构性盲区：多跳问题的桥接证据与查询没有直接
词汇重叠，两路召回均覆盖不到；图谱检索面（`graph_search`/`graph_neighbors`）只返回
图结构，不返回原文证据，实体联动问答拿不到可引用出处。SAG 论文（arXiv:2606.15971，
论证与消融证据见 ADR-0015）证明「chunk ↔ 实体」确定性 join 是该盲区的针对性机制，
且本项目图谱抽取管线的实体锚点已携带 chunk 级 `chunk_id`（`SourceAnchor`）——所需
索引原材料已在 entities.parquet 中存在，只是从未被检索面消费。落地成本为零模型调用、
零 schema 变更、零新抽取；本项目定位学习/求职项目，明确有价值且成本可控即主动落地。

## What Changes

- 新增 `entity-join` 内核能力：实体 join 检索通道——查询串对实体名确定性解析种子 →
  一跳共现 join 扩展（种子实体锚点 chunk → 同 chunk 共现实体 → 共现实体的 chunk）→
  打分去重返回带来源锚点的证据 chunk，附实体溯源（种子/桥接）与可审计空结果分型
  （无种子命中/扩展为空）。纯确定性、零模型调用，只读图谱 parquet 与检索索引两份
  既有派生物；两派生物时点错位时过滤缺失 chunk 并如实报告跳过数。
- MCP 面新增第八个只读工具 `entity_evidence`（自由文本进、证据 chunk 出、有界截断、
  图谱未构建给构建指引），复用既有归一化错误映射与「服务端有界查询 + 截断明示」口径。
- 新建中文多跳评测集（「问题 + 桥接证据 chunk」标注对）作为本通道质量门禁，并在其上
  给出 join 通道 vs 纯混合召回的对照数字（中文效果当前无文献证据，以该评测集验证，
  结果如实记录）。
- 决策依据见 ADR-0015；主检索链路、golden set 口径、既有图谱/wiki 行为全部不变。

## Capabilities

### New Capabilities

- `entity-join`：实体 join 检索通道——确定性种子解析、一跳共现扩展、有界可溯源的
  证据返回、派生物缺失与时点错位的可审计口径、无独立状态可全量重建。

### Modified Capabilities

- `mcp-server`：只读工具从六个增至七个（新增 `entity_evidence`），工具面需求更名并
  增补该工具的溯源与分型空结果场景；其余需求不变。

## Impact

新增 `src/siku/retrieve/` 实体 join 检索模块与 `src/siku/mcp/` 工具接线；`tests/` 新增
通道测试（确定性路线，全程假上游/fixture，无真实 API）与多跳评测集；README 增补工具
用法示例。无依赖新增、无存储 schema 变更、无 UI 变更、无 vault/图谱构建路径变更。

## Non-goals（不做清单）

- 不接 `/api/ask` 主链路与 WebUI：集成是 ADR-0015 复核信号驱动的后续 change，届时
  必须过 ADR-0006 golden set 门禁。
- 不做 LLM query 实体抽取、LLM 事件改写、LLM 证据链重排、实体向量扩展（SAG 的
  Path A/事件层/重排层）：均为复核信号升级路径，首发保持零模型调用。
- 不做 H≥2 多跳扩展与 PageRank 类图传播。
- 不新增存储组件、不改索引 schema、不建独立提及表：`SourceAnchor.chunk_id` 已使
  entities.parquet 足以派生全部 join 关系。
- 不做自由 Text-to-SQL 查询面（ADR-0015 被否选项；表格域仍归 ADR-0004 DuckDB
  触发器管辖）。
- 不做 CLI 查询面：MCP 是本通道首发消费面，CLI 面后补另议。
- 不动 golden set 口径、混合召回行为、图谱/wiki 构建路径与既有六个只读工具契约。
