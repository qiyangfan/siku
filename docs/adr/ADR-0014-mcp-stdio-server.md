# ADR-0014：MCP 服务器以 stdio 本地客户端形态接入

- **状态**：已接受（2026-10-10 设计裁决；2026-10-10 实施验收通过，证据见
  `openspec/changes/archive/2026-10-10-add-mcp-server/review.md`）
- **日期**：2026-10-10
- **关联**：延伸 ADR-0002 的进程边界口径（MCP 服务器与 CLI 同级，属内核本地客户端面，非 UI）；
  遵守 ADR-0009 的 BYOK 分层配置供给；遵守 ADR-0005 的轻量依赖纪律。
- **提案**：[add-mcp-server](../../openspec/changes/archive/2026-10-10-add-mcp-server/proposal.md)（已归档）

## 问题

siku 内核能力目前只有两个暴露面：CLI（`siku ingest/search/ask` 等命令，文本输出）与
localhost HTTP API（服务 WebUI）。AI 编码代理与桌面 AI 客户端（Claude Code、ZCode、
Claude Desktop、Cursor 等）已成为一等使用场景，但缺少标准接入面：agent 要么逐次拼 CLI
并解析人读文本（错误口径、进度、截断都不可靠），要么要求先有 serve 进程并自行管端口。
业界事实标准是 Model Context Protocol（MCP）：客户端以标准协议发现并调用工具，siku 需要决定
以何种传输、何种进程形态、暴露哪些工具接入。

## 决策

新增一等 CLI 命令 `siku mcp`：以 **stdio 传输**运行 MCP 服务器，**进程内直连内核**
（与 CLI 同一复用方式），不监听任何网络端口，不依赖 serve 进程。定位为"CLI 同级的
本地客户端面"，不是 UI，不进入 ADR-0002 的 UI↔HTTP 边界约束。

工具面为**六个只读工具 + 一个幂等写工具**：
`search`（混合检索带锚点）、`ask`（单轮有来源问答）、`list_documents`（资料库清单）、
`read_document`（单篇投影全文，服务端限额并明示截断）、`graph_search`（实体搜索）、
`graph_neighbors`（有界邻域展开）、`ingest`（文件/目录摄取，按 `source_hash` 幂等）。
全部复用既有内核服务与归一化错误映射；写操作走与 CLI/serve 相同的跨进程写入互斥。
不暴露任何管理或破坏性操作（移除、清理、重建、设置、来源目录、图谱/wiki 构建触发）。

实现选用官方 MCP Python SDK（PyPI `mcp`，MIT）v2 稳定线，作为核心依赖引入；
版本上界 `<3`。拒绝手写协议：MCP 规范持续演进（2025-03-26 引入 Streamable HTTP、
2025-06-18 修订授权、2026-07-28 大版本），自研 JSON-RPC 封装与 schema 协商是长期负债。

选 stdio 而非 Streamable HTTP 的理由：①stdio 是全部主流客户端的公共基线，连接配置
即"命令 + 参数"，无端口/生命周期协调；②MCP 规范对 HTTP 传输要求服务端按 OAuth 资源
服务器画像实现授权发现（RFC 9728 等），对 stdio 明确豁免并指引"从环境取凭证"——与
siku BYOK 分层配置（环境变量 > config.toml）天然同构；③本地单机产品引入鉴权面是负资产。

否决"stdio 进程代理到 localhost HTTP serve"：仍要求 serve 常驻，客户端配置与故障面
（两进程 + 端口）更差，收益为零。否决"在 serve 内挂载 /mcp（Streamable HTTP）"：把
serve 变成 AI 客户端的前置条件，违背"管线操作不以前端为前置"的工程口径，且引入授权
画像负担；若未来需要远程/多客户端共享会话，可作为独立增补另开 change 评估。

## 理由与代价

stdio 直连内核让 MCP 与 CLI 完全同权：无 serve 也能用，桌面用户配好客户端即插即用；
写冲突由既有跨进程文件锁边界兜住（MCP 进程与 serve 进程并发摄取互斥），读路径沿用
提交快照语义，不引入新的并发模型。缺点是 MCP 进程与 serve 进程各自打开 SQLite/LanceDB，
依赖既有"写互斥 + 读快照"口径；该口径已由 CLI 与 serve 的并发现状背书，非新增风险。

依赖代价：官方 SDK 自带一组轻量传递依赖（JSON Schema 校验、JWT、OTel API、SSE 等，
纯 wheel，无 torch 系、无 server 形态数据库）；uvicorn/starlette/pydantic/httpx 均在
核心依赖中已存在或相容。需在实施期锁定版本并核对 fastapi/starlette/mcp 三角相容。
SDK 锁定 v2 线：v1.x 已进入维护模式，新线对齐 2026-07-28 规范。实施核对记录
（2026-10-10，`uv lock` 实测）：既有 fastapi/starlette/pydantic/anyio 钉版零移动，
纯新增 12 个包；SDK 2.3 自带第二条 HTTP 客户端线（httpx2）与既有 httpx 并存，属上游
传递依赖事实，不构成冲突。

安全边界不变：stdio 与客户端同信任域（同 CLI），无网络监听、无鉴权面、无遥测；
语料不出用户磁盘的本地优先红线不受影响（ask/search 的模型端点瞬时调用沿用 ADR-0009 口径）。

## 上游依据

- [MCP 规范·授权（stdio 豁免、HTTP 资源服务器画像）](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)
- [MCP 规范·传输（stdio 与 Streamable HTTP）](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- [MCP Python SDK（v2 稳定线，MIT）](https://github.com/modelcontextprotocol/python-sdk)
