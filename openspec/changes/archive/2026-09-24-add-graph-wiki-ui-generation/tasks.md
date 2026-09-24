# 任务清单

## 约束冻结（实现前）

- [x] 冻结入口住址与形态（视图内空态主行动 + 已建态头部次行动，不做全局工具
      条）。（决议见 design.md 决议 #1）
- [x] 冻结门控语义（不做就绪门控，请求期错误映射兜底；llm-only 就绪留待后续
      立项）。（决议见 design.md 决议 #2）
- [x] 冻结 wiki 空态两段式流程（`graph_artifacts_missing` 就地引导，构建成功
      自动续跑）。（决议见 design.md 决议 #3）
- [x] 冻结调用语义（请求体 `{}` 幂等缓存路径；不暴露 `rebuild=true` 与目录
      覆写）。（决议见 design.md 决议 #4）
- [x] 冻结长任务反馈（禁用态 + 进行中文案 + 成功刷新 + 失败保留状态）。
      （决议见 design.md 决议 #5）

## UI（ui/src）

- [x] `api.ts` 新增 `GraphBuildResponse` / `WikiGenerateResponse` 类型与
      `buildGraph()` / `generateWiki()` 封装（POST 既有端点，请求体 `{}`）。
- [x] `GraphView`：空态「构建图谱」按钮（构建中禁用 + 进行中文案；成功加载
      画布；`empty_corpus`/warnings 如实反馈）；已建态头部「更新图谱」按钮；
      失败经 `ApiError` 展示中文 message。
- [x] `WikiView`：空态「生成 wiki」按钮 + 图谱缺失就地引导（构建成功自动续跑）；
      已建态头部「重新生成 wiki」按钮（成功刷新清单并清空旧选中）；终端导向
      文案替换为按钮化表述。
- [x] vitest：图谱空态构建成功/失败、已建态更新；wiki 空态生成、图谱缺失引导
      两段式、已建态重新生成、失败反馈；`npm run lint/test/build` 全绿。

## 交付门禁

- [x] pytest 全量、ruff check/format、mypy、pre-commit 全绿（Python 侧零改动，
      回归确认）；OpenAPI 快照无漂移（本 change 无契约变更）。
- [x] 手工冒烟（owner 指定 DASHSCOPE_API_KEY）：serve + tmp 语料 → 界面点击
      「构建图谱」→ 真实 LLM 抽取完成画布出现 → 点击「生成 wiki」→ 条目清单
      出现 → 「更新图谱」「重新生成 wiki」幂等路径缓存命中（llm_calls=0）。
- [x] 完成独立 review.md：红线 1（无业务逻辑进前端）、幂等路径、竞态序号、
      失败态不丢视图状态的证据。
