# 评审记录：本地问答内核与最小对话 UI

## 状态

通过。评审基于实现后的源码、测试和门禁结果；未引入流式、多轮会话、远程持久化或前端
知识库业务逻辑。

## 评审边界

- 问答是否严格基于本次检索上下文，证据不足是否拒答。
- citation 是否只允许引用本次上下文，成功/确定性无证据响应是否携带来源锚点和 request_id。
- 是否保持 localhost-only、BYO key、无账号、无付费、无云端持久化边界。
- 是否误把流式、多轮会话、图谱问答或前端业务逻辑带入本 change。
- Python 与 Node 两侧门禁、检索 golden set、OpenSpec strict 和 `ui-quality-gate` 是否全部通过。

## 证据

### 后端证据

- `uv run pytest`：427 passed；包含问答领域、API、provider 故障矩阵和 request_id 契约测试。
- `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy`、
  `uv run pre-commit run --all-files`：通过。
- `uv run siku evaluate-retrieval --golden-set benchmarks/golden-set-v0.jsonl
  --data-dir benchmarks/data --baseline benchmarks/retrieval-baseline-v0.json --json`：
  Recall@5=1.000、MRR@10=0.95679012345679，`passed=true`，无指标下降。
- `openspec validate --changes --strict`：归档前 1/1 通过；当前 `openspec validate --specs --strict`：5/5 通过。
- `contracts/openapi.json` 由 `uv run python -m siku.api.contract --refresh` 显式刷新，契约测试通过。

### UI 闸门验收

场景：工具类本地知识库（克制模式）｜Token：`ui/design-system/MASTER.md`

7 类缺陷：01✓ 02✓ 03✓ 04✓ 05✓ 06✓ 07✓

极端数据：长回答使用 `overflow-wrap:anywhere` 与预格式换行✓  空态/加载/失败态✓
引用来源长文本省略并可展开查看完整值✓

硬底线：对比度使用深色正文/明确语义色✓  触控目标 44px✓  375px 响应式无横向滚动✓
键盘焦点与原生 `details/summary`✓  `prefers-reduced-motion`✓  不保存 key✓

fake HTTP smoke：`npm ci`、`npm run lint`、`npm test`（4 tests）、`npm run build` 全部通过；
覆盖提交问题、展示回答、展开引用、证据不足和错误重试。

### 未覆盖项

未安装真实浏览器自动化运行时；fake HTTP smoke 使用 Vitest + jsdom 组件级浏览器交互环境，
并通过生产构建验证静态资源。真实 LLM 网络调用和真实浏览器跨进程冒烟不在 CI 范围内，
符合本 change 的“fake provider、CI 不访问外部网络”边界。
