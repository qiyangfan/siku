# 任务清单

> 纪律：本 change 只走"测量 → 纯 Python → 编译型 Python → 原生方案"的顺序；
> 任一门槛不达标即停并归档。验证命令统一用
> `env -u NO_PROXY -u no_proxy uv run ...`（NO_PROXY 的 `[::1]` 会让 httpx 假红）。
> M0 完成前不写任何编译/原生代码。

## 1. M0 测量（现在可开工，不含功能改动）

- [x] 1.1 新建 `scripts/bench_tokenizer.py`：固定语料 + 合成中文，测 `tokenize()`
  吞吐（MB/s、tokens/s）与 P50/P95，输出 JSON——验证：可在干净虚拟环境离线跑通、
  重复三次结果波动 < 10%。
- [x] 1.2 加分段模式：对同一批 note 测 `read_note` 解析 / `tokenize` / FTS 写入三段
  耗时（临时目录、无 embedding），输出占比——验证：三段耗时之和与端到端墙钟偏差 < 15%。
- [x] 1.3 记录基线到 `benchmarks/perf/tokenizer-baseline-<machine>.json`，新增
  `benchmarks/perf/README.md`（机器信息、复现命令、口径）——验证：文件入库、命令可复现。
- [x] 1.4 按 G1 裁决并在本 change 的 `review.md` 落结论：达标则继续 2；不达标则
  "不改造"结案，归档本 change——验证：review.md 有数字与结论，无悬空分支。
  （G1 成立；阈值 20% / 15MB/s 由 owner 于 2026-11-21 签核，已进入 M1。）

## 2. M1 纯 Python 优化（仅 G1 通过）

- [x] 2.1 以批量扫描替代逐字符 `_CJK_RE.match`，保留现有归一化/大小写/尾字符规则
  ——验证：先写差分测试（对语料与边界用例逐 token 比对旧实现），再改实现，零差异。
- [x] 2.2 复测 1.1/1.2 基准并与基线对比，记录到 review.md——验证：按 G2 给出
  "收工"或"进入 M1b"的明确结论。（G2 未达：A/B 中位 1.97× < 2×，按 design 进入
  M1b；试验结果见 3.3。）

## 3. M1b 编译型 Python 试验（仅 G2 判定需要）

- [x] 3.1 构建钩子验证：在 hatch-mypyc / hatch-cython / setuptools mypycify 中选出
  与 uv + hatchling 可用的一种，临时构建出可导入的编译产物——验证：
  `uv run python -c "import siku.retrieve.tokenizer"` 走编译模块；构建失败则记录
  失败原因并评估另一钩子或 Cython，仍失败即判 M1b 不可行。
  （结论：mypyc 与 Cython 均通过临时 setuptools 构建产出可导入扩展；未推进 hatchling
  集成，G2b 未达标后无采纳需求；试验产物已清理。）
- [x] 3.2 编译 tokenizer 模块：纯 Python 源码保留为唯一权威与回退路径，编译产物仅作
  加速——验证：先写差分测试（全语料 + 边界用例逐 token 比对纯 Python 实现），零差异。
- [x] 3.3 复测 1.1/1.2 基准，按 G2b 裁决：收工 / 进 M2 / M1b 不可行——验证：数字与
  结论进 review.md；不达标时删除构建钩子与编译配置，源码回到纯 Python。
  （结论：mypyc 2.06×、Cython 2.12× < 3×；落在 2–3× owner 裁决区间，建议停在 M1。）

## 4. M2 Rust/PyO3 PoC（仅 G2b 判定需要）

> 状态（2026-11-21）：owner 最终裁决「停在 M1，不采纳 M2/M3」——4.1–4.4 不实施，
> 保持未勾选以如实记录。

- [ ] 4.1 建 `crates/siku-tokenizer`（maturin、abi3-py312），只在本机 wheel 验证，
  不加入核心依赖——验证：`uv pip install` 后 `import siku_tokenizer` 可用。
- [ ] 4.2 按 design.md D4 实现逐 token 等价（NFKC、空白、大小写、边界规则），
  逐条记录裁决——验证：差分测试 0 差异。
- [ ] 4.3 差分与 fuzz：全部基准语料 + 人工边界用例 + ≥10 万随机串，逐 token 相等
  ——验证：测试入库、可重复。
- [ ] 4.4 复测：吞吐 ≥ 5× 基线、非 embedding 索引墙钟 ≥ 25% 改善、`TOKENIZER_VERSION`
  保持不变——验证：数字进 review.md，未达门槛则删除 PoC 并归档"不采纳"。

## 5. M3 集成与发布（仅 G3 通过且 owner 签核）

> 状态（2026-11-21）：owner 最终裁决不采纳 M2/M3——5.1–5.5 不实施，本 change 以
> `--skip_specs` 归档；保持未勾选以如实记录。

- [ ] 5.1 新增 ADR（原生分词扩展的采纳理由、分发与回退），状态"已接受"
  ——验证：`openspec validate --all --strict` 通过。
- [ ] 5.2 可选依赖 + 运行时回退 + `SIKU_TOKENIZER` 开关；导入失败静默回退纯 Python
  ——验证：两种模式各跑全量测试。
- [ ] 5.3 sidecar/PyInstaller 收集扩展并纳入三平台 CI/release（ADR-0008），记录体积
  增量——验证：三平台构建绿，体积 ≤ 5MiB/平台（G4）。
- [ ] 5.4 检索质量回归：golden set Recall@5/MRR@10 不低于该通道基线
  ——验证：`benchmarks/README.md` 命令，报告进 review.md。
- [ ] 5.5 文档收尾：README/benchmarks/perf 说明、回退步骤；归档本 change
  ——验证：全量 pytest + ruff 绿，review.md 证据齐全。
