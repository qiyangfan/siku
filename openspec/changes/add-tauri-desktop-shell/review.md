# 评审：Tauri 桌面壳与无签名分发

## 一、规划评审（实现前）

### 已核对事实

- ROADMAP 将 Phase 5 明确排序为 Tauri 壳、GitHub Releases + Homebrew；Phase 6 才是签名与
  自动更新。
- ADR-0001/0002 已确定 Rust 只用于 Tauri 壳，Python 继续承载内核，UI 与内核只经
  localhost HTTP 通信。
- 当前 `siku serve` 已有 `host`、`port`、`--with-ui`、LLM 配置参数，但 vault/data/ui
  路径仍主要依赖默认值；桌面 sidecar 需要显式路径适配。
- 当前 `/api/health` 和 `/api/ask` 已可作为 sidecar readiness 与问答冒烟入口；OpenAPI
  契约不需要因桌面壳改变。
- Tauri 官方文档支持 `bundle.externalBin` 携带按 target triple 命名的 sidecar，并提供
  GitHub Actions 发布构建路径；这些是实现约束参考，不是本 change 的业务契约。

### 评审结论

- 方案符合 ADR-0001、ADR-0002 和项目宪法：Rust 不承载业务，用户语料留在本机，问答仍走
  localhost HTTP，Phase 6 不提前进入。
- 动态端口 + readiness + 关闭回收是桌面化相对于 `siku serve` 的必要新增行为；缺少任一项
  都可能产生空白窗口、端口冲突或孤儿 Python 进程。
- 现阶段不把具体 PyInstaller/Nuitka 方案、target 架构或 Homebrew tap 名称写死到行为
  契约；它们必须在实现前根据 CI 可重复性和发布权限冻结。

## 二、实现评审（2026-09-18，实现完成后补充）

### 约束冻结落地（对应 design.md「约束冻结决议」）

- 平台矩阵：macOS aarch64/x86_64（10.15+）、Windows x86_64（10+，NSIS）、Linux
  x86_64（Ubuntu 22.04 基线，deb/AppImage）；runner macos-14 / ubuntu-22.04 /
  windows-2022。
- Homebrew：tap 约定 `qiyangfan/homebrew-tap`（workflow 参数化 `HOMEBREW_TAP_REPO`），
  cask 由 release workflow 从已上传资产生成（`scripts/generate_cask.py`，URL/版本/
  checksum 同源）；版本单一来源 `tauri.conf.json`，tag `v{version}` 强校验。
- 数据目录：`dirs::data_dir()/siku/{vault,data}`，首启初始化、零迁移、零隐式猜测；
  sidecar 全部显式绝对路径 + `--watch-stdin`。
- sidecar 形态：PyInstaller onedir（torch 系下 onefile 逐次解压不可接受），经
  `bundle.resources` 分发；bge-m3/bge-reranker-v2-m3 按冻结 revision（5617a9f6… /
  953dc6f6…）打包内置并以 `HF_HUB_OFFLINE=1` 离线加载；构建输入记录在产物
  `BUILD_INFO.json`（含 uv.lock sha256、逐模型文件 sha256 清单、关键包版本）。

### 实现证据（本机 macOS arm64 实测）

- sidecar（7.3 GiB onedir）：CLI/摄取/离线索引（内置模型加载）/检索（rerank 打分正常）
  全通过；曾出现冻结形态下 torch 触发 multiprocessing spawn 导致 CLI 被子进程重放
  （顶层 `No such option: -B`），修复为入口首行 `multiprocessing.freeze_support()`，
  复测通过。
- `siku serve` 路径参数：17 个 CLI/sidecar 测试覆盖旧默认值回归、绝对路径透传、
  `--ui-dir` 快速失败、watchdog 原语与 uvicorn `should_exit` 接线；既有 439 项 pytest
  全绿，ruff/format/mypy/pre-commit 全绿，OpenAPI 快照零漂移（契约测试在套件内）。
- .app 全链路 GUI 冒烟（fake openai 端点，未触真实 LLM/key）：启动 → 壳选动态端口 →
  sidecar 启动 → `/api/health` 通过（冷启动约 2~24s）→ lsof 捕获 webview 与 sidecar
  的同源 ESTABLISHED 连接（窗口已加载 sidecar 提供的 UI）→ `/api/ask` 返回带引用回答
  （citation 指向 fixture `热力学基础.md`）→ osascript 退出 → sidecar 2s 内回收、
  无孤儿进程。额外验证：杀壳进程后 sidecar 经 stdin EOF 自行优雅退出（watchdog 防线）。
- Rust：cargo check/test（3 项，含进程组 SIGTERM→SIGKILL 无孤儿测试）通过，clippy
  无告警，rustfmt 干净。
- 发布流水线：release.yml 四 job（版本校验 → 三平台/四 target 矩阵 → 失败不发布 Release
  → Cask 生成推送）；本地已校验 YAML 结构、版本校验逻辑与 cask 生成器输出；DMG 命名为
  `siku_<版本>_aarch64.dmg`（非完整 triple），cask glob 与文档已对齐。首次全量
  `tauri build` 已产出 siku.app + 4.1 GB DMG。

### 独立代码审查（子代理复核）与修复记录

- 结论：0 个 P0、3 个 P1、9 个 P2；核心生命周期设计（孤儿三防线、代际退役、CLI 回归
  安全、数据边界）经查成立。
- 已修复：Windows sidecar/taskkill 的 `CREATE_NO_WINDOW` 控制台黑窗（P1）；HANDOFF/
  tasks/review 与实现状态的自相矛盾（P1，本次同步重写）；CI 新增 desktop-shell Rust
  门禁作业 fmt/clippy/test（P1）；spawn→store 代际二次校验（P2）；SHA256SUMS 自包含
  （P2）；sidecar 日志改"每会话首轮截断、重试追加"（P2）；端口绑定与数据目录的 panic
  路径改为失败页（P2）；Windows 关闭增加优雅宽限（P2）；健康检查要求 siku 响应形状
  （P2）；移除不可达 return（P2）；补 `--watch-stdin` 接线测试（P2）；README 路线图
  同步（P2）。
- 有意不采纳：健康检查的内核版本强等值校验（会造成壳/内核部分升级脆弱耦合），放宽为
  siku 健康形状识别；端口释放后立即重绑的 OS 级断言测试（天然易碎，由真实安装冒烟覆盖）。

### 未覆盖项与阻塞（打首个 Release 前必须闭环）

- Windows / Linux 实机安装冒烟：本机无 Windows/Linux 环境，产物依赖 CI 矩阵首次运行，
  需在真实 Release 产出后按 docs/desktop.md 冒烟清单执行并回填结果。
- release.yml 从未被真实 runner 执行：x86_64 macOS 侧的 Rosetta + uv 解释器组合、
  Linux webkit 依赖安装、Windows NSIS 打包均属首跑风险。
- Homebrew tap 仓库 `qiyangfan/homebrew-tap` 尚不存在（一次性仓库外动作），且
  `HOMEBREW_TAP_TOKEN` secret 未配置；缺省时 Cask 步骤自动跳过，不阻塞 Release。
- Phase 6（签名/公证/自动更新）明确不在本 change。

### 归档判定

- 按任务清单门禁：macOS 链路证据充分，但「三平台安装后问答冒烟」未闭环，本 change
  **暂不归档**、主 spec 暂不同步；待 Release 产物实机冒烟回填后归档。
