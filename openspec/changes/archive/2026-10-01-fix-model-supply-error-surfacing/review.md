# 评审记录：fix-model-supply-error-surfacing

- **评审方式**：独立子代理逐条溯源两轮（R1 覆盖本变更全部未提交 diff，R2 专查 R1 修复自身引入的问题），
  主对话按结论修复后复验；允许评审者实跑 `pytest` / `vitest` / `ruff`，禁止改代码使其变绿。
- **评审时间**：2026-10-01
- **判据权威**：本 change 的 proposal/design/tasks/specs delta + `AGENTS.md` + `docs/adr/`；
  注释与文档只说明过去的意图，代码实际行为才是事实。

## 结论

初评「需修复后收口」。R1 确认 4 项真缺陷、排除 1 项；R2 确认 4 项（全部由 R1 的修复引入）、
登记 1 项限制。**全部修复项已复验，可收口**（唯一残留是一条需扩对外契约才能收口的显示精度问题，
不构成假性闭环，见文末）。

## R1 修复项

- **[P1] 坏配置文件的「保存自救」在桌面面不可达**：`ui/src/SettingsView.tsx` 的读取失败早退分支
  把表单与保存按钮一起藏掉，用户只剩「重试读取」，而 GET 的 503 文案承诺
  「可在『设置』页重新填写并保存」——指引不可执行，本变更的核心承诺只在内核侧成立。
  处置：拿到 HTTP 错误响应（=服务可达，PUT 同样可达）时新增显式确认按钮
  「确认以空配置覆盖本机配置文件并重新填写」，确认后以 `BLANK_CHANNEL_VIEW` 基底出图、不伪造
  `config_path`；连接失败仍保持阻断。破坏性动作以按钮文案本身完成告知，未新增契约字段。
- **[P2] 第三种成因被「未配置」顶替**：`model_supply.load_config` 的 `OSError` 分支抛基类
  `ModelNotAvailableError`，与「通道未配置」共用文案，用户被告知去补一个其实配好了的字段，
  且 `PUT` 同面被堵。处置：新增 `ModelConfigFileUnreadableError`（挂基类**子类**位，
  既有 `except ModelNotAvailableError` 处理器零回退），`api/messages.py` 给独立 cli/http 两套文案；
  `PUT` 的覆盖分支仍只捕 `ModelConfigFileError`（读不到不覆盖，spec 判据）。
- **[P2] 启动横幅自相矛盾**：`cli._announce_supply_channels` 的 `except ModelNotAvailableError`
  把文件故障吞成 `embedding=未配置 / rerank=none（RRF-only）`，与 serve 上一行刚打的
  「配置文件不可解析」告警冲突（serve 容忍坏文件继续启动后，两个通道的解析会再读同一个坏文件）。
  处置：`ModelConfigFileError` 单独分支播报「非未配置」；`_llm_config_error_message` 改为
  直接映射异常实例，不再合成假异常取文案。
- **[P3] 前端类型与契约不符**：`ui/src/api.ts` 把 `invalid_config_file_overwritten` 声明为必填，
  而 `contracts/openapi.json` 里它是 `default: false` 且不在 `required`。改为可选 + 读取处 `?? false`。
- **[排除] 「`--{channel}-api-key-env` 会为 llm 拼出不存在的 `--llm-api-key-env`」**：
  查构造点，`ModelCredentialError` 只在 `retrieve/api_providers.py` 以 `embedding`/`rerank` 抛出，
  llm 的 401/403 走 `graph/errors.py::LlmAuthError` 另有分支，路径不可达。未改。

## R2 修复项（全部为 R1 引入）

- **[P1] `api/settings.py::map_probe_error` 漏捕新类**：连通探测面把权限/IO 故障落回
  「embedding 端点配置不完整：请检查该通道的 base_url、model 与 api_key」——正是本变更 spec
  禁止的顶替（评审者实跑该函数复现）。补独立分支 + HTTP 用例。
- **[P2] R1 新加的 unreadable 横幅分支是死码，且用例只测 mock**：`siku serve` 对 unreadable 在
  LLM 解析处即 `_fail` 退出（实测：临时 `HOME` + `chmod 000`，输出即新文案，进程未起服），
  横幅永不打印；原用例靠 monkeypatch 两个 resolver 才进得去。删除该分支（`_config_file_gap_text`
  只留可达路径），用例改打到真实行为：`runner.invoke(serve)` 断言 exit 1 + 「无法读取」+ 不含「补全」，
  并加 `uvicorn.run` 护栏防意外起服挂住整轮。
- **[P2] spec 只描述横幅侧行为而实现止于启动面**：model-supply delta 的「读不到文件不等于通道未配置」
  补上「`siku serve` 在该情形快速失败退出」的判据；另补「读取失败后设置页仍能进入覆盖自救」场景。

## 真机验收（评审者要求补，此前只有 pytest 背书）

临时 `HOME=/tmp/siku-smoke-home` 只放一份写坏的 `Library/Application Support/siku/config.toml`，
`siku serve --port 8123` 实跑（本机真实配置文件全程未被读写，产物跑完即删）：

1. 启动横幅 `embedding=配置文件不可解析（非未配置，可在设置页重新保存覆盖）`；
2. `GET /api/settings` → 503「模型配置文件不可解析（内容已损坏）…」；
3. `PUT` → 200 且 `invalid_config_file_overwritten=true`，落盘为新内容，随后 `GET` → 200（自救闭环）；
4. 改 `chmod 000` 后 `GET`/`PUT` 均 503，文案「当前无法读取（权限或磁盘故障，不是内容损坏）」
   不含「补全」，`cmp` 证原文件逐字节未动。

## 限制（未收口，需 owner 决定是否扩契约）

三型供给故障共用 `code=model_not_available`，客户端无从区分「内容不可解析」与「权限读不到」，
故设置页的覆盖入口对后者也会出现、点下去必被服务端拒绝（空配置告警块已写明「只在内容损坏时
可覆盖」，且保存失败会给准确原因——属误导入口，不损坏数据）。要精确显示需在 GET/PUT 响应加一个
判别字段，属对外契约扩张，未擅动。

## 门禁

`.venv/bin/python -m ruff check src tests` / `ruff format --check`（106 files）绿；
`pytest` **724 passed**；`ui`：`tsc`、`eslint`、`vitest` **109 passed**；
`openspec validate --specs --strict` **8/8**、`--changes --strict` **1/1**。

`mypy src/siku` 剩 3 条错，全部落在 `graph/providers.py:229-255` 的协议文本抽取段
（`parts` 重定义 + `join` 收到 `list[Any | None]`）——该段属 2026-09-26 已提交的
`add-llm-protocol-adapters`，本变更在该文件的 diff 只有 401/403 分型一处，不属本批范围，
登记为相邻存量问题（siku 的 CI 与 AGENTS 均未把 mypy 列为门禁，故非门禁破口）。
