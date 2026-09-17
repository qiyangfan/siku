# siku UI

前端占位目录，尚未初始化。规划（阶段一）：

- 技术栈：TypeScript + React + Vite
- 图视图：Sigma.js + graphology（WebGL，Obsidian 同款路线）
- 与内核仅经 localhost HTTP API 通信（架构红线 #1，业务逻辑禁止进前端）

初始化时机：内核 localhost API 契约（摄取/检索/图谱三个端点）定型后。

CI 已预留 Node 24 前端作业（`.github/workflows/ci.yml` 的 ui job）：`ui/package.json` 出现即自动启用，依赖 `npm ci`（需提交 package-lock.json）。
