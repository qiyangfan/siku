# 设计：模型上手体验与资料库操作精细化

## 决议

### 决议 #1：DashScope 回退——仅 llm 通道、仅整通道缺省时、key 与端点绑定

`resolve_llm_channel` 在三层合并结果**四个字段全空**且 `DASHSCOPE_API_KEY`
非空时，返回通义千问 OpenAI 兼容端点回退（`base_url=`
`https://dashscope.aliyuncs.com/compatible-mode/v1`、`model=qwen-max`、
`api_key_env=DASHSCOPE_API_KEY`）。要点：

- **整通道缺省才回退**：任一字段被任何层显式配置（哪怕只配了 `api_key_env`）
  即不回退——部分配置说明用户有明确意图，劫持会造成「配了 A 家却被发到 B 家」
  的更糟混淆；既有 CLI 部分旗标组合的 DeepSeek 缺省语义不变。
- **key 与端点/模型绑定**：不做「只借 key」的回退——把 DashScope key 发往
  DeepSeek 缺省端点正是此前 401 误报的成因；回退必须三件成套。
- **模型选 `qwen-max`**：与 owner 演示 serve 的 CLI 组合（`--llm-model qwen-max`
  + compatible-mode/v1）一致，是实证过的可用组合。
- **embedding/rerank 永不回退**：embedding 换模型牵动全量重建（既有 MUST：
  不静默回退内置端点）；rerank 可选不阻塞。
- 判定与请求期解析同源：`ask_readiness`、图谱/wiki 生成、问答、连通性测试
  全部经 `resolve_llm_channel`，回退自动覆盖，无第二套事实源。

### 决议 #2：`llm_env_fallback` 契约字段——回退必须可解释

回退对「设置中心显示空表单但生成实际可用」的落差必须可解释，否则用户会重复
配置或在排查时被误导。`GET/PUT /api/settings` 响应新增可选
`llm_env_fallback: null | {vendor, base_url, model, api_key_env}`；计算走与
请求期相同的合并路径并计入 serve 的 CLI 层（`create_app` 持有 `llm_supply`），
保证「响应说回退生效」⇔「请求真的走回退」。前端 fail-open：字段缺失/形状非法
按无回退处理（兼容旧内核）。vendor 恒为 `"dashscope"`，为将来可能的同构回退
留形状，不在本 change 扩名单。

### 决议 #3：厂商预设只住 UI 层，精选官方 + 本地

预设是静态填充表（Select → 填 base_url/model/api_key_env + 凭证模式），不改
内核契约、不做厂商 API 探测、不拉取模型列表。名单按 owner 指示精选（cc-switch
裁剪，中转站不做）：

- **国内官方**：通义千问（阿里云百炼）、DeepSeek、Kimi（月之暗面）、智谱 GLM、
  硅基流动、火山方舟（豆包）、百度千帆。
- **国际官方**：OpenAI、Anthropic Claude（OpenAI 兼容层）、Google Gemini
  （OpenAI 兼容端点）、xAI Grok、OpenRouter（头部官方聚合）。
- **本地**：Ollama（无凭证，`key_mode` 置回直填且 key 留空）。

每通道只列该通道真实可用的预设（如 DeepSeek 无 embedding 则不列）。火山方舟
的模型名依赖账号推理接入点，预设填常用默认并在 hint 注明可改。选中预设不自动
保存——仍走「保存设置」提交，与既有编辑-保存模型一致。

**协议口径（owner 2026-09-26 插话补充）**：国内几乎所有主流厂商都有 Anthropic
协议分支（`/v1/messages`，cc-switch 名单多为其 Claude/Coding 分支）；siku 内核
只说 OpenAI 兼容协议（`/chat/completions`），故预设一律取各厂商 **OpenAI 兼容
端点**，Anthropic 协议分支不在预设内，UI hint 显式说明，防用户拿 Claude 分支
的 key/地址误配。Anthropic 官方本身经其 OpenAI 兼容层（`/v1/chat/completions`）
接入。

### 决议 #4：导入区——原生文件选择区，选完即传

替换 Mantine `FileInput`（视觉是输入框，控件-数据不匹配，owner 点名）为定制
投放区：虚线边框卡片 + 图标 + 「点击选择，或拖入文档」；点击与键盘 Enter/Space
触发隐藏的原生 `<input type="file" multiple>`，`dragover/drop` 原生事件高亮并
接收文件。**不引入 `@mantine/dropzone`**（依赖纪律：原生 input + 既有组件可
实现；react-dropzone 属新增传递依赖）。选中即沿用既有「立即摄取」语义，成功
失败反馈复用既有任务进度卡，不新增状态机。

### 决议 #5：危险操作分级——purge 危险配色，rebuild 保持中性

- **清理失效文档（原「清理已标记文档」）**：物理删除原件与投影、不可逆 =
  破坏性操作 → 触发按钮改 `.button-danger`（`--color-danger` 系 token，浅红
  底 + 危险色文字），确认弹窗保留，确认键 `.button-danger-solid`；按钮常显
  tooltip 说明「失效 = 来源缺失/已被替代」。更名理由：「标记」是内部状态语，
  用户不可读；「失效」与徽标文案（来源缺失/已被替代）同义对齐。
- **全量重建索引**：重操作但可重建（语料不动、产物可再生），非破坏性 →
  保持中性配色与既有确认弹窗。
- **移除来源目录登记**：只删登记不删文件，可逆 → 不加确认。

### 决议 #6：wiki/图谱空态就绪提示——信息层，不做门控

两视图空态（`graph_missing` / `wiki_missing`）增加就绪提示行：拉取
`GET /api/settings`，按 `ask_readiness.missing` 是否含 `llm.api_key` 分两种
文案——缺 key 时说明「构建需要调用 LLM 通道」并给「去设置」按钮（经新 prop
由 App 提供视图切换，与「在问答中查询」同模式）；就绪时说明「点击下方按钮
开始构建」。按钮不置灰、不加请求前拦截（上批 design 决议 #2 维持：请求期
错误映射兜底）。提示读取失败静默不渲染（fail-open，不阻塞主流程）。

## 风险与边界

- 本地开发 shell 若导出 `DASHSCOPE_API_KEY`，内核测试中断言 DeepSeek 缺省的
  用例会翻车：相关用例须 `monkeypatch.delenv` 隔离，不依赖外部环境。
- OpenAPI 快照（contracts/openapi.json）随字段增量再生成，防漂移测试兜底。
- 桌面 GUI 进程读不到 shell 环境变量（实证：launchctl/rc 文件均无）：
  回退主要惠及终端 serve 场景；桌面场景由预设 + 设置中心解决（Non-goal 声明）。
