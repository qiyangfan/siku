# siku（四库）

> 把你所有的文档丢进来：自动摄取、自动织成知识图谱、自动编成 wiki，然后用自然语言向它提问。

siku 取意《四库全书》——历史上最大规模的"汇总天下文献 → 自动编目（总目提要）→ 结构化检索"工程。本项目是它的个人本地版：**本地优先**，语料与索引永不离开你的磁盘；模型一律 BYOK 端点供给（ADR-0009）——图谱抽取、问答走你的 LLM 端点，向量检索/重排走你的 embedding/rerank 端点（本地 Ollama 或云端 API）。

🚧 当前处于脚手架阶段。架构定稿（北极星）见 [docs/architecture.md](docs/architecture.md)，
不可协商红线见 [openspec/project.md](openspec/project.md)（宪法）。

## 文档地图

| 想知道 | 去哪 |
|---|---|
| 接下来干什么、哪些先不做 | `docs/ROADMAP.md`（阶段闸门 + 触发器台账 + Backlog） |
| 某个选型为什么这么定 | `docs/adr/`（ADR-0001~0009） |
| 哪些规则碰不得 | `openspec/project.md`（宪法红线 + 工程口径） |
| 当前进度与接手状态 | `docs/HANDOFF.md` + `docs/ROADMAP.md` |
| 系统应如何行为 | `openspec/specs/`（随 change 归档生长） |
| 桌面应用安装与故障排查 | `docs/desktop.md` |
| 当前进度与选型总表 | `docs/architecture.md` |
| AI 协作规范 | `AGENTS.md` + `openspec/AGENTS.md` |

## 产品边界

- ✅ 知识库：万能摄取、检索、知识图谱、LLM wiki、自然语言问答
- ❌ 文档编辑器：不做 Office 在线预览与编辑，"打开原文"交给系统默认应用

## 架构一览

| 层 | 选型 |
|---|---|
| 内核 | Python 3.12+（FastAPI + uv） |
| 界面 | TypeScript / React（Sigma.js + graphology 图视图），终态 Tauri 壳 |
| 存储 | SQLite（元数据 + FTS5）+ LanceDB（向量）+ 内存图 + parquet（图谱） |
| 事实层 | Obsidian vault 兼容 Markdown，原件留存 `attachments/` |
| 摄取 | PDF：pypdf（默认轻量，ADR-0013）· Word：pandoc（桌面随包）· PPT：python-pptx · Excel：openpyxl |
| 检索质量 | BM25 + 向量混合召回 + 可选 rerank 端点重排（`reranker=none` 为一等公民）+ 通道化 golden set 回归 |

## 支持格式与转换指引

默认安装（含桌面包）开箱可摄取：**含文字层的 PDF、DOCX、PPTX、XLSX/XLSM、EPUB、HTML、Markdown**。
解析与投影在本地完成，不需要模型端点，也不联网下载任何依赖（ADR-0013）。

两类文件需要先转换：

- **扫描/纯图片 PDF**（没有可复制文字）：先用 OCR 工具（或系统自带识别）转成
  含文字层的 PDF，再导入；导入时报 `scanned_pdf_no_text` 即此情形。
- **旧版二进制 Office（.doc/.ppt/.xls）**：在 Office/WPS 中另存为 .docx/.pptx/.xlsx
  后再导入；报 `legacy_office_format` 即此情形。

加密文档请先解除密码；损坏或扩展名不符的文件会按 `corrupt_document` 如实报错，
不会被当成空文档"成功"导入。

命令行摄取 Word 依赖系统 pandoc（`brew install pandoc` 等）；桌面包内置固定版本
pandoc，无需系统安装。**同一文件的既有投影不会因更换默认解析器而自动重抽**：
投影按 `source_hash` 幂等，内容未变即跳过；`siku index --rebuild` 只重建派生索引，
不重新摄取文档。需要用新解析器重生成某个 PDF 的投影时，先从资料库移除该文档，
再从保留的外部原件重新导入。

## 快速开始

### 桌面应用（推荐，无需命令行）

