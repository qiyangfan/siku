# 设计：全栈依赖升级 2026-10

## 批次划分与耦合关系

每批独立可验证、独立可回退（lock/manifest 文件级回退即可，无数据迁移）。有硬耦合的
必须同批：eslint 10 必须与其四个插件一起动（插件 peer 范围决定）；vite 8 必须与
@vitejs/plugin-react 6 一起动（v6 peer 为 `vite ^8`）；TypeScript 6.0.2 需在 eslint 批
之后核对（typescript-eslint 8.71.2 支持区间 `>=4.8.4 <6.1.0` 覆盖 6.0）。

| 批次 | 内容 | 依赖 | 预估 |
|---|---|---|---|
| A | Python lock 刷新（filelock 除外） | 无 | 分钟级 |
| B | ruff 0.17 + mypy 2.4 消化 | 无 | 小时级 |
| C | filelock 4 专项 | A（lock 同文件） | 小时级 |
| D | 前端 minor/安全批（react/mantine/marked/dompurify/tabler/vitest/jsdom/jest-dom/tauri-cli） | 无 | 分钟~小时级 |
| E | eslint 10 全家桶（绑定批） | 无 | 小时级 |
| F | vite 8 + plugin-react 6（绑定批） | D（vitest 5.0.5 peer 已含 ^8） | 小时级 |
| G | TypeScript ~6.0.2 | E 之后核对 | 小时级 |
| H | sigma 4 + GraphCanvas 适配 + 视觉回归 | 独立 | 1–2 小时 |
| I | Rust：tauri 2.12.4 全家桶 + ureq 3 + edition 2024 | 独立 | 小时级 |
| J | CI：setup-uv v10.3.0 + pre-commit-hooks v6 | B（ruff rev 对齐） | 分钟级 |

## 关键升级点的事前核查结论（2026-10-18 实查代码）

- **filelock 4**（`src/siku/sync/locking.py`）：仅用 `FileLock(str(lock_path))` +
  `acquire(timeout=float, poll_interval=0.05)`。4.x 的 breaking 面为 SoftReadWriteLock
  磁盘协议变更、bool/str timeout 拒绝、singleton 重建约束——三者均不触及。锁文件不删
  语义保留；PyInstaller sidecar 新旧版本混跑场景下普通 fcntl 锁互斥不受影响。
  验证闸门：既有跨进程锁测试 + 手工双进程并发冒烟。
- **sigma 4**（`ui/src/GraphCanvas.tsx`）：当前用法很薄——构造参数
  `allowInvalidContainer/renderEdgeLabels/defaultEdgeType/labelSize/
  labelRenderedSizeThreshold`、`on("clickNode")`、`kill()`、`setSettings({labelColor})`、
  `forceAtlas2.assign`。需改点：① 删 `defaultEdgeType: "line"`（v4 移除，直边为默认）；
  ② `itemSizesReference` 默认从 `"screen"` 变 `"positions"`，若图谱观感变化则显式设回
  `"screen"`；③ `setSettings` 与 label 系列过一遍 TS 类型检查。graphology 0.26 与
  forceatlas2 0.10 与 sigma 4 兼容（sigma 4 无 graphology peer 硬约束）。
- **TypeScript 6.0.2**：TS 7（tsgo 原生编译器）已被 typescript-eslint 硬阻断；6.0 是
  官方 bridge 版，其新默认与弃用告警即 TS 7 迁移预演。升级动作：全量 `tsc -b` 回归，
  按告警清理 tsconfig（如 `baseUrl` 类 TS 7 移除项）；`vite`/`vitest` 不消费 tsc 编译
  API，无直接冲突。
- **vite 8（Rolldown 唯一打包器）**：兼容层自动转换 `esbuild`/`rollupOptions` 配置，
  但存在"配置静默失效"社区案例；本项目构建配置简单，仍须对照检查
  `vite.config.ts` 每一项在 8.x 下生效。Node 24 满足 engines。
