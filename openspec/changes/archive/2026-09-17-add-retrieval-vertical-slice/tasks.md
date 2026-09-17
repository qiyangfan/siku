# 任务清单

- [x] 先写检索领域模型、块身份、索引报告和搜索结果的失败测试，再实现 `retrieve` 包的
      类型与协议；任务粒度 ≤ 2 小时。
- [x] 先写 Markdown frontmatter/结构块解析与异常场景测试，再实现从 Phase 1 投影生成
      `DocumentRecord`/`ChunkRecord` 的解析器。
- [x] 先写中文、英文、数字、型号、标点和空白归一化的表驱动测试，再实现确定性
      tokenizer，并确认 FTS5 能力检查与用户可读错误。
- [x] 先写 SQLite WAL、schema 版本、参数化查询和 FTS5 BM25 召回测试，再实现
      `IndexStore` 的文档/块/全文表。
- [x] 先写 source_hash 未变化跳过、变化替换、旧块清理、全量重建失败保留旧版本的测试，
      再实现 manifest 同步与版本切换。
- [x] 先写 embedding/reranker provider 的正常、空返回、超长文本、模型错误 fake 测试，
      再实现领域协议、配置校验与本地模型适配器的延迟导入。
- [x] 先写向量维度、模型 revision、重复 chunk_id 和 provider 失败时不暴露半成品的测试，
      再实现嵌入式向量存储与 SQLite/向量索引一致性处理。
- [x] 先写 BM25/向量候选交集、差集、空候选、同分稳定排序的测试，再实现 RRF 融合、
      reranker 重排和带锚点的 `SearchResult`。
- [x] 先写 `siku index`、`siku search` 的 CLI runner 测试，再接入人类可读输出、JSON 输出、
      参数校验和缺索引/缺模型/无命中错误路径。
- [x] 建立至少 24 条版本化 golden set fixture，覆盖中文术语、英文/数字型号、跨结构块、
      同义表达、混合召回与无结果场景，并为每条保留标注理由。
- [x] 先写 Recall@5、MRR@10、逐题命中和基线比较的失败测试，再实现
      `siku evaluate-retrieval` 与不可覆盖旧基线的回归门禁。
- [x] 在 retrieval optional extra 中加入并锁定本地模型/向量运行时的兼容依赖；验证核心
      安装不导入重依赖，缺依赖时给出安装方向。
- [x] 使用 Phase 1 真实 PDF/DOCX/PPTX/XLSX 投影执行一次索引与查询冒烟，确认来源路径、
      source_hash 和 page/slide/sheet anchor 全部可返回。
- [x] 运行 golden set 本地质量评测并提交 baseline v0；记录模型标识、revision、tokenizer、
      参数、指标和运行环境，禁止用未说明原因的新分数覆盖旧基线。
- [x] 运行 `uv run pytest`、`uv run ruff check .`、`uv run ruff format --check .`、
      `uv run mypy`、`uv run pre-commit run --all-files` 与 OpenSpec strict 校验，完成独立
      review.md 后才允许归档并同步 retrieval spec。
