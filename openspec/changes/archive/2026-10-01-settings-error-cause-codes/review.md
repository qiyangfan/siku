# 评审记录：settings-error-cause-codes

- **评审方式**：独立子代理通读本变更全部未提交 diff（含新增 change 目录），判据为本件
  proposal/tasks/specs delta + `openspec/specs/{model-supply,http-api}/spec.md` + `AGENTS.md` +
  前一批 `archive/2026-10-01-fix-model-supply-error-surfacing/review.md`（其「限制」段正是本批要收的口子）；
  评审者被允许实跑 `pytest` / `vitest` / `ruff`，禁止改代码使其变绿。主对话按结论修复后逐条反向验证
  （撤掉修复看用例是否红），并补做真机冒烟。
- **评审时间**：2026-10-01
- **立论权威**：注释与文档只说明过去为什么这么做；异常类的真实继承关系、映射点实际输出的码、
  进程实际行为才是事实。本轮据此推翻了两处本批自己的表述（见 R1-6 与「排除项」）。

## 结论

初评「需修复后收口」。R1 确认 3 项真缺陷 + 2 项文档失真；修复后 R2 的真机冒烟又抓到 1 项
**既有**缺陷（非本批引入，落在本批正在处理的同一故障家族）。全部确认项已修并带红灯实证的回归用例，
**可收口**。登记 3 项相邻存量与 1 项措辞残留，未顺手修改。

## R1 修复项

- **[P2] 「同一请求只读一次配置文件」的用例无法失败**：
  `tests/test_api_settings.py::test_settings_reads_config_file_once_per_request` 只 patch
  `siku.api.app.load_config`，而 `api/app.py:118` 是 `from siku.model_supply import load_config`
  的名字绑定，`llm_env_fallback_channel` 内部那次读解析的是 `model_supply` 那一份
  （`model_supply.py:443`）。评审者用双钩子实测：把调用改回不传 `config`，app 侧计数 0、
  真实读文件 1——用例照绿。它钉住的是「app 自己读一次」，不是 http-api spec 的
  「单次设置请求 SHALL 只读取一次配置文件」这条 MUST。
  **处置**：两个模块名都 patch；反向验证——把 `config=config` / `config=merged` 改回不传，
  用例在 PUT 断言处红（`assert 2 == 1`）。实现本身是对的（实测 GET/PUT 各 1 次真实读）。
- **[P2] `PUT` 在文件已落盘后仍能返 500，且本批新写的注释声称已消除**：
  写入前的 `validate_channel_protocols(merged)` 只校验**文件层**，而响应里的就绪判定
  (`masked_view` → `ask_readiness` → `resolve_llm_channel`) 含 **env/cli 层**。
  评审者以 `SIKU_LLM_PROTOCOL=totally-bogus-protocol` 实测：`ProtocolConfigError` 从
  `app.py:1017`（`try` 之外）穿出，由全局兜底返 500 `internal_error`——文件已写好却被告知失败；
  同一异常在 `GET` 面位于 `try` 内（`app.py:951-960`）返 503 中文指引，两面就此分叉。
  我原先写的注释「重读在 try 之外会把保存变成 500」只消掉了「重读文件」那一支，属过度声称。
  **处置**：响应装配段独立 `try`，按 `GET` 面同一口径给码（协议越界 → 503 `invalid_settings`），
  文案前缀声明「本次提交的配置已写入本机配置文件（免重启生效）」；补 `test_put_with_invalid_env_protocol_reports_written_not_500`
  （断非 5xx、两面同码、本次提交确实落盘），并把它写进 http-api delta 成为一条 MUST + 场景。
  没有新增或放宽任何响应字段——`{code, message}` 结构不变，只把一条 500 改对。
