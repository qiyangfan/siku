# HANDOFF — siku 当前交接点

> 本文件只记录接手者马上需要的状态；常驻规则、架构与排序分别见 `AGENTS.md`、
> `docs/architecture.md`、`docs/adr/`、`openspec/project.md` 和 `docs/ROADMAP.md`。

- **更新时间**：2026-10-01
- **仓库/分支**：`~/siku` / `feature/adopt-mantine-ui-components`（错误分型三批已提交并推送；
  成因码本批（`settings-error-cause-codes`）随本文件同批入库）

## 本批完成：配置故障成因码分道与「落盘事实」保真

openspec change `settings-error-cause-codes`（已归档 `2026-10-01-settings-error-cause-codes`：
任务全勾 + `review.md` 两轮独立复核 + 门禁全绿，delta 已 sync 进 `http-api` / `model-supply` 主规格）。
收掉上一批 review.md 文末那条「不改契约就无法收口」的限制：

1. **成因码分道**：`map_domain_error` 与 `map_probe_error` 两个映射点给配置文件两型各自稳定的
   `code`——内容确证不可解析 `invalid_config_file`（保存可修）、内容未知（权限/IO 读不到）
   `config_file_unreadable`（保存不可修）；其余供给错误仍 `model_not_available`。状态码 503、
   `{code, message}` 结构、文案均不变——是把已有的异常分型推到机器可读面，不是新增行为。
2. **设置页自救入口由码驱动**：`loadErrorCode === "invalid_config_file"` 才给
   「确认以空配置覆盖本机配置文件并重新填写」，删掉「拿到错误响应 = 服务可达 = 可覆盖」的启发式
   （它对读不到型也会给入口，点下去必被服务端拒）。**中途试过并否掉的方案**：`GET` 对坏文件返
   200 + `config_file_invalid` 标记——请求期每请求现读该文件，读面一旦容忍就会出现
   「设置页说就绪、真实请求 503」的误就绪，比死路更难排查；已回退，别再走。
3. **同一请求只读一次配置文件**：`PUT` 响应的 `llm_env_fallback` 改传 `config=merged`
   （此前通道视图用 merged、回退判定再 `load_config()` 一次，是两套事实源）。
4. **落盘后不得谎报保存失败**（评审 R1 抓出）：就绪判定含 env/cli 层而写入前校验只管文件层，
   env 层协议越界会让 `PUT` 在文件已写好之后从 `try` 外抛穿、由全局兜底返 500 `internal_error`。
   现按 `GET` 面同一口径给码（503 `invalid_settings`）并在文案声明「本次提交的配置已写入本机
   配置文件」。**可达性口径**：`siku serve` 对 env/cli 层协议越界是启动即 fail-fast，故这条只在
   直接使用 `create_app()` 的形态可达，由进程内用例覆盖，未声称端到端验过。
5. **启动面不再漏 traceback**（评审 R2 真机冒烟抓出的既有缺陷，非本批引入）：`cli.py` 坏文件分支里
   「以空文件层再解析一次」抛出的 `ProtocolConfigError` 出自 `except` 块内部，不会被同一 `try` 的
   后续 `except` 接住，实测漏出完整 traceback 后退出。改为内层 `try` 嵌套归 `_fail`，
   用户面现为三行归一化文案（不可解析明示 → warning 记类名 → 协议取值指引），exit=1。

**验证**：`pytest` **731 passed**（本批新增 6 条用例，全部做过「撤掉修复即红」的反向验证：
把两个成因码改回 `model_not_available` → 三条同时红；把 `config=merged` 改回不传 → 单读用例红
`assert 2 == 1`；拆掉 `cli.py` 内层 `try` → 启动面用例红）；`ruff check`/`format --check` 绿；
`ui` `tsc`/`eslint`/`vitest` **109 passed**/`vite build` 绿；`--specs --strict` **8/8**、
`--changes --strict` 归档前 **1/1**。真机冒烟（临时 `HOME=/tmp/siku-r5` + 临时 vault/data，跑完即删，
本机真实 `config.toml` 全程未读写）：坏 TOML → serve 起服、`GET` 503 `code=invalid_config_file`、
`PUT` 200 `invalid_config_file_overwritten=true`、再 `GET` 200；坏 TOML 叠加
`SIKU_LLM_PROTOCOL=totally-bogus-protocol` → 归一化三行退出、`grep -c Traceback` = 0。
`chmod 000` 一型**只能进程内验**：该情形 serve 依约快速失败、根本不监听，故其「GET/PUT 均 503 +
不覆盖 + 原文件逐字节未动」由 `tests/test_api_settings.py` 断言（含 `cmp`）。

