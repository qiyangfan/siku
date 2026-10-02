# 设计：LLM 通道多协议接入

## 决议

### 决议 #1：协议是通道的第 5 个字段，枚举三值，缺省零漂移

`ChannelValues.protocol: str | None`，合法值 `openai-chat`（缺省）/`anthropic`/
`openai-responses`。加入既有三层合并（config.toml `[ll]` → `SIKU_LLM_PROTOCOL`
→ `--llm-protocol`），空白串归一为未设置。缺省 `openai-chat` 使既有 config、
脚本与 DashScope 回退通道零漂移。embedding/rerank 的 `resolve_*` 遇非空
`protocol` 抛 `ModelNotAvailableError` 带指引（fail loud，不静默忽略）——
二者的线协议事实上单一，开放字段只会制造「配了却没用」的错觉。

### 决议 #2：协议差异全部收敛在 HttpxLlmProvider 的请求/响应两端

| 维度 | openai-chat | anthropic | openai-responses |
|---|---|---|---|
| 端点 | `{base}/chat/completions` | `{base}/v1/messages` | `{base}/responses` |
| 凭证头 | `Authorization: Bearer` | `x-api-key` + `anthropic-version: 2023-06-01` | `Authorization: Bearer` |
| system | `messages[0]` | 顶层 `system` 字段 | 顶层 `instructions` 字段 |
| 幂等参数 | `temperature=0, stream=false` | 同左 + `max_tokens=8192`（协议必填） | 同左 + `max_output_tokens=8192` |
| 取文本 | `choices[0].message.content` | `content[]` 中 `type=="text"` 拼接 | `output[]` 中 `type=="message"` 的 `content[]` 中 `type=="output_text"` 拼接 |

anthropic 端点统一 `{base}/v1/messages`：Anthropic 官方（`https://api.anthropic.com`）与
国内分支（Kimi `…/anthropic`、智谱 `…/api/anthropic`、千问 claude-code-proxy 等）的
生态惯例都是客户端拼 `/v1/messages`，单规则覆盖。幂等语义（temperature=0、
非流式、同输入同输出）三协议一致，不破坏「重建产物 diff 为空」闸门。空响应、
429、>=400、超长上下文（hints 并入 anthropic「prompt is too long」措辞）、
断连五剧本错误映射复用，调用方零改动。

### 决议 #3：自建网关与官方端点平级（owner 定调），不做强制中转

muniu/one-api/new-api 类反代是**用户自选端点**，地位同 Ollama：手填 base_url
（OpenAI 兼容反代默认 `openai-chat`；Anthropic 协议反代选 `anthropic`）即可，
无任何特殊路径、不设默认中转、不内置其地址。UI hint 明示这一平级关系。
预设名单只收官方直连端点；「自定义（不自动填充）」即自建入口。

### 决议 #4：预设按「厂商 × 协议分支」组织，选预设联动协议

预设表每项带 `protocol`；新增 Anthropic 分支预设：Kimi（`https://api.moonshot.cn/anthropic`）、
智谱 GLM（`https://open.bigmodel.cn/api/anthropic`）、通义千问（claude-code-proxy
分支，模型名按账号可改）。LLM 表单新增「接口协议」NativeSelect（缺省
openai-chat），手改协议不改端点、选分支预设同时设端点与协议。embedding/rerank
不出现协议控件（内核拒绝，界面不给假入口）。

### 决议 #5：探测与设置契约随协议同构

`POST /api/settings/test` 按表单当前协议发起探测（anthropic 探测同样是最小
chat 调用）；`GET/PUT /api/settings` 的视图与提交值携带 `protocol`，枚举非法
返回 422 中文指引。OpenAPI 快照再生成，防漂移测试兜底。

## 风险与边界

- 协议配错（如把 OpenAI 兼容端点配成 anthropic）在请求期 404/400，映射为
  既有 `llm_provider_error`/`llm_connection_error` 中文指引，测连接即可发现。
- `max_tokens=8192` 为 anthropic 协议必填值的保守缺省；超长输入由超长剧本
  报可读错误，不做自动分片。
- 老内核/旧配置无 `protocol` 字段 → 一切按缺省，前后端 fail-open 兼容。
