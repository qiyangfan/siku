# siku UI

前端目录将在 `add-qa-vertical-slice` 中初始化为阶段一的最小问答界面：

- 技术栈：TypeScript + React + Vite
- 图视图：Sigma.js + graphology（WebGL，Obsidian 同款路线）
- 与内核仅经 localhost HTTP API 通信（架构红线 #1，业务逻辑禁止进前端）
- 当前交付优先实现单轮 `POST /api/ask`：前端不读取 vault、SQLite、LanceDB、parquet 或图谱缓存，
  不保存 API key；图谱/浏览/wiki 视图后续另行实现。
- 开发期运行：先在仓库根目录执行 `siku serve`，再在本目录执行 `npm run dev`；Vite 只把
  `/api` 请求代理到 `127.0.0.1:8000`。生产构建后可用 `siku serve --with-ui` 挂载 `ui/dist`。
- 页面状态、答案、引用和错误均来自 API；刷新页面不会恢复上一轮回答。

初始化时机：内核 localhost API 契约已定型，并由当前 change 补齐问答端点后。

CI 已预留 Node 24 前端作业（`.github/workflows/ci.yml` 的 ui job）：`ui/package.json` 出现即自动启用，依赖 `npm ci`（需提交 package-lock.json）。
