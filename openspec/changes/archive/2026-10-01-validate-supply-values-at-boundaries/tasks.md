# 实施任务：非法取值挡在输入边界之外

## 已回滚的第一版（记录以免有人重走）

同一目标下先实现过「让非法状态可见」版：`AskReadiness.invalid` + `AskReadinessView.invalid`
（扩响应字段）、`ProtocolConfigError.layer` + `_llm_protocol_layer` +
`_non_llm_protocol_layer`、`ask_readiness` 把协议异常译成判定项、启动面按层容忍
（`_serve_llm_channel` + `_illegal_llm_protocol_message`）、`App.tsx` 的 `INVALID_LABELS`
与 `describeReadiness`、`api.ts` 的 `invalid`、协议 `NativeSelect` 塞坏值禁用项、
`LlmReadinessHint` 按 `ready` 分话术，744 passed / 113 vitest 全绿后被整体
`git checkout HEAD --` 回滚。否决理由见 `design.md` D1；回滚后 `contracts/openapi.json`
回到与 HEAD 零差异（即本批不动对外契约）。

## 文件层边界

- [x] `model_supply.py`：新增 `_reject_invalid_file_protocols(config, file)`，
      在 `load_config` 校验段结构之后调用——`[llm] protocol` 不在 `LLM_PROTOCOLS`、
      或 embedding/rerank 段带 `protocol` → 抛 `ModelConfigFileError`
- [x] 校验的是**归一后的形状**（`_drop_blank` 之后）：`protocol = "  "` 与未设置等价，
      否则一个空白串就会让整个文件层被判无效（红灯实证过这条：先写在校验归一前，
      `test_blank_protocol_treated_as_unset` 直接红）
- [x] `retrieve/errors.py`：`ModelConfigFileError` 新增 `detail`（服务端自撰的字段级说明，
      走 args 位置参保 `__reduce__` 圆厂；只给字段名与合法名单，不回显用户原值）
- [x] `api/messages.py`：`invalid_config_file` 的两面文案由「不可解析」扩为「对模型供给无效
      （内容不可解析，或字段取值非法）」并拼接 `detail`；HTTP 面仍不含路径与命令行教程
- [x] `api/app.py`：`PUT` 落盘后降级分支的「已写入」事实文案改述为「原先无效的配置已被覆盖」

## 命令行边界

- [x] `cli.py`：新增 `LlmProtocol(StrEnum)` 与 `LlmProtocolOpt` 类型别名，
      `serve`/`ask`/`graph` 三处 `--llm-protocol` 统一改枚举参数；
      新增 `_protocol_value()` 把枚举还原成 `str | None` 供分层配置使用
- [x] `cli.py::_llm_config_error_message`：删掉自带的两个 `kind` 分支文案，
      `ProtocolConfigError` 与配置文件两类错误统一取映射层文案（CLI 与 HTTP 不再两套口径）

## 环境变量层与文案单源

- [x] `api/messages.py::map_domain_error` 补 `ProtocolConfigError` 分支 →
      503 `invalid_settings`，按 `kind` 出两种指引，点名真正杠杆
      （`SIKU_LLM_PROTOCOL`，并明说「设置页保存覆盖不了它」）——
      销掉上一批登记的相邻缺陷「env 层来源时仍让用户去设置页保存」
- [x] `api/settings.py::map_probe_error` 补同一分支：此前探测面把协议非法播成
      「请检查该通道的 base_url、model 与 api_key」（探测面与读取面同一故障给两个 code
      就是第二套事实源）
- [x] 删除 `api/settings.py::invalid_protocol_message` 与 `api/app.py` 的读写两处调用点
      （文案已单源到映射层）
- [x] 删除 `model_supply.validate_channel_protocols` 与 `PUT` 写入前的该调用
      （提交值由 `_validate_value` 逐字段校验、存量文件层由载入点校验，此处不可达）
- [x] `contracts/openapi.json` 重新生成：唯一 diff 是 `PUT /api/settings` 的 endpoint
      description 文案（法定成因由「不可解析」扩为「对模型供给无效」），
      request/response schema、字段与路径零漂移——本批不改对外契约

## 增量评审修正（评审循环内发现并修掉的五处文案失真）

上一版把 `ProtocolConfigError` 的文案写成「HTTP/CLI 同一段话」，违背 `messages.py`
模块 docstring 的双面纪律；又把探测面与该类映射的关系漏在了原地。逐条：

- [x] `messages.py::protocol_error_mapping`（新抽出，`map_domain_error` 与 `map_probe_error`
      共用）：按 `surface` 分文——HTTP 面禁现 `--llm-protocol` 与配置路径，CLI 面禁现
      「设置」页；`llm_enum` 只点名 `SIKU_LLM_PROTOCOL`（`--llm-protocol` 是枚举参数，
      非法值 exit 2 进不来；文件层已在载入点被拒，两者都不是该错误的杠杆）
- [x] `channel_unsupported` 不再说「来自启动参数」：embedding/rerank 无 `--*-protocol` 选项、
      其 env 层也没有 protocol 字段，该字段只剩「程序传入的配置」一个来源
- [x] `settings.py::map_probe_error`：`ModelConfigFileError` 分支由「不可解析（内容已损坏）」
      改为「对模型供给无效（内容不可解析，或字段取值非法）」并拼 `detail`
- [x] `cli.py::_config_file_error_message(exc)` 收下捕获到的异常：原先另造一个
      `ModelConfigFileError("...")` 合成告警，字段级 `detail` 到不了启动面
