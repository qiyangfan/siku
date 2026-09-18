# siku UI

TypeScript + React 前端与 Tauri 2 桌面壳（`src-tauri/`）。

- 技术栈：TypeScript + React + Vite
- 图视图：Sigma.js + graphology（WebGL，Obsidian 同款路线）
- 与内核仅经 localhost HTTP API 通信（架构红线 #1，业务逻辑禁止进前端）
- 当前交付优先实现单轮 `POST /api/ask`：前端不读取 vault、SQLite、LanceDB、parquet 或图谱缓存，
  不保存 API key；图谱/浏览/wiki 视图后续另行实现。
- 开发期运行：先在仓库根目录执行 `siku serve`，再在本目录执行 `npm run dev`；Vite 只把
  `/api` 请求代理到 `127.0.0.1:8000`。生产构建后可用 `siku serve --with-ui` 挂载 `ui/dist`。
- 页面状态、答案、引用和错误均来自 API；刷新页面不会恢复上一轮回答。

## 桌面壳（src-tauri/）

Tauri 壳只承载窗口与 sidecar 生命周期：选择 loopback 动态端口 → 启动
`siku-sidecar serve …`（绝对路径 + `--watch-stdin`）→ 轮询 `/api/health` →
成功后窗口导航到 sidecar 同源提供的 UI（相对 `/api` 请求零改动）；启动失败在本地
壳状态页展示可行动的中文提示。Rust 不实现任何业务逻辑；问答页（`http://127.0.0.1`）
不在 capabilities 授权范围内，天然没有 IPC 通道。

```bash
# 壳开发/构建的前置：ui/dist（npm run build）与
# src-tauri/binaries/siku-sidecar/（根目录 scripts/build_sidecar.py 产出）
npx tauri dev     # 调试壳（复用同一启动编排）
npx tauri build   # 产出安装包：src-tauri/target/release/bundle/
```

发布流水线（版本 tag → 三平台产物 → GitHub Release → Homebrew Cask）见
`.github/workflows/release.yml` 与 `docs/desktop.md`。

初始化时机：内核 localhost API 契约已定型，并由当前 change 补齐问答端点后。

CI 已预留 Node 24 前端作业（`.github/workflows/ci.yml` 的 ui job）：`ui/package.json` 出现即自动启用，依赖 `npm ci`（需提交 package-lock.json）。
