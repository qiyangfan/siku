# 设计：问答就绪门控

## 决议 #1：就绪判定住在内核，`missing` 用机器 token

判定函数 `model_supply.ask_readiness(config) -> AskReadiness(ready, missing)`，
与 `resolve_llm_channel` / `resolve_embedding_channel` 同住一层，直接复用
`_resolve_channel`（空串归一、env 覆盖、config.toml 底座）与 `resolve_api_key`
（明文 → api_key_env 间接引用），保证与请求期真实解析零分叉——判定说就绪而
请求报未配置（或反之）即为缺陷。token 取 `<channel>.<field>`（当前全集：
`llm.api_key`、`embedding.base_url`、`embedding.model`），是稳定契约；中文话术
由 UI 生成（展示层职责，且 UI 需要自行拼接「还差哪几项」的列表语义）。

被否选项：前端按掩码视图自行推导——掩码视图是文件层的，env 层覆盖需要前端
复刻合并逻辑，违反红线 1 且必然漂移；`/api/ask` 前置检查端点——多一个端点
却无额外信息，settings 响应本就是设置页与问答页共同的配置事实源。

## 决议 #2：判定口径

- llm 通道：`resolve_llm_channel` 后 `resolve_api_key() is None` 即缺
  `llm.api_key`；base_url/model 有兼容缺省（既有 CLI 语义），不作为缺项。
- embedding 通道：三层合并后 base_url / model 任一为空即分别记缺项；两者齐备
  即就绪（凭证可选，本地 Ollama 允许无凭证——与 `ResolvedChannel.resolve_api_key`
  的既有口径一致）。
- rerank 通道：永不进入 missing。reranker=none 是 ADR-0009 一等公民路径，
  把可选项算进阻塞会让所有未配 rerank 的用户被永久置灰。
- 判定不含索引存在性、端点可达性：前者是 409 既有路径，后者归连通性探测。
- 已知盲区（独立评审确认，偏保守方向、可接受）：`ask_readiness` 判定以
  cli=None 合并（只看 config.toml + env 层），而 serve 请求期还叠加
  `--embedding-base-url` 等 CLI 参数层（serve 启动参数属最高层）。用 CLI 参数
  启动 serve 时会出现「判定未就绪（UI 置灰）但请求可成功」的反向分叉；危险
  方向（判定就绪而请求报未配置）因 CLI 层单调增的覆盖语义被排除。设置中心
  上线后 serve 由桌面壳不带 CLI 参数启动，此盲区仅影响 CLI 高级用法；若要
  消除，需把 serve 的 CLI 层透传进 settings 视图，随后续 change 处理。

## 决议 #3：载体与刷新时机

`SettingsResponse` 新增 `ask_readiness`（PUT 经 `SettingsWriteResponse` 继承），
`masked_view` 是 GET/PUT 共同的构造点，一处接入两处生效。UI 侧三个刷新时机：
问答视图变为可见时拉取 `GET /api/settings`（覆盖手工改 config.toml 的场景）；
设置保存成功后直接读 PUT 响应的 `ask_readiness`（零额外请求）；初次挂载随
问答视图默认可见自然覆盖。获取失败 → `readiness=null` → fail-open 不置灰。

## 决议 #4：HTTP 错误文案与 CLI 文案分叉

`map_ask_error` 是 HTTP 专属映射（CLI 走 `retrieval_error_message` →
`map_domain_error`），在其中新增 `ModelNotAvailableError` 分支给 UI 导向文案
（「设置」页引导），`map_domain_error` 的 CLI 指引（config.toml 路径 +
`--embedding-base-url` 参数示例）原样保留。这与 `llm_not_configured` 已采用
的「同错误码、按场景分文案」格局一致（0b90c59 先例），错误码
`model_not_available` 本身不变。

## 决议 #5：UI 门控语义

未就绪时：提交按钮 `disabled`（置灰）、页脚提示语由快捷键说明替换为就绪指引、
表单下方展示引导卡片（含缺失项中文列表与「去设置」按钮，卡片操作切视图而不
弹窗）。问题输入不禁用——用户可先写问题，配置完成后直接提交。门控在 `submit`
入口二次校验（防 Enter 键绕过置灰按钮），就绪状态并发变化时以提交瞬间状态为准。
