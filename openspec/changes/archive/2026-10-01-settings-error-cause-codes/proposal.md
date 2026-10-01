# 提案：配置文件故障按成因给稳定 `code`，设置页自救入口由该码驱动

## Why

`fix-model-supply-error-surfacing` 把「凭证被拒 / 通道未配置 / 内容不可解析 / 内容读不到」
分成了不同**异常类**与不同**文案**，但 HTTP 面上它们共用一个 `code=model_not_available`。
于是上一轮为了打通「重新保存覆盖坏文件」这条自救路径，UI 只能靠**启发式**猜：
「拿到 HTTP 错误响应 = 服务可达 = 可以给覆盖入口」。这个猜法有两个洞：

- 权限/IO 读不到的文件同样给得出覆盖入口，点下去必被服务端拒（内容未知时禁止覆盖），
  是误导入口；
- 反过来，「越界 protocol」这类**内容可解析但取值已知非法**的情形也落在同一个 code 上，
  而它恰恰是保存能修的。

本会话中间试过另一种解：让 `GET /api/settings` 对坏文件返回 200 + 空文件层 + 标记。
**它被否掉了**，理由是硬伤：请求期每请求现读该文件，读面一旦容忍，就会出现
「设置页说就绪、真实请求 503」的误就绪——比死路更难排查，也正是既有场景
「读取面必须与请求期同源失败（非 500/非误就绪）」立约要防的东西。写这条是为了不让下一个
人再走一遍这条岔路。

根因是**分型止步于异常类，没有传到机器可读的响应面**。

## What Changes

1. **稳定成因码**：`map_domain_error` 与 `map_probe_error` 两处映射点（覆盖读取面、写入面、
   连通探测面、检索/问答请求面）给配置文件两型各自的码——
   内容确证不可解析 `invalid_config_file`（保存可修）、
   内容未知（权限/IO 读不到）`config_file_unreadable`（保存不可修）。
   状态码、文案与 `{code, message}` 结构不变；其余供给错误仍是 `model_not_available`。
2. **读取面继续报错**，不引入容忍式 200（理由见上）。
3. **UI 入口由成因码驱动**：只在 `invalid_config_file` 时给出「确认以空配置覆盖本机配置文件并
   重新填写」，删除「服务可达即可覆盖」的启发式；`config_file_unreadable` 与其它失败只留
   「重试读取」。空配置出图走显式的 `BLANK_CHANNEL_VIEW` 基底，不伪造 `config_path`。
4. **同一请求只读一次配置文件**：`PUT` 响应的 `llm_env_fallback` 改为复用刚写入的层
   （此前它再 `load_config()` 一次，通道视图用 `merged`、回退判定用重读结果，是两套事实源）。
5. **日志口径对齐**：读写两面遇坏文件只记异常类名与文件路径，不再记解码器详情文本
   （成因与处置已由响应面完整承载，详情文本对排障无增量）。评审实测纠正了此处原来的立论：
   `TOMLDecodeError` 只给行列、`UnicodeDecodeError` 只给字节十六进制与位置，都不回显出错行
   原文，所以「防 key 泄漏」不成立；防凭证值泄漏靠的是既有的「`ValidationError` 只保留
   字段路径与错误类型」（`model_supply.py:192-199`）。
6. **落盘后不得谎报保存失败**：`PUT` 的响应装配若抛领域错误（环境变量层的协议越界——
   写入前的 `validate_channel_protocols` 只管文件层，就绪判定却含 env/cli 层），按 `GET` 面
   同一映射给码，并在文案声明「本次提交已写入本机配置文件」。此前这段落在 `try` 之外，
   由全局兜底返 500 `internal_error`——文件其实已经写好，用户被告知失败。
7. **启动面不得漏 traceback**：`siku serve` 遇坏文件走「忽略文件层再解析一次」的分支，
   而那次再解析若因 env/CLI 层协议越界抛错，异常出自 `except` 块内部、不会被同一 `try` 的
   后续分支接住——实测（临时 HOME + `SIKU_LLM_PROTOCOL=totally-bogus-protocol`）直接漏出
   `ProtocolConfigError` 的完整 traceback 后退出。改为内层 `try` 嵌套，使其归入既有的 `_fail`
   归一化指引（该文案本就点名 `--llm-protocol`、`SIKU_LLM_PROTOCOL` 与 `[llm] protocol`）。

## Non-goals

- **不改配置文件两型的状态码**：仍是 503（服务活着但该资源不可用），只改 `code` 值。
  唯一例外是 What Changes #6：`PUT` 落盘后装配失败原走全局兜底的 500，那是「错误地宣称
  服务器失败」而非本批要改的语义分型，改为与 `GET` 面同码同指引。
- **不做容忍式读取面**：`config_file_invalid` 一类「成功响应里的降级标记」不引入，
  它必然与请求期真实结果分叉。
- **不改写面语义**：`invalid_config_file_overwritten` 的触发条件、原子替换、0600 权限不动。
- **不自动备份坏文件再覆盖**：文件既确证不可解析，其可读配置量为零；旁路产物会让「覆盖」
  变成不易察觉的数据动作。
- **不在 HTTP 文案里出现配置文件路径或命令行教程**（既有红线，本批沿用）。

## Impact

- **契约**：`{code, message}` 结构不变，新增两个稳定 code 取值；这是把已存在的语义分型
  暴露到机器可读面，不是新增行为。`contracts/openapi.json` 随快照再生成（`code` 为自由字符串，
  schema 无枚举需扩）。既有 6 处断言 `model_not_available` 的测试里，仅配置文件两型改判新码，
  未配置/凭证被拒等仍断原码。另修正一条错误响应：`PUT` 在「文件已写入、就绪判定因 env 层
  协议越界而抛错」时由 500 `internal_error` 改为 503 `invalid_settings`（与 `GET` 面同码），
  属把错误路径改对，不新增字段、不改成功响应形状。
- **可达性**：坏 TOML 与越界 protocol 两型下，设置页给出可执行自救入口；
  权限/IO 读不到时不再给出任何覆盖入口（此前会误导）。
- 门禁：`pytest` 733 passed（较上一批 724 净增 9 条）、`ruff check/format` 绿、ui `tsc`/`eslint`/`vitest` 109 passed、
  `openspec validate --specs --strict` 8/8；真机冒烟（临时 HOME + 坏文件/`chmod 000` 两态）
  实录见 `tasks.md`。
