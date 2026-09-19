# benchmarks/ — 检索质量基准

golden set 与基线快照是检索链路的**可执行规格**（ADR-0006/0009）：任何改动检索链路的
change（切块/embedding/召回/重排/参数）必须重跑评测并通过基线门禁，未跑不得合入。
基线按**模型通道**保存：每个通道一份快照，闸门语义不变（同通道不低于基线即通过）。

## 布局

```text
benchmarks/
  corpus/                  # 基准语料（入库）：PDF/DOCX/PPTX/XLSX 各一 + 生成脚本
  golden-set-v0.jsonl      # golden set v0（入库）：27 条问题-期望来源标注对
  retrieval-baseline-v0.json  # 历史记录（进程内 bge 时代的 v0 基线，不再参与比较）
  baselines/{channel}.json    # 通道基线（入库）：如 local-bge-m3.json
  vault/                   # 派生：语料投影（gitignore）
  data/                    # 派生：检索索引（gitignore）
```

## 复现评测（BYOK：先配置 embedding/rerank 端点）

```bash
uv sync                                   # 核心依赖即可；模型经端点供给（ADR-0009）
uv run siku ingest benchmarks/corpus --vault benchmarks/vault
# 首次生成某通道基线（文件已存在时换新通道/版本号，绝不覆盖旧基线）：
uv run siku evaluate-retrieval \
  --golden-set benchmarks/golden-set-v0.jsonl \
  --data-dir benchmarks/data \
  --embedding-base-url http://127.0.0.1:11434/v1 --embedding-model bge-m3 \
  --channel local-bge-m3 \
  --save-baseline benchmarks/baselines/local-bge-m3.json
# 回归门禁（默认对比 benchmarks/baselines/{通道}.json，可用 --baseline 覆盖）：
uv run siku evaluate-retrieval \
  --golden-set benchmarks/golden-set-v0.jsonl \
  --data-dir benchmarks/data \
  --embedding-base-url http://127.0.0.1:11434/v1 --embedding-model bge-m3 \
  --channel local-bge-m3
```

`--reranker api --rerank-* ...` 启用重排通道；`--reranker none` 或未配置 rerank
端点时按 RRF-only 评测（provider_kind 记为 `rerank-none`）。评测报告的 config 段
记录通道身份（provider_kind、模型、端点主机——不含凭证），跨通道分数不可比。
rerank=none vs rerank 的增量由双通道基线分数对比呈现。

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
