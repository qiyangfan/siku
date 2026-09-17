# 提案：完成 Phase 1 摄取纵切面

## Why

Phase 0 只完成脚手架与治理层，下一步唯一排队能力是让用户把常见文档放入本地
vault，并得到可追溯、可重复生成的 Markdown 事实层。本 change 将摄取能力收敛为
一个可测试的内核模块和 CLI 入口，为后续检索与图谱提供稳定输入。

## What Changes

- 定义位于 `src/siku/extractors/` 的统一 `Extractor` 协议与格式注册表。
- 支持 PDF、Word、PPT、Excel 四类闸门格式，并顺手支持 EPUB、HTML、Markdown。
- 将原件复制到 `vault/attachments/`，将结构化 Markdown 投影写入 `vault/notes/`。
- 在投影 frontmatter 与内容块中保留 `source_hash` 和格式锚点。
- 对同一路径的原件按 SHA-256 幂等重跑：hash 不变跳过，hash 变化只更新该文件。

## 受影响决策

- ADR-0004：万能摄取、Markdown 事实层、原件留存、结构锚点与 `source_hash`。
- ADR-0005：可插拔 Extractor、引擎隔离与重依赖放入 extras。

## 不做清单（Non-goals）

- 不实现 SQLite、LanceDB、parquet、检索、图谱、wiki 或 HTTP API。
- 不实现 Office 在线预览/编辑，不把业务逻辑放入 UI 或 Tauri。
- 不实现删除/重命名源文件后的垃圾投影回收；本 change 只处理摄取与同路径重抽。
- 不把 Docling、pandoc、python-pptx、openpyxl 的重量依赖移入核心依赖。
- 不承诺扫描 PDF OCR 质量；MinerU 仍按 ADR-0004/0005 留作后续隔离后端。
