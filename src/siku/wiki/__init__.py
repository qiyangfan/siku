"""wiki 包：社区摘要与总目条目生成。

边界（design.md）：只读取 `data/graph/` 的 parquet 产物与缓存，
写 `data/wiki/`；`vault/` 不写入任何数据（宪法红线 3）。
"""
