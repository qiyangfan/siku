# 摄取纵切面

## Purpose

为本地文档建立可追溯、可重建的 Markdown 事实层。

## ADDED Requirements

### Requirement: 支持统一 Extractor 协议

系统 SHALL 通过统一的 Extractor 协议接入每一种源格式，并 SHALL 将第三方格式库对象
隔离在对应适配器内部。

#### Scenario: 根据扩展名选择适配器

- **GIVEN** 一个扩展名在支持注册表中的源文件
- **WHEN** 摄取流水线解析该文件
- **THEN** 系统选择对应 Extractor 并返回标题、正文块和格式锚点

#### Scenario: 依赖不可用

- **GIVEN** 源文件属于需要可选依赖或外部程序的格式，且依赖不可用
- **WHEN** 调用对应 Extractor
- **THEN** 系统返回明确的用户可读错误，且不在 vault 写入半成品

### Requirement: 生成本地 Markdown 事实层

系统 SHALL 将原件复制到 `vault/attachments/`，并将 Markdown 投影写入 `vault/notes/`；
投影 SHALL 包含 `source_hash`、源文件名、格式适配器和结构锚点。

#### Scenario: 四类闸门格式摄取

- **GIVEN** 一个 PDF、Word、PPT 或 Excel 原件
- **WHEN** 用户执行摄取
- **THEN** 系统在 attachments 保留原件，并在 notes 生成可读 Markdown 投影

#### Scenario: 结构锚点保留

- **GIVEN** 抽取结果包含页、slide 或 sheet 边界
- **WHEN** 系统生成投影
- **THEN** 投影为对应块保留 `page:N`、`slide:N` 或 `sheet:NAME` 锚点

### Requirement: 按 source_hash 幂等重抽

系统 SHALL 使用原件字节的 SHA-256 作为 `source_hash`；同一路径原件 hash 不变时 SHALL
跳过写入，hash 变化时 SHALL 只更新该文件对应的原件副本与投影。

#### Scenario: 相同原件重复摄取

- **GIVEN** 某源文件已经摄取且其字节未变化
- **WHEN** 再次执行同一路径摄取
- **THEN** 系统报告 skipped，投影与原件字节均不发生变化

#### Scenario: 单文件内容变化

- **GIVEN** 某源文件已经摄取后内容发生变化
- **WHEN** 再次执行同一路径摄取
- **THEN** 系统只更新该文件对应产物，frontmatter 中的 `source_hash` 与正文同步变化

### Requirement: CLI 支持单文件与目录

系统 SHALL 提供 `siku ingest SOURCE [--vault VAULT]` 命令；SOURCE 为目录时 SHALL 按稳定
顺序递归处理支持格式，未知扩展名 SHALL 被跳过并报告。

#### Scenario: 目录摄取

- **GIVEN** 一个包含支持格式与未知格式的目录
- **WHEN** 用户执行目录摄取
- **THEN** 系统处理所有支持格式、跳过未知格式，并输出 created/updated/skipped/ignored 统计

#### Scenario: 单文件失败

- **GIVEN** 单文件的 Extractor 无法完成抽取
- **WHEN** 用户执行摄取
- **THEN** CLI 以非零状态退出并显示原因，不报告该文件成功
