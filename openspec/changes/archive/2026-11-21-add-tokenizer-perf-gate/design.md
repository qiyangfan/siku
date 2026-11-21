# 设计：分词瓶颈的可执行门禁、候选方案与语义等价策略

## Context

- 分词实现：`src/siku/retrieve/tokenizer.py`（`cjk-uni-bigram-v1`）。中文连续汉字
  同时产出单字与相邻二元；英文/数字/型号整体保留并转小写；NFKC 归一化后空白折叠。
  模块 docstring 已写明："若 bigram 成为瓶颈，再按 ROADMAP 触发器重选"。
- 索引写入：`src/siku/retrieve/indexer.py` 逐 chunk 调 `tokenize` 后写
  `chunks_fts`；`src/siku/retrieve/store.py` 建表为
  `fts5(chunk_id UNINDEXED, tokens, tokenize='unicode61')`，FTS 查询走 BM25。
- 查询路径同样经过 `tokenize_query`/`build_fts_match`，必须与索引侧同源。
- 质量门禁：`benchmarks/README.md` 规定任何检索链路改动必须重跑 golden set；
  语料与基线按模型通道保存。
- 桌面分发：`scripts/build_sidecar.py` + `scripts/siku-sidecar.spec`（PyInstaller
  onedir），sidecar 随 Tauri 壳分发；原生扩展会影响收集、体积与签名。
- 触发器：`docs/ROADMAP.md` 触发器台账「中文分词成为检索瓶颈 → 重开 FTS5 分词器选型」。

## Goals / Non-Goals

- 目标：把"分词是否瓶颈"变成可复现、可裁决的数字；用最小代价拿收益；语义零漂移。
- 不做：见 proposal.md Non-goals。设计层额外排除——不为了凑指标改变 token 定义、
  不把网络等待算进收益、不给测试开豁免。

## Decisions

### D1 测量口径与工具

新增 `scripts/bench_tokenizer.py`，只用标准库与现有依赖，离线可跑：

1. **微基准**：对固定语料（`benchmarks/corpus` 的 Markdown 投影 + 合成 10MB 中文
   文本）反复执行 `tokenize()`，输出吞吐（MB/s、tokens/s）与 P50/P95；
2. **分段基准**：对同一批 note 依次测 `read_note` 解析、`tokenize`、
   `SqliteIndex` FTS 写入三段耗时（临时目录，不接 embedding），输出占比表；
3. 结果写 `benchmarks/perf/tokenizer-baseline-<machine>.json`（入库）并在
   `benchmarks/perf/README.md` 记录机器、复现命令与口径。

收益口径只认**本地 CPU**：embedding/rerank 是网络调用，不计入分母。

### D2 门禁阈值（提议，M0 评审时由 owner 签核）

| 门槛 | 判定 | 达标后 | 不达标时 |
|---|---|---|---|
| G1 痛点成立 | tokenize 占"非 embedding 索引 CPU" ≥ 20%，且 10MB 中文吞吐 < 15 MB/s | 进入 M1 | 结论"非瓶颈"，归档本 change |
| G2 纯 Python 优化 | M1 后吞吐 ≥ 2× 基线，且非 embedding 索引墙钟 ≥ 10% 改善 | 收工，不进 M1b/M2 | 进入 M1b |
| G2b 编译型 Python | M1b 后吞吐 ≥ 3× 基线，且墙钟 ≥ 15% 改善 | 收工，不进 M2 | 仍 < 2× 或构建不可行 → 评估 M2；介于两档之间 → owner 裁决 |
| G3 Rust PoC 达标 | token 流与 v1 **零差异**；吞吐 ≥ 5× 基线；非 embedding 索引墙钟 ≥ 25% 改善；golden set Recall@5/MRR@10 不低于通道基线 | 进入 M3 | 不采纳，删除 PoC |
| G4 发布可行 | 三平台 sidecar 构建通过；PyInstaller 无缺失收集；单平台体积增量 ≤ 5MiB | 发布 | 不采纳或降级为可选外挂 |

阈值是**提议值**：M0 的基线数字出来后，在 review.md 里一次性确认或调整，避免
"先射箭再画靶"。

### D3 候选方案对比

| 方案 | 预期收益 | 成本 / 风险 | 结论 |
|---|---|---|---|
| A. 纯 Python 优化 | 中（去掉逐字符 `match`，改为批量扫描） | 零分发成本；语义须逐 token 对齐 | **M1 必做，先于一切原生方案** |
| A2. 编译型 Python（mypyc / Cython） | 中高（逐字符循环编译为 C；regex/unicodedata 调用仍是解释器边界） | 需构建钩子（hatch-mypyc/hatch-cython 或 setuptools mypycify，待验）；扩展按 CPython 小版本编译（非 abi3）；dev 双模式；无 Rust 工具链 | **M1b，M1 不足时先做** |
| B. PyO3 进程内扩展 | 高（原生字符扫描 + 归一化） | wheel/ABI 矩阵、PyInstaller 收集、签名与体积 | M2 主候选 |
| C. Rust sidecar（stdin/stdout 批量） | 高 | 进程/IPC、额外产物、错误传播复杂 | 备选；B 打包失败时评估 |
| D. 换 FTS5 分词器（trigram/ICU） | 中 | 改变 token 语义 → 版本升级 + 全量重建 + 质量重评 | 语义变化，非本件路径；另立 change |

