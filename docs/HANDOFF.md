# HANDOFF — siku 交接文档

> **接驳点，非常驻知识库。** 常驻知识分属四层（按此顺序读，约 5 分钟）：
> 宪法 `openspec/project.md` → 协作规范 `AGENTS.md` → 路线 `docs/ROADMAP.md` →
> 相关决策 `docs/adr/`。本文件每次交接**整体重写**（历史看 `git log`），
> 硬上限 ~60 行：只写“接手者马上需要的状态”，重复常驻文档的内容即为违规。

- **更新时间**：2026-09-17
- **仓库**：`~/siku` → github.com/qiyangfan/siku（私有；SSH 推送，gh keyring 认证）

## 现状

- Phase 0 完成（78e53d5）：脚手架全绿，治理层四件入库。
- Phase 1 摄取纵切面已完成并归档：`2026-09-17-add-ingest-vertical-slice`。
  `siku ingest` 已支持 PDF/DOCX/PPTX/XLSX，并顺手支持 EPUB/HTML/Markdown；原件落在
  `vault/attachments/`，投影落在 `vault/notes/`，按路径稳定标识与 `source_hash` 幂等。
- 本地证据：19 个 pytest、ruff、mypy、pre-commit、OpenSpec strict 全部通过；四类真实
  原件均完成投影冒烟。当前分支 `feature/phase1-ingest` 已提交并推送。

## 下一步（唯一）

**Phase 2 首个 change：检索纵切面**（闸门与边界见 ROADMAP，决策依据 ADR-0003/0006）

- 范围：SQLite schema + FTS5 中文分词 + LanceDB + bge-m3 + BM25 混合召回 + reranker
  + golden set v0；必须先创建并严格校验 OpenSpec change，再写行为代码。

## 验证命令

```bash
uv sync && uv run pytest && uv run ruff check . && uv run ruff format --check .
uv run mypy && uv run pre-commit run --all-files
openspec validate --changes --strict && openspec validate --specs --strict
```

## 已知坑

无——当前未发现需要写入常驻文档的新坑；新问题先补 ADR 或 AGENTS.md，过期即删。
