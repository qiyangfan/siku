# ROADMAP — siku 路线图与触发器台账

> 本文件是**唯一的排序队列**，回答"接下来干什么、哪些先不做"。
> openspec change 只代表"正在干的下一步"——**不预写远期骨架**：proposal 的 Non-goals
> 与 ≤2h 任务粒度需要执行前的上下文，提前写是小说；spec 是行为契约，实现前写是猜测，
> 过期 spec 比没有 spec 危险（它有权威外衣）。遗忘的防线 = 本台账 + ADR 复核信号 +
> 流程门禁（无 change 不写功能代码），而不是许愿池。
>
> 纪律：开 change 前先来此对齐排序；归档 change 后回来更新勾稽（完成项划线并指向
> archive）。Backlog 升格规则：用户点名 + 影响当前架构设计时，先补 ADR 再排期。

## 阶段总览

阶段划分对齐 ADR-0002 三阶段发布：Phase 1–4 属发布阶段一（localhost WebUI），
Phase 5 = 发布阶段二（Tauri 无签名），Phase 6 = 发布阶段三（签名）。

| Phase | 主题 | 交付物 | 核心闸门 |
|---|---|---|---|
| 0 | 脚手架与治理层 | uv 项目、CI 三作业绿、宪法+ADR+openspec、ROADMAP | ✅ 已完成（2026-09-17） |
| 1 | 摄取纵切面 | `Extractor` 协议 + MD 投影 + `source_hash` 幂等 + vault 布局；PDF/Word/PPT/Excel 各通一格式 | ✅ 已完成（2026-09-17，归档 `2026-09-17-add-ingest-vertical-slice`） |
| 2 | 检索纵切面 | SQLite schema + FTS5 中文分词 + LanceDB + BM25 混合召回 + reranker + **golden set v0** | ✅ 已完成（2026-09-17，归档 `2026-09-17-add-retrieval-vertical-slice`；baseline v0：Recall@5=1.000 / MRR@10=0.957，该基线已随 BYOK 退役为历史记录，见 Phase 5+ 行） |
| 3 | 图谱与 wiki | 抽取后端（graphify 方法复用）+ 实体/关系/社区落 parquet + 总目条目生成 | ✅ 已完成（2026-09-18，归档 `2026-09-18-add-graph-wiki-vertical-slice`；幂等闸门 + 五剧本 fake 全绿，真实冒烟 DeepSeek 通道 10 次调用质量复核合格） |
| 4 | WebUI 最小集与问答 | 问答编排 + `/api/ask` + React 对话最小闭环；浏览/图谱/wiki 为支撑视图 | ✅ 已完成（2026-09-18，归档 `2026-09-18-add-qa-vertical-slice`；无状态、非流式） |
| 5 | Tauri 壳（阶段二） | 无签名桌面包，GitHub Releases + Homebrew | ✅ 已完成（2026-09-19，归档 `2026-09-19-add-tauri-desktop-shell`，desktop-shell spec 入主 specs；macOS arm64 冒烟 ✅，Windows/Linux 冒烟经用户裁决豁免、移触发器台账；Release 无限期禁用） |
| 5+ | 模型供给 BYOK 端点化（发布前瘦身打磨） | 删除进程内模型（torch/权重），LLM/embedding/rerank 全走用户端点；分层 config.toml；sidecar 305MiB；通道化基线 | ✅ 已完成（2026-09-19，归档 `2026-09-19-add-byok-model-supply`；model-supply spec 入主 specs；双通道基线实测由用户裁决豁免，可随时按 benchmarks/README.md 补录） |
| 5++ | 桌面上手补齐（配模型 → 进资料 → 看知识） | 设置中心 / 资料管理 / 浏览·图谱·wiki 视图 | ✅ 已完成（2026-09-19，归档 `2026-09-19-add-ui-settings-center` 三端点 + 免重启生效 + React 设置视图；归档 `2026-09-19-add-desktop-library` 五端点 + 进程内单任务槽 + React 资料库视图；归档 `2026-09-19-add-browse-graph-wiki-views` 八个只读端点 + Sigma.js 图谱画布 + 浏览/wiki 视图 + 实体联动问答，http-api/web-ui spec 增量均已入主 specs）——上手链路（配模型 → 进资料 → 看知识）闭环 |
| 5++⁺ | 来源目录同步（进资料自动化延伸） | 受管喂养 + 定时扫描 + 标记式删除 | ✅ 已完成（2026-09-24，归档 `2026-09-24-add-directory-sync`：`siku.sync` 内核 + `library.sqlite3` 库域状态 + serve 轮询调度 + 来源/扫描/间隔/清理端点 + `siku scan` + 资料库来源目录区；library-sync spec 入主 specs；ADR-0010；取消收尾衔接索引修订 desktop-library 决议 #3；评审循环四轮 + 追加裁决） |
| 5++⁺⁺ | 桌面格式补齐与单文档移除 | 轻量默认摄取运行时 + 手动文档确认移除 | ✅ 已完成（2026-10-02，归档 `2026-10-02-complete-desktop-format-ingest` 与 `2026-10-02-remove-manual-library-document`：pypdf/Office 进核心、pandoc 随包 + 三平台产物门禁、稳定格式错误码；`source_id`/`removable` 清单、`POST /api/library/remove` + `siku remove`、无模型索引消减与暂存对恢复、图谱/Wiki 快照失效、filelock 跨进程写互斥；ADR-0013 接受、ADR-0004/0010 回写；ingest/desktop-shell/library-sync/http-api/web-ui/graph-wiki 六主规格增量入档） |
| 6 | 签名与更新（阶段三） | Apple 公证 + Windows 签名 + 自动更新 | 更新链路灰度可用 |

