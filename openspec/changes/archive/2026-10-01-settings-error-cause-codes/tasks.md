# 实施任务：配置文件故障的稳定成因码与自救入口

## 内核

- [x] `retrieve/errors.py` 的两型（`ModelConfigFileError` / `ModelConfigFileUnreadableError`）
      保持既有类分型不动，本批只把分型传到响应码
- [x] `api/messages.py::map_domain_error`：两型各自分支的 `code` 改为
      `invalid_config_file` / `config_file_unreadable`（cli 与 http 两套文案共用同一映射点，
      状态码 503 与 `{code, message}` 结构不变）
- [x] `api/settings.py::map_probe_error`：连通探测面同步两个码（此前它也落
      `model_not_available`，同一异常在两个面给两个码就是第二套口径）
- [x] `api/app.py`：`PUT` 响应的 `llm_env_fallback` 改传 `config=merged`，消除同一请求内
      第二次读配置文件（通道视图用 merged、回退判定用重读结果是两套源）
- [x] `api/app.py`：读写两面遇坏文件的日志一律只记异常类名与路径，不记 `detail=%s`
      （成因与处置已由响应面承载，详情文本无增量；防凭证值泄漏是既有的
      「`ValidationError` 只保留字段路径」那条，与本项无关——评审实测纠正了这里的立论）
- [x] `api/app.py`：`PUT` 的响应装配段独立兜领域错误——env 层协议越界会让就绪判定抛错，
      而写入前的校验只管文件层；原代码该段落在 `try` 之外，由全局兜底返 500
      `internal_error`（文件其实已写好）。现按 `GET` 面同一映射给码（503 `invalid_settings`），
      文案前缀声明「本次提交的配置已写入本机配置文件」
- [x] 读取面明确**不**做容忍式 200：`GET` 仍按成因报错（理由写进 `read_settings` docstring
      与本件 Non-goals，避免后人重走这条岔路）
- [x] `cli.py::serve`：坏文件分支里「以空文件层再解析一次」抛出的 `ProtocolConfigError`
      会穿出 `serve`（`except` 块内再抛的异常不会被同一 `try` 的后续分支接住），用户面
      漏出一段裸 traceback。改为内层 `try` 嵌套，让其归 `except ModelNotAvailableError`
      → `_fail`（既有文案已点名 `--llm-protocol` / `SIKU_LLM_PROTOCOL` / `[llm] protocol`）；
      同分支日志按本批口径只记异常类名

## 前端

- [x] `ui/src/SettingsView.tsx`：新增 `loadErrorCode` 状态，自救入口条件由
      「拿到了错误响应」这一启发式改为 `loadErrorCode === "invalid_config_file"`；
      空配置出图走 `BLANK_CHANNEL_VIEW` 基底（不伪造 `config_path`），确认动作以按钮文案自证
- [x] `ui/src/api.ts`：撤销中间方案的 `config_file_invalid` 字段（未采纳，避免留下没人读的字段）
- [x] `ui/src/SettingsView.tsx`：「按空配置显示」告警改为条件式措辞——原句「保存将以本次提交
      覆盖该文件」只反映 GET 时刻的判定，PUT 面服务端会重判（其间用户手动修好文件则走正常
      合并），改成「读取时已损坏…是否覆盖由 `invalid_config_file_overwritten` 如实标注」

## 用例

- [x] `tests/test_api_settings.py::test_corrupt_config_get_gives_overwritable_cause_code`：
      读面 503 + `code=invalid_config_file` + 双面文案红线（不含路径/命令行教程）+ 同客户端
      保存覆盖闭环（再 GET 回 200）
- [x] `tests/test_api_settings.py::test_unreadable_config_is_never_overwritten_and_says_so`：
      文案与「不覆盖 + 原文件逐字节未动」保持（既有），本批补 `code=config_file_unreadable`
      断言（GET/PUT 两面）——只断文案钉不住成因码
- [x] `tests/test_api_settings.py::test_probe_corrupt_config_gives_overwritable_cause_code`：
      探测面的 `invalid_config_file`（此前该面两个码都零服务端断言）
- [x] `tests/test_api_settings.py::test_put_with_invalid_env_protocol_reports_written_not_500`：
      env 层越界协议下 `PUT` 非 5xx、`code` 与 `GET` 面一致、文案声明已写入且本次提交确实落盘
- [x] `tests/test_api.py::test_every_domain_error_has_stable_http_mapping` 补三行：
      凭证被拒仍 `model_not_available`、两型各走自己的码（把任一映射点改回共用码即此红灯）
- [x] `tests/test_api_settings.py::test_settings_reads_config_file_once_per_request`
      （评审确认原用例**无法失败**）：`from siku.model_supply import load_config` 让两个模块
      各持一份名字，只 patch `siku.api.app.load_config` 计数会漏掉 `llm_env_fallback_channel`
      内部那次读；现两处都 patch，实测把 `config=merged`/`config=config` 改回不传即红
      （`assert 2 == 1`）
- [x] `tests/test_api.py::TestDualSurfaceErrorCopy::test_search_surface_config_file_error_copy`：
      请求期端点同码（`invalid_config_file`），钉住「分道覆盖所有映射点」
