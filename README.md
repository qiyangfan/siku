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
| 摄取 | PDF：Docling / MinerU · Word：pandoc · PPT：python-pptx · Excel：openpyxl |
| 检索质量 | bge-m3 向量 + BM25 混合召回 + reranker 重排 + golden set 回归 |

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