## 当前排序队列

2026-11-09 两项已实施验收归档：

1. ~~add-entity-join-retrieval~~ ✅（2026-11-09，归档
   `2026-11-09-add-entity-join-retrieval`）：实体 join 检索增强通道——SAG
   （arXiv:2606.15971）式查询时动态超边：查询串确定性种子解析 → H=1 共现 join 扩展
   → 带溯源的桥接证据 chunk；纯确定性零模型调用，只读 entities.parquet 实体锚点
   （`SourceAnchor.chunk_id`）与检索索引两份既有派生物，零 schema 变更；消费面 = MCP
   第八个只读工具 `entity_evidence`；entity-join 主规格入档 + mcp-server 增量入档；
   ADR-0015 已接受；中文多跳评测（16 对标注）：桥接场景 join Recall@10 **8/8** vs
   纯混合召回 **1/8**，共现/歧义场景持平 8/8；升级路径见触发器台账 ADR-0015 两行。
2. ~~add-ci-e2e-smoke~~ ✅（2026-11-09，归档 `2026-11-09-add-ci-e2e-smoke`，
   skip_specs）：CI 版 E2E 冒烟门禁——`tests/e2e`（fake 三通道端点 + 真实 serve
   五段编排 + 端点自检）、pytest `e2e` marker 默认排除、ci.yml 独立 job + changes
   门控（fail-open）；断线演练自证红/绿；CI 首跑两面验证随推送后首周观察纪律执行
   （纪律与降级预案见归档 review.md）。

2026-10-02 三项提案已实施并通过验收归档：

1. ~~complete-desktop-format-ingest~~ ✅（2026-10-02，归档
   `2026-10-02-complete-desktop-format-ingest`）：pypdf 默认 PDF + Office 库进核心
   依赖 + pandoc 3.11 随包（SHA-256 锁定、三平台产物门禁入 CI/release）+ 扫描件/
   旧二进制格式稳定错误码；ADR-0013 已接受，ADR-0004 同步修订；冻结 sidecar
   干净环境冒烟通过（615 MiB，无 torch）；Release 禁用与实机豁免保持。
2. ~~remove-manual-library-document~~ ✅（2026-10-02，归档
   `2026-10-02-remove-manual-library-document`）：手动文档按 `source_id` 确认移除
   （`POST /api/library/remove` / `siku remove`）、`removable` 服务端资格、无模型
   索引消减与暂存对恢复、旧图谱/Wiki 快照失效、`user_removed` 完整收尾入全量
   清理、filelock 跨进程同库写互斥 + 扫描锁后重验；UI 行内移除/重试与知识缓存
   失效通知；ADR-0010 清理边界已回写。
3. ~~dark-theme~~ ✅（2026-10-02，归档 `2026-10-02-dark-theme`）：暗色三态主题——
   Mantine 内建 auto 初值 + 库默认键持久化、resolver light/dark 分流取值（暗色
   对比度逐族标定并守卫钉住 ≥4.5:1）、两处 HTML 接 ColorSchemeScript 同源初始化
   脚本（防首帧闪烁 + 防漂移测试）、壳页暗色块同源、header 两态切换入口、图谱
   边线/标签色随主题；web-ui 主规格新增「主题三态与两态对比度」需求。

排序队列已清空。2026-10-10 本轮两项已实施验收归档：