- **[P2] `config_file_unreadable` 在服务端零断言**：全库 `grep` 只命中
  `ui/src/SettingsView.test.tsx`（自造 fetch mock）；`test_unreadable_config_is_never_overwritten_and_says_so`
  与探测面 `test_probe_unreadable_config_says_file_not_channel` 只断 message 文本不断 `code`，
  `map_probe_error` 的 `invalid_config_file` 无任何用例，`test_api.py` 的映射表也没列这两个子类。
  把任一处码改回 `model_not_available`，725 条仍全绿——而 spec 明写分道 SHALL 在**所有**映射点生效。
  **处置**：GET/PUT 两面补 `code` 断言、新增探测面不可解析用例、映射表补三行
  （凭证被拒仍 `model_not_available`、两型各走自己的码）。反向验证：把 `messages.py` 的
  `config_file_unreadable` 与 `settings.py` 的 `invalid_config_file` 同时改回 `model_not_available`
  → 三条用例同时红。
- **[P3] 「按空配置显示」告警是无条件承诺**：文案写「保存将以本次提交覆盖该文件」，但那只是
  `GET` 时刻的判定；`PUT` 面服务端会重判——若其间用户手动修好了文件，保存走的是正常合并、
  `invalid_config_file_overwritten=false`。措辞改为「读取时已损坏…是否覆盖由该响应字段如实标注」。
- **[P3] 本批给「删掉 `detail=%s`」立的理由是错的**：原写「解码错误文本可能内嵌出错行片段，
  而 key 写成未加引号字面量正是常见损坏形态」。评审者实测 `str(TOMLDecodeError)` 只有
  `Invalid value (at line 1, column 11)` 这类行列信息、`str(UnicodeDecodeError)` 只有字节十六进制
  与位置，都不回显原文；真正防凭证值泄漏的是既有的「`ValidationError` 只保留字段路径与错误类型」
  （`model_supply.py:192-199`）。改动本身保留（详情文本对排障无增量，路径另有单列字段），
  但 proposal/tasks/http-api delta 里的立论按实测改写——不为已做的改动编理由。

## R2（修复后自查 + 真机冒烟）

- **[P1，既有缺陷非本批引入] `siku serve` 漏出裸 traceback**：为验证上面第 2 项跑真机冒烟
  （临时 `HOME=/tmp/siku-r5` + 坏 `config.toml` + `SIKU_LLM_PROTOCOL=totally-bogus-protocol`），
  进程直接打完整 `ProtocolConfigError` traceback 后退出。根因是 `cli.py:1033` 那次「以空文件层
  再解析」落在 `except ModelConfigFileError` 的**体内**——`except` 块内再抛的异常不会被同一
  `try` 的后续 `except ModelNotAvailableError` 接住。它不属于本批 diff，但落在本批正在治理的
  同一故障家族（`fix-model-supply-error-surfacing` 决议 #3 承诺的「坏文件不堵启动面」），
  且形态是用户面漏 traceback，故直接修：内层 `try` 嵌套，令其归 `_fail`（既有文案本就点名
  `--llm-protocol` / `SIKU_LLM_PROTOCOL` / `[llm] protocol`）。补
  `test_cli.py::test_serve_reports_invalid_env_protocol_when_config_also_corrupt`
  （断 exit 1 + 「线协议非法」+ 无 `Traceback` + 文件层故障仍先行明示），红灯实证：把嵌套拆回
  平铺即在 `result.exception` 处红。冒烟复跑：三行归一化输出，`grep -c Traceback` = 0。
  该面日志同步按本批口径只记异常类名。
- **可达性口径纠偏**：`env/cli 层协议越界`在 `siku serve` 的 LLM 解析处就 fail-fast、服务永不监听，
  所以 R1-2 那条「PUT 落盘后返 500」只在**直接使用 `create_app()`** 的形态（测试、嵌入式调用）可达。
  tasks 里如实写明「真机面无法演示，本批不据此声称端到端验证」，避免把一个进程内用例读成全链路验证。

## 排除项（评审提出的怀疑，经查不成立）

- **`isinstance` 链影子**：怀疑 `ModelConfigFileUnreadableError` 被 `ModelConfigFileError` 分支提前吞掉。
  实测两型是**兄弟**（都直接继承 `ModelNotAvailableError`，`errors.py:70/:79`），`issubclass` 双向 False，
  四条映射链（`messages.py:246→266`、`settings.py:455→462`、`cli.py:280` 元组、`app.py:986` 覆盖分支）
  实际输出四个正确的码；覆盖分支不会接住 unreadable。未改。