**排除的臆断（评审提出、经查不成立，记此免重复排查）**：① `ModelConfigFileUnreadableError` 被
`ModelConfigFileError` 分支提前吞掉——两型是兄弟（`errors.py:70/:79` 同直接继承基类），`issubclass`
双向 False，四条映射链实测各归其码；② UI 里 `loadErrorCode` 二次失败残留、`blankFormConfirmed`
在无错误时仍出黄色告警——`load()` 开头成对清零 + `App.tsx` 条件挂载切页即重挂，两路不可达。

## 上一批完成：模型供给错误分型与双面文案

openspec change `fix-model-supply-error-surfacing`（已归档 `2026-10-01-fix-model-supply-error-surfacing`：
任务全勾 + `review.md` 两轮独立复核收口 + 门禁全绿）。
收掉上一批 HANDOFF「上报待立项」的四条缺陷：

1. **凭证被拒不再等于「未配置」**：新增 `ModelCredentialError`（retrieve 侧，带结构化 `channel`）
   与 `LlmAuthError`（graph 侧 401/403）。两者都挂在既有基类的**子类**位置，所以全部既有
   `except ModelNotAvailableError` / `except LlmProviderError`（reranker=none 判定、settings 读写、
   serve 启动）行为零回退；`channel` 走 args 位置参（照 `ProtocolConfigError.kind` 先例，保
   pickle/copy 圆厂）；上游响应体不回显，凭证值不进 message。
2. **坏 config.toml 不再是死路**：`ModelConfigFileError`（内容不可解析：坏 TOML／非法段／非 UTF-8）
   与 `ModelConfigFileUnreadableError`（权限/IO 读不到，内容未知）**刻意分型**——前者允许覆盖自救，
   后者覆盖即丢配置必须继续报错。
   `PUT /api/settings` 在文件不可解析时以空文件层为基底合并本次提交并原子替换，响应带
   `invalid_config_file_overwritten=true`；GET 面与连通探测面给「在设置页重新保存即可覆盖」指引，
   **且设置页真的出图**（评审循环补：读取失败但服务可达时经显式确认进入空配置表单，见下方评审节）。
3. **`ask_readiness` 计入 serve 的 CLI 层**（决议 #4）：`masked_view(cli=…)` 由 app 传入 serve 的三层，
   与 `llm_fallback` 同口径，消除「UI 说未配置、请求期其实可用」的第二套事实源。
4. **双面文案**：`map_domain_error` 增加 `surface`（`cli` 缺省保持原指引；HTTP 面一律指向「设置」页
   与免重启保存，不再出现 config.toml 路径与 `--embedding-base-url` 一类 CLI 教程）。

前端随行（原计划「零改动」被证伪）：`ui/src/api.ts` 补该字段类型，`SettingsView` 用独立
`role="status"` 告警呈现覆盖自救告知——**不复用 `warnings` 区块**，其标题固定「需要重建索引」，
把覆盖写塞进去会误导成索引问题；用例同时断言告知出现与下次正常保存后撤下。

## 验证（上一批）

- `uv run pytest` **724 passed**（基线 681 + 本批 43）；`ruff check` / `ruff format --check` 绿。
  该计数是上一批的终态，成因码本批之后为 **731**。
- `ui`：`vitest` **109 passed**；`tsc -b --noEmit`、`eslint .`、`vite build` 绿。
- `openspec validate --specs --strict` **8/8**、`--changes --strict` **1/1**；`contracts/openapi.json` 已随契约再生成。
- 真机验收第 3 条（临时 vault/data-dir，跑完即删）：`siku serve --embedding-base-url … --embedding-model …`
  → `GET /api/settings` 的 `ask_readiness` = `{ready:true, missing:[]}`；去掉这两个 CLI 参数的对照组
  → `{ready:false, missing:["embedding.base_url","embedding.model"]}`。
