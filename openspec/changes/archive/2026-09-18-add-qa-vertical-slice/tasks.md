# 任务清单

## 问答领域层（先测试后实现）

- [x] 定义问答领域模型、AnswerProvider 协议、结构化回答 payload 和稳定 prompt 版本；冻结
      question/top_k/candidate_k/context 的服务端硬上限与 `top_k <= candidate_k` 校验。
- [x] 先写上下文打包与引用校验测试：确定性编号、有界参数、上下文超限、未知引用、重复
      引用（按首次出现顺序去重）、正常回答无引用和空命中。
- [x] 实现问答服务：复用 `SearchService`，无命中确定性拒答，有命中才调用注入的 provider。
- [x] 先写 LLM/provider 输出故障矩阵测试：正常、非法 JSON、字段缺失/状态矛盾、空返回、
      限流、断连、输入过长和 key 缺失；确认结构化输出失败为 `llm_provider_error`/503，且
      不带图谱缓存续传文案。
- [x] 接入现有 openai 兼容 provider 或抽取为共享 provider 模块，保持 graph/wiki 既有行为不变。

## HTTP API 与 CLI

- [x] 先写 `POST /api/ask` 契约测试：成功、无证据、空问题、缺索引、LLM 未配置、未知引用
      和 `request_id`，再实现请求/响应模型与端点。
- [x] 扩展 `siku serve` 的 LLM base URL、model、api-key-env 配置，使 `/api/ask`、`/api/graph`、
      `/api/wiki` 共用该配置，并完成默认行为回归测试。
- [x] 更新统一错误映射与 `contracts/openapi.json`，契约漂移必须由显式刷新命令恢复。
- [x] 验证问答日志每请求带 `request_id`，用户响应不泄漏 traceback、key 或异常类名；日志
      也不得写入问题正文、prompt、回答正文或引用正文。

## 最小对话 UI

- [x] 初始化 `ui/` TypeScript + React + Vite 工程、锁文件和基础脚本，创建
      `ui/design-system/MASTER.md` token 基线，更新 `ui/README.md` 的问答入口说明，并确认
      Node 24 CI 可启用。
- [x] 先写健康/加载/错误/重试/证据不足组件测试，再实现 localhost API client 和问题输入。
- [x] 先写回答与引用展示测试，再实现答案正文、引用折叠、模型信息和 request_id 展示。
- [x] 接入 `siku serve --with-ui` 静态目录，验证开发期 localhost CORS 与生产同源路径。
- [x] 使用 fake HTTP API 完成浏览器级冒烟：提交问题、展示答案、展开引用、无证据、重试。
- [x] 通过 `ui-quality-gate`：键盘焦点、窄窗口、长答案、错误/空态、不溢出、不保存 key、
      对比度、触控目标、375px 布局和 reduced-motion；把真实填充验收结果及未覆盖项写入
      `review.md`。

## 交付门禁

- [x] 运行 `npm ci`、类型检查、lint、生产构建及前端测试。
- [x] 运行 `uv run pytest`、`uv run ruff check .`、`uv run ruff format --check .`、
      `uv run mypy`、`uv run pre-commit run --all-files` 和检索 golden set 回归。
- [x] 运行 `openspec validate --changes --strict` 与 `openspec validate --specs --strict`，
      完成独立 `review.md` 后再归档并同步 `http-api` 与 `web-ui` 主 spec。