从 [Releases](https://github.com/qiyangfan/siku/releases) 下载对应平台安装包即可。
**Phase 5 产物为未签名（unsigned）构建**：macOS/Windows 首次打开会出现系统安全提示，
需手动放行；签名与自动更新属于 Phase 6。安装说明、数据目录、API key 配置与故障排查
见 [docs/desktop.md](docs/desktop.md)。

### 命令行

```bash
# 需要先安装 uv：https://docs.astral.sh/uv/
uv sync

# 冒烟验证
uv run siku version
```

### 模型端点配置（BYOK，必需）

siku 不内置模型（ADR-0009）：检索（embedding）、可选重排（rerank）与问答/图谱
（LLM）一律调用你自己的端点。配置优先级：CLI 参数 > 环境变量 > `config.toml`。

本地 Ollama 一分钟路径（`ollama pull bge-m3` 后即可检索）：

```bash
uv run siku index \
  --embedding-base-url http://127.0.0.1:11434/v1 --embedding-model bge-m3
uv run siku search "你的问题" \
  --embedding-base-url http://127.0.0.1:11434/v1 --embedding-model bge-m3 --reranker none
```

或写入配置文件（`~/.config/siku/config.toml`；macOS 为
`~/Library/Application Support/siku/config.toml`，Windows 为 `%APPDATA%\siku\config.toml`，
含明文 key 时 siku 自动以 0600 创建/重写）：

```toml
[embedding]
base_url = "http://127.0.0.1:11434/v1"   # 本地端点无需 key
model = "bge-m3"

[llm]
base_url = "https://api.deepseek.com"
model = "deepseek-chat"
api_key_env = "SIKU_LLM_API_KEY"         # 与 api_key 明文二选一

[rerank]                                  # 可选；未配置时按 reranker=none（RRF-only）
base_url = "https://api.siliconflow.cn/v1"
model = "BAAI/bge-reranker-v2-m3"
api_key_env = "SILICONFLOW_API_KEY"
```

环境变量 `SIKU_EMBEDDING_*` / `SIKU_RERANK_*` / `SIKU_LLM_*` 与 config.toml 字段同形；
key 不进日志、索引元数据与评测基线。桌面端配置说明见 [docs/desktop.md](docs/desktop.md)。

### AI 客户端接入（MCP）

siku 内置 stdio MCP 服务器（ADR-0014）：`siku mcp` 以 Model Context Protocol 标准
stdio 传输暴露知识库工具，供 AI 客户端（ZCode、Claude Code、Claude Desktop、Cursor 等）
直接调用。不监听网络端口、不依赖 `siku serve`；与桌面应用/CLI 并发安全（同库写入互斥）。

暴露八个工具：`search`（混合检索带锚点）、`ask`（单轮有来源问答）、`list_documents`
（资料库清单）、`read_document`（读投影全文，超长明示截断）、`graph_search` /
`graph_neighbors`（知识图谱查询）、`entity_evidence`（实体 join 证据检索，ADR-0015：
查询中的实体名解析为种子，一跳共现扩展返回带溯源的桥接证据，零模型调用，适合多跳/
关联问题）、`ingest`（幂等摄取文件或目录）。移除、重建、设置等管理操作不经 MCP 暴露，
请使用 WebUI 或 CLI。

客户端配置（`--vault`/`--data-dir` **必须传绝对路径**：客户端以任意工作目录拉起服务器
进程；模型通道经环境变量与 `config.toml` 解析，见上一节）：

```jsonc
// ZCode / Claude Code / 通用 stdio 客户端的 mcpServers 配置同构
{
  "mcpServers": {
    "siku": {
      "command": "siku",           // 或 uv tool 安装后的绝对路径
      "args": ["mcp",
               "--vault", "/absolute/path/to/vault",
               "--data-dir", "/absolute/path/to/data"]
    }
  }
}
```

Claude Code 一条命令接入：

```bash
claude mcp add siku -- siku mcp --vault /absolute/path/to/vault --data-dir /absolute/path/to/data
```

### 经 muniu 网关使用（可选）

muniu 提供 openai 兼容端点时，无需 siku 侧代码级对接；执行图谱或 wiki 命令时切换
端点和模型即可：

```bash
uv run siku graph \
  --llm-base-url http://127.0.0.1:8787/v1 \
  --llm-model <muniu 模型别名> \
  --api-key-env MUNIU_API_KEY
uv run siku wiki \
  --llm-base-url http://127.0.0.1:8787/v1 \
  --llm-model <muniu 模型别名> \
  --api-key-env MUNIU_API_KEY
```

经 muniu 使用 siku 时，必须关闭 siku 租户的语义缓存：模糊命中可能破坏重建 diff
为空的幂等闸门。切换通道或模型后，图谱与 wiki 必须使用同一个模型身份；否则摘要身份
校验会拒绝复用旧图谱产物，应先用新参数重新执行 `siku graph`。

## 开发

```bash
uv run pytest               # 测试
uv run ruff check .         # Lint
uv run ruff format .        # 格式化
uv run pre-commit install   # 启用 git hooks（克隆后执行一次）
uv run pre-commit run --all-files   # 手动全量跑一遍 hooks
```

桌面壳开发（Tauri 2 工程 `ui/src-tauri/`）与源码构建流程见
[docs/desktop.md](docs/desktop.md)「从源码构建桌面应用」。

## 路线图

1. **阶段一 ✅**：localhost WebUI（FastAPI + React）+ CLI（摄取/索引/图谱/wiki/问答）已完成
2. **阶段二（当前）**：Tauri 桌面壳（不签名，GitHub Releases + Homebrew 分发），见 [docs/desktop.md](docs/desktop.md)
3. **阶段三**：代码签名 + 自动更新

## License

MIT（见 [LICENSE](LICENSE)，如需调整请在首次提交前修改）
