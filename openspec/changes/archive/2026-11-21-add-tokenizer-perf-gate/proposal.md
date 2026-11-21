# 提案：分词性能门禁与原生加速评估（Rust/PyO3 仅为候选）

## Why

检索索引的本地 CPU 成本里，分词是唯一还没有基线的环节：

- `src/siku/retrieve/tokenizer.py` 是纯 Python 逐字符扫描（每个字符一次
  `_CJK_RE.match` 调用）+ NFKC 归一化 + 小写折叠，索引与查询共用同一实现；
- `src/siku/retrieve/store.py` 的 FTS5 表只存预分词文本（`tokenize='unicode61'`），
  分词结果直接决定索引质量与构建耗时；
- embedding/rerank 走网络（ADR-0009），语料增长时"网络等待"之外的可优化部分
  集中在解析 → 分词 → FTS 写入这一段。

`docs/ROADMAP.md` 触发器台账已有「**中文分词成为检索瓶颈 → 重开 FTS5 分词器选型**」，
但没有可操作定义：什么算瓶颈、达到多少才动、动了如何证明语义不变。本件先把这个
触发器落成可执行门禁，再决定是否需要原生加速。用户点名调研 Rust 改造 siku；
本件的立场是**测量先行**——没有基线就不引入原生扩展。

## What Changes

- 新增可复现的分词/索引 CPU 基准（固定语料 + JSON 结果入库），记录基线。
- 按门禁推进，任一步不达标即停：
  1. **M0 测量**：tokenize 吞吐与"非 embedding 索引 CPU"占比；
  2. **M1 纯 Python 优化**（G1 成立后先做，零打包成本）；
  3. **M1b 编译型 Python 试验**（mypyc/Cython，仅 M1 不足时；无 Rust 工具链）；
  4. **M2 Rust/PyO3 PoC**（仅当 M1b 仍不足）；候选还包括 Rust sidecar、
     FTS5 分词器重选，均在 design.md 对比；
  5. **M3 集成**（PoC 达标 + 新增 ADR + 用户签核后）。
- 全程保持 token 流与 `cjk-uni-bigram-v1` **完全一致**：不改 `TOKENIZER_VERSION`、
  不重建索引、不改变检索结果与索引格式。
- 任一门槛不达标：按仓库纪律归档结论并删除 PoC，不留死代码。

## 受影响决策

只引用、不修改：ADR-0003（存储三件套 / FTS5）、ADR-0006（检索质量 golden set 门禁）、
ADR-0008（CI 版本矩阵）、ADR-0002（local-first，不引入常驻服务）。
若采纳原生扩展，**新增 ADR** 记录分发与打包取舍。

## Impact

- 只增不改（M0）：`scripts/bench_tokenizer.py`、`benchmarks/perf/`（基线 JSON + README）。
- 条件性改动（M1+）：`src/siku/retrieve/tokenizer.py` 内部实现；M1b 的构建钩子与编译
  配置（试验期依赖，不达标即移除）；M2 的可选依赖、`scripts/siku-sidecar.spec` 或构建
  脚本、`.github/workflows/ci.yml`。
- 行为：检索结果、索引格式、错误语义均不变；无 spec 级行为变化，`skip_specs: true`。

## Non-goals（不做清单）

- 不重写 FTS5/BM25，不更换 SQLite/LanceDB/parquet，不改 bigram v1 语义与
  `TOKENIZER_VERSION`。
- 不做常驻分词 sidecar/服务（IPC 与运维成本不划算，且违背单进程形态）。
- 不把 Rust 或编译型 Python 的构建依赖带进核心安装；试验不达标即移除。
- 不把 Rust 引入 siku 的其他模块。
- 不优化 embedding/rerank 网络链路（不属于本件收益口径）。
- 首版不承诺 PyPI 通用 wheel 分发（是否分发在 M3 ADR 中决定）。
- 不为"练 Rust"而改造；没有数据支撑就不做。
