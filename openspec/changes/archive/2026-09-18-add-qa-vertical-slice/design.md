# 设计：本地问答内核与最小对话 UI

## 数据流与分层

```text
问题
  → POST /api/ask
    → AskService
      → SearchService（既有混合检索）
      → ContextPacker（有界、带 citation_id）
      → AnswerProvider（可注入 LLM 协议）
      → AnswerParser + CitationValidator
  → answer + citations + retrieval + request_id
```

UI 只负责输入、展示和引用展开；API 负责请求模型、错误映射和 request_id；问答服务负责
检索编排、提示词、结构化输出校验和引用完整性；LLM provider 只负责补全。任何一层都不
读取原始存储格式，不把业务逻辑下沉到前端。

## 问答请求与响应

`POST /api/ask` 请求：

```json
{
  "question": "这个项目的本地优先边界是什么？",
  "top_k": 6,
  "candidate_k": 30
}
```

请求必须先经过边界校验：`question` 去除首尾空白后不能为空，并设置明确的字符上限；
`top_k` 与 `candidate_k` 必须为正数、满足 `top_k <= candidate_k`，且两者都有硬上限。
上下文打包器还必须设置固定的总字符/token 安全上限，超出时不得静默截断证据或继续调用
LLM，而是返回 `503` 的输入过长错误。具体限制作为问答领域常量和契约测试的一部分冻结，
不能由前端绕过。

响应的稳定核心字段：

```json
{
  "request_id": "uuid",
  "question": "这个项目的本地优先边界是什么？",
  "answer": "……",
  "insufficient_evidence": false,
  "citations": [
    {
      "citation_id": "C1",
      "source_name": "architecture.md",
      "note_path": "notes/architecture--...md",
      "anchor": "产品定位",
      "chunk_id": "...",
      "source_hash": "...",
      "text": "……"
    }
  ],
  "retrieval": {"top_k": 6, "candidate_k": 30, "result_count": 3},
  "model": "deepseek-chat"
}
```

回答 provider 使用严格 JSON 输出：`answer`、`citation_ids`、`insufficient_evidence`。服务端
必须拒绝无法解析的输出、未知 citation id 和与 `insufficient_evidence` 状态矛盾的结果；
这些错误映射为外部依赖不可用，不把半成品答案返回给 UI。无检索结果时不调用 LLM，直接
返回 `insufficient_evidence=true` 的确定性响应，减少费用并避免无依据生成；该响应仍返回
当前配置的模型身份，但不表示实际发生了模型调用。

## Grounding 规则

- 上下文只由 `SearchService` 返回的 chunk 组成，按最终 rerank 顺序编号，默认最多 6 条。
- 每个上下文片段包含 `citation_id`、正文、来源名、note path、anchor 和 source hash。
- system prompt 要求仅基于给定片段回答；无法由片段支持时必须拒答，不得补充常识性猜测。
- `insufficient_evidence=false` 时，回答和 `citation_ids` 都必须非空；`true` 时服务端返回
  确定性的证据不足文案和空引用，不信任模型自由编写的无依据结论。
- citation validator 确认回答引用的每个 id 都属于本次上下文；重复 id 按首次出现顺序去重，
  未知 id、字段矛盾或无法解析均视为结构化输出失败。API 返回完整引用对象，UI 不自行解析
  或猜测引用。
- 既有检索排序和参数语义不改；问答质量首先通过固定 fake 和引用/拒答契约验收，后续再
  用真实使用失败案例扩充评测集。

## LLM 配置与生命周期

- `siku serve` 增加 `--llm-base-url`、`--llm-model`、`--api-key-env`，默认沿用现有
  DeepSeek 配置；这些配置同时作用于 `/api/ask`、`/api/graph` 和 `/api/wiki` 的 provider
  工厂，key 只从进程环境读取，不进入 HTTP 请求体、前端状态或持久化。
- API 应用工厂允许注入 fake `AnswerProvider`，测试不发真实网络请求。
- 首版使用现有同步补全协议，单请求一次回答；不实现 SSE/WebSocket/stream 参数。
- provider 的连接资源由应用或请求生命周期显式关闭；LLM 异常统一映射为既有 503 错误族。
- 问答使用独立的错误映射入口复用稳定错误码；不得直接套用图谱抽取的 422 映射，且问答
  文案不得包含“已完成部分已入缓存”“重跑自动续传”等不适用语义。请求成功和确定性无证据
  响应返回 `request_id`；错误响应继续保持现有 `{code, message}` 结构，request_id 只写入
  日志，以免改变既有错误契约。

## 对话 UI

### 规划闸门

- 场景定级为工具类本地知识库界面，采用克制模式。唯一核心任务是“提交问题并判断回答
  是否有来源”；用户进入页面 3 秒内先看到问题输入和当前回答状态，模型身份、request_id
  和引用属于次要信息。
- token 作为 UI 唯一来源：主色、辅助色、成功/警告/危险语义色；display/body/caption 三档
  字阶；4/8 基础间距、统一圆角和轻量阴影。实现时落盘为 `ui/design-system/MASTER.md`，
  组件内不得出现未登记的裸色值或裸尺寸。
- 控件选型固定为：问题文本 → 多行文本框（Enter 提交、Shift+Enter 换行）→ 提交按钮；
  加载中提交按钮禁用；可重试错误使用同一提交按钮文案，不自造弹窗或 toast 基础组件。
  若提供取消，只使用浏览器请求中止，不伪造服务端取消状态。
- 页面和组件必须满足对比度至少 4.5:1、可见键盘焦点、触控目标至少 44×44px、375px 无
  横向滚动，并尊重 `prefers-reduced-motion`。

- 输入区：问题文本、提交、禁用重复提交；不提供账号、模型 key 或远程地址输入。若提供
  取消，仅允许中止浏览器侧等待，不对服务端或 LLM 调用作取消承诺。
- 回答区：答案正文、证据不足提示、引用折叠面板，引用显示来源和 anchor。
- 状态：内核未启动、索引不可用、LLM 未配置、限流、超长、断连、空返回、解析失败、
  加载中和无证据均显示可行动中文提示。
- 本次回答在页面内展示即可，不写入服务器或磁盘；刷新页面即结束当前单轮状态。
- UI 通过 `ui-quality-gate` 验收键盘焦点、窄窗口、长答案、引用折叠和错误态；验收结果和
  未覆盖项写入本 change 的 `review.md`。

## 测试与验收

- 问答领域测试：正常回答、无命中拒答、未知引用、非法 JSON、空回答、上下文超长、限流、
  断连和 key 缺失。
- API 测试：成功响应、请求校验、索引缺失 409、LLM 失败 503、无 traceback、request_id。
- UI 测试：提交问题、展示答案、展开引用、无证据、错误重试、内核不可用。
- 既有 `uv run pytest`、Ruff、mypy、pre-commit、OpenSpec strict 和检索 golden set 门禁
  全部通过；前端测试使用 fake HTTP/LLM，CI 不访问外部网络。
