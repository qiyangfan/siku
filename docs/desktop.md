# 桌面应用（Phase 5，unsigned）

桌面应用把既有 React UI 与 Python 内核封装为可双击启动的应用。壳（Tauri 2）只负责
窗口与内核进程生命周期；问答、引用、索引状态等业务数据一律经既有 localhost HTTP
API 流转，不经过 Rust 或前端本地状态。

> **未签名声明**：Phase 5 产物是 unsigned 构建。macOS/Windows 首次打开会出现系统
> 安全提示，属预期行为，不等于"受信任安装"。代码签名、公证与自动更新属于 Phase 6。

## 安装与启动

| 平台 | 产物 | 安装方式 | 安全提示处理 |
|---|---|---|---|
| macOS (Apple Silicon) | `siku_<版本>_aarch64.dmg` | 拖入 Applications | 首次打开若被 Gatekeeper 拦截：右键 → 打开，或"系统设置 → 隐私与安全性 → 仍要打开" |
| macOS (Intel) | `siku_<版本>_x64.dmg` | 同上 | 同上 |
| Windows 10+ | `siku_<版本>_x64-setup.exe`（NSIS） | 双击安装 | SmartScreen 提示"未知的发布者"：点击"仍要运行" |
| Linux (x86_64) | `siku_<版本>_amd64.deb` / `.AppImage` | `sudo dpkg -i` / `chmod +x` 后直接运行 | — |

也可经 Homebrew 安装（需要先发布过 Release 并配置 tap）：

```bash
brew install --cask qiyangfan/tap/siku
```

## 数据目录（冻结策略）

首次启动在平台应用数据目录下初始化 `siku/`（内含 `vault/` 与 `data/`），不迁移、
不读取已有 CLI 工作目录：

| 平台 | 数据根目录 |
|---|---|
| macOS | `~/Library/Application Support/siku/` |
| Windows | `%APPDATA%\siku\` |
| Linux | `$XDG_DATA_HOME/siku/`（缺省 `~/.local/share/siku/`） |

- 桌面数据与 CLI 数据互不干扰；路径选择/迁移功能属后续 change，桌面壳不做隐式猜测。
- 内核日志写入 `<数据根目录>/sidecar.log`（每次启动重建），排查问题先看这里。
- 当前阶段桌面端没有资料导入/索引界面（见 proposal Non-goals）；语料摄取与索引请用
  CLI 对同一目录操作，或等待后续资料管理 change。

## 模型端点配置（BYOK，ADR-0009）

siku 不内置任何模型：问答（LLM）、向量检索（embedding）与可选重排（rerank）一律
调用你自己配置的端点（本地 Ollama / vLLM / LiteLLM，或云端 API）。key 只进请求头，
不进入安装包、Tauri 配置、前端状态、日志与索引产物。

配置优先级：CLI 参数 > 环境变量 > 配置文件 `config.toml`：

| 平台 | 配置文件路径 |
|---|---|
| macOS | `~/Library/Application Support/siku/config.toml` |
| Windows | `%APPDATA%\siku\config.toml` |
| Linux | `~/.config/siku/config.toml` |

最小模板（本地 Ollama 一分钟路径：`ollama pull bge-m3` 后即可检索）：

```toml
[embedding]
base_url = "http://127.0.0.1:11434/v1"
model = "bge-m3"                # 本地端点无需 key

[llm]
base_url = "https://api.deepseek.com"
model = "deepseek-chat"
api_key_env = "SIKU_LLM_API_KEY"   # 与 api_key 明文二选一
```

云端示例（硅基流动提供 embedding 与 rerank 通道）：

```toml
[embedding]
base_url = "https://api.siliconflow.cn/v1"
model = "BAAI/bge-m3"
api_key_env = "SILICONFLOW_API_KEY"

