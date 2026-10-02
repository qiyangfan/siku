# 评审记录：非法取值挡在输入边界之外

评审范围：本 change 的全部未提交改动（`git status` 未提交集 = 本明评审对象）。两轮：
R1 实现后自查 + R2 增量 review（对 R1 结论逐条复查，剔除自证臆断）。

## R1（实现自查，两处独立证据）

1. **撤掉修复即红**（不是靠读代码断言「有测试」）：
   - 关掉 `_reject_invalid_file_protocols` → 5 红（文件层坏值 3 + PUT 自救 2）。
   - 把 `map_domain_error` 的 `ProtocolConfigError` 分支改成 `if False` → 4 红。
   - 把 `ProtocolConfigError` 从 `map_probe_error` 摘掉 → 1 红（本轮新补）。
   - 把 `_config_file_error_message` 改回合成异常 → 1 红（本轮新补）。
   - 把 `protocol_error_mapping` 的 `surface` 分家打平 → 1 红（本轮新补）。
2. **契约零漂移有机器证明**：`contracts/openapi.json` 重新生成后 diff 仅一行，且是
   `PUT /api/settings` 的 endpoint description（法定成因措辞由「不可解析」扩为「对模型供给
   无效」）；request/response schema、字段、路径零变化。`ui/` 未出现在 `git status`。
3. **真机冒烟**（临时 `HOME` + 临时 vault/data，跑完即删，本机真实 config.toml 未读写）：
   坏值起服 → 启动告警点名 `[llm] protocol` → `GET /api/settings` 503 字段级指引 →
   `PUT` 修复 200 且 `invalid_config_file_overwritten=true` → 再 `GET` 200；
   `--llm-protocol bogus` exit 2；env 坏值 exit 1 无 traceback。
4. **不回显原值**：越界值不出现在异常文本、映射文案、日志与响应面（用例逐面钉住；
   `detail` 只由 `_reject_invalid_file_protocols` 产生，故可证明不含用户输入）。

## R2（增量 review：五处真实缺陷，已修 + 已补可失败用例）

R1 的结论「文案单源」实际只做了单源一半——同一段话发给两张面。逐条溯源后确认：

1. **`ProtocolConfigError` 文案违反双面纪律**（`messages.py` 模块 docstring 明令 HTTP 面
   MUST NOT 出现 CLI 参数教程、CLI 面保留文件与参数级指引）：R1 那份文案把
   `--llm-protocol` 写进 HTTP 面、把「设置」页写进 CLI 面。headless CLI 用户没有页面可存。
   → 抽 `protocol_error_mapping(exc, surface)`，两面分文；`map_domain_error` 与
   `map_probe_error` 共用。
2. **`channel_unsupported` 点名不存在的杠杆**：说「来自启动参数」，而 embedding/rerank
   没有 `--*-protocol` 选项、其 env 层也没有 protocol 字段——该字段只剩「程序传入的配置」
   一个来源。改名并点名真来源。
3. **探测面漏协议分支**：`ProtocolConfigError` 被通用类吞成「请检查该通道的 base_url、model」，
   同一故障读出面给 `invalid_settings`、探测面给 `model_not_available`——两张面两个 code
   正是 D4 承诺杜绝的第二套事实源。→ 补分支并复用同一映射函数。
4. **`map_probe_error` 的 `ModelConfigFileError` 文案滞后**：仍说「不可解析（内容已损坏）」，
   而本类已覆盖取值非法。→ 改为同措辞并拼 `detail`。
5. **启动告警丢 `detail`**：`_config_file_error_message()` 另造
   `ModelConfigFileError("Model supply config file is not valid TOML")`，字段级说明到不了
   启动面。→ 收下捕获到的异常本身。
   连带：`_config_file_gap_text` 横幅、`api/app.py` 写入自救日志与 docstring、
   `model_supply.load_config` 分型说明、`ask_readiness` 注释、规格两处「或启动参数」
   措辞全部随成因口径统一（旧措辞会把取值问题说成语法问题）。

**核验方式**：上述 5 处各配「撤掉修复即红」用例（见 tasks.md 门禁段红线计数）；
规格 delta 相应补「SHALL NOT 点名 `--llm-protocol`」「连通性测试同一 code 与 message」；
`--changes --strict` / `--specs --strict` 通过；mypy 本批新增 0 条。

## 排除项（核验后判定为非缺陷，附理由）

- **`ask_readiness` 里的 `_reject_channel_protocol("embedding", ...)` 变为不可达？**
  否。文件层的该字段已在 `load_config` 被拒，但 `cli` 层与调用方直接递入的 `config` 仍可
  携带它；且这是 spec MUST（embedding 遇非空 protocol 报指引而非静默忽略），保留为嵌入式
  调用的边界（注释已改述为实际挡哪一层）。
- **`ChannelValues.protocol` 为何不做 schema 级枚举校验？** 该字段被三通道共用，而
  「embedding/rerank 不得有 protocol」是跨通道规则，塞进共享字段会把两件事耦在一个类型里；
  文件层由载入点拒、CLI 层由枚举参数拒、提交值由 `_validate_value` 拒，三面覆盖已闭合。
- **`_reject_invalid_file_protocols` 与 `validate_channel_protocols` 重复？** 后者管的是
  「载入合法但合并后可非法」，而合并路径（PUT）已被 `_validate_value` 逐字段校验，写入前
  整体校验不可达，已删。删除后无测试变红、无调用点残留（grep 全仓确认）。
- **`load_config` 抛错文本内联 `{exc}`（TOMLDecodeError 详情）会泄用户内容？** 该文本只进
  异常对象，映射层自撰中文文案、日志按 spec 只记类名与路径；且既有纪律已限定
  `ValidationError` 只留 loc+type。属既有形态，非本批引入。

## 遗留登记（范围外，未改）

- `cli.py` 其余 `except` 分支把异常文本 `%s` 记进日志（实测不含凭证，属口径不齐）——
  与本批无因果关系，登记待办不动手。
- `test_api.py` 与 `tests/test_api_cli.py` 各有 monkeypatch `config_file_path` 后仍读到
  宿主机路径的情形（双模块名绑定，`from X import name` 造成）：已按「改断言抓成因」处理，
  未改代码路径。
