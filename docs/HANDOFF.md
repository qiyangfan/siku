# HANDOFF — siku 当前交接点

> 即时状态见本文；常驻规则见 `AGENTS.md`，架构/排序见 `docs/architecture.md`、
> `docs/adr/`、`docs/ROADMAP.md`。实现与评审明细在各 change 工件，不在此重复。

- **更新时间**：2026-10-02；分支 `feature/adopt-mantine-ui-components`。
- 本轮把 2026-10-02 提出的两个 change 全部实施、验证并归档；改动随本次提交
  入库（含代码、依赖锁、契约快照、文档与归档工件），**未推送**。
- 跨仓/外部依赖事项（CI 三平台作业待 Actions 实跑、pandoc 上游资产锁定）已
  写入上级 `longzhong/HANDOFF.md` 的 siku 批次小节。

## 当前队列（按 ROADMAP 执行）

1. 无活跃 change；两个 2026-10-02 change 已归档：
   - `archive/2026-10-02-complete-desktop-format-ingest`：pypdf 默认 PDF、Office
     库进核心、pandoc 3.11 随包（`scripts/resources/pandoc.json` SHA-256 锁定），
     三平台产物门禁入 ci.yml/release.yml。ADR-0013 已接受，ADR-0004 修订。
   - `archive/2026-10-02-remove-manual-library-document`：`POST /api/library/remove`
     与 `siku remove`、清单 `source_id`/`removable`、无模型索引消减
     （`retrieve/reduction.py` 暂存对恢复）、图谱/Wiki 快照失效、filelock
     同库写互斥（`vault/.siku/library.lock`）。ADR-0010 边界已回写。

## 验证状态

- 全量 pytest **801 通过**（含独立评审第二轮 5 项缺陷修复的回归）；ruff
  check/format 干净；UI vitest **114 通过**、tsc/eslint/vite build 通过；
  OpenSpec 主规格 **8/8** 严格校验通过，两个 change 已归档、delta 已入主规格。
- 冻结 sidecar（macOS arm64，615 MiB）干净 PATH/隔离 HOME/代理黑洞环境经
  HTTP 摄取四类文档冒烟通过（`scripts/smoke_clean_env.py`）；产物检查脚本
  `scripts/check_sidecar_artifacts.py --probe` 通过。
- 独立子代理评审两轮：第一轮确认 5 缺陷（相对 vault 移除、残片砖化、恢复
  异常卡槽、CLI scan 锁外索引、purge 误报）全部修复带回归；结论见归档
  review.md「第二轮验证补充」。CI 侧三平台新作业需推送后由 Actions 执行。
- UI 三视口（375/768/1280）验收通过；「亮暗两态」不适用——产品
  `forceColorScheme="light"` 从未实现暗色，是否补暗色主题待 owner 决策。
  顺带修复既有 Switch 轨道顶贴缺陷（一属性恢复组件居中）。
- golden set 实端点基线沿用 2026-09-19 用户豁免；fake 链路有测试覆盖。

## 上一批状态与必须保留的判断

- 非法协议取值在输入边界拒绝；不要恢复已回滚的运行期容忍/禁用选项方案。
- 文件不可解析沿 `invalid_config_file` 自救；不可读取沿 `config_file_unreadable`
  禁止覆盖。
- 全量 purge 中 missing/superseded 的索引追平仍依赖任务收尾增量同步
  （需当时 BYOK 可用）；`user_removed` 收尾不受该依赖影响。
- CLI `siku wiki` 无 `--vault`，非默认 vault 布局的互斥以默认 vault 锚定
  （serve 侧全量正确）——见归档 review「已知边界」。

## 既有待办与外部边界

- `cli.py` 其他 except 分支仍 `%s` 记录异常文本，属于既有口径待办。
- “siku 走查发现 2026-09”剩余清单不在仓内；余项未核销。
- GUI 进程读不到 shell env；sidecar 注入不是当前目标。
- Phase 6 公证/签名/自动更新需证书；Windows/Linux 实机安装冒烟保持
  2026-09-19 豁免，发布解禁时按 `docs/desktop.md` 回填。
- 暗色主题未实现（`forceColorScheme="light"`）：任务文本中的「亮暗两态」
  验收项在当前产品上不适用，是否补做待 owner 决策。
- CI 新增 `sidecar-artifacts` 三平台作业与 release 产物门禁未在本地跑过
  （需推送后由 GitHub Actions 执行）。

## 本机执行口径

- pytest 用 `-o addopts=""` 得到汇总，避免已有 `-q` 再叠加变成 `-qq`。
- `ui/` 真正锁文件是 package-lock.json；直接用已有 `node_modules/.bin`，
  不运行会触发 install/孤儿锁文件的 pnpm 11 命令。
- 仓库迁移后 hook 路径失效用 `.venv/bin/python -m pre_commit install` 重生，
  禁用 `--no-verify`。
- mypy 有既有错误且不是当前门禁；发生真实失败先归因，不能据历史记录假定
  本轮通过。
- pandoc 构建缓存在 `~/.cache/siku-build/pandoc/<triple>/`；重新构建 sidecar
  直接 `uv run python scripts/build_sidecar.py`。
