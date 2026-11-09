# HANDOFF — siku 当前交接点

> 即时状态见本文；常驻规则见 `AGENTS.md`，架构/排序见 `docs/architecture.md`、
> `docs/adr/`、`docs/ROADMAP.md`。实现与评审明细在各 change 工件，不在此重复。

- **更新时间**：2026-11-09；分支 `main`，本轮两项归档已提交并推送远端。
- 本轮收口归档两项：`2026-11-09-add-entity-join-retrieval`（实体 join 检索通道 +
  MCP 第八个只读工具 `entity_evidence`，ADR-0015；entity-join 主规格入档 +
  mcp-server 增量入档，现八工具 = 七只读 + ingest）与 `2026-11-09-add-ci-e2e-smoke`
  （CI 版 E2E 冒烟门禁，skip_specs）。活跃 changes 归零，排序队列清空。
- **唯一在途待办**：CI 首跑两面验证（改动 `src/` 触发 e2e job、纯文档跳过；首周
  flake 纪律与降级预案见归档 review.md）——**2026-11-09 起被账号级 Actions 锁定
  阻塞**（配额/付费/存储待 owner 在 Settings → Billing 核查解除；对照实验已排除
  工作流文件问题，见 d216fab 提交说明），解除后按同一口径补验首跑两面。

## 验证状态（归档前全量复验，2026-11-09 本机）

- pytest **887 passed + 2 deselected**（e2e 默认排除）；`pytest -m e2e` **2 passed**；
  ruff check + format 双清（340 文件）；`openspec validate --specs --strict` **10/10**
  （新增 entity-join）；活跃 changes 零。
- **既有 flaky（HEAD 既有，已归因未修，勿顺手改）**：
  `test_two_process_mutex_via_subprocess`——时序余量 ~1s vs `import siku.cli` 实测
  3.8–6.9s，本机时红时绿（本轮复验恰绿）；修法另开小件：setup 显式建 `vault/notes/`
  或加长 holder 持锁，使断言不依赖启动时序。

## 必须保留的判断

- **E2E 门禁纪律**：确定性是入闸前提；禁止以放宽断言换绿（断言松动 = 门禁失效）。
  fake 端点按三消费方 system prompt 特征分流（图谱抽取/百科编辑/本地问答器），prompt
  改动会让 e2e 500 变红——是特性（跨段契约漂移报警），不是误报。
- **entity_join 边界（ADR-0015）**：只读图谱快照 + 检索索引两份派生物，零模型调用
  零独立状态；`rerank_score` 契约 = 最终排序第一关键字（种子分层偏移恒序）。升级路径
  （LLM 抽取/重排、`/api/ask` opt-in）由触发器台账信号驱动，勿顺手做。
- **依赖升级遗留口径**：TS 钉 `~6.0.2`（TS 7 被 typescript-eslint `<6.1.0` 阻断）；
  tauri MSRV 1.90；typer 留 0.26.8（docling-core 上界）；`react-hooks/set-state-in-effect`
  9 处待独立重构清零后恢复 error。
- MCP：不监听端口、无鉴权面；`--vault`/`--data-dir` 须绝对路径；SDK 上界 `>=2,<3` 保留。
- 基线：改检索链路必须过 `dashscope-text-embedding-v3` 通道门禁；本地 Ollama 通道仍缺。
- **图谱自动刷新（`graph_auto_refresh`，缺省关）**：身份闸门 (extractor_id, model_id,
  prompt_version)，换模型跳过并要求显式更新（防静默全量重抽）。

## 既有待办与外部边界

- **多平台打包（owner 2026-10-10 明示除外）**：Windows/Linux 实机安装冒烟维持豁免；
  Phase 6 签名/自动更新维持 2026-10-02 终态裁决无限期缓滞（双条件齐备才重启）。
- 本地 Ollama 通道基线：待在线环境按 benchmarks/README.md 补录（触发器台账已记）。
- 2026-10-17 登记（HEAD 既有、范围外）：`tests/test_api_sync.py:252-260` 轮询
  `snapshot` 可能未绑定；`src/siku/graph/providers.py:229,249` 两处 `Unknown | None`；
  其余既有 pyright 错误（全树 52 处，多为测试文件）。mypy 既有解析错误且非门禁。
- openspec 主规格 Requirement 正文 ≤500 字符是 CLI 新增强检查。

## 本机执行口径

- pytest 口径：`env -u DASHSCOPE_API_KEY uv run python -m pytest`（直呼 `uv run pytest`
  spawn 失败；该 key 致假红）；跑 e2e 追加 `-m e2e`（addopts 已默认排除）。
- UI 门禁必须在 `ui/` 内跑（根目录 npx 命中假包）；锁文件是 package-lock.json，用已有
  `node_modules/.bin`，不跑 pnpm 11；`ui/node_modules` 缺失按锁文件 `npm ci`。
- 仓库迁移后 hook 路径失效用 `.venv/bin/python -m pre_commit install` 重生，禁用
  `--no-verify`。
- pandoc 构建缓存在 `~/.cache/siku-build/pandoc/<triple>/`；重建 sidecar 直接
  `uv run python scripts/build_sidecar.py`。
