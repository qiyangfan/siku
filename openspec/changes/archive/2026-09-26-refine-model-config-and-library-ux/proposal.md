# 提案：模型上手体验与资料库操作精细化（DashScope 回退 + 厂商预设 + 导入/危险操作修型）

## Why

owner 2026-09-26 会话点名六项（截图 + 插话）：①资料库「导入文件」呈输入框样式，
不像文件选择控件；②「清理已标记文档」语义不可读；③该按钮与「全量重建索引」
是否高危、配色与二次确认存疑；④wiki/图谱显示「未创建」而 owner 多次说明可用
`DASHSCOPE_API_KEY`——内核 LLM 通道完全不感知该变量，且 wiki/图谱空态不说明
「缺什么、点哪里」；⑤设置中心三通道纯手写 base_url/model，应预设国内外著名
官方厂商（cc-switch 同类能力做精选裁剪，中转站不做）；⑥顺此思路全面排查同类
问题。实证：本机桌面 App 侧 config.toml 不存在、数据目录无图谱产物，GUI 进程
也读不到 shell 环境变量，「未创建」是诚实状态但界面未给出可行动路径。

## What Changes

- **内核（model-supply）**：LLM 通道新增唯一一个厂商环境变量回退——三层均未
  配置且 `DASHSCOPE_API_KEY` 非空时，回退为通义千问 OpenAI 兼容端点（固定
  base_url + `qwen-max`，与 owner 演示 serve 的 CLI 组合一致）；任一 LLM 字段
  显式配置时不回退；embedding/rerank 永不回退（红线：不静默回退内置端点的
  既有 MUST 保持）。图谱/wiki/问答/连通性测试同源生效。
- **契约（http-api）**：`GET/PUT /api/settings` 响应新增可选字段
  `llm_env_fallback`（null 或 `{vendor, base_url, model, api_key_env}`），
  让 UI 能如实说明「当前回退生效」；OpenAPI 快照再生成。
- **设置中心（web-ui）**：三通道各加「厂商预设」下拉（官方几家 + Ollama 本地，
  精选裁剪），选中即填充 base_url/model/api_key_env 与凭证模式，仍可手改；
  LLM 通道回退生效时展示说明 Alert。
- **资料库（web-ui）**：导入入口改为文件选择区（点击选择 + 拖拽投放，原生
  input 实现，不新增依赖）；「清理已标记文档」更名「清理失效文档」并以危险
  配色标识（确认对话框保留）；清单状态徽标补 title 释义。
- **wiki/图谱空态（web-ui）**：补模型就绪提示——LLM 通道缺 key 时说明缺项并
  给「去设置」入口，就绪时说明点击即可构建；不做就绪门控（沿用上批决议，
  叠加信息层而非置灰）。

## 受影响决策

- 红线 1 / ADR-0009（BYOK 分层）：回退使用的是用户自己的 `DASHSCOPE_API_KEY`，
  与「绝不静默回退内置端点」不冲突——端点/模型与 key 作为一组厂商缺省绑定，
  显式配置整体优先；embedding 通道不回退的既有 MUST 不变。
- ADR-0011 / 设计 token：危险配色使用既有 `--color-danger` 三 token，新增
  `.button-danger` 类，不引入裸色值。
- 不新增 ADR：厂商回退是 ADR-0009 分层口径下的缺省值修订，非架构级新决策。

## 与项目路线的关系

Phase 5「桌面无 CLI 上手」的配置一环补齐：owner 点名的修型批次。不改变 ROADMAP
其它项优先级（当前队列为空）。

## Non-goals

- 不接入中转站/聚合商全量清单：只精选官方几家 + Ollama 本地；预设模型名为常用
  默认，可手改，不做厂商模型列表拉取。
- 不解决桌面 GUI 进程读不到 shell 环境变量的问题：桌面侧以设置中心直填 key 或
  预设 + `api_key_env` 引用解决；sidecar 环境注入属 Tauri 壳议题，另立。
- 不改 CLI 旗标语义：部分旗标组合（如仅 `--api-key-env`）沿用既有 DeepSeek
  缺省，不在本 change 内修（既有文档化语义）。
- 不做 wiki/图谱生成的就绪门控：只加提示层，按钮不置灰（上批 design 决议 #2）。
- 不给「移除来源目录登记」加二次确认：仅移除登记不改文件，可逆低危。
- 不改生成端点契约、幂等语义与错误码；OpenAPI 仅有 `llm_env_fallback` 增量。
