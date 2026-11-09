# 实施任务

每项 ≤ 2h；先写失败测试，再实现对应步骤。

## 1. 种子解析与 join 内核

- [x] 1.1 失败测试先行：种子解析表驱动——实体名子串命中、casefold 折叠、长名优先
  截断、歧义名单逐实体返回、零命中分型 `seed_miss`；实现确定性种子解析纯函数。
- [x] 1.2 失败测试先行：join 纯函数表驱动——零跳种子证据、H=1 桥接扩展（经第三实体
  桥接的跨文档中间证据）、chunk_id 去重、frontier 预算按连接密度截断、同分字典序
  确定性、`expansion_empty` 分型；实现打分与扩展。
- [x] 1.3 失败测试先行：装配层——图谱未构建 / 索引缺失的归一化失败、时点错位过滤
  并如实计数、结果复用 `SearchResult` 形态附实体溯源；实现 `entity_join` 服务模块
  （只读 `load_graph` + `SqliteIndex.open_if_exists`，无新 IO 抽象）。

## 2. MCP 工具面

- [x] 2.1 失败测试先行：`entity_evidence` 正常返回带溯源、空结果分型返回定位建议
  而非失败、图谱未构建给构建指引、超限明示截断；实现工具（复用既有错误映射与
  有界查询口径），工具描述写明与 `graph_search`/`read_document` 的组合用法。
- [x] 2.2 协议层回归：子进程 stdio 拉起 `siku mcp`，断言 `tools/list` 为八只读 +
  一摄取，`entity_evidence` 真实往返成功，stdout 协议纯净不回归。

## 3. 多跳评测集与对照

- [x] 3.1 构建中文多跳评测集 fixture：合成语料 + 「问题 + 桥接证据 chunk」标注对
  15~30 对，覆盖单文档共现 / 跨文档第三实体桥接 / 歧义名干扰三类；fixture 入库
  管理并附构建理由说明。
- [x] 3.2 对照评测：同一问题集上纯混合召回 vs join 通道的桥接证据 Recall@K 对照，
  数字与结论如实写入 review.md（不设达标阈值；不优于混合则记录"通道保持工具面
  定位"结论）。

## 4. 验证与交付

- [x] 4.1 全量 pytest、ruff、`openspec validate --changes --strict`；核对既有七个
  工具行为与 golden set 零触碰（混合召回链路 diff 为空）。
- [x] 4.2 README 增补 `entity_evidence` 用法与组合查询示例（绝对路径配置沿用既有
  三例格式）；归档时同步主规格（`entity-join` Purpose 入档；`mcp-server` Purpose
  工具数与清单更新为七个只读）。
  - 注：README 已更新（八工具清单 + entity_evidence 说明）；主规格已于 2026-11-09
    归档时同步——`entity-join/spec.md` 入主 specs，`mcp-server/spec.md` 按 RENAMED +
    MODIFIED 合并，`openspec validate --specs --strict` 通过。
