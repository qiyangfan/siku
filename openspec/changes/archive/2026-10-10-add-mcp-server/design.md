# 设计：`siku mcp` — stdio MCP 服务器直连内核

## 当前证据与单一结论

内核已有三个成熟消费壳：CLI（`src/siku/cli.py`，进程内装配 + 跨进程写锁 + 归一化中文
错误）、HTTP API（`src/siku/api/app.py`，同一内核 + `map_domain_error` 双面文案）、桌面
sidecar（`siku serve --with-ui`）。MCP 服务器不需要第四种业务实现——它是一个与 CLI 同级
的本地客户端壳：装配方式照抄 CLI（解析模型供给通道 → 构建 SearchService/AnswerService/
图谱只读服务），错误口径照抄 CLI 面，写互斥复用 `library_write_lock` +
`ensure_library_writable`。读路径（检索/清单/笔记/图谱）全部是提交快照上的只读查询，
与 HTTP 读路径同构，无锁。

传输裁决（stdio、直连内核、否决 HTTP 挂载与 HTTP 代理）见 ADR-0014，此处不重复论证。

## D1：进程形态与生命周期

`siku mcp [--vault PATH] [--data-dir PATH]`：typer 子命令进入 MCP 服务器主循环，
stdio 传输，进程随客户端生命周期（stdin 关闭即退出），不监听端口。`--vault`/`--data-dir`
缺省与既有命令一致（`./vault`、`./data`，相对 CWD）；**客户端配置必须传绝对路径**——
MCP 客户端以任意 CWD 拉起服务器进程，README 示例统一给绝对路径写法。

协议通道与日志通道严格分离：stdout 只承载协议帧，任何日志（含告警）只进 stderr；
日志文本英文、`SIKU_LOG_LEVEL` 语义与 CLI 相同，缺省 WARNING。启动期不打印模型供给
横幅到 stdout（serve 的播报走 stderr 的做法在此同样适用，但缺省静默，避免污染客户端
日志视图）。

## D2：工具面与有界读取

| 工具 | 入参 | 复用内核 | 出参要点 |
|---|---|---|---|
| `search` | `query`, `top_k?`, `candidate_k?` | 检索装配（同 `siku search`） | 结果带 `source_name/note_path/anchor/text` 与分数；与 `--json` 同构 |
| `ask` | `question`, `top_k?`, `candidate_k?` | `AnswerService.ask` | `answer/insufficient_evidence/citations/request_id/model`（`request_id` 由 MCP 工具层生成，内核 `AskResult` 无此字段）；证据不足不是错误 |
| `list_documents` | 无 | 资料库清单内核 | 来源级 `source_id/source_hash/ingest_status/index_status` |
| `read_document` | `source_id` | 投影读取内核 | Markdown 全文 + 锚点序列；超限明示截断 |
| `graph_search` | `query`, `limit?` | `graph_search` | 实体 + 集合内诱导边；截断明示 |
| `graph_neighbors` | `entity_id`, `limit?`, `depth?` | `graph_neighbors` | 有界 BFS 子图；截断明示 |
| `ingest` | `path` | `ingest_path`（白名单格式） | 来源级 `created/updated/skipped/ignored`；幂等 |

有界读取（`read_document`）：单篇投影全文可能远超工具结果合理体积，服务端设硬顶并返回
`truncated` 标记与已返回字节数，与图谱查询"服务端裁决 + 截断明示"同一哲学。工具描述
（docstring/描述文本）写明建议先用 `search` 定位锚点、再用 `read_document` 全文跟进。

`ingest` 入参只收路径（客户端本地文件系统与 siku 同机）；不存在/越界返回归一化错误，
格式不在白名单沿内核语义计入 `ignored` 并如实返回计数（与 CLI 面同一口径，不造第二套
报错）。摄取成功后无需主动刷新——所有读工具都是现读，下一个请求即见新内容。

工具命名用动宾短名（`search`/`ask`/…），不加 `siku_` 前缀：服务器名本身已提供命名空间，
客户端展示为 `siku.search`。

## D3：错误口径与模型供给

领域错误一律映射为工具级失败（`isError` 结果）：稳定错误码 + 归一化中文 message，映射层
复用 `siku/api/messages.py` 的既有双面文案，**不新写第二份文案**；技术细节（异常链）只进
stderr 英文日志。关键分型与 HTTP 面一致：

