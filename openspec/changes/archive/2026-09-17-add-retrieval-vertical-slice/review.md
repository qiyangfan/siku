# Review：add-retrieval-vertical-slice

- **评审方式**：独立子代理全量评审（只读），覆盖全部未提交变更（`src/siku/retrieve/` 12 模块、
  tests 10 文件、benchmarks、pyproject、cli.py、.gitignore、uv.lock）。
- **评审时间**：2026-09-17
- **评审时验证**：pytest 全绿、ruff check / format 全过、mypy 无问题、openspec strict 双过；
  FTS5 注入面与 notes_reader 边界由评审代理实测。

## 发现与整改

| 级别 | 位置 | 问题 | 处置 |
|---|---|---|---|
| P1 | service.py | 查询路径 tokenizer 版本校验传了 `stored.tokenizer_version` 自比自，恒真；分词方案升级后 search 会用新分词器查旧索引且无报错 | 已修：改传当前 `TOKENIZER_VERSION`；补 tokenizer 漂移拒绝查询的测试 |
| P1 | vector_store.py | 缺 retrieval extra 时 `import lancedb/pyarrow` 裸抛 ImportError，CLI 层只捕 RetrievalError → 用户看到 traceback 而非安装指引 | 已修：`_import_lancedb/_import_pyarrow` 包装为 `ModelNotAvailableError`（含 `uv sync --extra retrieval` 指引）；isolation 探针补 create/open 两路径 |
| P2 | indexer.py | rebuild/首建路径不清旧库 `-wal/-shm` sidecar，残留 WAL 帧可污染换入的新库 | 已修：切换前无条件 unlink sidecar |
| P2 | design.md vs 实现 | 版本切换（向量目录+SQLite 两次 replace）非严格原子，窗口内崩溃会退化为"可检出、需重建"而非"旧版本仍可查" | 记档：见下文【有意偏离】#4；凭证标记保证损坏必被检出（`vectors_commit` 互检），恢复路径 `--rebuild` 明确 |
| P2 | notes_reader.py | H1 剥离对真实 Phase 1 投影失效（frontmatter 后总有空行，`body_lines[0]` 是空行），H1 标记混入正文/embedding | 已修：剥 H1 前跳过起始空行；补对应测试 |
| P2 | cli.py | NoteParseError/ProviderError/FtsUnavailableError/GoldenSetError/EvaluationError 五类走英文兜底，违反"CLI 简体中文文案" | 已修：五类全部补中文映射（细节按错误双轨进日志） |
| P3 | service.py | 一次 search 两次打开索引（召回/回表），切换竞态下误报 IndexCorrupt | 已修：单会话覆盖召回+回表，消除 TOCTOU |
| P3 | indexer/store | 跨实例访问 `_connection` 私有属性 | 已修：新增 `SqliteIndex.fts_count()` 公开方法；`copy_sources_from` 为同类内受控访问，保留 |
| P3 | cli.py | `--save-baseline` 写盘 OSError 未捕获 | 已修：`save_baseline` 内转 `EvaluationError` |
| P3 | evaluation.py | 空结果题 token 匹配大小写敏感 | 已修：正文 `.lower()` 后比较 |
| P3 | local_models.py | 非默认模型加载前 `dimensions=0`（CLI 不受影响，公共 API 注意项） | 保留：记录为已知限制，Phase 3+ 按需收敛 |
| P3 | vector_store/indexer | `iter_rows` 全表物化；临时产物名固定不支持并发 `siku index` | 保留：proposal 已把并发列为非目标；个人语料量级可接受 |

## 有意偏离（评审确认合理，不属违规）

1. **golden set 用 `source_name` 而非 design.md 草图的 `source_id`**：`source_id` 由原件绝对
   路径 SHA 派生，跨机器不稳定；文件名单语料目录内稳定可读。
2. **空结果题判定语义**：语料不存在相关信息时，以"查询多字 token（CJK bigram/非 CJK
   token）不出现在 top 结果正文"为准，单字 unigram 与向量近邻噪声不计。无阈值 KNN 必返回
   近邻，若要求"检索返回空"则空题永远失败、门禁失去区分度。代码注释与 benchmarks/README
   双记录。
3. **search/evaluate-retrieval 未提供 `--vault`**：二者只读 `--data-dir` 索引，design.md CLI
   草图中的 `--vault` 无实际用途，不设死参数。
4. **版本切换两步写**：design.md"任一步失败都保留旧版本可查询"在两文件（向量目录 + SQLite）
   场景下收窄为"任一步失败旧版本保留（构建期）/ 崩溃残留必被凭证检出并可 `--rebuild` 恢复
   （切换窗口）"。单机单用户下这是工程合理收窄，若未来要求严格原子需引入单文件封装格式。
5. **LanceDB 同时进 dev 组与 retrieval extra**：dev/CI 用可编程 fake embedding 打真实 LanceDB
   存储（CI 不装 torch）；模型运行时（sentence-transformers/torch）锁定在 retrieval extra；
   核心安装零触碰由 isolation 探针验证。

## 结论

P1×2、P2×4 全部修复或记档，P3 修复 4 项、保留 2 项（均有非目标依据）。整改后全量门禁重跑：
pytest 181 项全绿、ruff/format/mypy/pre-commit/openspec strict 全过；真实模型 golden set 复跑
分数与 baseline v0 完全一致（Recall@5=1.0000，MRR@10=0.9568），回归门禁通过。

**达到归档标准。**

## 附：归档后评审循环整改记录（2026-09-17，第 1–4 轮）

归档后按「评审-修复」循环又执行了 4 轮全覆盖独立评审，缺陷收敛 12 → 5+1 → 4 → 1，
全部核实并修复；每轮均以真实模型复跑基线确认分数逐位一致（Recall@5=1.0000 /
MRR@10=0.9568）。要点：

- 第 1 轮（12 项，P2×3）：Recall@5 改按「被覆盖期望条目」计数（同期望多 chunk 命中
  不再膨胀指标）；`LocalEmbeddingProvider.dimensions` 改惰性 property（非默认模型不再
  以 0 维建库崩溃）；LanceVectorStore.open 表缺失改判 IndexCorruptError；sync 句柄
  泄漏/投影改名/批量向量追加/Unicode 读取/CLI 中文映射等。
- 第 2 轮（5 项，P2×1）：`_model_dimensions` 兼容层异常与 None 返回转 ProviderError；
  lance 引擎异常统一转 IndexBusyError（切换窗口瞬态可重试）；BaselineExistsError/
  FixtureMismatchError 细分 + 门禁前置 fixture 指纹校验；CLI 日志默认 WARNING、细节降
  DEBUG；逐题展示区分 PART。
- 第 3 轮（4 项）：损坏数值元数据转 IndexCorruptError；create_corpus 临时文件
  try/finally；iter_rows 行解析与查询同口径转域错误；SIKU_LOG_LEVEL 空串视为未设置。
- 第 4 轮（1 项 + 收尾）：SqliteIndex.open 增加核心表结构完整性校验（缺表判损坏）；
  SIKU_LOG_LEVEL/iter_rows/index_version 补回归测试；本记录与 HANDOFF 措辞修正；
  .gitignore 显式覆盖 benchmarks/data。
- 补充「有意偏离」：design.md 称 manifest 按 source_id/chunk_id 排序，实现按 note
  路径排序（分类逻辑不依赖排序，行为等价）；golden set 评测空题的指纹校验只比
  sha256，name/cases 仅入档供追溯。
- 最终门禁：pytest 202 全绿、ruff/mypy/pre-commit/openspec strict 全过、基线复验一致。