- **eslint 10**：项目已是 flat config，v10 主要工作（移除 eslintrc 逃生门）对本项目
  顺路；消化 `eslint:recommended` 新增 3 规则的可能告警。`eslint-plugin-react` 明确
  不兼容 v10——本项目未使用，无影响。
- **pydantic-settings 2.16**：`validation_alias` 优先级与 `validate_by_alias` 行为
  变化——升级后过一遍设置中心（config.toml 分层 + PUT 覆盖）相关测试。
- **ruff 0.17**：默认 target-version py311、F406 进默认、format 行长计算忽略行尾
  pragma 注释——预计少量机械 diff，单独提交便于评审。
- **mypy 2.4**：native parser（ruff parser）默认开启；`for`/`with` 目标的
  `# type:` 注释不再支持——先 grep 确认存量（预计为零），CI 全量跑。
- **Rust edition 2024**：`cargo fix --edition` 机械迁移；重点人工排查
  `static_mut_refs`（升为 deny）与块尾临时值 drop 时机。自有 unsafe 少，预期工作量小。
  ureq 3 迁移点仅 loopback 健康检查一处（typestate builder + body 读取 API 变化）。
- **docling extra 2.140**：默认不安装，仅 lock 层面；2.132 重写 reading-order，若未来
  启用重引擎需全量重建派生物——此注意点记入 review.md。
- **uv 0.13**：不钉版本自动跟随；`.python-version` 已钉 3.12，默认解释器变化无影响；
  升级后 CI 缓存首次 miss 属预期。

## 验证策略

- 每批闸门：`uv run ruff check . && uv run ruff format --check . && uv run pytest`；
  前端批加 `npm run lint && npm test && npm run build`；Rust 批加
  `cargo fmt --check && cargo clippy -- -D warnings && cargo test`。
- 批次 C（filelock）加跨进程并发锁冒烟；批次 H（sigma）加图谱视图亮/暗主题视觉回归；
- 收尾：`pre-commit run --all-files`、sidecar 产物门禁脚本三平台形态检查
  （filelock 4 / lancedb 0.40 / pyarrow 26 进包后）、ui vitest + Python 全量各一遍
  最终绿。
- 不动 golden set：检索链路零改动的声明由"无检索相关文件改动"佐证。

## 风险与回退

- 全部变更落在 lock/manifest/少量代码文件，按批独立提交，任一批异常可单批回退。
- lancedb 0.40 官方未在 pyarrow 26 上跑过 CI（约束 `pyarrow>=16` 无上界，满足）：
  批次 A 后若向量相关测试出现异常，回退组合为 lancedb 0.38 + pyarrow 25，并在
  review.md 记录待上游验证后重试。
- typer 0.27 metavar 打印变化影响 help 外观：CLI help 快照如有断言需同步更新
  （先 grep 测试确认）。

## 手搓面替代评估：证据与方案对比（2026-10-18 实查）

### A. 检索 FTS 层：SQLite FTS5 + 自研 unigram+bigram + 手搓 RRF ⟷ LanceDB 原生 FTS + hybrid

替代方案实况（lancedb 0.38–0.40，源码与官方文档核实）：FTS 已移除 tantivy 依赖、改为
lance 原生实现（`lance-tokenizer` 吸收 tantivy v0.24 analyzer），jieba 分词自 0.38 进
Python SDK（PR #3289，`base_tokenizer="jieba/default"`，jieba-rs Search 模式粗细粒度
都出）；FTS 索引存表目录内，与向量索引同级；`search(query_type="hybrid")` 两腿并发、
按 `_rowid` join 后送 RRFReranker。