1. ~~add-mcp-server~~ ✅（2026-10-10，归档
   `2026-10-10-add-mcp-server`）：MCP 标准接入面——`siku mcp` stdio 服务器直连内核，
   六只读工具（search/ask/list_documents/read_document/graph_search/graph_neighbors）
   + 幂等 `ingest`，与 CLI/serve 共用写入互斥；官方 MCP Python SDK v2（2.3.0）进核心
   依赖（既有钉版零移动）；ADR-0014 已接受；mcp-server 主规格入档；全量 pytest 830 通过。
2. ~~fix-supply-protocol-dead-end~~ ✅（2026-10-10，归档
   `2026-10-10-fix-supply-protocol-dead-end`）：待裁项收口（owner 授权定案）——
   协议越界在就绪判定转数据（`ask_readiness.invalid` token，与请求期同源不谎报）、
   设置读取面文件层可读时恒 200、`PUT` 落盘成功返回成功形状、`siku serve` 统一容忍
   供给配置错误启动（部分可用性：LLM 通道坏不废检索）、请求面 503 归一零漂移；
   UI 无效警示条不提供保存可修入口；顺带收敛 5 处主规格超长 Requirement，
   `--specs --strict` 恢复 **9/9**；全量 pytest 834、ui vitest 131 通过。

收款继续 Mock，不另开支付方案。最近完成并归档：

0. **全栈依赖升级至 2026-10-18 最新稳定版**：归档 `2026-10-18-upgrade-dependencies-2026-10`
   （skip_specs）——Python lock 刷新（filelock 4.2.2 跨大版本 + 跨进程锁验证；typer 被
   docling-core 上界钉住留 0.26.8）、前端 eslint 10/vite 8/TS 6.0.2/sigma 4（GraphCanvas
   适配 + 亮暗视觉回归）/react 19.3.1/marked 18.1.1（ReDoS 修复）、Rust tauri 2.12.4 +
   ureq 3 + edition 2024（MSRV 1.90）、setup-uv v10.3.0 + pre-commit-hooks v6；
   `react-hooks/set-state-in-effect` 9 处降 warn 待独立重构。评审证据见该归档 review.md。

1. **模型供给错误分型与双面文案**：归档 `2026-10-01-fix-model-supply-error-surfacing`——401/403 凭证
   被拒不再与「未配置」同型；config.toml 不可解析时 PUT 可覆盖自救 + serve 可启动，且设置页给出
   显式确认的覆盖入口；`ask_readiness` 计入 serve 的 CLI 层；`map_domain_error` 分 CLI/HTTP 双面文案。

1. **通用组件与移动端导航**：归档 `2026-09-24-adopt-mantine-ui-components`；新增 ADR-0011，接入 Mantine Core 9.x，移动端使用三项底部导航与更多视图菜单。
2. **桌面本地服务恢复**：归档 `2026-09-24-recover-sidecar-after-exit`；Tauri 监测 sidecar 运行期故障，并提供重新启动和串行关闭清理。
3. **基于内容的提问建议**：归档 `2026-09-24-recommend-content-based-questions`；从已导入笔记章节与 wiki 实体生成可编辑建议，空语料不展示固定示例。

阶段依赖：1→2→3→4 严格串行（2 依赖 1 的投影，3 依赖 2 的元数据）；Phase 4 的 UI
骨架可与 3 后半并行（契约先行）；5、6 按 ADR-0002 触发，不抢先。

## 各阶段一句话目标

- **Phase 1**：让语料"进得来"——任何格式丢进 `vault/`，投影与锚点自动落位，重跑无害。
- **Phase 2**：让检索"答得准"——混合召回 + 重排，且每个参数改动都有分数裁决。✅
- **Phase 3**：让知识"自己长"——图谱与总目条目从语料可再生，换模型可全量重建。✅
- **Phase 4**：让产品"答得上"——localhost API 契约、检索驱动的有来源单轮问答与 React
  对话闭环已完成；浏览/图视图/wiki 后续围绕问答补齐。
- **Phase 5**：让用户"装得上"——双击即开，无需命令行。
- **Phase 6**：让更新"敢点"——签名与自动更新，面向全量用户。

## 触发器台账（散落在各 ADR 复核信号的统一收口）

