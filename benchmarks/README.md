# benchmarks/ — 检索质量基准

golden set 与基线快照是检索链路的**可执行规格**（ADR-0006）：任何改动检索链路的
change（切块/embedding/召回/重排/参数）必须重跑评测并通过基线门禁，未跑不得合入。

## 布局

```text
benchmarks/
  corpus/                  # 基准语料（入库）：PDF/DOCX/PPTX/XLSX 各一 + 生成脚本
  golden-set-v0.jsonl      # golden set v0（入库）：27 条问题-期望来源标注对
  retrieval-baseline-v0.json  # 基线快照 v0（入库）：评测分数 + 模型/参数/环境元数据
  vault/                   # 派生：语料投影（gitignore）
  data/                    # 派生：检索索引（gitignore）
```

## 复现评测

```bash
uv sync --all-extras                      # 检索模型与向量运行时在 extras 里
uv run siku ingest benchmarks/corpus --vault benchmarks/vault
uv run siku index --vault benchmarks/vault --data-dir benchmarks/data
# 首次生成基线（文件已存在时换新版本号，绝不覆盖旧基线）：
uv run siku evaluate-retrieval \
  --golden-set benchmarks/golden-set-v0.jsonl \
  --data-dir benchmarks/data \
  --save-baseline benchmarks/retrieval-baseline-v0.json
# 回归门禁（默认对比 data/retrieval-baseline.json，用 --baseline 指向入库基线）：
uv run siku evaluate-retrieval \
  --golden-set benchmarks/golden-set-v0.jsonl \
  --data-dir benchmarks/data \
  --baseline benchmarks/retrieval-baseline-v0.json
```

## 标注语义

- 每条用例含稳定 `id`、`query`、`expected`（允许的多个正确来源）、`note`（标注理由）。
- **来源用 `source_name`（原件文件名）而非 `source_id` 标注**：`source_id` 由原件
  绝对路径派生，跨机器不稳定；文件名在单语料目录内稳定且可读。
- `anchor` 为 null 表示该来源任意结构块命中即可；否则必须命中指定锚点
  （`page:N` / `slide:N` / `sheet:名` / 章节名 / `content`）。
- **空结果用例（`expected: []`）判定语义**：语料中不存在相关信息，全文（BM25）
  通道必须零命中；向量通道的近邻噪声不计为命中（无阈值 KNN 总会返回近邻，
  若计入则空题永远失败，门禁失去区分度）。
- 指标：`Recall@5`（期望来源在 top5 的覆盖比例，多期望按比例计分）、
  `MRR@10`（首个相关结果排名的倒数）；任一指标低于基线即门禁失败。

## 改基线须知

基线快照记录 fixture 的 SHA-256、模型标识/revision、tokenizer 版本、检索参数与
运行环境。改标注必须连同理由一起提交并生成**新版本文件**（如
`retrieval-baseline-v1.json`），禁止覆盖旧基线——旧分数是历史证据链。
