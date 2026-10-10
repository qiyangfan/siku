## Why

siku 内核能力目前只有 CLI（人读文本输出）与 localhost HTTP API（服务 WebUI）两个暴露面。
AI 编码代理与桌面 AI 客户端（Claude Code、ZCode、Claude Desktop、Cursor 等）已成为一等
使用场景：用户希望在对话里直接问自己的资料库、检索、读文档、收文件，但 agent 现在只能
逐次拼 CLI 并解析人读输出，错误口径与截断都不可靠，也没有发现机制。Model Context
Protocol（MCP）是该场景的事实标准，主流客户端全部支持；siku 需要一个标准接入面，否则
"AI 调用知识库"每家客户端都要各写一遍私有集成。

## What Changes

- 新增一等 CLI 命令 `siku mcp`：以 stdio 传输运行 MCP 服务器，进程内直连内核，不监听
  网络端口、不依赖 serve 进程（定位与论证见 ADR-0014）。
- 暴露七个工具：六个只读（`search` 混合检索带锚点、`ask` 单轮有来源问答、
  `list_documents` 资料库清单、`read_document` 单篇投影全文、`graph_search` 实体搜索、
  `graph_neighbors` 有界邻域展开）+ 一个幂等写（`ingest` 文件/目录摄取）。
- 全部工具复用既有内核服务与归一化错误映射，与 CLI/HTTP 面同口径；写操作进入与
  CLI/serve 相同的跨进程写入互斥边界；vault/data-dir 经命令选项供给，缺省与既有命令一致。
- 引入官方 MCP Python SDK（MIT）v2 稳定线为核心依赖（纯 wheel 轻依赖，无 torch 系），
  遵守 ADR-0005 依赖纪律；协议细节不手写。
- 遵守 ADR-0002（本地客户端面，非 UI）、ADR-0004（摄取幂等）、ADR-0009（BYOK 分层配置）、
  ADR-0014（本件决策）。

## Capabilities

### New Capabilities

- `mcp-server`：siku 的 MCP 标准接入面——stdio 服务器生命周期、工具集行为、失败口径、
  与既有客户端的内核与写入互斥共用。

### Modified Capabilities

无。所有工具复用既有能力（ingest/retrieval/graph-wiki/http-api/model-supply/
library-sync），其行为契约不变，本件不修改任何既有 spec。

## Impact

新增 `src/siku/mcp/` 模块与 `siku mcp` CLI 接线；`pyproject.toml` 核心依赖 +1（`mcp`）；
`tests/` 新增 MCP 服务器测试（假上游复用既有 fake 设施）；README 增补客户端接入配置示例。
不触碰 vault 布局、存储 schema、检索链路与 golden set 口径；无 UI 变更。

## Non-goals（不做清单）

- 只做 tools：不做 MCP resources、prompts、sampling、elicitation、进度通知。
- 只做 stdio：不做 Streamable HTTP / SSE 端点，不在 serve 内挂载 `/mcp`；远程或
  多客户端共享场景另开 change 评估（含授权画像）。
- 不暴露任何管理或破坏性操作：移除、全量清理、索引/图谱/wiki 构建触发、设置读写、
  来源目录 CRUD、扫描调度一律不经 MCP 暴露，仍归 WebUI 与 CLI。
- 不做 wiki 条目读取与图谱统计工具（增量另议，避免本件一次带全截断策略与清单分页口径）。
- 不做鉴权、多租户、远程访问；stdio 与客户端同信任域，不新增网络监听面。
- 不做流式输出：`ask` 沿内核无状态、非流式口径。
- 不改检索/摄取/图谱的任何既有行为，不动 golden set 与基线口径；不引入 server 形态
  数据库或新的存储组件。
