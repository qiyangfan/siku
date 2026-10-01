# HANDOFF — siku 当前交接点

> 本文件只记录接手者马上需要的状态；常驻规则见 `AGENTS.md`，架构与排序见 `docs/architecture.md`、
> `docs/adr/`、`docs/ROADMAP.md`。每个 change 的取舍、评审与反向验证明细留在其归档件
> （`openspec/changes/archive/<件>/{proposal,design,tasks,review}.md`），不在此复述。

- **更新时间**：2026-10-01；分支 `feature/adopt-mantine-ui-components` 与 origin 同步，
  活动 openspec 变更为零，工作区仅剩下述待裁项对应的未提交改动。

## 本批完成：模型供给错误三面分型 → 成因码分道（两件均已归档推送）

- 归档 `2026-10-01-fix-model-supply-error-surfacing`：凭证被拒 / 未配置 / 内容不可解析 /
  内容读不到四类故障各有异常类与可行动文案；坏 TOML 允许「重新保存覆盖」自救，读不到禁止覆盖。
- 归档 `2026-10-01-settings-error-cause-codes`：分型推到机器可读面——HTTP `code` 为
  `invalid_config_file`（保存可修）/ `config_file_unreadable`（内容未知，禁止覆盖）/ 其余仍
  `model_not_available`，两个映射点（`api/messages.py::map_domain_error`、`api/settings.py::map_probe_error`）
  同码；设置页覆盖自救入口**只由第一个码驱动**，客户端禁止再用「服务可达与否」猜「保存能否修好」。
  同批修掉：单请求重复读配置文件、`PUT` 落盘后装配抛领域错误返 500（把成功说成失败）、
  `cli.py` 坏文件分支漏裸 traceback、降级响应静默丢掉覆盖告知与重建告警。

## 待裁（一条真实死路，需 owner 定方向才能收口）

**文件层 `[llm] protocol` 越界时桌面用户没有任何出路**：`GET /api/settings` 返 503
`invalid_settings`，文案指着「在设置页重新选择协议并保存即可覆盖」，但入口按成因码收窄后
**不给这个码**（页面只剩「重试读取」）；且 `siku serve` 对该状态启动即 fail-fast（实测 exit=1、
端口拒连），sidecar 连页面都进不到。实测该状态 `PUT` 修正 protocol 即 200、再 `GET` 200——
能修，只是 UI 不给路径。收口须动对外交互规则，故暂停：技术决策取**①**——`ProtocolConfigError`
携带来源层（file/env/cli）→ serve 只容忍文件层并明示 → 设置页出「仅修正协议」控件；
它不动读取面「与请求期同源失败」的铁律，也不新增响应字段。②（`GET` 返 200 带视图、以
`ask_readiness.missing` 表达不可用）被否：会顶掉主规格既有场景，且重演下面这条已回退的岔路。

**别再走的老岔路**：让 `GET` 对**不可解析**的坏文件返回 200 + 降级标记——请求期每请求现读该文件，
容忍必然造出「设置页说就绪、真实请求 503」的误就绪，比死路更难排查（判据已写进 http-api 主规格）。

## 门禁与本机执行口径

- `pytest` **733 passed**（较上批 724 净增 9 条，逐条做过「撤掉修复即红」）、`ruff check`/
  `format --check`/`pre-commit run --all-files` 绿；`ui`：`tsc`/`eslint`/`vitest` **109 passed**/
  `vite build` 绿；`openspec validate --specs --strict` **8/8**。
- `pytest` 直跑不出汇总行（`addopts` 已含 `-q`，再 `-q` 即 `-qq`），要计数用 `-o addopts=""`。
  `ui/` 下禁用 `pnpm exec`/`pnpm test`：pnpm 11 先跑 install、在 `ERR_PNPM_IGNORED_BUILDS: esbuild`
  处退出并写出孤儿 `pnpm-lock.yaml`/`pnpm-workspace.yaml`（真正锁文件是 `package-lock.json`），
  直接调 `./node_modules/.bin/*`。`.git/hooks/pre-commit` 的 `INSTALL_PYTHON` 会随仓库迁移失效，
  用 `.venv/bin/python -m pre_commit install` 重生，禁止 `--no-verify`。

## 相邻存量与边界（均不在本批 diff 内）

- `invalid_protocol_message` 的 `llm_enum` 文案断言「值来自本机配置」，env 层来源时页面保存覆盖不了
  ——与上面待裁项同根，随其一并收口。`cli.py` 其余 `except` 分支仍把异常文本 `%s` 记进日志
  （实测不含凭证，属口径不齐）。
- `mypy src/siku` 在 `graph/providers.py:229-255` 报 3 条错，属 2026-09-26 已提交段；
  siku 未把 mypy 列入门禁，故非门禁破口。
- **已核不缺陷**（免重复排查）：`retrieve/errors.py:70/:79` 两型是兄弟类，映射链无 isinstance 影子；
  设置页状态机（`loadErrorCode`/`blankFormConfirmed`）经条件挂载分析无残留态。
- 「siku 走查发现 2026-09」清单：ink-faint 对比度项已销，余项待修（清单本体不在仓内）。
- 桌面 GUI 进程读不到 shell 环境变量：env 回退只在终端 `serve` 生效，sidecar 注入是 Non-goal。
- Phase 6（Apple 公证 / Windows 签名 / 自动更新）需付费证书，属外部条件；Windows/Linux 实机安装
  冒烟沿用 2026-09-19 豁免裁决，发布解禁时按 `docs/desktop.md` 回填。
