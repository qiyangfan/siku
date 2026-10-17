# HANDOFF — siku 当前交接点

> 即时状态见本文；常驻规则见 `AGENTS.md`，架构/排序见 `docs/architecture.md`、
> `docs/adr/`、`docs/ROADMAP.md`。实现与评审明细在各 change 工件，不在此重复。

- **更新时间**：2026-10-17；分支 `main`。
- 本轮一项实施验收归档：`add-graph-auto-refresh`（内容变更后图谱增量自动维护，
  库级开关缺省关）。改动一笔提交推送 origin/main。归档明细：
  `archive/2026-10-17-add-graph-auto-refresh`（四规格 2 新增需求/3 修订，review 含
  实现过程 6 项自查修复与决策表 6 分支测试）。
- 上一轮（2026-10-10）清空全部上报/决策点（多平台打包除外），两项实施验收归档 + 一项基线补录：
  ①`add-mcp-server`（`siku mcp` stdio 服务器，ADR-0014）；②`fix-supply-protocol-dead-end`
  （协议越界三处死路收口，定案采纳「解析结果是数据」）；③DashScope 通道基线
  （Recall@5=0.9630 / MRR@10=0.9444）。改动已按 change 拆两笔提交并推送 origin/main
  （cli.py 的 mcp 命令与 serve 容忍分支分属两笔）。
- 归档明细：`archive/2026-10-10-add-mcp-server`（mcp-server 主规格 4 需求/10 场景，
  review 含真实子进程 stdio 冒烟）；`archive/2026-10-10-fix-supply-protocol-dead-end`
  （三规格 5 需求修订，review 含评审循环 P1×1+P2×8 与真机冒烟）；旧归档
  `2026-10-01-settings-error-cause-codes` 的上报待裁已销号（指向②）。
- 排序队列已清空，下一项待 owner 对齐排序。

## 验证状态

- pytest **862**；ruff check/format 双清；`openspec validate --specs --strict` **9/9**；
  `--changes` 无活跃 change；ui vitest **133**、`npm run build`/lint 绿。
- 本机 pytest 口径：`env -u DASHSCOPE_API_KEY uv run python -m pytest -o addopts=""`
  （`uv run pytest` 直呼 spawn 失败；该 key 致假红）。MCP 子进程测试自带 HOME 隔离。
- UI 门禁必须在 `ui/` 内跑：仓库根 `npx tsc` 命中同名假包、`npx vitest run` 扫错测试集
  （实测 89 假失败）。

## 必须保留的判断

- **协议越界新契约**：`ask_readiness.invalid` 与请求期同源——视图说无效 ⇔ 请求必失败；
  读取面文件层可读恒 200；serve 统一容忍供给配置错误启动（LLM 坏不废检索）；请求面
  503 `invalid_settings` 零漂移。不要改回 CLI 面话术、不要恢复读取面 503、不要加
  「保存可修环境变量」控件。
- 场景名「坏文件叠加上层协议越界时归一化失败」按硬规则保留旧名（THEN 已收敛为
  「明示后继续启动」）——名字与语义的字面差是刻意的，不要顺手改名。
- MCP：不监听端口、无鉴权面；`--vault`/`--data-dir` 客户端配置必须绝对路径；模型供给
  错误固定 HTTP 面话术；白名单外格式沿内核 `ignored` 计数语义；SDK 上界 `>=2,<3` 保留
  （httpx2 与 httpx 并存是上游事实）。
- 基线：改检索链路必须过 `dashscope-text-embedding-v3` 通道门禁；本地 Ollama 通道仍缺。
- **图谱自动刷新（`graph_auto_refresh`，缺省关）**：自动路径只维护既有快照——
  不创建图谱、不重建失效快照、不生成 wiki（「图谱已更新、wiki 待显式重建」是既有
  产品状态）；触发面仅 HTTP ingest/scan 任务与 CLI `siku scan`，且条件与索引逐字
  一致（非 rebuild、有变更）；MCP `ingest` 与 CLI `siku ingest` 不接线（两入口连
  索引都不维护，另案）；抽取失败不改任务成功终态、旧 parquet 原样可读（原子写）；
  取消/rebuild 任务不触发。身份闸门记 (extractor_id, model_id, prompt_version) 于
  `graph/cache.py` cache_meta，换模型/prompt 时自动路径跳过并要求显式更新（防静默
  全量重抽烧 key）；`identity_unknown`（升级路径）诚实分流，提示显式更新一次启用。
- 既有判断：非法协议取值挡在输入边界；`config_file_unreadable` 禁止覆盖、serve 对该型
  仍快速失败（内容未知不带病启动）；CLI `siku wiki` 无 `--vault` 互斥边界；主题机制
  只用 Mantine 内建三态。

## 既有待办与外部边界

- **多平台打包（owner 2026-10-10 明示除外）**：Windows/Linux 实机安装冒烟维持豁免
  （发布解禁时按 `docs/desktop.md` 回填）；Phase 6 签名/自动更新维持 2026-10-02 终态
  裁决无限期缓滞（证书到位且 owner 明确指令双条件齐备才重启）。
- 本地 Ollama 通道基线：待有在线环境按 benchmarks/README.md 补录（触发器台账已记）。
- 本轮登记（评审循环发现，均在本轮变更集范围外、HEAD 既有，未顺手修改）：
  ①`tests/test_api_sync.py:252-260` 轮询循环 `snapshot` 可能未绑定（pyright
  reportPossiblyUnboundVariable，与本轮在 test_api_library.py 已修的同模式）；
  ②`src/siku/graph/providers.py:229,249` 两处 `Unknown | None` 类型错误；
  ③未触及文件其余既有 pyright 错误（test_mcp_server×20、test_qa×7、
  vector_store×5、test_sync_removal×3 等，全树 52 错误中 50 处在本轮范围外）。
- pi-lens 检查器模块索引可能滞后于新建模块（本会话 `siku.graph.refresh` 被反复
  误报无法解析），以 pyright/测试/运行时导入为准，勿据陈旧声明改代码。
- GUI 进程读不到 shell env；sidecar 注入不是当前目标。
- openspec：主规格 Requirement 正文 ≤500 字符是 CLI 新增强检查（本轮已全部收敛）。

## 本机执行口径

- `ui/` 真正锁文件是 package-lock.json；直接用已有 `node_modules/.bin`，不运行
  会触发 install/孤儿锁文件的 pnpm 11 命令。若 `ui/node_modules` 缺失（实测发生过），
  按锁文件 `npm ci` 恢复即可（esbuild postinstall 被 allowScripts 阻止不影响门禁）。
- 仓库迁移后 hook 路径失效用 `.venv/bin/python -m pre_commit install` 重生，禁用
  `--no-verify`。
- mypy 有既有错误且不是当前门禁；发生真实失败先归因，不能据历史记录假定本轮通过。
- pandoc 构建缓存在 `~/.cache/siku-build/pandoc/<triple>/`；重建 sidecar 直接
  `uv run python scripts/build_sidecar.py`。
