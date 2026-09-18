# 设计：Tauri 桌面壳与无签名分发

## 目标拓扑

```text
Tauri window
  ├─ 壳职责：窗口、配置目录、sidecar 生命周期、健康检查、错误启动页
  └─ HTTP：127.0.0.1:<port>/api/*
       ↓
Python sidecar: siku serve --with-ui
  ├─ 既有 FastAPI API / QA / retrieval / graph / wiki
  ├─ 显式 --vault / --data-dir / --ui-dir
  └─ API key 仅从继承的环境变量读取
```

生产窗口优先加载 sidecar 提供的同源 UI，使现有相对 `/api` 请求继续成立；如果 Tauri
实现选择将静态 UI 直接嵌入 webview，则必须为 API client 提供运行时 API origin，并通过
loopback HTTP 调用内核，不能改成 Tauri command 承载问答业务。最终方案须避免把两份完整
前端资源无理由打入安装包。

## 启动与关闭生命周期

1. Tauri 解析平台应用数据根目录，准备 `vault/`、`data/` 和只读 UI 资源路径。
2. 壳选择未占用的 loopback 端口，启动 sidecar，并传入绝对路径、端口和 `--with-ui`。
3. 壳轮询 `GET /api/health`，在超时或进程提前退出时显示可行动的启动失败页面，不展示
   空白窗口，也不把异常栈暴露给用户。
4. 健康检查通过后再展示问答界面；问答请求仍由 UI 通过 HTTP 发往 sidecar。
5. 窗口关闭时先优雅终止 sidecar，超时再强制回收；重复启动不得遗留孤儿进程或占用端口。

首版桌面默认数据根目录使用平台应用数据目录下的 `siku/` 子目录。路径选择、迁移已有
   CLI vault、导入向导和多库切换不是本 change 的行为；实现前必须确认这一默认策略是否
   足以支撑手工验收。无论最终策略为何，sidecar 接口必须使用显式路径，不能通过 cwd 猜测。

## 内核适配

- `siku serve` 增加 `--vault`、`--data-dir` 和 `--ui-dir` 可选参数；未提供时维持现有
  `vault/`、`data/` 和 `ui/dist` 默认值。
- `--with-ui` 继续控制静态挂载；`--ui-dir` 只改变资源位置，不改变 API 路径。
- 桌面壳不传 API key；sidecar 继承用户已配置的 key 环境变量，日志不得记录 key、完整
  问题、prompt、回答或引用正文。
- 端口只绑定 `127.0.0.1`。除非用户明确选择现有 CLI 的 `--host 0.0.0.0`，桌面壳不开放
  局域网访问。

## 构建与分发

- Tauri 项目放在 `ui/src-tauri/`，前端仍由 `ui/package.json` 管理；Rust 代码只包含
  生命周期和平台适配。
- Python sidecar 按目标平台分别构建，并以 Tauri `externalBin`/resource 机制打包；
  不把本地 `.venv`、用户 `vault/`、`data/`、API key 或 graphify 缓存打入安装包。
- GitHub Actions 以版本 tag 触发，在 macOS、Windows、Linux runner 上构建并上传可安装
  产物；版本号来自单一版本源，产物名、target 和 checksum 可追溯。
- Homebrew 使用 Cask 形式指向对应 GitHub Release 资产；tap 所属仓库和维护权限是实现前
  的待确认项，不在文档中虚构仓库名。
- Phase 5 产物明确标注 unsigned。签名/公证缺失导致的系统警告要写入安装说明，不能把
  构建成功描述为受信任安装。

## 测试与验收策略

- Python：路径参数和旧默认值回归、UI 资源不存在、端口/host 传递、sidecar 健康失败；
  既有 API/QA/golden set 门禁继续执行。
- Tauri/前端：壳启动等待、健康失败页、关闭回收、runtime API origin（如采用）和现有
  问答 UI 测试；不调用真实 LLM。
- 安装后手工冒烟：在三种操作系统上安装 unsigned 产物，启动后健康检查成功，准备一个
  小型 fixture vault 并建立索引，完成“打开应用 → 提问 → 返回引用”的全链路；同时确认
  关闭应用后无残留 sidecar。
- 发布流程：验证 tag 产物、checksum、Homebrew Cask URL 与版本一致；不验证更新链路，
  因为更新属于 Phase 6。

