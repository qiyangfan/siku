# http-api Specification（delta）

## ADDED Requirements

### Requirement: 提供浏览只读端点

系统 SHALL 提供浏览读取端点：返回 vault 笔记投影的分页清单（稳定排序、含来源名与
元数据）与单篇 Markdown 内容（含来源锚点信息）；请求不存在的条目 SHALL 返回 404。
端点为只读，SHALL NOT 提供任何写回路径。

#### Scenario: 清单与单篇读取

- **GIVEN** vault 已摄取若干文档并生成笔记投影
- **WHEN** 客户端请求清单后请求其中一篇
- **THEN** 清单含稳定排序的分页与总数，单篇返回 Markdown 内容与来源锚点信息

#### Scenario: 读取不存在的条目

- **GIVEN** 客户端请求的笔记标识不存在
- **WHEN** 客户端请求单篇内容
- **THEN** 返回 404 与 `{code, message}` 中文提示，无其他副作用

### Requirement: 提供图谱有界只读查询

系统 SHALL 提供图谱读取端点：返回实体/边/社区的聚合统计，以及有界子图查询（度数
top-N、实体搜索、邻域展开，请求含返回上限）。候选结果超过上限时系统 SHALL 按既定
优先级裁剪并在响应中明示「已截断」与总数。端点 SHALL NOT 暴露存储文件路径或一次性
推送全图。

#### Scenario: 聚合统计

- **GIVEN** 图谱已构建
- **WHEN** 客户端请求统计
- **THEN** 返回节点数、边数、社区数等聚合指标

#### Scenario: 大图截断明示

- **GIVEN** 子图查询的候选结果超过返回上限
- **WHEN** 客户端请求邻域展开
- **THEN** 返回不超过上限的结果集，并携带「已截断」标记与候选总数

### Requirement: 提供 wiki 只读端点

系统 SHALL 提供 wiki 条目清单与单条内容读取端点，内容派生自 `data/wiki/entries/`；
响应 SHALL 携带生成时间等时效元数据。端点为只读，读取 SHALL NOT 触发生成或重建。

#### Scenario: 条目阅读

- **GIVEN** wiki 已生成
- **WHEN** 客户端请求条目清单与其中一条
- **THEN** 清单返回条目列表，单条返回内容与生成时间元数据，且未触发重新生成