- **UI 状态机的两条陈旧态**：怀疑 `loadErrorCode` 能在二次失败时残留、或 `blankFormConfirmed`
  能在错误清除后仍出黄色告警。查 `SettingsView.tsx:399-405`（`load()` 开头成对清零）、
  `:392`（`applySettings` 清 `blankFormConfirmed`）、`App.tsx:402-407`（`view === "settings" &&`
  条件挂载，切页即整棵重挂）与重试按钮在 blank 态已随面板隐藏——两条路径都不可达。未改。
- **契约漂移**：openapi 快照只改 `GET /api/settings` 的 description，`/api/settings` 无 503 响应体定义、
  `code` 非枚举，漂移用例绿。未新增字段。

## 登记的相邻存量（不在本批 diff 内，未顺手改）

- `cli.py:1030` 之外的启动面日志仍会把异常文本 `%s` 打进 warning（本批只统一了 settings 读写两面
  与刚修的坏文件分支）；泄露面为零（消息含路径不含 key），属口径不齐。
- `settings.py:113-118` 的 `llm_enum` 指引写「来自本机配置的越界填写，请在「设置」页重新选择协议并保存即可覆盖」，
  但当值来自 **env 层**时页面保存覆盖不了（env 优先于文件层）。要修需让 `ProtocolConfigError`
  携带层信息，属另立变更。
- `mypy src/siku` 在 `graph/providers.py:229-255` 的 3 条错仍在（2026-09-26 已提交段，siku 未把
  mypy 列入门禁）。

## 门禁（修复后重跑）

`pytest` **733 passed**（较上一批 724 净增 9 条：7 个新用例函数 + 3 行映射表参数化，另 1 条重命名）；`ruff check` / `ruff format --check` 绿；
`ui`：`tsc --noEmit`、`eslint src --max-warnings 0`、`vitest` **109 passed**、`vite build` 绿；
`openspec validate --specs --strict` **8/8**、`--changes --strict` **1/1**。
`contracts/openapi.json` 无漂移，故未再刷新（快照内容与本批错误码无枚举耦合）。

**工具坑记此**：`siku/ui` 下不要用 `pnpm exec`/`pnpm test`——pnpm 11 会先跑 install 并在
`ERR_PNPM_IGNORED_BUILDS: esbuild` 处退出，且顺手写出 `ui/pnpm-lock.yaml` 与
`ui/pnpm-workspace.yaml` 两个孤儿文件（本仓真正锁文件是 `package-lock.json`）。直接调
`./node_modules/.bin/{tsc,eslint,vitest,vite}` 可绕开，产生的两个文件已删除。

## R3（对 R1/R2 修复自身的增量复核，独立子代理只审 `3f24327..c8e3be9` 与 kongming `1d16f42..a562bc8`）

确认 6 项，修 5 项、上报 1 项：

- **[P2 回归，已上报未修] 成因码收窄把「文件层协议越界」变成 UI 死路**：入口条件从「拿到错误响应」
  收窄到 `loadErrorCode === "invalid_config_file"` 之后，`GET` 返 503 `invalid_settings`
  （文件可解析、`[llm] protocol` 越界）时设置页只剩「重试读取」，而服务端文案正指着这个页面
  （`settings.py:119-122`「请在『设置』页重新选择协议并保存即可覆盖」）。实测该状态 `PUT`
  修正 protocol 后 200、再 `GET` 200——保存确实能修，页面却不再给出口。叠加另一条既有形态
  （`cli.py` 只在 `ModelConfigFileError` 上容忍，文件层协议越界仍让 `siku serve` exit=1，
  桌面 sidecar 根本进不到页面），修复需要择一：给 `ProtocolConfigError` 带层信息并让 serve
  只容忍文件层 + 页面出「仅修正协议」控件，或让 `GET` 带视图返回 200 并以 `ask_readiness.missing`
  表达不可用（后者会顶掉既有场景「越界协议在读取面 503」）。两者都动对外交互规则，按循环纪律
  暂停上报，未擅自改。
