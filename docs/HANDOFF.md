# HANDOFF — siku 当前交接点

> 即时状态见本文；常驻规则见 `AGENTS.md`，架构/排序见 `docs/architecture.md`、
> `docs/adr/`、`docs/ROADMAP.md`。实现与评审明细在各 change 工件，不在此重复。

- **更新时间**：2026-10-18；分支 `main`。
- 本轮归档 `2026-10-18-upgrade-dependencies-2026-10`（skip_specs）：全栈依赖升级至
  2026-10-18 最新稳定版——Python lock 刷新 + filelock 4（跨进程锁验证过）；前端
  eslint 10 / vite 8（Rolldown）/ TS 6.0.2 / sigma 4（GraphCanvas 适配 + 亮暗视觉回归）/
  react 19.3.1 / marked 18.1.1（ReDoS 修复）；Rust tauri 2.12.4 + ureq 3 + edition 2024；
  setup-uv v10.3.0 + pre-commit-hooks v6。评审证据与决策记录见该归档 review.md。
- 排序队列已清空，下一项待 owner 对齐排序；ROADMAP 触发器台账本轮新增四条
  （TS 7、Node 26、lancedb FTS 重评、typer 上界）。

## 验证状态

- pytest **862**；ruff 双清；`openspec validate --specs --strict` **9/9**；`--changes` 无活跃。
- ui vitest **133**、`npm run build` 绿；lint **0 error / 9 warn**（warn 全部是
  `react-hooks/set-state-in-effect`，刻意降级，见下）。
- Rust：fmt/clippy -D warnings/test **11** 绿；sidecar 产物门禁本机 arm64 通过
  （641 MiB，pandoc 3.11 SHA-256 校验随包）；Windows/Linux 平台留 CI。
- 本机 pytest 口径：`env -u DASHSCOPE_API_KEY uv run python -m pytest -o addopts=""`
  （该 key 致假红）。UI 门禁必须在 `ui/` 内跑（根目录 npx 命中假包）。

## 必须保留的判断

- **依赖升级遗留口径**：TS 钉 `~6.0.2`（TS 7 被 typescript-eslint `<6.1.0` 阻断，触发器
  已记 ROADMAP）；tauri MSRV 1.90；typer 留 0.26.8（docling-core 上界 `<0.27`）；
  `react-hooks/set-state-in-effect` 9 处为取数模式债务，独立重构清零后恢复 error。
- **协议越界新契约**：`ask_readiness.invalid` 与请求期同源；读取面文件层可读恒 200；
  serve 统一容忍供给配置错误启动；请求面 503 `invalid_settings` 零漂移。不要改回。
- 场景名「坏文件叠加上层协议越界时归一化失败」按硬规则保留旧名，不要顺手改名。
- MCP：不监听端口、无鉴权面；`--vault`/`--data-dir` 须绝对路径；SDK 上界 `>=2,<3` 保留。
- 基线：改检索链路必须过 `dashscope-text-embedding-v3` 通道门禁；本地 Ollama 通道仍缺。
- **图谱自动刷新（`graph_auto_refresh`，缺省关）**：自动路径只维护既有快照——不创建
  图谱、不重建失效快照、不生成 wiki；身份闸门记 (extractor_id, model_id, prompt_version)，
  换模型跳过并要求显式更新（防静默全量重抽烧 key）。
- 既有判断：非法协议取值挡在输入边界；`config_file_unreadable` 禁止覆盖、serve 对该型
  快速失败；CLI `siku wiki` 无 `--vault` 互斥边界；主题机制只用 Mantine 内建三态。

## 既有待办与外部边界

- **多平台打包（owner 2026-10-10 明示除外）**：Windows/Linux 实机安装冒烟维持豁免；
  Phase 6 签名/自动更新维持 2026-10-02 终态裁决无限期缓滞（双条件齐备才重启）。
- 本地 Ollama 通道基线：待在线环境按 benchmarks/README.md 补录（触发器台账已记）。
- 2026-10-17 登记（HEAD 既有、范围外，未顺手修改）：`tests/test_api_sync.py:252-260`
  轮询 `snapshot` 可能未绑定；`src/siku/graph/providers.py:229,249` 两处 `Unknown | None`；
  其余既有 pyright 错误（全树 52 处，多为测试文件）。mypy 有既有解析错误且非门禁
  （2.4 与 2.3.1 输出一致，零新增）。
- pi-lens 检查器模块索引可能滞后于新建模块，以 pyright/测试/运行时导入为准。
- GUI 进程读不到 shell env；sidecar 注入不是当前目标。
- openspec：主规格 Requirement 正文 ≤500 字符是 CLI 新增强检查。

## 本机执行口径

- `ui/` 真正锁文件是 package-lock.json；用已有 `node_modules/.bin`，不跑会触发
  install/孤儿锁文件的 pnpm 11 命令；`ui/node_modules` 缺失就按锁文件 `npm ci`。
- 仓库迁移后 hook 路径失效用 `.venv/bin/python -m pre_commit install` 重生，禁用
  `--no-verify`。
- pandoc 构建缓存在 `~/.cache/siku-build/pandoc/<triple>/`；重建 sidecar 直接
  `uv run python scripts/build_sidecar.py`。