## 风险与取舍

- Python sidecar 的体积、启动时间和平台依赖是阶段二已知代价；优先选择可重复构建和
  可诊断性，不为减小体积把内核业务拆成 Rust 重写。
- Linux webkit/系统库差异需要在 CI 与最低支持发行版中明确记录；不能仅以 macOS 本地
  构建通过推断 Linux 可用。
- 动态端口避免多实例冲突，但要求 UI 能获得 runtime API origin；若采用同源 sidecar
  页面，可减少 CORS/注入复杂度，优先验证这一方案。

## 约束冻结决议（2026-09-18，实现前）

以下决议由实现阶段按资深工程判断冻结；冻结后如需推翻，须在 review.md 记录理由并同步
本文件，不得在实现中途静默变更。

1. **目标平台矩阵与构建 runner**
   - macOS 10.15+（Tauri 2 最低支持版本）：`aarch64-apple-darwin` 与
     `x86_64-apple-darwin` 双架构，产物 .app/.dmg；Intel 侧 sidecar 经 Rosetta 2 +
     uv 管理的 x86_64 CPython 交叉构建。
   - Windows 10+：`x86_64-pc-windows-msvc`，产物 NSIS 安装器；Windows on ARM 记为
     未覆盖项。
   - Linux：`x86_64-unknown-linux-gnu`，基线 Ubuntu 22.04（webkit2gtk-4.1 的最低
     主流 LTS），产物 .deb + .AppImage；构建 runner 用 ubuntu-22.04 以压低 glibc 基线。
   - Runner 矩阵：`macos-14`（arm64）、`ubuntu-22.04`、`windows-2022`。
2. **Homebrew Cask 与版本约定**
   - tap 仓库按 GitHub 同账号惯例定为 `qiyangfan/homebrew-tap`，cask 名 `siku`；
     workflow 以 `HOMEBREW_TAP_REPO` 参数化（默认上述值），推送凭据用
     `HOMEBREW_TAP_TOKEN` secret。仓库实际创建是一次性仓库外动作，属待确认项。
   - 版本单一来源 = `ui/src-tauri/tauri.conf.json` 的 `version`；发布 tag 约定
     `v{version}`，workflow 校验两者一致否则失败（失败不发布）。
   - checksum = Release 产物的 SHA-256；cask 由 release workflow 直接从已上传资产
     生成，URL/版本/checksum 与 Release 天然同源。
3. **桌面默认数据目录与 CLI 迁移边界**
   - 数据根目录 = 平台应用数据目录下的 `siku/` 子目录：macOS
     `~/Library/Application Support/siku`、Windows `%APPDATA%\siku`、Linux
     `$XDG_DATA_HOME/siku`（缺省 `~/.local/share/siku`），内含 `vault/` 与 `data/`。
   - 桌面首启动初始化空数据目录；不做已有 CLI vault 的隐式迁移/复制，不做路径选择
     UI——CLI 用户继续使用 cwd 相对默认值，两侧数据互不干扰。路径选择/迁移属于
     后续独立 change。
   - 冒烟 fixture 用 sidecar 自带 CLI 形态（同一二进制的 `ingest`/`index` 子命令）
     准备 vault 与索引，不经桌面 UI。
4. **sidecar 形态与 UI 加载方案（实现级确认）**
   - sidecar 采用 PyInstaller **onedir**（torch 系体积下 onefile 的每次启动解压
     不可接受），经 Tauri `bundle.resources` 分发目录；权重随包内置（bge-m3 +
     bge-reranker-v2-m3），sidecar 启动时指向内置模型目录并置 `HF_HUB_OFFLINE=1`，
     安装后无需联网即可问答。
   - UI 采用设计倾向的**同源加载方案**：生产窗口加载 sidecar 提供的
     `http://127.0.0.1:<port>/`，现有相对 `/api` 请求零改动成立；启动前/失败态由
     壳自带的本地 splash/错误页呈现。浏览器开发模式继续走 Vite 代理，不受影响。
   - shell 侧孤儿防线：Unix 以独立进程组启动并在关闭时先 SIGTERM 后 SIGKILL 整组；
     sidecar 增加 `--watch-stdin`（stdin EOF 即退出）兜底父进程被强杀的场景。
