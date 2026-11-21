# 评审记录：2026-11-21-add-tokenizer-perf-gate

> propose 阶段（2026-11-21）。尚无实现与基准数据；M0 完成后在此回填数字与裁决，
> 未达 G1 即按"不改造"归档，不留下未执行的 M2/M3 代码。

## 当前状态

- [x] proposal / design / tasks 全件
- [x] M0 基准与基线入库（`benchmarks/perf/tokenizer-baseline-darwin-arm64.json`）
- [x] G1 阈值签核（owner 2026-11-21 确认 20% / 15MB/s）
- [x] M1 纯 Python 优化（批量扫描；差分测试零差异）
- [x] M1b 编译型 Python 试验（mypyc 2.06× / Cython 2.12×，未达 G2b 的 3×）
- [x] 结构门禁复核（2026-11-21）：`scripts/bench_tokenizer.py` 的两个 dataclass 触发
  pylint R0902（8/7、9/7），按 CI 同命令修复为 `NoteShape` 拆分 + 采样类去掉冗余字段，
  结构门禁 0 条；insert 段计时改为含提交与 WAL 截断（README 已同步口径）
- [x] 最终裁决（owner 2026-11-21）：停在 M1，不采纳 M2/M3；本 change 归档
  （`--skip_specs`）。M2 的 4.x / M3 的 5.x 记为不适用，不予实施。

## M0 基线（2026-11-21，darwin-arm64，repeat=5）

复现：`uv run python scripts/bench_tokenizer.py --repeat 5 --output benchmarks/perf/tokenizer-baseline-darwin-arm64.json`

| 指标 | 基线 | 目标 | 实测 |
|---|---|---|---|
| tokenize 吞吐（10MB 中文） | 待测 | G1：< 15 MB/s 才算瓶颈 | **12.77 MB/s**（P50 0.783s / P95 0.809s） |
| tokenize 占非 embedding 索引 CPU | 待测 | G1：≥ 20% | **56.47%**（parse 0.017s / tokenize 0.096s / insert 0.057s） |
| 分段之和 vs 端到端墙钟偏差 | 待测 | 任务 1.2：< 15% | **0.61%** |
| 非 embedding 索引墙钟 | 待测 | G3：≥ 25% 改善 | — |
| M1b 编译型 Python 吞吐 | 待测 | G2b：≥ 3× 基线 | — |
| golden set（对应通道） | 见 `benchmarks/baselines/` | 不低于基线 | 未触及检索行为，未跑 |

稳定性：micro 3.72%、segments 4.85%（均 < 10%）。机器：macOS 26.6.2 / arm64 /
10 CPU；Python 3.12.13（Unicode 15.0.0）、SQLite 3.53.1、`cjk-uni-bigram-v1`。

G1 两条件均成立（份额 56.47% ≥ 20%，吞吐 12.77 MB/s < 15 MB/s），阈值已签核。

## M1 纯 Python 优化（2026-11-21）

改动：`_SCAN_RE` 单次批量扫描（CJK 连续段与 ASCII token 两条分支）替代逐字符
`_CJK_RE.match`；`tokenize` 走 `_normalize_for_tokenize`（ASCII 快路径、仅 NFKC，
空白折叠对 token 流无影响）；bigram 用列表推导拼接。语义与 v1 逐 token 一致。

正确性证据：

- 差分测试：13 条人工边界 + 8420 条短组合（20 个边界字符 × 长度 1–3）+ 16 万字符
  长混合文本，与冻结 v1 参考实现逐 token 相等；
- `tests/test_retrieve_tokenizer.py`、service/store/sync 四套件 108 通过。

性能（同机 A/B，进程 CPU 口径；机器被外部 vitest 占用，墙钟不作判据）：

| 指标 | 结果 |
|---|---|
| v1 vs 当前 CPU 倍率（三次独立运行） | 1.95× / 1.97× / 2.01×，**中位 1.97×** |
| tokenize 10MB CPU 吞吐 | 23.58 MB/s（末次） |
| segments CPU：parse / tokenize / insert | 0.020s / 0.057s / 0.059s（tokenize 占 41.8%） |
| 分段总 CPU 改善（由 A/B 推算） | ≈ 28%（0.190s → 0.136s） |

**G2 裁决：未达**（要求吞吐 ≥ 2× 且墙钟 ≥ 10%；中位 1.97× < 2×，墙钟口径受负载
污染未采信，以 CPU 推算改善 28% 满足）。按 design.md 进入 M1b（编译型 Python），
M1 改动保留（语义零漂移、纯收益）。

## M1b 编译型 Python 试验（2026-11-21）

构建钩子：mypyc（随 mypy，已在 dev 依赖）与 Cython 均通过临时
`setuptools build_ext --inplace` 在 uv 环境下产出可导入扩展；未改
`pyproject.toml`/build-system，试验后删除全部 `.c`/`.so` 与临时 setup 文件。
hatchling 集成未推进——G2b 未达标，原生构建链只在采纳时才需要。

正确性：编译产物就地替换导入后，tokenize 差分测试全量通过（v1 参考逐 token 相等）。

性能（进程 CPU 口径，同机 A/B，repeat=7）：

| 实现 | tokenize 10MB CPU 吞吐 | v1 倍率 | tokenize CPU 占比 |
|---|---|---|---|
| M1 纯 Python | 23.58 MB/s | 1.97× | 41.8% |
| M1b mypyc | 25.39 MB/s | **2.06×** | 41.8% |
| M1b Cython | 25.61 MB/s | **2.12×** | 40.6% |

**G2b 裁决：未达**（要求 ≥ 3×）。结果落在 design.md 的「2–3× → owner 裁决」区间：
M1b 相对 M1 仅多 5–8%，却引入按平台/解释器版本的构建与打包成本（PyInstaller 收集、
签名/公证）；NFKC 约占 45%，编译 Python 循环无法消除这部分开销。

## 结论

**最终裁决（owner 2026-11-21）：停在 M1，不采纳 M2/M3，本 change 归档（`--skip_specs`）。**

依据：M0 / M1 完成；M1b 两种实现（mypyc 2.06×、Cython 2.12×）均未达 G2b 的 3×，
落在 design.md 的 2–3× owner 裁决带。M1 已把 tokenize 从 12.77 提至 23.58 MB/s
（1.97×），非 embedding 索引 CPU 中占比 56% → 42%；即便 M2 达到 G3 的 5×，该段总
CPU 最多再降约三成，而 120 篇 note 的 tokenize 仅 57ms，端到端大头是解析与
embedding 网络等待。对应代价是第二套分词实现、跨语言逐 token 等价、三平台打包与
永久维护。M2/M3 不在本轮实施，4.x / 5.x 维持未实施状态。

若大语料重建索引的本地耗时成为真实痛点，按 G3 门禁另开 change 重评，不改本结论。
