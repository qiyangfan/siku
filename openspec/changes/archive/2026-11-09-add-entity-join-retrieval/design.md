# 设计：实体 join 检索通道——SAG 式查询时动态超边

## 当前证据与单一结论

图谱合并产物 `Entity.anchors` 已携带 `SourceAnchor(chunk_id, source_hash, note_path,
anchor)`（`graph/models.py`），检索索引 `SqliteIndex.get_chunks` 可按 `chunk_id` 批量
取回正文（`retrieve/store.py`）——join 所需的正反向邻接（实体 → chunk、chunk → 实体）
都可由这两份既有派生物在内存中派生，**不需要任何新表、新索引或新抽取**。决策依据、
消融证据与被否选项见 ADR-0015，此处不重复。

## D1：模块形态与数据流

新模块 `src/siku/retrieve/entity_join.py`（包名按领域切，落 retrieve 因输出是检索块
语义；图谱侧只消费其既有只读加载器，不新增 graph 职责）：

```
查询串 ──种子解析──▶ 种子实体集（entity_id, name, 歧义标记）
         │                     │
         │            实体锚点 join（entities.parquet）
         │                     ▼
         │            种子 chunk 集 S
         │                     │
         │            frontier = S 内 chunk 共现的非种子实体
         │                     ▼
         │            桥接 chunk 集 = frontier 锚点 − S   （H=1，固定）
         ▼                     ▼
   SqliteIndex.get_chunks ◀── 打分排序 + chunk_id 去重 + 缺失过滤
```

- 图谱数据经既有 `load_graph` 只读加载（与 `graph_neighbors` 同源，不建第二份加载）；
  chunk 正文经 `SqliteIndex.open_if_exists` 读取。索引缺失按"先建索引"指引失败；
  图谱未构建按"先构建图谱"指引失败——两者都走既有归一化错误映射，不新写文案。
- **纯函数内核**：种子解析、join 扩展、打分均为无 IO 纯函数，IO 只在装配层——
  全程可表驱动 fake，CI 永不打真实 API。

## D2：种子解析（确定性）

- 匹配规则：实体名（合并后 `name`）经 casefold 后作为子串在查询串中查找；命中按
  名称长度降序取前 N（长名更具体，抑制短名误命中），种子数上限 8。
- 同名歧义：`ambiguous_entity_names` 名单内的命中，按合并后 `entity_id` 逐实体返回
  并保留歧义标记，不静默合并。
- 空结果分型（沿用 SAG 可审计链哲学）：`seed_miss`（查询串无任何实体命中）与
  `expansion_empty`（有种子但零跳与一跳均无 chunk）是**正常空结果**而非错误，分型
  原因与定位建议（"先用 graph_search 定位实体名"）随结果返回。

## D3：join 扩展与打分（H=1 固定）

- 种子 chunk：种子实体全部锚点的 `chunk_id` 去重集合 S。
- frontier：锚点 `chunk_id ∈ S` 的非种子实体（frontier 实体数上限 50——对应 SAG 的
  剪枝预算；其自述局限是固定预算截断低频桥接实体，本项目以"frontier 实体与种子的
  共现 chunk 数"排序后截断，把预算给连接密度最高者）。
- 桥接 chunk：frontier 实体锚点 `chunk_id − S`，上限与返回上限一致。
- 打分：种子 chunk 按"命中种子实体数"降序、桥接 chunk 按"贡献的 frontier 实体连接
  数"降序；同分按 `chunk_id` 字典序保证确定性。无向量、无 BM25 参与——本通道的价值
  恰是独立于两路召回的第三信号。
- 时点错位：`chunk_id` 在索引中不存在时过滤并计数，随结果如实返回
  `skipped_missing_chunks`，不报错、不补偿（自动维护归 graph-auto-refresh 开关）。
- 结果条目复用 `SearchResult` 形态（来源名/路径/锚点/正文/分数）另附实体溯源
  （种子实体名 / 桥接实体名），保证与既有检索消费端同构。

## D4：MCP 工具 `entity_evidence`

- 入参：`query`（必填）、`limit?`（缺省与服务端有界缺省一致）。不提供 `hop` 参数：
  H=1 固定（SAG 消融 H=1 为默认最优；参数化是预建抽象）。
- 出参：`results`（带溯源）、`seed_entities`（命中种子清单）、`bridge_entities` 计数、
  `skipped_missing_chunks`、`truncated` + 总量线索、空结果分型 `empty_reason`。
- 错误口径：图谱未构建 / 索引缺失 → 既有"派生物未构建"归一化指引（同 `graph_*`
  工具面），不出现堆栈；工具描述写明建议先用 `graph_search` 定位、再用本工具取证据、
  `read_document` 读全文的组合用法。
- 命名与既有工具一致用动宾短名，客户端展示为 `siku.entity_evidence`。

## D5：多跳评测集与门禁

- 评测集：中文「问题 + 桥接证据 chunk 标注对」，先以合成语料构建（桥接结构可控、
  断言可定位），结构上覆盖：单文档共现 / 跨文档经第三实体桥接 / 歧义名干扰三类；
  规模 15~30 对（ADR-0006 纪律：小而真，随真实失败案例沉淀增长）。fixture 入
  `tests/`，与 golden 文件同款管理（变更须连同理由提交）。
- 对照口径：同一问题集上比较 (a) 纯混合召回（既有 `SearchService`）与 (b) join 通道
  的桥接证据命中（Recall@K），数字如实记录进 review.md——**这是中文效果的验证方式**
  （ADR-0015 风险条款），不预设达标阈值；若 join 不优于混合，通道保持 MCP 工具面
  定位并在 review.md 记录结论，后续升级路径照复核信号走。
- 测试（假上游设施，CI 零真实 API）：种子解析表驱动（命中/歧义/大小写/空）；join
  纯函数表驱动（零跳/桥接/去重/截断/时点错位过滤）；工具层进程内直调 + 协议层子进程
  stdio 断言 `tools/list` 八工具与一次真实往返（沿用 mcp-server 既有测试基建）。
- 验证门禁：全量 pytest、ruff、`openspec validate --changes --strict`；既有七个工具
  与 golden set 行为不变（不跑混合召回回归——本件不触碰其链路）。

## 上游依据

- [SAG: SQL-Retrieval Augmented Generation with Query-Time Dynamic Hyperedges
  (arXiv:2606.15971)](https://arxiv.org/abs/2606.15971)——方法、消融数字与局限，
  论证见 ADR-0015。
- ADR-0015（本件决策）、ADR-0005（数据主权/可插拔后端）、ADR-0006（golden set 门禁
  边界：主链路不变故不触发）、ADR-0014（MCP 接入面）。