| 维度 | 现状（FTS5+bigram） | 迁 lancedb hybrid |
|---|---|---|
| 可删代码 | — | 自研分词器 96 行 + FTS MATCH 构建 + 手搓融合 + FTS5 可用性探测 + 双存储切换的一半 |
| 新增负担 | — | jieba dict.txt 资产分发（约 5MB）+ `LANCE_LANGUAGE_MODEL_HOME` + 写后 optimize 调度（未索引尾部平扫兜底） |
| 确定性 | 分词确定性自持，重建 diff 为空 | **#4516（open，无时间表）**：`_score` 并列行跨调用/多进程顺序不稳定、limit 并列分内随机保留——直接违反重建确定性红线 |
| 分词策略 | unigram+bigram，零词典，OOV（人名/代号/型号）鲁棒 | 仅 jieba（词典依赖，OOV 回退单字）或 ngram（查询侧同样拆解、过度匹配，#2168 实测）；自定义 analyzer 无支持（#4364 open） |
| 中文召回质量 | golden 基线在案（Recall@5=0.963 / MRR@10=0.944） | 无任何公开中文对比数据——**待验证**：golden set A/B（同 embedding 通道仅换 BM25 腿） |
| 融合实现 | 手搓 RRF（自维护） | 客户端 Python 代码（上游替维护，非引擎级） |
| 生态成熟度 | FTS5 十余年稳定 | 两年两次重写（tantivy→native→model-backed）；0.37.1–0.39 曾有 FTS 索引目录损坏拖垮 `list_indices` 回归（#4250 已修） |
| 迁移成本 | — | 检索层重写 + golden 重基线 + sidecar 资产 + 全量测试改造，数天级 |

结论：不迁。触发器（记 ROADMAP）：#4516、#4364 关闭且 golden A/B 不降。

### B. pandoc 供给：手搓下载+SHA-256 钉死 ⟷ pypandoc-binary wheel

| 维度 | 现状 | pypandoc-binary 1.17（2026-03-14） |
|---|---|---|
| pandoc 版本 | 3.11（2026-08-29，自控、仅落后 1 版） | 捆绑 3.9（2026-02-04），**切了即降级**；落后官方 8.5 个月，发版间隔 3–10 个月受制于单一维护者 |
| 供应链 | 手动钉二进制 SHA-256（官方 release） | uv.lock 对 wheel hash 强校验同级；但 wheel 内 pandoc 是其 CI 构建时拉 "latest"，pandoc 级无钉定，信任面扩至第三方 CI |
| 确定性 | 自有定位逻辑，路径确定 | "系统 PATH 更高版本优先"（除非设 `PYPANDOC_PANDOC`）——**切了仍须保留自有定位代码** |
| 打包 | 已有收集+门禁 | 无官方 PyInstaller hook，需 `collect_data_files('pypandoc')` 自加；wheel 三平台齐全（25–41MB，Linux 静态链接无 glibc 门槛） |
| 许可证 | 聚合分发 GPLv2 二进制，附声明+源链接 | 同口径，无差异 |
| 可省代码 | — | 约 350 行，全部是构建期脚本（下载段+哈希表+门禁段），年维护成本极低 |

结论：不换——版本失控落在核心摄取路径上，换不回等值收益。

### C. BYOK HTTP 通道：httpx 直连 ⟷ openai SDK / litellm

- 通道面：`/embeddings`、`/chat/completions`（OpenAI 标准）+ `/rerank`（Cohere/Jina 风格，
  **openai SDK 无此 API**）。换 SDK 后 rerank 仍手搓，同一子系统并存两套异常语汇与超时语义。
- SDK 实际增益逐项：类型模型（不需要——只解析少数字段）、流式（非目标）、自动重试
  （唯一缺口，httpx `HTTPTransport(retries=N)` 一行可补，出现需求时补）；错误分型
  （401/403 凭证被拒 vs 429 限流 vs 其余）是产品 UX，属业务代码，SDK 不供给。
- litellm：重依赖、接口翻动快、超出问题范围，排除。
- 结论：不换；重试需求出现时在 httpx transport 层补，不引 SDK。

### D. 社区发现：louvain（固定 seed）⟷ leiden（networkx 3.7 新增）

换算法成本：社区重编号 → wiki 条目全量 LLM 重摘要（真实 API 费用 + 全部快照失效 +
golden 复核）；收益：官方称划分质量"常更好"，无本场景证据。确定性口径与成本权衡下不换；
leiden 记为未来对照实验选项（同 seed 对照划分差异，仅在图谱规模触发器触发时一并评估）。