- 模型通道未配置/配置无效：返回配置指引，与 `ask_readiness` 口径同源。MCP 面**固定
  HTTP 面话术**：本面无 CLI 通道覆盖参数，CLI 面「`--embedding-base-url`」类指引指向
  不存在的杠杆；HTTP 面「设置页 + 保存免重启生效」对桌面用户（主要分发形态）可行动，
  码两面一致（`model_not_available` 等）。`ask` 沿 `map_ask_error` 既有单一口径。
- 同库写忙：`ingest` 遇另一进程持锁，等待窗口（与 CLI 相同的短超时）后返回忙错误与
  "稍后重试"指引，不顺延重试（工具调用方是 AI，明确失败优于长阻塞）；码与 HTTP 面
  同为 `library_job_busy`。
- `source_id` 不存在 / 图谱未构建：返回未找到与"先构建图谱"指引（与 HTTP 读面同码）。

模型供给沿用分层解析（CLI 选项层留空 → 环境变量 → config.toml）；`siku mcp` 不提供
三通道 CLI 覆盖选项——服务器是长驻进程，通道覆盖经既有 config.toml/环境变量供给即可，
避免选项矩阵翻倍。BYOK 凭证仍只经环境变量名间接引用，不进工具结果。

## D4：依赖与版本

- 引入官方 `mcp` SDK v2 稳定线（MIT，纯 Python wheel），核心依赖记 `mcp>=2,<3`
  （官方指引：v2 起主版本上界必须钉住）。传递依赖（JSON Schema 校验、JWT、OTel API、
  SSE、starlette/uvicorn 等）均为轻量纯 wheel 或核心已有组件；无 torch 系、无 server
  形态数据库，符合 ADR-0005。不装 `mcp[cli]` extra（Inspector 等开发工具不进核心安装）。
- 实施期用 `uv lock` 落定版本并核对 fastapi/starlette/pydantic/mcp 四角相容；若 fastapi
  下界不足则上调（纯版本线事务，无代码影响）。`pydantic>=2.12` 等下界提升随 lock 提交。
- 协议规范基线：SDK v2 对齐 2026-07-28 规范并兼容更早修订；本件不直接依赖任何
  规范新特性（只做 tools + stdio），降低规范漂移暴露面。

## D5：并发、安全与测试

- 写互斥：`ingest` 经 `_library_write_guard` 同款边界（跨进程文件锁 + 已确认消减恢复
  预检），与 CLI/serve 并发安全；短等待后如实报忙。读工具不取锁，读提交快照——与 HTTP
  读路径同语义；serve 正在重建索引时读到旧快照是既有可接受口径，不是缺陷。与 CLI
  `ingest` 的一处面差异：MCP 版恒执行 `ensure_library_writable` 恢复预检（CLI 摄取传
  `data_dir=None` 跳过），副作用是失败前也会经 SyncRegistry 确立 `data/` 下的库域
  registry DB——该预检是本件 spec 明文要求，非缺陷。
- 安全边界：无网络监听、无鉴权面、无遥测，与 CLI 同信任域；工具结果不含 API key 明文
  （沿用掩码口径）。语料不出户红线不受影响：出户仅有模型端点瞬时调用（ADR-0009）。
- 测试（假上游为核心设施，CI 永不打真实 API）：
  - 工具层：进程内直调工具函数，复用 `tests/fakes.py` 的 Fake embedding/reranker 与
    `tests/graph_fakes.py` 的五剧本 LLM fake；表驱动覆盖正常/证据不足/未配置/忙/不存在。
  - 协议层：子进程拉起 `siku mcp`，经 SDK 客户端 stdio 连接，断言 `tools/list` 七工具、
    一次真实调用往返、stdout 无协议外输出、stdin EOF 后进程退出。
  - 并发层：MCP 进程摄取与 serve 摄取两进程竞争，断言一方忙失败、语料无交叉损坏。
- 验证门禁：全量 pytest、ruff、`openspec validate --changes --strict`；真实客户端冒烟
  （MCP Inspector 或 ZCode/Claude Code stdio 配置）走一轮 search → read_document →
  ask → ingest。

## 上游依据

- [MCP 规范·授权（stdio 从环境取凭证，HTTP 需资源服务器画像）](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)
- [MCP Python SDK v2（版本与上界指引）](https://github.com/modelcontextprotocol/python-sdk)
- [MCP 规范·工具](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
