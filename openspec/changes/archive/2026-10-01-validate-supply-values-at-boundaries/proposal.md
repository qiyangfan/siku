# 提案：把非法取值挡在各输入边界之外——运行期不存在非法配置状态

## Why

`[llm] protocol = "gemini-native"` 这类手改坏值，此前会造成桌面死路：读取面因就绪判定
解析通道而整资源 503，设置页拿不到视图、只剩「重试读取」，可 503 的文案正指着
「请在『设置』页重新选择协议并保存即可覆盖」；同时 `siku serve` 在同一次解析处退出，
sidecar 连页面都进不到。另外三处指引还把杠杆指错：值来自 `SIKU_LLM_PROTOCOL` 或
`--llm-protocol` 时也告诉用户「去设置页保存」，而那两层优先级高于文件层，页面根本覆盖不了。

本批**先按「让非法状态可见」做过一版**，被否掉并回滚，理由记下来以免重复踩：那一版的做法是
①给 `ask_readiness` 新增 `invalid` 字段，②`ProtocolConfigError` 携带来源层，③启动面按层
决定是否容忍，④设置页把坏值作为禁用项塞进协议下拉。它把「一个校验点」摊成「四层各一套
善后」，还扩了对外响应字段——本质是给本该消灭的状态做兜底。**非法状态不该活到运行期**：
它应当在进入系统的那一层就被拒。

回到根源看，这个死路本来就已经有解了：上一批为「文件读不出内容」建好了
`invalid_config_file` → 设置页「重新保存覆盖」的自救闭环。手改坏值与坏 TOML 对读者是
同一件事——**这个文件对模型供给无效**，出路也是同一条。缺的只是让坏值在载入点就归入该类。

## What Changes

1. **文件层（config.toml）边界**：`load_config` 在校验段结构之后，再校验协议取值——
   `[llm] protocol` 不在枚举内、或 embedding/rerank 段多出 `protocol` 字段，一律抛
   `ModelConfigFileError`（=该文件无效）。异常带一个服务端自撰的 `detail`，指明是哪个字段、
   合法名单是什么（**不回显用户原值**，与凭证不回显同一纪律），因此 HTTP/CLI 文案能落到
   「改哪一行」。于是坏值自动继承既有出路：`GET` → 503 `invalid_config_file` → 设置页覆盖
   自救 → 保存修复 → `GET` 200。
2. **命令行边界**：`--llm-protocol` 由自由字符串改为枚举参数（`siku serve`/`ask`/`graph`
   三处共用同一类型别名），`bogus` 在解析阶段就以用法错误退出（exit 2，列出合法值），
   非法值交不进运行期，也不再进入服务启动。
3. **环境变量与程序传入的 CLI 层**：这两层没有载入边界，越界值仍在通道解析时拒绝，但
   指引改对杠杆——`invalid_settings` 的文案现在说明「该值来自优先级高于配置文件的环境变量
   `SIKU_LLM_PROTOCOL`（或程序传入的配置），设置页保存覆盖不了它，请修正该来源后重启」。
   `--llm-protocol` 不再是这条指引的对象：它已改为枚举参数，非法值在解析阶段即被拒。
   这一条同时销掉上一批登记的相邻缺陷（原指引断言「值来自本机配置、页面可覆盖」）。
4. **协议指引单源**：CLI 面与 HTTP 面不再各写一份（`cli.py::_llm_config_error_message` 原有
   两个 `kind` 分支、`api/settings.py::invalid_protocol_message` 又一份），统一由
   `map_domain_error` 的 `ProtocolConfigError` 分支出文；连通探测面补该分支——此前它落回
   「请检查该通道的 base_url、model」，把取值非法说成配置不全。
5. **删掉因此不可达的东西**：`validate_channel_protocols` 与其在 `PUT` 写入前的调用
   （提交值已由 `_validate_value` 逐字段校验、存量文件层已由载入点校验），
   `invalid_protocol_message`，以及 HTTP 写入面对协议错误的 422 特判。

## Non-goals

- **不新增成因码，不新增响应字段**：`invalid_config_file` / `config_file_unreadable` /
  `invalid_settings` / `model_not_available` 四个既有码承载全部形态；`contracts/openapi.json`
  的 schema、字段与路径零漂移（已实测；唯一 diff 是 `PUT /api/settings` 的 endpoint
  description 文案）。给就绪判定加 `invalid` 一类的新状态词汇明确不做。
- **不做「带病启动」式的容忍**：文件层坏值走的是「该输入源无效 → 以空文件层继续 + 大声明示
  + 保留页面自救入口」，这是上一批已归档的既有裁决，不是容忍非法值（非法值没进运行期）；
  env/cli 层的坏值一律当场失败，不启动、不降级继续。
- **不自动纠正、不回填合法值、不替用户改写文件**：siku 不猜用户想要哪个协议。
- **不改三层优先级与合并路径**，也不引入 sidecar 环境注入（既有 Non-goal）。
- **不动状态码**：坏值情形仍是 503（服务活着但该资源不可用），命令行是用法错误退出。

## Impact

- **契约**：`{code, message}` 结构、`code` 取值集、`ask_readiness` 形状全部不变，
  OpenAPI 快照零漂移。变的是**文案的准确性**（点出字段与合法值、按来源层指对杠杆）与
  **异常归类**（文件层坏值由 `invalid_settings` 改归 `invalid_config_file`）——
  后者是让既有码回到它本来说明的范围，不是重定义码义。
- **可达性**：桌面用户手改坏协议值后仍能打开设置页并一次保存自愈；终端用户拿到指对杠杆的
  指引；命令行坏参数不再可能进入运行期。
- **删除**：`validate_channel_protocols`、`invalid_protocol_message`、`_llm_config_error_message`
  的两个 `kind` 分支、`write_settings` 的协议 422 特判。
- 门禁：`pytest` **744 passed**、`ruff check/format`、`pre-commit run --all-files`、
  `mypy` 4 errors 全为 HEAD 既有（本批新增 0）、ui
  `tsc`/`eslint`/`vitest` **109 passed**（UI 零改动）、`openspec validate --specs --strict`
  **8/8**；真机冒烟（临时 HOME：坏值起服 → `GET` 503 `invalid_config_file` 带字段级指引 →
  `PUT` 修复 200 → 再 `GET` 200；`--llm-protocol bogus` exit 2）实录见 `tasks.md`。
- 受影响 ADR：**ADR-0009**（三层分层供给——本批只加校验位置，不改优先级）、
  **ADR-0012**（多协议——枚举由运行时校验前移到输入边界）。