- **[P3 已修] 主规格场景与实现矛盾**：场景写「返回非 5xx」而实现是 503（503 就是 5xx）。
  改为「返回 503 且与 `GET` 面同码，而非 500 `internal_error`」，并把「降级分支不得静默丢弃
  成功响应本该携带的事实」写成 requirement。同批把 `app.py` 降级分支改为把「已写入 / 已覆盖坏文件 /
  embedding 重建告警」一并写进 message（错误体仍是 `{code,message}` 两字段，不扩契约），
  补两例 `test_degraded_put_over_corrupt_file_discloses_overwrite`、
  `test_degraded_put_keeps_rebuild_warning`——撤掉修复即两条同时红，复原即两条绿。
- **[P3 已修] ADDED 需求把「取值越界」归进 `invalid_config_file`**：代码里 protocol 越界抛
  `ProtocolConfigError`、走 `invalid_settings`，只有类型不符的 `ValidationError` 才是
  `ModelConfigFileError`。需求文本改为「非法 TOML、段结构非法、非 UTF-8、字段类型不符」，
  越界一句挪进场景并点名 `invalid_settings`。
- **[P3 已修] 用例计数错**：本批相对上一批是净增 9 条（7 个新函数 + 3 行映射表，另 1 条重命名），
  实测 733 passed；proposal/tasks/review/HANDOFF 四处「6 条」口径已改。
- **[P3 已修] 需求文本越过 500 字符 INFO 线**：细则移入 scenario 后回到 477 字符；
  `提供模型供给设置的读写端点` 那条 1508→1561 是既有超长，非本轮新增。
- **[P3 已修，kongming 侧] 三处口径**：覆盖率两次实测 72.94%/72.93%/72.95%（该套件带
  pytest-randomly，逐次微抖），HANDOFF 改为「72.9% 级、按 run 微抖」；「原先 5 个读取点里只有
  `user_role_scopes` 读 status」漏了 083 起就带闸的 `datascope/repository.py::custom_dept_ids`
  ——本批前是 6 处授权读取、其中 2 处已带闸，本批后 7 处全覆盖；「降级分支只剩主表无法定位」
  漏了 `applier.py:112-115` 的 `FilterType.SKIP`（目标列不存在等结构性原因，主规格自定场景钉着，
  与「主体不可确定」不是一类）。三处均已改。
- **[说明] 兜底分支不是死码**：`invalid_protocol_message` 返 None 时的 `map_domain_error` 分支
  在当前可达集合里不会命中（该 `try` 内的解析都显式传 `config`，只可能抛协议越界），但 spec 那条
  「装配失败 SHALL NOT 返 internal_error 类 5xx」要求它对任何供给类异常都成立，故保留并在注释
  里写明它是 MUST 的载体，不是防御性冗余。

**R3 排除（查证后不是缺陷）**：`cli.py` 内层 `try` 前后行为等价（unreadable 仍由外层 `_fail` 接住，
warning 格式串 1 占位 1 参）；`DataScopeUnsupported` 唯一生产调用方 `internal/service.py:273` 走
`_fin("BLOCKED")` 并落审计，无「记录后放行」；`auth/repository.py::list_role_keys` 不带 status
谓词属角色名呈现（鉴权一律走 `perm_codes`），不构成 fail-open，作为「已核不缺陷」登记；两份主规格
sync 无重复/孤儿需求（kongming `datascope` 告警 6→6、`rbac` 16→15）；siku 无 pytest-randomly，
`config_path` fixture 先清 `SIKU_LLM_*` 再用 `setenv`，`chmod 000` 与 `read_text` patch 的逐字节
断言成立；`map_ask_error` 复用 `map_domain_error`，无第三映射点。

**R3 门禁**：`pytest` **733 passed**、`ruff check`/`format --check` 绿、`openspec validate --specs --strict`
**8/8**；kongming 覆盖率与用例数按上条口径复核。
