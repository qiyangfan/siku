# 提案：全栈依赖升级至 2026-10 最新稳定版

## Why

上一轮全量依赖盘点后，多数依赖已落后于 2026-10 时点的最新稳定版，且出现多处跨大版本缺口：
Python 侧 filelock 3→4、pyarrow 25→26；前端侧 sigma 3→4、eslint 9→10、vite 7→8、
TypeScript 5.9→6/7、jsdom 26→30、jest-dom 6→7；Rust 侧 ureq 2 已停更近两年、edition 2021
落后于稳定的 edition 2024；pre-commit hooks v5→v6。落后版本同时意味着错过一批安全修复
（marked ReDoS、pydantic-settings 强制的 dotenv CVE 修复、pypdf 安全修复、tauri NSIS 降级
修复）与构建体验增量（vite 8 Rolldown、TS 6 迁移前瞻）。

## 上游功能增量与"手搓替代"评估

按同一工程标准逐项对比当前实现与可行替代方案（完整证据与对比矩阵见 design.md"手搓面
替代评估"一节），**裁决：四处手搓面维持现状，检索 FTS 层新增一条证据驱动的重评触发器**。
理由只看复杂度/确定性/性能/迁移成本，不以"既有 ADR 这么裁过"为据：

| 手搓面 | 替代方案 | 裁决（决定性依据） |
|---|---|---|
| FTS5 + 自研 CJK unigram+bigram 分词器 + 手搓 RRF 融合 | 整体迁 LanceDB 原生 FTS + hybrid（0.38 起 lance-native，内置 jieba 分词） | 不迁：① lancedb `_score` 并列行跨调用/跨进程顺序不稳定（#4516 open，1014 万文档实测），直接违反本管线"重建 diff 为空"的确定性要求；② 分词只有 jieba（词典依赖）或 ngram（查询侧过度匹配）可选，unigram+bigram 无法移植（#4364 open 无时间表）——个人笔记语料 OOV 密集，无词典 bigram 的召回鲁棒性是实质优势；③ 写后需 optimize 才入 FTS 索引；④ 收益端祛魅：hybrid 融合实测是客户端 Python 代码，与自搓同层。jieba vs bigram 的中文召回无公开数据（待验证：golden set A/B） |
| BYOK httpx 直连 embeddings/rerank/LLM 三通道 | openai SDK + 保留手搓 rerank；或 litellm | 不换：rerank 端点本不在 openai SDK 内，换后同一子系统仍留一套手搓 HTTP 且并存两套异常语汇；SDK 增益中我们唯一缺的重试用 httpx transport 约 10 行可补；litellm 属重依赖且接口翻动快。401/403 与 429 的错误分型是业务 UX，SDK 不供给 |
| pandoc 二进制供给（下载 + SHA-256 钉死 + 产物门禁） | pypandoc-binary wheel（1.17 捆绑 pandoc 3.9） | 不换：今天切 = pandoc 从 3.11 **降级**到 3.9（该 wheel 落后官方 8.5 个月是常态，节奏受制于单一维护者）；其"系统 PATH 更高版本优先"的定位逻辑破坏确定性，切了仍须保留自有定位代码；可省的约 350 行全是构建期脚本，年维护成本极低，换来的核心摄取路径版本失控不划算 |
| networkx 内建 louvain（固定 seed） | networkx 3.7 新增 leiden_communities | 不换：换算法 = 社区重编号 → wiki 全量 LLM 重摘要（真实费用 + 快照全失效），换取无场景证据的划分质量提升；确定性口径优先 |
| MCP stdio 服务器 | 官方 mcp SDK | 无动作：协议本就不手写，已在用最新 2.3.0（含 stdio stdout 硬化） |
| 设置缓存 | pydantic-settings 2.16 `settings_cached()` | 不适用：项目无手搓缓存对位物 |

真实的升级收益在安全与工程体验面，列进 What Changes。

## What Changes

按批次独立升级、独立验证（批次划分与耦合关系见 design.md），全部升级到 2026-10-18
时点的最新稳定版：

- **Python lock 刷新**：fastapi 0.143.3、pydantic 2.14.1、pydantic-settings 2.16.0、
  uvicorn 0.54.0、typer 0.27.3、networkx 3.7、pyarrow 26.0.0、lancedb 0.40.0、
  pypdf 6.21.1、docling（extra）2.140.0；httpx / mcp / pytest 系 / pyinstaller /
  reportlab / hatchling 已是最新不动。`pyproject.toml` 宽约束口径不变，仅刷新 uv.lock。
- **filelock 3→4.2.2 专项**：唯一 Python 侧跨大版本；已核查本项目仅用普通 `FileLock`
  （fcntl 协议）+ float timeout，不触及 4.x 的 SoftReadWriteLock 协议与 timeout 类型
  breaking 面，仍须跑跨进程写互斥并发验证。
