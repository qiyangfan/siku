# 设计：Phase 2 检索纵切面

## 边界与事实源

检索模块位于 `src/siku/retrieve/`，只读 Phase 1 生成的 `vault/notes/`，不依赖 UI、HTTP
或图谱模块。图谱与 wiki 仍是 Phase 3 的核心产品能力；本阶段只提供它们可复用的稳定
chunk、来源锚点和质量基线，不提前实现图谱/wiki 管线。`vault/` 不写入任何索引数据；
索引和评测结果是可删除、可全量重建的派生物。

默认派生目录为 `data/`，布局固定为：

```text
data/
  retrieval.sqlite3       # 文档、块、FTS5 与索引元数据
  vectors/                # 嵌入式向量表
  retrieval-baseline.json # evaluate-retrieval 生成的基线快照
```

CLI 允许通过 `--data-dir` 覆盖默认目录。索引同步不得修改 `vault/`，失败时不得把半成品
作为可用索引暴露给查询。

## Markdown 投影到检索块

1. 读取 frontmatter 的 `source_id`、`source_hash`、`source_name`、`extractor`；缺失或
   不符合格式的必需字段视为用户可读的索引错误，不静默吞掉。
2. 以每个 `## <anchor>` 区块作为一个结构块，忽略空块；没有二级标题时将正文作为一个
   `content` 块。不得用固定 token 窗口切断 Phase 1 的结构边界。
3. `ChunkRecord` 至少包含 `chunk_id`、`source_id`、`source_hash`、`source_name`、
   `note_path`、`anchor`、`ordinal` 与 `text`。`chunk_id` 由稳定字段和规范化正文的
   SHA-256 派生，不含当前时间。
4. 同一 `source_id` 的 hash 未变化时跳过解析、分词和 embedding；hash 变化时只替换该
   来源的全部旧块及向量。全量同步以当前 notes 清单为准，删除索引中不再存在的派生块，
   但绝不删除 vault 文件。

## SQLite 与中文全文检索

- SQLite 连接启动时启用 WAL；所有 SQL 使用参数绑定。
- 普通表保存 `documents`、`chunks`、`index_meta`；FTS5 表保存 `chunk_id` 与预分词
  文本，并通过 `chunk_id` 回表取得完整元数据。
- 中文内容与查询统一经过同一个 tokenizer：中文按可检索词切分，英文、数字、型号和
  连字符序列保留为可检索 token，标点与多余空白归一化后以空格写入 FTS5。禁止把原始
  连续中文直接交给裸 FTS5。
- FTS5 命中按 BM25 得分排序；无命中不是错误，返回空候选。
- schema 版本写入 `index_meta`。不兼容迁移拒绝启动并给出重建提示，不自动猜测迁移。

## 向量、provider 与模型隔离

- 向量表保存 `chunk_id`、`source_hash`、模型标识、维度、向量和必要的来源元数据；
  SQLite 的 chunk 记录仍是返回结果的权威元数据。
- embedding 与 reranker 通过项目自有的 provider 协议注入，领域层不暴露第三方模型对象。
  测试使用正常、空返回、超长文本、模型错误五种可编程 fake 剧本。
- 本地适配器延迟导入模型运行时；默认配置使用 ADR-0006 约定的 bge-m3 embedding 与
  bge-reranker 系列模型。缺少 optional extra、模型文件或维度不一致时，CLI 返回安装、
  下载/配置方向明确的中文错误，不静默降级为另一种排序。
- 模型标识、模型 revision、tokenizer 版本和向量维度进入索引元数据；查询发现配置与
  已建索引不一致时拒绝混用，要求显式重建。

## 索引同步与一致性

`IndexStore` 是 SQLite、FTS5 与向量表的唯一写入口。同步分为扫描、构建 manifest、写入
临时结果、切换可用版本四步：

1. 扫描并校验所有 notes，生成按 `source_id/chunk_id` 排序的 manifest。
2. 对未变化块复用已有向量，对新增或 hash 变化的块调用 embedding provider。
3. 在临时 SQLite/向量结果中完成全量校验，校验内容包括块数、hash、模型标识、向量维度
   与唯一性。
4. 校验成功后切换索引版本；任一步失败都保留旧版本可查询，并清理临时结果。

`siku index` 默认执行同步；`--rebuild` 忽略旧派生数据，从 notes 全量生成新版本。命令
报告 `created/updated/skipped/removed` 计数以及当前索引版本，但不把路径、hash 或模型
细节写进不稳定的自然语言文本之外；`--json` 输出稳定字段。

## 混合召回与重排

`SearchService.search(query, options)` 执行以下固定顺序：

1. 对 query 同时执行预分词 BM25 检索和 embedding 向量检索，各取 `candidate_k`。
2. 对候选集合做等权 Reciprocal Rank Fusion，默认 `rrf_k=60`；相同候选只保留一条。
3. 将融合后的候选交给 reranker，默认取前 `candidate_k`；最终按 reranker 分数、融合分数、
   `chunk_id` 升序做稳定排序，返回前 `top_k`。
4. 每个结果必须带 `chunk_id`、来源名称、相对 note 路径、`source_hash`、结构锚点、正文、
   `bm25_score`、`vector_score`、`hybrid_score` 与 `rerank_score`，使调用者可以跳回
   `vault/attachments/` 的原件定位信息。

默认参数为 `top_k=10`、`candidate_k=50`；CLI 可覆盖，但不得改变排序阶段顺序。空 query
是用户输入错误；合法但无命中的 query 返回空结果并以成功状态退出。

## CLI 入口

```text
siku index [--vault VAULT] [--data-dir DATA_DIR] [--rebuild] [--json]
siku search QUERY [--vault VAULT] [--data-dir DATA_DIR] [--top-k N]
           [--candidate-k N] [--json]
siku evaluate-retrieval --golden-set PATH [--vault VAULT] [--data-dir DATA_DIR]
                        [--baseline PATH] [--json]
```

`search` 只读当前可用索引；未建立索引、模型配置不一致或索引版本损坏时失败并提示先
执行 `siku index` 或 `--rebuild`。CLI 用户文案为简体中文，日志文本为英文。

## Golden set v0 与回归

- fixture 使用 JSONL 保存至少 24 个问题，每条包含稳定 id、query、期望 `source_id`/锚点、
  允许的多个正确来源和标注说明，覆盖中文短语、英文/数字型号、跨块定位、同义表达、
  空结果和混合召回场景。
- 评测至少报告 `Recall@5`、`MRR@10` 和每条样例的命中来源；基线快照同时保存 fixture
  版本、模型标识/revision、tokenizer 版本、top_k/candidate_k/rrf_k 与分数。
- `evaluate-retrieval` 默认对比已提交基线：分数低于基线即失败，分数相同或提升才通过；
  需要重标注时必须显式生成新版本并在提交中说明原因，不能覆盖旧基线。
- CI 不下载或调用真实模型/API。测试通过 fake provider 验证索引、排序、指标和回归门禁；
  本地质量基线在安装 retrieval extra 且模型可用时执行并保存结果。

## 验证策略

先写失败测试，再按领域模型、tokenizer、存储、provider、排序和 CLI 分层实现。除单元测试
外，使用 Phase 1 生成的 PDF/DOCX/PPTX/XLSX 最小投影做一次真实索引与搜索冒烟，确认四类
来源都能返回结构锚点；最终运行 pytest、ruff、mypy、pre-commit、OpenSpec strict，并记录
golden set 基线证据。