- **坏文件真机冒烟（临时 `HOME=/tmp/siku-smoke-home`，跑完即删；本机真实 `config.toml` 全程未被读写）**：
  ① 写入坏 TOML 后 `siku serve` 正常起服，启动横幅播报
  `embedding=配置文件不可解析（非未配置，可在设置页重新保存覆盖）`（此前会播「未配置」，与上一行告警自相矛盾）；
  ② `GET /api/settings` → 503「内容已损坏，可重新保存覆盖」；③ `PUT` → 200 且
  `invalid_config_file_overwritten=true`，落盘为新写入内容，随后 `GET` → 200（自救闭环）；
  ④ 把该文件 `chmod 000` 后 `GET`/`PUT` 均 503，文案为「当前无法读取（权限或磁盘故障，不是内容损坏）」
  且不含「补全」二字，`cmp` 证原文件逐字节未动（读不到≠可覆盖，用户配置不被毁）。
- **桌面面的一条边界**：sidecar 的 stderr 进 `sidecar.log`，桌面 UI 无日志入口，故「启动即明示」只在终端
  `serve` 面成立；桌面用户实际看到的是设置页的读取失败指引 + 覆盖自救入口（本批已开）。
- 桌面/移动安装包未重新冒烟（本批改了 `ui/`）。

## 评审迭代循环（2026-10-01，R1→R2 一轮收敛，独立子代理复核）

报 4 项候选，确认 3 项真缺陷全部修复、排除 1 项臆断：

- **[高] 「坏 config.toml 不再是死路」当时只在内核侧成立**：`SettingsView` 的读取失败早退分支把表单连
  保存按钮一起藏掉，桌面用户只剩「重试读取」，而服务端文案承诺「重新保存即可覆盖」——指引不可执行。
  现改为：拿到 HTTP 错误响应（=服务可达、PUT 同样可达）时给一枚显式确认按钮
  「确认以空配置覆盖本机配置文件并重新填写」，确认后以 `BLANK_CHANNEL_VIEW` 基底出图、不伪造
  `config_path`；连接失败（没拿到响应）仍阻断——那时保存也无处可去。破坏性动作以按钮文案本身完成告知。
  反向验证：撤掉确认门（恢复旧早退条件）即恰好一条用例红。
- **[中] 第三种成因被「未配置」顶替**：`load_config` 的 `OSError` 分支原抛基类，与「通道未配置」共用文案，
  `PUT` 同面也被堵；新增 `ModelConfigFileUnreadableError`（挂基类子类位，既有 `except` 零回退）
  + 独立 cli/http 文案，覆盖分支仍只捕 `ModelConfigFileError`（读不到不覆盖，spec 判据）。
  同型漏网在 `cli.py` 启动横幅：serve 容忍坏文件继续启动后，embedding/rerank 解析再读同一个坏文件，
  被 `except ModelNotAvailableError` 吞成「未配置 / none（RRF-only）」，与刚打出的告警自相矛盾。
- **[低] 前端类型与契约不符**：`api.ts` 把 `invalid_config_file_overwritten` 声明为必填，而 OpenAPI 快照里
  它是 `default: false` 且不在 `required`；改为可选 + 读取处 `?? false`。
- **排除的臆断**：「`--{channel}-api-key-env` 会为 llm 拼出不存在的 `--llm-api-key-env`」——查构造点，
  `ModelCredentialError` 只在 `retrieve/api_providers.py` 以 `embedding`/`rerank` 抛出，llm 的 401/403 走
  `LlmAuthError` 另有分支，路径不可达，未改。

### R2（同一轮的第二遍复核，专查本轮改动自身）

报 5 项，4 项确认为本轮引入并已修，1 项是限制而非缺陷：

- **[中高] 探测面漏捕新异常类**：`api/settings.py::map_probe_error` 有 `ModelCredentialError` /
  `ModelConfigFileError` 分支却没有新类分支，权限故障落回通用文案
  「embedding 端点配置不完整：请检查该通道的 base_url、model 与 api_key」——正是本变更 spec
  明令禁止的顶替（实跑 `map_probe_error(...)` 复现）。补独立分支 + HTTP 用例
  `test_probe_unreadable_config_says_file_not_channel`。
- **[中] 新加的横幅分支是死码，且用例只测了 mock**：`siku serve` 对 unreadable 在 LLM 解析处就
  `_fail` 退出（实测：临时 HOME + `chmod 000`，输出即新文案，进程未起服），横幅永不打印。
  删掉 unreadable 分支（`_config_file_gap_text` 不再收异常参数、只捕 `ModelConfigFileError`），
  用例改打到真实路径：`runner.invoke(app, ["serve", …])` 断言 exit 1 + 「无法读取」+ 不含「补全」，
  并加 `uvicorn.run` 护栏防意外起服挂住整轮。
