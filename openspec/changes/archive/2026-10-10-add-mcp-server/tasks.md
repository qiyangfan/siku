# 实施任务

每项 ≤ 2h；先写失败测试，再实现对应步骤。验证证据见 review.md。

## 1. 服务器骨架与协议通道

- [x] 1.1 失败测试先行：子进程拉起 `siku mcp`，stdio 客户端完成握手与 `tools/list`；
  断言七个工具在列、至少一只读工具全往返调用成功、stdout 无协议外输出、
  `SIKU_LOG_LEVEL` 日志只进 stderr、stdin EOF 后进程退出。
- [x] 1.2 引入 `mcp` SDK 依赖（`>=2,<3`），`uv lock` 落定并核对 fastapi/starlette/pydantic
  相容；冲突则上调相关下界，纯版本线事务单独提交。
- [x] 1.3 实现 `siku mcp` 子命令与服务器装配（`--vault`/`--data-dir`，缺省与 CLI 一致）。

## 2. 只读工具

- [x] 2.1 失败测试先行（假上游）：`search`/`list_documents` 正常、未配置 embedding 指引、
  索引缺失三条路径；实现两工具，检索装配与 `siku search` 同源，出参与 `--json` 同构。
- [x] 2.2 失败测试先行：`read_document` 正常读取、不存在 `source_id`、超长投影截断
  （`truncated` 标记与硬顶）；实现该工具。
- [x] 2.3 失败测试先行（五剧本 LLM fake）：`ask` 正常回答、证据不足（非错误）、
  LLM 失败映射、`request_id` 在日志可追踪；实现该工具。
- [x] 2.4 失败测试先行：`graph_search`/`graph_neighbors` 正常与有界截断、图谱未构建
  指引；实现两工具（复用图谱只读内核）。

## 3. 写入工具与跨进程互斥

- [x] 3.1 失败测试先行：`ingest` 幂等重跑 `skipped`、格式白名单拒绝、路径不存在、
  写锁忙短等待后报忙；实现该工具，写入口与 CLI 同一互斥边界与恢复预检。
- [x] 3.2 两进程竞争回归：MCP 进程 `ingest` 与 serve 摄取并发，断言一方忙失败、
  vault 与索引无交叉损坏；读工具在写进程持锁期间照常读提交快照。

## 4. 错误口径与交付

- [x] 4.1 失败测试先行：领域错误 → 工具失败全表映射（复用 `map_domain_error` 既有
  双面文案与 model-supply 分型），断言用户面无异常栈、技术细节只进 stderr 日志。
- [x] 4.2 运行全量 pytest、ruff、`openspec validate --changes --strict`；README 增补
  MCP 接入文档（绝对路径配置示例：ZCode / Claude Code / 通用 stdio 客户端三例）。
- [x] 4.3 真实客户端手工冒烟：Inspector 或 ZCode/Claude Code 经 stdio 连接，走一轮
  `list_documents → search → read_document → ask → ingest`，记录证据入 review.md。
- [x] 4.4 回写 ADR-0014 验收状态、ROADMAP 勾稽、architecture.md 快照核对；同步主
  规格并归档。

## 执行注记（评审循环与语义修订留痕）

- 依赖事务（1.2）：fastapi/starlette/pydantic/anyio 既有钉版零移动，纯新增 12 包；
  design D4 预留的"下界上调"未发生。SDK 2.3 自带 httpx2 与既有 httpx 并存，已记 ADR-0014。
- spec 语义修订（实施期裁决，归档前完成）：场景「摄取幂等且受限白名单」中"不支持的
  格式返回归一化拒绝"改为"计入 ignored 并如实返回计数"——白名单外格式沿内核既有
  ignored 语义（CLI 面同为 ignored 计数），不另造第二套报错口径。
- 错误话术口径（独立评审 P1 后裁决）：`_mapped` 固定 HTTP 面话术——MCP 面无 CLI
  通道覆盖参数，CLI 面指引指向不存在的杠杆；design.md D3 已同步。
- 独立评审：P0=0、P1=2（测试未隔离 HOME/config.toml；模型供给话术面错位）、P2=5
  （S10 测试缺失、S2 stderr 断言、NoteParseError 映射、两处 docstring 失实、registry
  面差异记录），全部修复后复验；证据见 review.md。
