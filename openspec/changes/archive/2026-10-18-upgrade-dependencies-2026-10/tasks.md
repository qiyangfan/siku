# 任务清单

每批独立验证、独立提交；闸门命令见 design.md 验证策略。

## 批次 A：Python lock 刷新（无风险批）

- [x] `uv lock --upgrade`（filelock 钉在 3.x 不动，留批次 C）刷新 fastapi/pydantic/
  pydantic-settings/uvicorn/typer/networkx/pyarrow/lancedb/pypdf/docling(extra) 至
  2026-10 最新稳定；确认 httpx/mcp/pytest 系/pyinstaller/reportlab/hatchling 无版本移动。
- [x] 全量 pytest 绿；重点盯 pydantic-settings 2.16（validation_alias/alias 行为）与
  lancedb 0.40 + pyarrow 26 组合的向量相关测试；若 lancedb+pyarrow 组合异常，按 design.md
  回退组合执行并在 review.md 记录。

## 批次 B：工具链消化

- [x] ruff 0.17.1 升级：跑 `ruff format` 与 `ruff check --fix`，消化 format diff、F406
  等默认规则集变化带来的机械改动，lint/format 双绿。
- [x] mypy 2.4 全量通过：先 grep 确认无 `for`/`with` 目标 `# type:` 注释存量，native
  parser 默认开启后全量无新增报错。

## 批次 C：filelock 4 专项

- [x] filelock 升至 4.2.2（lock 层面）；确认 `src/siku/sync/locking.py` 无需改码
  （事前核查见 design.md）。
- [x] 跨进程写互斥验证：既有并发锁测试全绿 + 手工双进程（serve + CLI 写命令）冒烟
  互斥与快速报忙行为不变；结论记 review.md。

## 批次 D：前端 minor/安全批

- [x] react 19.3.1 / react-dom 19.3.1 / @mantine 9.7.3 / @tabler/icons-react 3.49 /
  marked 18.1.1（ReDoS 修复）/ dompurify 3.4.17 / vitest 5.0.5 / jsdom 30 /
  @testing-library/jest-dom 7（确认 @testing-library/dom peer 满足）/
  @tauri-apps/cli 2.12.3；lint/test/build 绿。

## 批次 E：eslint 10 全家桶（绑定批）

- [x] eslint 10 + @eslint/js 10 + typescript-eslint 8.71.2 + eslint-plugin-react-hooks 7
  + eslint-plugin-react-refresh 0.5.7 + globals 17 同批升级；消化 `eslint:recommended`
  新增规则的告警；全量 lint 绿。
- [x] 核对 typescript-eslint 支持区间（`<6.1.0`）作为批次 G 前提。

## 批次 F：vite 8（绑定批）

- [x] vite 8.3.4 + @vitejs/plugin-react 6.1.2 同批升级；逐项核对 `vite.config.ts`
  配置在 Rolldown 打包器下生效（防"静默失效"）；dev server 冒烟 + 产物构建回归 +
  全量 vitest 绿。

## 批次 G：TypeScript 6.0.2

- [x] `~5.9.2` → `~6.0.2`；全量 `tsc -b` 绿；按弃用告警清理 tsconfig（TS 7 移除项
  如 `baseUrl` 类），不做超前的行为性重构。

## 批次 H：sigma 4 + 图谱视觉回归

- [x] sigma 4.0.3 升级 + `ui/src/GraphCanvas.tsx` 适配：删 `defaultEdgeType: "line"`、
  核对 `itemSizesReference` 观感（必要时显式 `"screen"`）、label 系列设置过类型检查；
  graphology/forceatlas2 版本不动。
- [x] 图谱视图视觉回归：亮/暗主题下节点/边/标签渲染、点击实体联动问答、缩放行为
  与升级前一致（截图对照记 review.md）。

## 批次 I：Rust 桌面壳

- [x] `cargo update` 同窗升级 tauri 2.12.4 / tauri-build 2.7.3 /
  tauri-plugin-single-instance 2.5.4（wry/tao 随依赖解析）；`cargo fmt/clippy/test` 绿。
- [x] ureq 3.4.2：迁移 loopback 健康检查调用点（typestate builder + body API），
  features 仅保留 tls，clippy/test 绿。
- [x] edition 2021→2024：`cargo fix --edition` + 人工排查 `static_mut_refs` 与
  临时值 drop 时机；`rust-version` 声明按需更新；全量 Rust 门禁绿。

## 批次 J：CI 与 hooks

- [x] `.github/workflows/ci.yml` 与 `release.yml`：setup-uv v10.2.0 → v10.3.0；
  确认官方 Actions 五件套维持最新 major 不动。
- [x] `.pre-commit-config.yaml`：pre-commit-hooks v5 → v6.0.0（未用被移除 hook id，
  事前已核查）、ruff-pre-commit rev → v0.17.1；`pre-commit run --all-files` 全绿。

## 收尾

- [x] sidecar 产物门禁复跑：`scripts/check_sidecar_artifacts.py` 本机可跑平台形态
  检查通过（filelock 4 / lancedb 0.40 / pyarrow 26 进包）；三平台完整门禁留 CI 佐证。
- [x] 确认无检索链路文件改动（golden set 免跑声明）；全量 pytest + ui vitest 最终
  各一遍绿，数字记 review.md。
- [x] 独立评审 `review.md`（证据已写入，含三项评审决策与归档前待办）；归档时向
  `docs/ROADMAP.md` 触发器台账写入三条（已随 2026-10-18 归档写入）：
  ① typescript-eslint 宣布支持 TS 7 → 另开 TS 7 升级件；② Node 26 进 LTS（2026-10-28
  已过）→ 例行维护顺手切换 CI Node 版本；③ LanceDB 原生 FTS 重评——上游 #4516
  （并列分顺序不稳定）与 #4364（自定义分词器）关闭、且 golden set A/B 对比不降 →
  另开 FTS 迁移件；并勾稽本 change 完成状态。
