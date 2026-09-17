# siku（四库）

> 把你所有的文档丢进来：自动摄取、自动织成知识图谱、自动编成 wiki，然后用自然语言向它提问。

siku 取意《四库全书》——历史上最大规模的"汇总天下文献 → 自动编目（总目提要）→ 结构化检索"工程。本项目是它的个人本地版：**本地优先**，语料永不离开你的磁盘（仅图谱抽取/问答时按需调用你自己的 LLM API key）。

🚧 当前处于脚手架阶段。架构定稿（北极星）见 [docs/architecture.md](docs/architecture.md)，
不可协商红线见 [openspec/project.md](openspec/project.md)（宪法）。

## 文档地图

| 想知道 | 去哪 |
|---|---|
| 接下来干什么、哪些先不做 | `docs/ROADMAP.md`（阶段闸门 + 触发器台账 + Backlog） |
| 某个选型为什么这么定 | `docs/adr/`（ADR-0001~0008） |
| 哪些规则碰不得 | `openspec/project.md`（宪法红线 + 工程口径） |
| 系统应如何行为 | `openspec/specs/`（随 change 归档生长） |
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
| 摄取 | PDF：Docling / MinerU · Word：pandoc · PPT：python-pptx · Excel：openpyxl |
| 检索质量 | bge-m3 向量 + BM25 混合召回 + reranker 重排 + golden set 回归 |

## 快速开始

```bash
# 需要先安装 uv：https://docs.astral.sh/uv/
uv sync

# 冒烟验证
uv run siku version
```

## 开发

```bash
uv run pytest               # 测试
uv run ruff check .         # Lint
uv run ruff format .        # 格式化
uv run pre-commit install   # 启用 git hooks（克隆后执行一次）
uv run pre-commit run --all-files   # 手动全量跑一遍 hooks
```

## 路线图

1. **阶段一（当前）**：uv 安装的本地 WebUI（FastAPI + React，localhost）+ CLI（摄取/索引/重建一等命令）
2. **阶段二**：Tauri 桌面壳（不签名，GitHub Releases + Homebrew 分发）
3. **阶段三**：代码签名 + 自动更新

## License

MIT（见 [LICENSE](LICENSE)，如需调整请在首次提交前修改）
