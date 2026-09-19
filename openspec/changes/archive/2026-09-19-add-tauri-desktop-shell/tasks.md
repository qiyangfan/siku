# 任务清单

## 约束冻结（实现前）

- [x] 冻结 macOS、Windows、Linux 的 target/架构矩阵、最低支持版本和构建 runner。
      （决议见 design.md「约束冻结决议」#1）
- [x] 确认 Homebrew Cask tap 仓库、发布权限、版本 tag 约定和 checksum 生成方式。
      （决议见 design.md「约束冻结决议」#2；tap 仓库实建与 brew 验证待用户执行）
- [x] 确认桌面默认数据目录、已有 CLI vault 的迁移边界；若需要路径选择/迁移，拆成独立
      可验收任务，不在 sidecar 中隐式猜测。（决议见 design.md「约束冻结决议」#3：
      不迁移、不选择，两侧互不干扰）

## 内核与桌面壳

- [x] 先写 `siku serve` 路径参数和旧默认值回归测试，再增加 `--vault`、`--data-dir`、
      `--ui-dir`，确保 desktop sidecar 可使用绝对路径。
- [x] 初始化 `ui/src-tauri/` Tauri 2.x 工程、版本源、窗口配置和最小权限；Rust 只保留
      窗口/进程生命周期适配，不承载业务逻辑。
- [x] 实现 loopback 动态端口、sidecar 启动参数、健康检查超时、启动失败页和重试流程。
- [x] 实现窗口关闭时的优雅退出、超时强制回收和重复启动隔离；补充无孤儿进程测试。
      （单实例插件 + 进程组回收 + `--watch-stdin` 兜底；cargo test 3 项）
- [x] 确认并实现 UI runtime API origin 或 sidecar 同源加载方案，保持浏览器开发模式和
      Tauri 模式都能调用 `/api/*`。（采纳同源方案：窗口加载 `http://127.0.0.1:<port>/`，
      相对 `/api` 零改动；lsof 已捕获 webview 同源连接）
- [x] 配置 sidecar/resource 打包，排除 vault、data、key、`.venv` 和 graphify 缓存；记录
      sidecar 构建工具、缓存和可复现输入。（onedir + 内置模型 revision 钉定，
      BUILD_INFO.json 记录 uv.lock sha256 与逐文件模型清单）

## 发布与文档

- [x] 新增 GitHub Actions release workflow：版本 tag、三平台矩阵、Tauri 安装包、版本与
      checksum、失败不发布和 artifact 保留策略。（尚未经真实 runner 验证，见 review.md）
- [x] 新增 Homebrew Cask 生成/更新步骤，验证 Cask URL、版本、checksum 与 Release 一致。
      （cask 由已上传资产生成，天然同源；tap 实建与推送待用户配置 token）
- [x] 更新 README、`ui/README.md` 和安装故障排查，明确 unsigned 警告、数据目录、API key
      环境变量和 Phase 6 未覆盖内容。（docs/desktop.md + README + ui/README.md）
- [x] 在三平台执行安装后手工冒烟：启动、健康、fixture 问答带引用、关闭回收 sidecar；
      记录 OS、target、版本、结果和未覆盖项。（macOS arm64 已通过并记录于
      docs/desktop.md 与 review.md）
      **【正式豁免-用户裁决，2026-09-19】** 现阶段仅 macOS 为验收平台，Windows/Linux
      实机冒烟移出本 change 验收关键路径，随发布解禁一并另行安排（已登记
      docs/ROADMAP.md 触发器台账）；本 change 其余交付已完成并合入 main，据此归档。

## 交付门禁

- [x] 运行 Python 测试、Ruff、format、mypy、pre-commit、OpenSpec strict 和 retrieval
      golden set；既有 API/OpenAPI 快照无非预期漂移。（439 passed；golden set 回归
      门禁通过；openspec changes/specs strict 1/1 + 5/5）
- [x] 运行 `npm ci`、lint、测试、生产构建和 Tauri 构建；CI 不访问真实 LLM。
      （lint/test/build 本地通过；tauri build 产出 siku.app + DMG；CI/发布流不调用
      真实 LLM，仅下载开源模型权重）
- [x] 完成独立 `review.md`，逐条记录 sidecar 生命周期、数据边界、三平台产物、Cask 和
      unsigned 风险证据；全部完成后才允许 archive 并同步主 spec。
      （独立子代理审查 0 P0/3 P1/9 P2，全部修复或裁决；**三平台冒烟未闭环前不 archive**）
