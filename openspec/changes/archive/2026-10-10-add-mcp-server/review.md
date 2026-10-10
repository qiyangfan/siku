# 评审记录：add-mcp-server

## 实现范围

`src/siku/mcp/`（server.py + `__init__.py`）：stdio MCP 服务器，七工具（六只读 +
幂等 `ingest`），进程内直连内核；`cli.py` 新增 `siku mcp` 子命令（延迟导入）；官方
`mcp>=2,<3` SDK（2.3.0）进核心依赖；`tests/test_mcp_server.py` 28 条测试；README
AI 客户端接入节；ADR-0014。

## 验证证据（2026-10-10，本机）

- 全量 pytest：**830 通过**（基线 802 + 本 change 净增 28），0 失败。
  命令：`env -u DASHSCOPE_API_KEY uv run python -m pytest -o addopts=""`（本机口径，见 HANDOFF）。
- ruff：全仓 `uv run ruff check .` **All checks passed**。
- OpenSpec：`openspec validate add-mcp-server --changes --strict` 通过。
- 协议层（真实子进程 stdio + SDK 客户端）：握手、`tools/list` 七工具齐全、
  `list_documents` 真实往返、stdout 无协议外混入、`SIKU_LOG_LEVEL=INFO` 日志只进
  stderr（含启动日志行断言）、stdin EOF 后进程退出码 0。
- 真实 vault 冒烟（SDK 客户端经 stdio 子进程，只读工具）：
  `tools: 7 个全列`；`list_documents` 返回真实清单（本工作副本 attachments 为空，
  诚实返回空清单）；`graph_search`/`ask` 在未构建图谱/未配通道时返回带稳定码的
  错误结果（`[graph_missing]`/`[model_not_available]`），无堆栈泄漏。
- 跨进程写入互斥：真实子进程持 `vault/.siku/library.lock` 期间，`ingest` 短等待后
  返回 `library_job_busy`（忙语义先于路径语义，耗时 ≥ 2s×0.9）；同时只读工具
  `list_documents`/`read_document` 照常返回。

## 评审循环（两轮）

**第 1 轮（主对话交叉自查）**：实现过程中发现并修复——`uuid4` 未导入；`_call` 意外
分支误抛 `McpToolError`（进程内客户端会以 UnexpectedToolError 上抛）改为 ToolError；
`list_tools()` 返回形状；写锁文件名实查（`library.lock`）；清单 `ingest_status` 无索引
时为 `pending`、`source_hash` 为附件真实 SHA-256（两处断言按实现事实修正）。

**第 2 轮（独立子代理评审，A–G 七组）**：结论"需修复后合入"，P0=0、P1=2、P2=5。
全部修复并复验：

| 级别 | 发现 | 修复 |
|---|---|---|
| P1 | 子进程测试未隔离 HOME，`config_file_path()` 会读到开发机真实 config.toml，「未配置」断言依赖机器状态 | `_scrubbed_env(home=...)` 把 HOME 指向 tmp_path |
| P1 | `_mapped` 固定 CLI 面话术：指引推荐 `siku mcp` 不存在的 `--embedding-*` 参数，且同面内 search（CLI 话术）/ask（HTTP 话术）不一致 | 固定 HTTP 面话术（本面无 CLI 覆盖参数，HTTP 面指引可行动、码一致）；design D3 同步 |
| P2 | S10「写入期间读工具照常可用」无测试 | 补持锁子进程 + 读工具返回断言 |
| P2 | S2「日志只进 stderr」无显式断言 | EOF 测试改 INFO 级并断言 stderr 含启动日志行 |
| P2 | `tool_read_document` 漏接 `NoteParseError`（会落 internal_error，HTTP 同路径为 422 note_parse_error） | 并入捕获元组 |
| P2 | 两处 docstring 失实（ToolError 前缀说法；坏文件报错顺序依赖） | 照实修正 |
| P2 | MCP ingest 恒执行 registry 预检的面差异未记录 | design D5 补记 |

## 实施期语义裁决（归档前修订，均已留痕 tasks.md 执行注记）

1. **不支持格式 ≠ 报错**：spec 场景原写"返回归一化拒绝"；实查内核白名单语义为计入
   `ignored`（CLI 面同样 ignored 计数），不另造第二套口径。spec 场景已改为"计入
   ignored 并如实返回计数"。
2. **话术面**：见上表 P1 第二条。
3. **冒烟客户端替代说明**：任务 4.3 提到 Inspector 或 ZCode/Claude Code；本会话无法
   向 GUI 客户端注册 MCP 服务器，采用官方 SDK `Client` 经 `StdioServerParameters`
   真实子进程 stdio 连接作为等价冒烟（与 GUI 客户端同一传输与协议栈；协议层测试同路径）。

## 已知边界（不构成缺陷）

- `ask` 运行期错误沿 `map_ask_error` 既有文案（其中 ModelNotAvailableError 分支按该
  函数既有设计回落 HTTP 面）；与 `search` 的 HTTP 面话术一致，码一致。
- `_search_service` 的 rerank 解析 `except ModelNotAvailableError` 与 CLI
  `_reranker_component` 同构，依赖"embedding 先解析"顺序拦截坏配置文件（docstring 已记）。
- MCP ingest（含失败路径）恒确立 `data/` 库域 registry DB（spec 要求的恢复预检副作用）。
- 本机未装 MCP Inspector（`mcp[cli]` extra 未进核心安装），冒烟采用 SDK 客户端等价路径。

## 上报项（非本 change 范围）

- 主 specs `http-api`/`model-supply`/`web-ui` 在 `openspec validate --specs --strict`
  下各报 1–2 条「Requirement 文本 >500 字符」WARNING（严格模式计失败）。归因：主规格
  内容自 2026-10-02 归档后未变（当时 8/8 通过），系 openspec CLI 升级新增强检查；修复
  需拆分既有 Requirement（须走独立 change 的 delta 流程，保留全部场景名），不在本件
  能力域内擅自扩界。建议单开 spec 格式卫生小 change。
- 归档件 `2026-10-01-settings-error-cause-codes` 的「上报待裁」项（文件层协议越界的
  UI 死路）维持搁置：两种收口都要动对外交互契约，须 owner 裁决。