- **工具链消化**：ruff 0.17.1（默认规则集与 format 行为变化，预计少量机械 diff）+
  mypy 2.4（native parser 默认开启）。
- **前端**：react 19.3.1、@mantine 9.7.3、marked 18.1.1（ReDoS 修复，渲染不可信
  markdown 的安全面）、dompurify 3.4.17、@tabler/icons-react 3.49.0、vitest 5.0.5、
  jsdom 30、jest-dom 7、@tauri-apps/cli 2.12.3；eslint 10 全家桶（typescript-eslint
  8.71.2 / react-hooks 7.1.1 / react-refresh 0.5.7 / globals 17）；vite 8.3.4 +
  @vitejs/plugin-react 6；TypeScript ~5.9.2 → ~6.0.2（7.0 被 typescript-eslint 支持区间
  `<6.1.0` 硬阻断，6.0 是官方过渡 bridge 版）；sigma 4.0.3（唯一需改 UI 代码项：
  `GraphCanvas.tsx` 适配 + 图谱视觉回归）。
- **Rust 桌面壳**：tauri 2.12.4 / tauri-build 2.7.3 / tauri-plugin-single-instance 2.5.4
  同窗 `cargo update`；ureq 2→3.4.2（2.x 停更近两年，仅 loopback 健康检查一处调用）；
  edition 2021→2024（`cargo fix --edition` 为主，重点排查 `static_mut_refs`）。
- **CI 与 hooks**：setup-uv v10.2.0→v10.3.0；pre-commit-hooks v5→v6.0.0（本项目未用
  被移除的 hook id，已核查）；ruff-pre-commit rev 对齐 v0.17.1。官方 Actions 五件套
  （checkout v7 / setup-node v7 / setup-python v7 / upload v7 / download v8）已是最新
  major，不动。

## 受影响决策

只引用、不修改：ADR-0003（存储三件套——lancedb/pyarrow 升级不动存储契约）、ADR-0005
（依赖纪律——无新增依赖、不引 torch 系与 openai SDK）、ADR-0006（检索口径——检索链路与
golden set 零改动）、ADR-0008（Python 版本策略——基线保持 3.12，CI 两端 3.12/3.14 不变）、
ADR-0009（BYOK——httpx 通道不换）、ADR-0011（Mantine——9.x 线内小版本）、ADR-0013
（pandoc 供给口径不变）、ADR-0001（UI↔内核边界——纯前端工具链升级不引入业务进前端）。

## Impact

文件面：`uv.lock`、`ui/package.json` + lock、`ui/src-tauri/Cargo.toml` + Cargo.lock、
`ui/src/GraphCanvas.tsx`（sigma 4 适配）、`.pre-commit-config.yaml`、
`.github/workflows/ci.yml` 与 `release.yml`（setup-uv rev）。`pyproject.toml` 预计零改动。
验证面：全量 pytest（834+）、ui vitest（131+）、双端 lint/build、Rust fmt/clippy/test、
filelock 跨进程并发测试、图谱视图亮/暗主题视觉回归、sidecar 产物门禁
（check_sidecar_artifacts 三平台）。行为对用户不可观察（docling extra 默认不安装，
其 reading-order 重写仅在启用重引擎时生效，随 lock 记录）。

## Non-goals（不做清单）

- 不升 TypeScript 7：typescript-eslint 8.71 支持区间为 `>=4.8.4 <6.1.0`，硬阻断；升
  6.0.2 并在 ROADMAP 触发器台账记录"typescript-eslint 宣布支持 TS 7 时另开升级件"。
- 不切 Node 26：2026-10-28 才进 LTS，CI 保持 Node 24；记触发器"10-28 后例行维护顺手切"。
- 不动 Python 基线（3.12）与 CI 3.14 哨兵结构（ADR-0008 域，触发器未触发）。
- 不迁 LanceDB 原生 FTS / 不采纳 lancedb embedding registry（依据见评估表与 design.md
  证据节；检索链路零改动，golden set 口径不动）。重评触发器随本件归档记入 ROADMAP：
  lancedb #4516（并列分不稳定）与 #4364（自定义分词器）关闭、且 golden set A/B 对比
  不降，再另开 FTS 迁移件。
- 不换 pandoc 供给（pypandoc-binary 版本滞后 8.5 个月且二进制定位非确定，见评估表）；
  不动 sidecar 打包结构；不升 tauri 3.0 alpha。
- 不新增任何运行时依赖、不引入 openai SDK / torch 系（ADR-0005）。
- 不改任何 spec 级行为：无用户可观察行为变化，由 `.openspec.yaml` 声明 `skip_specs: true`
  （先例：`adopt-mantine-ui-components`）。

## 与项目路线的关系

纯维护性升级，不占排序队列的产品项；执行前已对齐 `docs/ROADMAP.md`（排序队列清空状态）。
归档时回写 ROADMAP 触发器台账两条（TS 7、Node 26）。
