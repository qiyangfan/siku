# HANDOFF — siku 当前交接点

> 本文件只记录接手者马上需要的状态；常驻规则见 `AGENTS.md`，架构与排序见 `docs/architecture.md`、
> `docs/adr/`、`docs/ROADMAP.md`。每个 change 的取舍、评审与反向验证明细留在其归档件
> （`openspec/changes/archive/<件>/{proposal,design,tasks,review}.md`），不在此复述。

- **更新时间**：2026-10-01；分支 `feature/adopt-mantine-ui-components`，工作区有本批未提交改动
  （尚未获提交指示）。活动 openspec 变更：**无**（本批已归档，见下）。

## 上一批（已归档推送）：配置故障成因码分道

`fix-model-supply-error-surfacing` + `settings-error-cause-codes`：凭证被拒 / 未配置 /
内容不可解析 / 内容读不到四类故障分型分文案（`invalid_config_file` 保存可修 /
`config_file_unreadable` 禁止覆盖 / `model_not_available` / `invalid_settings`），
两个映射点（`messages.py::map_domain_error`、`settings.py::map_probe_error`）同码；
设置页覆盖自救入口只由第一个码驱动。细节见归档件。

## 本批（已归档，**未提交推送**）：非法取值挡在输入边界之外

死路来源：手改 `[llm] protocol = "gemini-native"` 时读取面整资源 503、设置页只剩
「重试读取」，而 503 文案让用户去那个页面保存；`siku serve` 同处退出，sidecar 进不到页面。
**第一版「让非法状态可见」已实现并整体回滚**（`ask_readiness.invalid`、
`ProtocolConfigError.layer`、启动面按层容忍、UI 塞禁用项）：容忍本身就是坏设计，
**非法状态不该活到运行期**，别在这条路上再捡回来。

现行做法（openapi schema/字段/路径零 diff、UI 零改动）：

- 文件层：`load_config` 在段结构校验后校验协议取值（`_reject_invalid_file_protocols`，
  作用于 `_drop_blank` 归一后形状），坏值抛 `ModelConfigFileError` → 继承既有
  `invalid_config_file` + 设置页覆盖自救闭环。异常新增 `detail`（只给字段名与合法名单，
  **不回显用户原值**）。
- 命令行：`--llm-protocol` 改 `StrEnum` 参数，坏值解析阶段 exit 2。
- env/程序传入层无载入边界，仍在解析时拒；文案单源到 `messages.py::protocol_error_mapping`
  （读出面与探测面共用），按 `surface` 分文且只点名真杠杆——`llm` 枚举越界只有
  `SIKU_LLM_PROTOCOL`（`--llm-protocol` 是枚举参数，不是来源），`channel_unsupported`
  只有「程序传入的配置」。删掉 `invalid_protocol_message`、`validate_channel_protocols`、
  CLI 面自带的两份协议文案。

**门禁**：`pytest -o addopts=""` **744 passed**（较 733 净增 11，全部做过撤掉修复即红）、
`ruff`/`pre-commit` 绿、`mypy` 4 errors 全为 HEAD 既有、ui `vitest` **109 passed**、
`--specs --strict` **8/8**；冒烟用临时 `HOME=/tmp/siku-bound`，本机 config.toml 未读写。
归档件：`openspec/changes/archive/2026-10-01-validate-supply-values-at-boundaries/`。

## 待办与边界

- **下一步只剩提交推送**（未获指示，等用户）：本批 14 个源/测试文件 + HANDOFF + 归档件未提交。
- `cli.py` 其余 `except` 分支仍把异常文本 `%s` 记进日志（实测不含凭证，属口径不齐）。
- 「siku 走查发现 2026-09」清单：ink-faint 对比度项已销，余项待修（清单本体不在仓内）。
- 桌面 GUI 进程读不到 shell 环境变量：env 回退只在终端 `serve` 生效，sidecar 注入是 Non-goal。
- Phase 6（Apple 公证 / Windows 签名 / 自动更新）需付费证书，属外部条件；Windows/Linux 实机
  安装冒烟沿用 2026-09-19 豁免裁决，发布解禁时按 `docs/desktop.md` 回填。

## 本机执行口径（省时间，别重新试错）

- `pytest` 直跑不出汇总行（`addopts` 已含 `-q`，再 `-q` 即 `-qq`）：加 `-o addopts=""`。
- `ui/` 下禁用 `pnpm exec`/`pnpm test`：pnpm 11 先跑 install、在 `ERR_PNPM_IGNORED_BUILDS: esbuild`
  处退出并写出孤儿 `pnpm-lock.yaml`/`pnpm-workspace.yaml`（真正锁文件是 `package-lock.json`）；
  直接调 `./node_modules/.bin/{tsc,eslint,vitest,vite}`。
- `.git/hooks/pre-commit` 的 `INSTALL_PYTHON` 会随仓库迁移失效，用
  `.venv/bin/python -m pre_commit install` 重生；禁止 `--no-verify`。
- `mypy src/siku` 在 `graph/providers.py:229-255` 报 3 条错，属 2026-09-26 已提交段，
  siku 未把 mypy 列入门禁，故非门禁破口。
