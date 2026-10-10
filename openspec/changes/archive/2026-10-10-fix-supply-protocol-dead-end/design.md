# 设计：协议越界的三处死路收口——解析结果是数据

## 当前证据与单一结论

实测代码路径（`src/siku/model_supply.py`、`api/settings.py`、`api/app.py:1016-1131`、
`cli.py serve`）：运行期 `ProtocolConfigError` 只可能来自环境变量层（`SIKU_LLM_PROTOCOL`）
与程序传入层——文件层非法值在 `load_config` 载入点即拒（`_reject_invalid_file_protocols`），
`--llm-protocol` 是 typer 枚举参数在解析阶段即拒。该异常在三个面被当成「整个视图/进程的
失败」：`masked_view → ask_readiness` 抛出 → GET 503；PUT 落盘后装配同源抛出 → 503 降级；
serve 启动解析抛出 → `_fail` 退出。根因不是缺 UI 控件（方案①的「仅修正协议」写的是被
env 层压制的文件层，是死控件），而是**就绪判定把解析失败当异常上抛，而读面需要的是数据**。

旧否决（`settings-error-cause-codes` 提案）针对的是「200 + 空文件层」：伪造数据 + 与
请求期现读分叉 → 误就绪。本设计不伪造：视图仍走请求期同一解析函数，失败以 `invalid`
token 成为视图数据——「视图说无效 ⇔ 请求必失败」同源成立，误就绪不可能出现。

## D1：就绪判定协议越界转为数据（内核单点）

`model_supply.ask_readiness`：llm 通道解析 `except ProtocolConfigError` → 记
`invalid` token（常量 `INVALID_LLM_PROTOCOL = "llm.protocol"`），跳过该通道
的凭证缺项检查；embedding 通道的非空 protocol 由原 `_reject_channel_protocol` 抛出
改为记 `INVALID_EMBEDDING_PROTOCOL = "embedding.protocol"`。`ready = not missing
and not invalid`。`AskReadiness` 增 `invalid: tuple[str, ...]`。请求面解析函数
（`resolve_llm_channel`/`resolve_embedding_channel`/`_reject_channel_protocol`）零改动，
其余调用方（检索装配、MCP、probe）行为零漂移。

## D2：serve 容忍启动，规则收敛

`cli.py serve`：`except ProtocolConfigError` 先于 `except ModelNotAvailableError`，
命中则 stderr 中文告警（点名 `SIKU_LLM_PROTOCOL`、说明 LLM 通道将不可用、给出
「修正变量后重启」指引）+ `logger.warning`，`llm = None` 继续启动。下游：`api_key_env`
回落 `DEFAULT_API_KEY_ENV`；`_announce_supply_channels` 接受 `llm=None` 并播报
「llm=invalid（SIKU_LLM_PROTOCOL 越界）」。与既有「坏文件不堵启动面」（决议 #3）收敛为
同一条规则：**供给配置错误不堵启动面，请求面归一失败**。CLI 一次性命令不改（fail-fast
的指引在 shell 里可行动）。

## D3：设置读写两面贯通

`GET`：`masked_view` 透传 `readiness.invalid`（`AskReadinessView` 增 `invalid:
list[str]`，default 空）；读面 except 分支只剩文件层两型（语义不变）。`PUT`：落盘成功
后 `masked_view` 不再因协议越界抛出 → 返回 200 `SettingsWriteResponse`（含既有
`invalid_config_file_overwritten`/`warnings` 与视图内 invalid token）；503 降级分支
保留为未来供给类异常的兜底（其 spec MUST 载体不变）。连通性测试 `resolve_probe_target`
仍走解析函数 → 503 `invalid_settings` 不变（与请求面同码同文案）。

## D4：UI 呈现与「不可修」纪律

`api.ts`：`AskReadiness` 增 `invalid?: string[]`（可选，兜底旧内核）。`SettingsView`：
视图就绪后在表单上方渲染黄色警示条（token → 中文话术映射函数，如 `llm.protocol` →
「该值来自环境变量 `SIKU_LLM_PROTOCOL`，优先级高于本页设置，保存覆盖不了；请在启动服务
的终端修正或取消该变量后重启」），SHALL NOT 渲染任何保存可修入口；保存成功反馈照旧，
警示条随新视图持续可见。`LlmReadinessHint`：保留「关心 llm 面」的原有判定
（`!missing.includes("llm.api_key")`）并叠加 llm.* invalid 检查——组件只关心 LLM 通道，
不越权代答全局 ready；无效时给「模型通道配置无效」变体文案 + 去设置按钮（fail-open
语义不变）。契约快照 `--refresh` 再生成。

## D5：规格修订与超长正文收敛（同件完成）

MODIFIED 四个需求（场景名全保留）+ 其中正文超 500 字符的按新 CLI 严格检查收紧到 ≤500
（细则本就在场景里，删除的是与场景重复的论证性文字）：http-api「提供模型供给设置的读写
端点」（1590→≤500，10 场景，落盘后场景 THEN 改 200+标记，新增读取面 invalid 场景）、
「配置文件故障以稳定 code 分道」（1077→≤500，4 场景，上层协议越界场景 THEN 改为
分面结果）；model-supply「LLM 通道支持多协议接入」（775→≤500，7 场景，非法协议值
场景 THEN 分面）、「配置文件不可解析时用户可自救」（814→≤500，纯文本收敛零行为
变化）；web-ui「提供模型供给设置表单」（602→≤500，增 invalid 警示条场景）。1 处
纯文本收敛随本件 model-supply delta 顺带完成并在 proposal 留痕，不另开 ceremony change。

## 验证

先写失败测试：`SIKU_LLM_PROTOCOL=garbage` 下 ask_readiness 返回 invalid token 不抛；
GET 200 + invalid；PUT 200 成功形状含事实；probe/ask 仍 503 invalid_settings 同文案；
serve 启动成功 + stderr 告警 + /api/health 可达 + ask 503；embedding protocol 程序层
越界 → invalid token。UI：警示条渲染、无保存可修入口、LlmReadinessHint 无效变体。
门禁：全量 pytest、ruff、ui vitest/tsc/eslint/build、`openspec validate --changes
--strict` 与 `--specs --strict`（收口后应 9/9）、契约快照 diff 审查、真机冒烟
（临时 HOME + 垃圾 env 变量，两处死路逐一复核）。
