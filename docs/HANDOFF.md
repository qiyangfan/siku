# HANDOFF — siku 当前交接点

> 即时状态见本文；常驻规则见 `AGENTS.md`，架构/排序见 `docs/architecture.md`、
> `docs/adr/`、`docs/ROADMAP.md`。实现与评审明细在各 change 工件，不在此重复。

- **更新时间**：2026-10-02；分支 `feature/adopt-mantine-ui-components`。
- 本轮实施、验证并归档 `2026-10-02-dark-theme`（暗色三态主题）：Mantine 内建三态
  （auto 初值 + 库默认存储键持久化）、resolver light/dark 分流取值（守卫钉对比度）、
  两处 HTML 接 `ColorSchemeScript` 同源初始化脚本（带防漂移守卫）、壳页暗色块同源、
  header 切换入口、图谱边线/标签色随主题。守卫先行先红后绿，独立评审放行。
  改动随本次提交入库（含代码、守卫测试、规格 sync、文档与归档工件），**未推送**。
  顺带核销既有待办：`cli.py` `_fail` 的 `%s` 异常文本
  记录改与 serve 启动面同口径（只记 `error_class`，异常文本交 `exc_info`）。

## 当前队列（按 ROADMAP 执行）

1. 排序队列已清空：2026-10-02 三项全部归档入库，下一项待 owner 对齐排序
   （`docs/ROADMAP.md` 排序队列区为唯一队列）。
2. 2026-10-02 已归档三项（明细见各自 archive 工件）：
   - `archive/2026-10-02-dark-theme`：web-ui 主规格新增「主题三态与两态对比度」需求；
     review.md 含对比度取证、四级主题路径冒烟与独立评审结论（7 项必查合格，无 P0/P1）。
   - `archive/2026-10-02-complete-desktop-format-ingest`：pypdf 默认 PDF、Office 进核心、
     pandoc 随包、三平台产物门禁；ADR-0013 接受。
   - `archive/2026-10-02-remove-manual-library-document`：`POST /api/library/remove`、
     `removable`、无模型索引消减、图谱/Wiki 快照失效、filelock 写互斥。

## 验证状态

- 全量 pytest **802 通过**；ruff 干净；UI vitest **126 通过**（净增 12）、
  tsc/eslint/vite build 通过；OpenSpec 主规格 **8/8** 严格校验通过。
- UI 三视口（375/768/1280）× 亮暗两态冒烟 + 四级主题路径（系统暗→刷新→手动覆盖→
  清除回系统）+ 壳启动页两态，内嵌浏览器实测通过；证据见归档 review.md。
- 独立评审放行；P2 已处置（accent-wash 余量备注落 theme.ts；壳页 token 未逐项
  测试断言留痕 review.md）。

## 上一批状态与必须保留的判断

- 非法协议取值在输入边界拒绝；不要恢复已回滚的运行期容忍/禁用选项方案。
- 文件不可解析沿 `invalid_config_file` 自救；不可读取沿 `config_file_unreadable`
  禁止覆盖。
- 全量 purge 中 missing/superseded 的索引追平仍依赖任务收尾增量同步（需当时 BYOK
  可用）；`user_removed` 收尾不受该依赖影响。
- CLI `siku wiki` 无 `--vault`，互斥以默认 vault 锚定——见归档 review「已知边界」。
- golden set 实端点基线沿用 2026-09-19 用户豁免；fake 链路有测试覆盖。
- 主题机制只用 Mantine 内建三态，不要自造存储键/监听/解析；暗色对比度有守卫钉住，
  调 ramp 前先看 design-system.test.ts。

## 既有待办与外部边界

- 「siku 走查发现 2026-09」清单已找回(2026-10-02,存于 siku 会话记忆
  `siku-ui-audit-2026-09.md`,P2×3+P3×6 共 9 项),逐条对码核销:
  ①ink-faint 对比度(现值 #545f6e,守卫 design-system.test.ts)②跨视图文件名溢出
  (browse/library 统一 overflow-wrap:anywhere+2 行钳制)⑤graph-chip 触控高度
  (min-height: var(--control-height))⑥破坏性确认 danger 色(button-danger/-solid)
  ⑨边框 token 卫生(0.0625rem/1px 混写零残留)——5 项已核销;
  ④日期裸 toLocaleString 随宿主 locale 漂移——2026-10-02 已修,单源
  `ui/src/datetime.ts` 固定 zh-CN(LibraryView/WikiView 改走);
  ⑦「总目」判误报(wiki 模块正式用语,与 WikiView 两处一致,非笔误);
  剩余 2 项待实机走查复核:③375px 资料库文件名列挤行 ⑧fieldset legend 骑边框
  ——需起 serve/桌面壳目检,随下次 UI 批次销项。
- GUI 进程读不到 shell env；sidecar 注入不是当前目标。
- Phase 6 签名/自动更新：**owner 2026-10-02 终态裁决，无限期缓滞**——证书到位且
  owner 明确指令双条件齐备才重启；期间不作为待办、不反复评审。
- CI 三平台 sidecar 作业与 release 门禁未在本地跑过（需推送后由 Actions 实跑）。
- Windows/Linux 实机安装冒烟维持 2026-09-19 豁免，发布解禁时按 `docs/desktop.md` 回填。

## 本机执行口径

- pytest 用 `env -u DASHSCOPE_API_KEY uv run python -m pytest -o addopts=""`：
  `uv run pytest` 直呼在本机稳定 spawn 失败；DASHSCOPE_API_KEY 致测试假红，须隔离。
- `ui/` 真正锁文件是 package-lock.json；直接用已有 `node_modules/.bin`，
  不运行会触发 install/孤儿锁文件的 pnpm 11 命令。
- 仓库迁移后 hook 路径失效用 `.venv/bin/python -m pre_commit install` 重生，
  禁用 `--no-verify`。
- mypy 有既有错误且不是当前门禁；发生真实失败先归因，不能据历史记录假定本轮通过。
- pandoc 构建缓存在 `~/.cache/siku-build/pandoc/<triple>/`；重建 sidecar 直接
  `uv run python scripts/build_sidecar.py`。
