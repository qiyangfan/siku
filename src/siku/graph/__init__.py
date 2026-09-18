"""图谱领域包：实体/关系抽取、缓存、图谱构建与体检报告。

边界（design.md）：本包只读取 `vault/notes/` 投影与检索层固化的 chunk 元数据，
复用 `retrieve.notes_reader` 的解析器；`vault/` 不写入任何图谱数据，
`data/graph/` 为可删除、可全量重建的派生物（宪法红线 3）。
"""