- **[中] jinguan 侧牵出的口径冲突**：本轮把三管计数点后置，与 jinguan 主规格「每次被调用必须计入」
  分叉——已另立变更 `2026-10-01-control-pull-count-point` 收口（与本仓无关，记此以免两处口径失联）。
- **[低] `docs`/`spec` 与本仓行为的同步**：model-supply delta 补一条「serve 在该情形快速失败退出」的
  判据，避免规格只描述横幅侧行为而实现其实止于启动面。
- **当时登记的限制已在下一批收口**（归档 `2026-10-01-settings-error-cause-codes`）：三型故障
  曾共用 `code=model_not_available`，UI 只能靠启发式猜「保存能否修好」；现已按成因分道为
  `invalid_config_file` / `config_file_unreadable` / `model_not_available`。

## 待办与边界

- **已归档**：本仓流程要求的 `review.md`（独立评审两轮）已随批入库，delta 已 sync 进
  `model-supply` / `http-api` 主规格（strict 8/8）。归档件
  `openspec/changes/archive/2026-10-01-fix-model-supply-error-surfacing/` 与
  `openspec/changes/archive/2026-10-01-settings-error-cause-codes/`（后者含 R1 三项 + R2 一项
  的修复与红灯实证、以及被推翻的两条臆测）。活动变更清零。
- **配置故障成因码已分道并落地**：`invalid_config_file`（内容确证不可解析，保存可覆盖自救）/
  `config_file_unreadable`（内容未知，禁止覆盖）/ 其余仍 `model_not_available`。设置页的覆盖
  自救入口只由第一个码驱动——上一轮「拿到错误响应即给入口」的启发式、以及它对读不到型误给
  入口的问题，同时消除。**中途试过并否掉的方案**：让 `GET /api/settings` 对坏文件返回 200 +
  `config_file_invalid` 标记——因请求期每请求现读该文件，容忍会造成「设置页说就绪、真实请求
  503」的误就绪，比死路更难排查；此路已回退，别再走。
- **相邻存量（不在本批 diff 内，一句话记此）**：① `mypy src/siku` 在 `graph/providers.py:229-255`
  报 3 条错（`parts` 重定义、`join` 收 `list[Any | None]`），属 2026-09-26 已提交的
  `add-llm-protocol-adapters`；siku 未把 mypy 列入门禁（CI/AGENTS 均无），故非门禁破口。
  ② `api/settings.py::invalid_protocol_message` 的 `llm_enum` 文案说「来自本机配置的越界填写，
  在设置页重新选择协议并保存即可覆盖」，但当值来自 **env 层**（`SIKU_LLM_PROTOCOL`）时页面覆盖不了
  （env 优先于文件层）——要修准需让 `ProtocolConfigError` 携带层信息，属另立变更。
  ③ 除本批统一的两处外，`cli.py` 其余 `except` 分支仍会把异常文本 `%s` 打进日志；实测泄露面为零
  （消息含配置文件路径、不含 key），属口径不齐而非破口。
- **工具坑（本机门禁执行口径）**：`pytest` 直跑只输出进度点不输出汇总行（`addopts` 已含 `-q`，
  再加 `-q` 即 `-qq`），要计数用 `-o addopts=""`；`ui/` 下别用 `pnpm exec`/`pnpm test`——pnpm 11
  会先跑 install、在 `ERR_PNPM_IGNORED_BUILDS: esbuild` 处退出，并写出 `ui/pnpm-lock.yaml` 与
  `ui/pnpm-workspace.yaml` 两个孤儿文件（本仓真正锁文件是 `package-lock.json`），直接调
  `./node_modules/.bin/{tsc,eslint,vitest,vite}` 绕开。
- 桌面 GUI 进程读不到 shell 环境变量：回退只在终端 `serve` 场景生效；sidecar 环境注入仍是 Non-goal。
- 「siku 走查发现 2026-09」清单：ink-faint 对比度已销，余项待修。
- Phase 6（Apple 公证 / Windows 签名 / 自动更新）未启动：需开发者账号与付费证书，属外部条件不是代码缺口；
  Windows/Linux 实机安装冒烟沿用 2026-09-19 豁免裁决，发布解禁时按 `docs/desktop.md` 回填。
- 上一批提到的本机残留旧 `serve` 进程（:51194、:8123）现已不在监听，无需再重启清理。