| 触发条件 | 动作 | 来源 |
|---|---|---|
| CI 总时长 > 2 分钟 | 3.14 哨兵作业降级为每周定时跑 | ADR-0008 |
| Phase 5 打包钉死解释器 | 重评 3.14 哨兵必要性 | ADR-0008 |
| 图谱达 10⁵ 边级 | NetworkX 换 igraph | ADR-0003 |
| 语料 > 10⁶ chunk 或出现多用户并发写 | 重开存储 ADR（产品定位不变） | ADR-0003 |
| 接入第三个抽取引擎时接口仍放不下 | 重开 Extractor 接口设计 | ADR-0005 |
| 某格式抽取差评持续（如扫描件） | 换/加 Extractor，不动存储契约 | ADR-0004 |
| 出现 Excel 深度查询需求 | 加 DuckDB 直查通道，不塞检索层 | ADR-0004 |
| 出现超大原件（百 MB 级） | 附件"链接模式"例外 | ADR-0004 |
| 回归分数不降但满意度降 | 扩 golden set 标注，而非调参 | ADR-0006 |
| 中文分词成为检索瓶颈 | 重开 FTS5 分词器选型 | ADR-0006 / ADR-0003 |
| 强多人协作需求 | 独立产品线评估，不改单机内核契约 | ADR-0002 |
| 商业化决策 | 商标全类目清查（SIKU 玩具品牌） | ADR-0007 |
| 发布解禁（Release 重启 / Phase 6 启动） | 执行 Windows/Linux 实机安装冒烟并回填（清单见 docs/desktop.md） | 用户裁决 2026-09-19，归档 `2026-09-19-add-tauri-desktop-shell` |
| 有 Ollama / 云端 key 的环境 | 补录双通道基线（复现路径见 benchmarks/README.md） | 用户裁决 2026-09-19，归档 `2026-09-19-add-byok-model-supply` |
| 云端 key 环境补录 ✅ | `dashscope-text-embedding-v3` 通道基线已入 `benchmarks/baselines/`（Recall@5=0.9630 / MRR@10=0.9444，rerank-none，2026-10-10）；本地 Ollama 通道仍待环境 | 归档 `2026-10-10-fix-supply-protocol-dead-end` 轮次 |
| Phase 6（代码签名 + 自动更新）重启 | 证书到位且 owner 明确指令双条件齐备才启动；期间不作为待办、不反复评审 | 用户裁决 2026-10-02 |
| 有真实 BYOK 端点环境 | 设置中心/资料库/浏览·图谱·wiki 三视图 Tauri 壳内手工冒烟（serve 级全链路冒烟已记账于各归档 change review.md） | 归档 `2026-09-19-add-ui-settings-center` 及后续桌面上手 change |
| typescript-eslint 宣布支持 TS 7 | 另开 TS 7 升级件（当前钉 ~6.0.2 过渡版，区间 `<6.1.0`） | 归档 `2026-10-18-upgrade-dependencies-2026-10` |
| Node 26 进入 LTS（2026-10-28 已过） | 例行维护顺手把 CI/setup-node 从 24 切 26，不单独开窗 | 归档 `2026-10-18-upgrade-dependencies-2026-10` |
| lancedb #4516（并列分顺序不稳定）与 #4364（自定义分词器）关闭，且 golden set A/B 对比不降 | 另开 LanceDB 原生 FTS 迁移件（证据与对比矩阵见该归档 design.md） | 归档 `2026-10-18-upgrade-dependencies-2026-10` |
| docling-core 放开 `typer<0.27` 上界 | typer 随下一轮依赖升级带入 0.27（当前 0.26.8 可用，无急迫性） | 归档 `2026-10-18-upgrade-dependencies-2026-10` |
| 多跳评测已证 join 通道显著补盲（桥接 8/8 vs 混合 1/8） | 评估 `/api/ask` opt-in 集成与 WebUI 呈现（届时过 golden set 门禁，另开 change；是否立案先对齐排序） | 归档 `2026-11-09-add-entity-join-retrieval` / ADR-0015 |
| 种子召回或排序成为多跳瓶颈 | 引入 LLM query 实体抽取 / LLM 证据链重排（SAG 消融旁证见 ADR-0015） | 归档 `2026-11-09-add-entity-join-retrieval` / ADR-0015 |

## Backlog（明确不进当前阶段，防 scope creep）

Ollama 全离线通道（✅ 已随 BYOK 端点化落地为自部署端点供给，2026-09-19）·
只读发布 / vault 同步伴侣功能（Phase 5 后）·
DuckDB 直查 Excel（见触发器）· 附件链接模式（见触发器）· 大语料增量图谱更新
（当前全量重建已够快）· EPUB/HTML 摄取（零边际成本，Phase 1 顺手带走，不入闸门）·
多语言界面 · 移动端阅读。
