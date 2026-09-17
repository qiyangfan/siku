# 设计：Phase 1 摄取纵切面

## 边界

CLI 只负责接收源文件/目录与 vault 位置，业务逻辑位于 `siku.ingest`。摄取模块不
知道 UI、HTTP 或下游索引；它只产生原件和 Markdown 投影。

## 数据流

```text
源文件/目录
    -> suffix 注册表选择 Extractor
    -> ExtractedDocument（标题 + 结构块 + 锚点）
    -> SHA-256 与稳定 source_id
    -> vault/attachments/ 原件
    -> vault/notes/ Markdown + frontmatter
```

`source_id` 由源文件的规范绝对路径稳定计算，仅用于避免同名文件覆盖；它不是内容
事实。内容事实只有原件字节和 `source_hash`。因此同一路径内容更新会复用同一投影名，
而不同路径的同名文件可以共存。

## Extractor 协议

协议只返回领域模型，不暴露第三方库对象：

- `ExtractedBlock(text, anchor)`：正文块及 `page:N`、`slide:N`、`sheet:NAME` 等锚点；
- `ExtractedDocument(title, blocks)`：一个源文件的规范化抽取结果；
- `Extractor.extract(path)`：每个格式实现自己的依赖加载和错误转换。

第三方依赖全部延迟导入。PDF 使用可选 Docling；Word 使用外部 pandoc 进程；PPT
使用 python-pptx；Excel 使用 openpyxl。依赖缺失时抛出包含安装/配置方向的明确错误，
不得让核心包在 import 阶段失败。

## 投影与幂等

投影 frontmatter 使用稳定 JSON 字符串写入 `title`、`source_hash`、`source_name`、
`source_id`、`extractor`。正文按抽取块输出二级标题和锚点注释；不写当前时间等非确定
字段，保证 hash 不变时输出字节稳定。

摄取前先计算源文件 hash。若同一 `source_id` 的 note 已有相同 hash 且 attachment
存在，则返回 skipped，不写任何文件；否则原子替换 note，并仅在原件 hash 不同时
更新 attachment。目录摄取按稳定路径排序，报告 created/updated/skipped 数量。

## 格式范围

闸门格式：`.pdf`、`.docx`/`.doc`、`.pptx`、`.xlsx`/`.xlsm`。顺手格式：`.md`、
`.html`/`.htm`、`.epub`。未知扩展名跳过并在 CLI 报告中计数，不进入 vault。

## 失败策略

单文件抽取失败立即以用户可读错误退出，不写该文件的半成品；已完成的前序文件保持
有效。批量目录不吞掉失败，避免用户误以为全部成功。
