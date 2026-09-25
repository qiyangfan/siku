# HANDOFF — siku 当前交接点

> 本文件只记录接手者马上需要的状态；常驻规则、架构与排序分别见 `AGENTS.md`、
> `docs/architecture.md`、`docs/adr/`、`openspec/project.md` 和 `docs/ROADMAP.md`。

- **更新时间**：2026-09-25
- **仓库/分支**：`~/siku` / `feature/adopt-mantine-ui-components`

## 本批完成

- 三个 OpenSpec change 已完整归档，deltas 已同步主规格：
  `2026-09-24-adopt-mantine-ui-components`、
  `2026-09-24-recommend-content-based-questions`、
  `2026-09-24-recover-sidecar-after-exit`；当前没有活动 change。
- UI 统一接入 Mantine Core 9.6.2，新增 ADR-0011 与设计 token 基线；桌面保留六个视图，
  移动端为问答/浏览/图谱三项底部导航，其余视图从更多菜单进入。
- 问答建议取自已导入笔记和 wiki；通用抽取标题会跳过。Tauri 壳监测 sidecar 退出或
  健康检查失败，返回本地恢复页供用户重启。
- 间距、字阶、行高、边框和圆角使用命名 token；React 样式与独立启动页都有回归约束。

## 验证与限制

- UI：lint 通过；Vitest 10 个文件、89 项通过；Vite build 通过。bundle 788.09 kB
  （gzip 235.13 kB），超过 Vite 500 kB 建议值但不阻断构建。
- Tauri：`cargo fmt --check`、`cargo check --locked`、`cargo test --locked` 通过，
  11 项测试通过。OpenSpec 规格校验 8/8 通过；无活动 change 可供 `--changes` 校验。
- 浏览器预览在 320/375/1280px 检查了导航、问答、资料库、设置、浏览、图谱与 wiki；
  受检窄屏视图均无横向溢出。真实打包应用尚未针对本批改动重新安装冒烟。
- `codex review --uncommitted` 未返回结论，zread MCP 握手缺少 `content-type`；源码与
  预览人工复审完成，未发现未修复问题。

## 下一步

- 若继续发布/安装流程，按 `docs/desktop.md` 重建 sidecar 与 Tauri 应用，并在 macOS
  实际安装包中冒烟；Windows/Linux 实机冒烟仍待对应平台 CI 产物。
- 当前 ROADMAP 队列为空。开新 change 前先按 `docs/ROADMAP.md` 对齐排序；常驻技术
  决策不复制到本文件。