[rerank]
base_url = "https://api.siliconflow.cn/v1"
model = "BAAI/bge-reranker-v2-m3"
api_key_env = "SILICONFLOW_API_KEY"
```

- 明文 `api_key` 写入 config.toml 时，siku 创建/重写该文件一律为 0600；也可用
  `api_key_env` 只存环境变量名。任何路径下 key 不进日志与持久化产物。
- 未配置 embedding 端点时，检索/问答返回配置指引类错误（不静默降级）；
  rerank 未配置时按 `reranker=none`（RRF-only）检索，serve 启动日志会明示三通道
  的解析结果（embedding/rerank/llm）。
- macOS 图形启动不继承 shell 环境：`launchctl setenv SIKU_LLM_API_KEY <key>` 后
  重启应用，或从终端 `open -a siku` 继承当前 shell 环境；`SIKU_LLM_BASE_URL` /
  `SIKU_LLM_MODEL` / `SIKU_EMBEDDING_*` / `SIKU_RERANK_*` 环境变量与 config.toml
  同形，可整体替代配置文件。

## 故障排查

| 现象 | 处置 |
|---|---|
| 窗口停留在"正在启动本地服务"很久 | 查 `sidecar.log`；首次解压可能需要数十秒 |
| 恢复页提示本地服务停止或启动后立即退出 | 点击“重新启动本地服务”；若再次失败，查 `sidecar.log` 的最后几行，常见原因为磁盘空间不足或权限问题 |
| 检索/问答报"模型端点未配置" | 按 BYOK 指引配置 `config.toml`（本地 Ollama 或云端端点），见上文模板 |
| 问答报 LLM/key 错误 | 确认端点配置与 API key 在应用可见的环境中已设置 |
| 导入 PDF 报 `scanned_pdf_no_text` | 该 PDF 无文字层（扫描件）：先用 OCR 转成含文字的 PDF 再导入（ADR-0013，不做内置 OCR） |
| 导入 .doc/.ppt/.xls 报 `legacy_office_format` | 旧二进制格式不受支持：在 Office/WPS 另存为 .docx/.pptx/.xlsx 后再导入 |
| 导入报 `corrupt_document` / `encrypted_document` | 文件损坏或加密：确认能正常打开、解除密码后重试 |
| 关闭应用后端口仍被占用 | 不应发生（关闭时先优雅退出、超时强制回收整个进程组）；若出现请附带 `sidecar.log` 反馈 |
| 双实例同时运行 | 单实例隔离：第二次启动只会聚焦已有窗口 |

## 随包格式运行时（ADR-0013）

桌面包携带常用格式摄取所需的全部非模型运行时：pypdf（PDF 文本）、python-pptx、
openpyxl 与固定版本 pandoc（DOCX 转换）。pandoc 版本、下载 URL 与 SHA-256 固定在
`scripts/resources/pandoc.json`，构建期下载校验后收集到
`ui/src-tauri/binaries/siku-sidecar/_internal/pandoc/`（附上游版权说明），运行时
**零下载、不查系统 PATH**；开发/命令行环境则回退系统 pandoc。

- 产物完整性由 `scripts/check_sidecar_artifacts.py` 在 CI 各平台构建后检查：
  资源齐备、二进制架构相符、无 torch/模型权重。
- 支持范围与转换指引（扫描件 PDF、旧二进制 Office）见 README「支持格式与转换指引」。

## 从源码构建桌面应用

前置：uv、Node 24、Rust（rustup）。

```bash
# 1. 前端构建产物（桌面壳以 resources 挂载 ui/dist）
cd ui && npm ci && npm run build && cd ..

# 2. sidecar（PyInstaller onedir，BYOK 瘦身版约 305 MiB，产出 ui/src-tauri/binaries/）
uv sync
uv run python scripts/build_sidecar.py

# 3. 桌面应用
cd ui && npx tauri build                        # 产物在 src-tauri/target/release/bundle/
```

要点：

- sidecar 与桌面壳之间的约定只有一条命令：
  `siku-sidecar serve --with-ui --host 127.0.0.1 --port <动态端口> --vault <绝对路径>
  --data-dir <绝对路径> --ui-dir <绝对路径> --watch-stdin`。
- `--watch-stdin`：stdin EOF（壳进程消亡）时 sidecar 受控退出，作为孤儿进程兜底防线。
- sidecar 不内置任何模型（ADR-0009）：LLM/embedding/rerank 一律经 config.toml 或
  环境变量指向用户端点；构建输入清单见
  `ui/src-tauri/binaries/siku-sidecar/BUILD_INFO.json`（`models_included: false`）。
- 开发期调试壳本身：`cd ui && npx tauri dev`（同样需要第 1、2 步产物先存在）；仅开发
  前端时不需要壳：`siku serve` + `npm run dev`（Vite 代理），与 Phase 4 流程一致。

## 冒烟状态（安装后问答全链路）

| 平台 | target | 版本 | 结果 | 备注 |
|---|---|---|---|---|
| macOS 26 (arm64) | aarch64-apple-darwin | 0.1.0 | ✅ 本机通过 | 健康→fake LLM 问答带引用→关闭回收 sidecar 全链路 |
| Windows 10+ | x86_64-pc-windows-msvc | — | ⏳ 待 CI 产物 | 需 Release 后实机手工冒烟 |
| Linux (Ubuntu 22.04+) | x86_64-unknown-linux-gnu | — | ⏳ 待 CI 产物 | 同上 |