- [x] `tests/test_cli.py::test_serve_reports_invalid_env_protocol_when_config_also_corrupt`：
      坏文件叠加 env 层协议越界 → exit 1 + 「线协议非法」+ 无 traceback（红灯实证：把内层
      `try` 拆回平铺，`ProtocolConfigError` 即穿出 `serve`，用例在 `result.exception` 处红）
- [x] 三条新用例与两处 code 断言均做过反向验证：把 `messages.py`/`settings.py` 的成因码
      改回 `model_not_available` → `test_unreadable_config_is_never_overwritten_and_says_so`、
      `test_probe_corrupt_config_gives_overwritable_cause_code`、映射表用例三条同时红
- [x] `ui/src/SettingsView.test.tsx` 两例：`invalid_config_file` → 入口出现、确认后按空配置
      出图且保存生效；`config_file_unreadable` → 只给重试、无覆盖入口、表单不出图

## 真机冒烟（临时 HOME + 临时 vault/data，跑完即删；本机真实 config.toml 全程未读写）

- [x] 坏 TOML：`siku serve` 起服，启动横幅播报「配置文件不可解析（非未配置，可在设置页重新
      保存覆盖）」；`GET /api/settings` → 503 + `code=invalid_config_file`；
      `PUT` → 200 + `invalid_config_file_overwritten=true`；再 `GET` → 200（自救闭环全链实测）
- [x] 坏文件 + `SIKU_LLM_PROTOCOL=totally-bogus-protocol`（临时 `HOME=/tmp/siku-r5`，跑完即删）：
      原实现漏出 `ProtocolConfigError` 的完整 traceback 后进程退出；改后输出三行归一化文案
      （①「模型配置文件不可解析：…请修正或删除该文件」②warning 只记 `error_class=`
      ModelConfigFileError ③「LLM 线协议非法：仅支持 openai-chat / anthropic /
      openai-responses；请修正 --llm-protocol、SIKU_LLM_PROTOCOL 或 config.toml 的
      [llm] protocol」），exit=1，`grep -c Traceback` = 0
- [x] **可达性口径（别把上一条读成「PUT 面 503 已真机验过」）**：env/cli 层协议越界在
      `siku serve` 的 LLM 解析处就 fail-fast，服务永不监听，故「落盘后装配抛领域错误」这条
      只在**直接使用 `create_app()`** 的形态（测试、嵌入式调用）可达；进程内用例
      `test_put_with_invalid_env_protocol_reports_written_not_500` 覆盖它，真机面无法演示。
      本批不据此声称端到端验证。
- [x] 读不到（`chmod 000`）一型**只能进程内验**：该情形下 `siku serve` 依约在 LLM 解析处
      快速失败退出，进程根本不监听（实测 `curl` 连接被拒；这也是为什么 UI 侧不需要、
      也不应该出现覆盖入口）。因此该型的「GET/PUT 均 503 + 不覆盖 + 原文件逐字节未动」
      由 `tests/test_api_settings.py` 两例在进程内断言（含 `cmp` 逐字节比对），
      启动面的退出与文案由 `tests/test_cli.py::test_serve_fails_fast_on_unreadable_config_with_accurate_copy`
      走真实 CLI 入口断言

## 门禁

- [x] `ruff check` / `ruff format --check` 绿；`pytest` 733 passed（较上一批 724 净增 9 条：
      探测面成因码、PUT 落盘后装配两例、serve 坏文件叠加协议越界、单读计数、
      映射表三行参数化；另 `test_corrupt_config_get_gives_recovery_guidance` 重命名为
      `..._gives_overwritable_cause_code`）
- [x] ui：`tsc` / `eslint` / `vitest` 109 passed
- [x] `contracts/openapi.json` 经 `-m siku.api.contract --refresh` 再生成，漂移测试绿
- [x] `openspec validate --specs --strict` 8/8、`--changes --strict` 通过；归档 sync

## 第 3 轮增量复核（审本轮修复自身）

- [x] `app.py` 降级分支带回成功路径本该携带的事实（已写入 / 已覆盖坏文件 / 重建告警），
      错误体仍是 `{code,message}` 两字段；补两例并做撤掉修复即红的反向验证
- [x] http-api 主规格与本件 delta：场景「返回非 5xx」改为「503 而非 500」（503 本身是 5xx，
      原句与实现矛盾）；ADDED 需求里的「取值越界」移出 `invalid_config_file` 定义
      （代码中它走 `invalid_settings`），细则挪进 scenario 使需求文本回到 500 字符内
- [x] proposal/tasks/review/HANDOFF 的用例计数改为「较上一批净增 9 条，实测 733 passed」
- [x] kongming HANDOFF 三处口径修正（覆盖率抖动、授权读取点 6→7 且漏 `custom_dept_ids`、
      `FilterType.SKIP` 漏述）
- [ ] **上报待裁**：文件层协议越界的 UI 死路（成因码收窄后 `invalid_settings` 无自救入口 +
      `siku serve` 对该状态 fail-fast 使桌面 sidecar 进不到页面）。两种收口都要动对外交互规则：
      ①`ProtocolConfigError` 携带来源层 + serve 只容忍文件层 + 设置页出「仅修正协议」控件；
      ②`GET` 返回 200 带视图并以 `ask_readiness.missing` 表达不可用（会顶掉既有场景
      「越界协议在读取面 503」）。按循环纪律暂停，未擅自改契约
