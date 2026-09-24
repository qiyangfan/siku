# 提案：图谱与 wiki 生成入口界面化（保留 CLI）

## Why

图谱与 wiki 的生成端点（`POST /api/graph`、`POST /api/wiki`）自 http-api vertical
slice 起就已存在且带领域错误归一，但 UI 从未接入：图谱/wiki 视图为纯只读，空态与
时效提示均引导「请在终端执行 `siku graph` / `siku wiki`」。桌面上手链路
「配模型 → 进资料 → 看知识」在「看知识」一环断回终端。owner 2026-09-24 点名：
生成收编为界面按钮（CLI 保留不动），冒烟可用 DASHSCOPE_API_KEY。

## What Changes

- `ui/src/api.ts` 新增 `buildGraph()` / `generateWiki()` 封装（POST 既有端点，
  请求体 `{}`，全部走服务端默认路径）。
- 图谱视图：空态「图谱尚未构建」卡片的终端导向文案替换为「构建图谱」按钮
  （构建中禁用 + 进行中文案，成功后自动加载画布）；已建态头部新增「更新图谱」
  按钮（幂等缓存路径，成功后刷新统计与画布）。
- wiki 视图：空态「wiki 尚未生成」的终端导向文案替换为「生成 wiki」按钮；若
  图谱产物缺失（`graph_artifacts_missing`）则就地引导并提供「构建图谱」按钮，
  构建成功后自动续跑生成；已建态头部新增「重新生成 wiki」按钮（成功后刷新清单）。
- 纯 UI 变更：内核、端点契约、错误映射、OpenAPI 快照均不动。

## 受影响决策

- 红线 1 / ADR-0002：生成动作全部经既有 localhost HTTP 端点完成，无业务逻辑
  进入前端；按钮只做「触发 + 反馈」。
- ADR-0009 / BYOK 供给：生成使用设置中心当前 LLM 通道（免重启生效），UI 不
  复刻凭证判定；未配置时由既有请求期错误映射给出中文指引。
- 不新增 ADR：无架构级新决策，属既有生成能力在 UI 面上的入口呈现。

## 与项目路线的关系

Phase 5「桌面无 CLI 上手」链路补齐（「看知识」一环的最后一处终端断点），owner
2026-09-24 会话点名立项。不改变发布形态与排序中其它项的优先级。

## Non-goals

- 不改 CLI 行为与文案：`siku graph` / `siku wiki` 保留且为等价路径。
- 不改后端端点契约、错误码与文案：无 OpenAPI 变更；`graph_artifacts_missing`
  等既有 code 的服务端文案不变，UI 按错误码就地给出按钮化引导。
- 不做生成前置就绪门控：问答的 `ask_readiness` 含 embedding 口径，与图谱/wiki
  仅需 LLM 不匹配；引入 llm-only 就绪语义属扩权，不做（见 design.md 决议 #2）。
- 不暴露 `rebuild=true` 强制全量重建入口：避免误触大额 LLM 开销；默认按钮走
  幂等缓存路径（等价 `siku graph` 默认行为）。
- 不做生成进度流式/轮询：端点为同步阻塞式，按钮以「进行中」状态表达长耗时。
