# perf — 分词与索引 CPU 基线

本目录服务于 `openspec/changes/2026-11-21-add-tokenizer-perf-gate`（M0），对应
`docs/ROADMAP.md` 触发器「中文分词成为检索瓶颈」。基线按机器标签保存，**不覆盖旧文件**；
换机器或换口径时新增一份。

## 口径

- **micro**：固定合成中文文本（中英混排），执行 `tokenize()`（含 NFKC 归一化），
  统计吞吐与分位数；
- **segments**：生产路径分段——`read_note` 解析 → `tokenize` → `SqliteIndex` 写入
  FTS（临时目录，无 embedding），取三段中位数与占比；insert 段含提交，自 2026-11-21
  第二轮起同时含 WAL 截断（M1/M1b 记录仅含提交，差值为亚毫秒级）
- 收益只看**本地 CPU**；embedding/rerank 是网络调用，不进入分母；
- 语料由确定性逻辑生成（相同参数得到相同文本），可用 `--notes-dir` 改测真实
  `vault/notes`。

## 复现

```bash
uv run python scripts/bench_tokenizer.py --repeat 5 \
  --output benchmarks/perf/tokenizer-baseline-darwin-arm64.json
```

参数：`--size-mb 10 --notes 120 --sections 8 --section-chars 500`（默认值）；
基线取 5 次重复的中位数（默认 repeat=3，机器噪声大时调高）。
复现命令会覆盖同名结果文件；要保留既有记录，请换 `--output` 路径。

输出 JSON 的 `schema` 字段标识结构版本：`v1` 只有墙钟耗时（M0 基线）；
`v2` 增加进程 CPU 耗时/占比（M1 起的对照结果）。M1/M1b 三个文件按实际结构补标为
`v2`，测量数值未改动。

## 基线：darwin-arm64（2026-11-21）

| 指标 | 值 |
|---|---|
| micro 语料 | 10.0 MB / 4,131,903 字符 / 5,244,566 tokens |
| tokenize 中位吞吐 | **12.77 MB/s** |
| tokenize P50 / P95 | 0.783 s / 0.809 s（10MB） |
| micro 稳定性（max/min−1） | 3.72% |
| segments：parse / tokenize / insert | 0.017 s / 0.096 s / 0.057 s |
| **tokenize 占非 embedding 索引 CPU** | **56.47%** |
| 分段之和 vs 端到端墙钟偏差 | 0.61%（< 15%） |
| segments 稳定性 | 4.85% |
| G1（share ≥20% 且吞吐 <15MB/s） | **成立** |

机器：macOS 26.6.2 / arm64 / 10 CPU；Python 3.12.13（Unicode 15.0.0）、
SQLite 3.53.1、tokenizer `cjk-uni-bigram-v1`。

## 判读

- 分词是本链路最大的本地 CPU 项（56%），且吞吐低于 G1 的 15MB/s 阈值 → 瓶颈成立；
- 后续先做 M1（纯 Python 优化），不足再做 M1b（mypyc/Cython），最后才评估 Rust；
  阈值与语义等价要求见 change 的 `design.md`；
- 判据变化或阈值签核结果回填到 change 的 `review.md`，不要只改本文件。

## M1 结果（2026-11-21）

实现：批量正则扫描 + ASCII 归一化快路径 + bigram 列表拼接；逐 token 与 v1 等价
（差分测试 8420 组短组合 + 16 万字符混合文本）。

同机 A/B（进程 CPU 口径；机器有外部负载时以 CPU 为准）：

| 指标 | 结果 |
|---|---|
| v1 vs 当前 CPU 倍率（三次） | 1.95× / 1.97× / 2.01×，中位 **1.97×** |
| tokenize 10MB CPU 吞吐 | 23.58 MB/s |
| segments CPU：parse / tokenize / insert | 0.020s / 0.057s / 0.059s（tokenize 占 41.8%） |
| 分段总 CPU 改善（推算） | ≈ 28% |

G2 要求吞吐 ≥ 2× 且墙钟 ≥ 10%；中位 1.97× 未达，按 `design.md` 进入 M1b。
复现：`uv run python scripts/bench_tokenizer.py --repeat 7 --compare-legacy \
  --output benchmarks/perf/tokenizer-m1-python-darwin-arm64.json`

## M1b 结果（2026-11-21）

| 实现 | tokenize 10MB CPU 吞吐 | v1 倍率 | tokenize CPU 占比 |
|---|---|---|---|
| M1 纯 Python | 23.58 MB/s | 1.97× | 41.8% |
| M1b mypyc | 25.39 MB/s | 2.06× | 41.8% |
| M1b Cython | 25.61 MB/s | 2.12× | 40.6% |

G2b 要求 ≥ 3×，两种编译方案均未达，落在 2–3× 的 owner 裁决区间（试验产物已清理，
仅保留结果 JSON）。数据文件：

- `tokenizer-m1b-mypyc-darwin-arm64.json`
- `tokenizer-m1b-cython-darwin-arm64.json`