- [x] `cli.py::_config_file_gap_text()` 横幅由「配置文件不可解析」改为「配置文件无效」；
      `api/app.py` 写入自救分支的日志与 docstring、`model_supply.load_config` 的分型说明
      同步改为同一措辞（本类现覆盖两种成因，旧措辞会把取值问题说成语法问题）

## 用例（全部做过「撤掉修复即红」）

- [x] `tests/test_model_supply.py`：坏 llm 值在 `load_config` 就被拒且 detail 含三个合法值、
      **异常文本不含越界原值**；embedding 段多余 protocol 同归文件无效；
      env 层坏值仍在解析时抛 `ProtocolConfigError`；`ModelConfigFileError.detail`
      过 copy/deepcopy/pickle；`test_protocol_error_survives_copy_and_pickle` 改用 env 来源
      （文件层已不可能产生该异常）
- [x] `tests/test_api.py`：新增 detail 进文案 + 码仍为 `invalid_config_file` 的用例；
      新增双面协议文案用例（`--llm-protocol` 不出现在 HTTP 面、「设置」页不出现在 CLI 面、
      `SIKU_LLM_PROTOCOL` 两面同点）与探测面共用同一 code/文案的用例；
      `test_config_file_error_copy_names_the_broken_file` 断言随新措辞改写
- [x] `tests/test_api_settings.py`：文件层坏值 → 503 `invalid_config_file` + 文案点出
      `[llm] protocol` 与合法名单 + 无路径/无参数教程；保存修正 → 200
      `invalid_config_file_overwritten=true` + 文件内坏值消失 + 再 `GET` 200（自愈闭环）；
      embedding 坏值同码且请求期 `resolve_embedding_channel()` 同样抛（无中间态）；
      env 层坏值 → `invalid_settings` 且文案含 `SIKU_LLM_PROTOCOL` 与「覆盖不了」；
      探测面对 env 层坏值同码同文案、对文件层坏值点名字段（两条均「撤掉修复即红」）
- [x] `tests/test_cli.py`：`--llm-protocol bogus` → exit 2、不起服、列出三个合法值、无 traceback；
      枚举名单与 `LLM_PROTOCOLS` 相等的漂移断言；坏取值的启动告警点名字段
      （红线实证：改回合成异常即红）；坏文件叠加上层协议越界用例按新口径改写
      （点名环境变量，而非旧句「线协议非法」；`--llm-protocol` 断言反转为「不出现」）
- [x] `tests/test_api_cli.py`：启动告警断言由「不可解析」改为「不是合法 TOML」+ 指向
      config.toml（措辞随成因口径向「对模型供给无效」统一；该用例测的是坏 TOML，
      断言改抓成因本身，不是放松）
- [x] 被本批语义取代的旧用例改写而非删除：`test_hand_edited_invalid_protocol_put_rejected_before_write`
      → `..._repaired_by_save`（原口径「422 拦下、文件不动」现改为「以本次提交覆盖」，
      与 `invalid_config_file` 的承诺一致）

## 真机冒烟（临时 `HOME=/tmp/siku-bound` + 临时 vault/data，跑完即删；本机真实 config.toml 未读写）

- [x] 文件层 `[llm] protocol = "gemini-native"` + `siku serve`：**照常起服**（health 200），
      启动面先打「模型配置文件对模型供给无效：…（内容不是合法 TOML、段类型不符，或字段取值
      不在允许范围）…」再打 warning（只记类名）；`GET /api/settings` → 503
      `invalid_config_file`，message 含「其中 [llm] protocol 取值不在允许范围，仅支持
      openai-chat / anthropic / openai-responses」；`PUT` 提交合法协议 → 200 且
      `invalid_config_file_overwritten=true`、`llm.protocol=anthropic`（一例为 openai-chat）；
      再 `GET` → 200。全程无 traceback，越界原值不出现在任何响应文本里
- [x] `siku serve --llm-protocol bogus` → exit=2，
      `Invalid value for '--llm-protocol': 'bogus' is not one of 'openai-chat', 'anthropic',
      'openai-responses'.`，不进入启动流程
- [x] `SIKU_LLM_PROTOCOL=totally-bogus` + 有效文件 → serve fail-fast（既有形态），
      指引现点名环境变量与启动参数（进程内用例覆盖，起服面不监听）

## 门禁

- [x] `ruff check` / `ruff format --check` / `pre-commit run --all-files` 绿
- [x] `pytest -o addopts=""` **744 passed**（相对入库基线 733 净增 11 条：文件层边界 3 条、
      detail 圆厂 1 条、CLI 边界 3 条、双面协议文案 2 条、探测面共用文案 2 条；
      另把 4 条旧口径用例改写为新口径，无删除测试）
- [x] `mypy src tests`：**4 errors**，全部为 HEAD 既有（`graph/providers.py` 3 条 +
      `test_cli.py` 的 `_raises` 缺注解 1 条）；本批新增 0 条，并顺带修掉基线里
      `test_model_supply.py` 两条 `kind` 注解错误（HEAD 基线为 6 条）
- [x] ui：`tsc` / `eslint` / `vitest` **109 passed** / `vite build` 绿——本批前端零改动
      （回滚第一版后 `ui/` 与 HEAD 一致）
- [x] `openspec validate --specs --strict` **8/8**、`--changes --strict` 通过；
      review.md 后归档 sync