A2 的意义：本件目标是用最小代价拿到性能，不是"必须用 Rust"。mypyc 随 mypy 已在 dev
依赖中，Cython 只多一个 C 编译器；若 M1b 达标即收工，不进入 Rust 路径。

D 与本件的"零语义漂移"目标冲突，若要做必须单独立项并重跑 golden set。

### D4 语义等价策略（Rust 方案的前置条件）

Rust 实现必须与 Python v1 逐 token 相等，风险点已识别：

- **NFKC**：Python 3.12 的 Unicode 数据版本与 Rust `unicode-normalization` 可能不同；
  跨版本字符需按实际差异裁决，不能假定一致。
- **空白折叠**：Python `re` 的 `\s` 与 Rust `char::is_whitespace` 集合存在差异。
- **小写折叠**：Python `str.lower()` 与 Rust `to_lowercase()` 在特殊字符（如 `İ`、
  `Σ`/`ς`）上可能不同。
- **边界规则**：token 尾字符剥离集合 `._/@-`、CJK 区间（含扩展 A 与兼容区）、
  ASCII token 起止条件必须逐条复刻。

验证：差分测试固定三方输入——① 全部基准语料；② 人工边界用例；③ 随机 fuzz
（≥10 万字符串，覆盖 CJK/全角/混合/极端标点）。任一差异即视为不达标；若必须
改变语义，则升级 `TOKENIZER_VERSION`、全量重建索引并重跑 golden set——那已不是
本 change 的范围，应拒绝而不是妥协。

A2（mypyc/Cython）理论上编译的是同一份 Python 语义，但仍须通过同一套差分测试：
构建钩子、类型收窄或 C 扩展边界都可能暴露隐藏的动态行为。

### D5 打包与分发

- 若走 B：`maturin` 构建 `abi3-py312` 扩展；**只作为可选依赖**，运行时可回退纯
  Python；首版只在桌面 sidecar 中内置，不承诺 PyPI 分发。
- 若走 A2：mypyc/Cython 产物同样是原生模块，`scripts/siku-sidecar.spec` 必须能收集；
  扩展按 CPython 小版本编译（非 abi3），桌面钉 3.12 时可控，但 CI 矩阵与构建钩子
  必须在 M1b 先验证（hatch-mypyc/hatch-cython 或 setuptools mypycify 的选型是开放问题）。
- `scripts/siku-sidecar.spec` 需显式收集扩展二进制（PyInstaller 静态分析可能漏掉
  条件导入）；三平台构建纳入既有 CI/release 矩阵（ADR-0008）。
- 体积与签名/公证影响作为 G4 门禁，不达标即放弃。

### D6 回退

- 运行时开关：`SIKU_TOKENIZER=python|native`（默认 native，导入失败自动回退）；
- 移除可选依赖即回到纯 Python，索引与查询格式不变，无需重建；
- M1 的 Python 优化以差分测试保证可回退到旧实现；
- M1b 试验若失败，删除构建钩子与编译配置，源码保持纯 Python 可运行。

## Risks

| 风险 | 影响 | 缓解 |
|---|---|---|
| 语义漂移导致检索质量变化 | 高 | D4 差分测试 + golden set 门禁；零差异是硬门槛（A2 同样适用） |
| mypyc/Cython 构建钩子与 uv/hatchling 不兼容 | 中 | M1b 先做构建验证；不可行则记录并直接评估 M2，不硬撑 |
| 原生扩展破坏 Windows/Linux 打包 | 高 | G4；B 失败则评估 C 或放弃 |
| 收益被网络等待淹没 | 中 | 收益只按本地 CPU 口径统计，明确用户可见场景 |
| 维护两套分词实现 | 中 | 只在 M2 达标的条件下保留；Python 实现为权威参照 |
| 无基线就上 Rust | 高 | G1/G2/G2b 门禁，M0 未过直接归档 |

## Open Questions

- A2 的构建钩子选型（hatch-mypyc / hatch-cython / setuptools mypycify）与 uv 模式下的
  editable 构建是否可用；编译模块的覆盖率与堆栈口径如何记录。
- 桌面渠道之外的安装方式（pip/uv）是否需要原生加速？默认不承诺，M3 ADR 决定。
- 5MiB/平台的体积上限是否可接受？需在 PoC 实测后由 owner 裁决。
