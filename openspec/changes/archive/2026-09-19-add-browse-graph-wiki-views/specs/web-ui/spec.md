# web-ui Specification（delta）

## ADDED Requirements

### Requirement: 提供浏览/图谱/wiki 三个只读视图

界面 SHALL 提供视图导航与三个只读视图：浏览（分页清单 + Markdown 只读渲染）、
图谱（Sigma.js WebGL 画布：节点搜索、邻域展开、社区着色、截断提示）、wiki（条目
清单 + 阅读 + 「可重建」时效提示）。全部数据 SHALL 经只读端点获取；Markdown 渲染
SHALL 产出安全只读输出（不执行内嵌脚本）；图谱画布 SHALL 遵守服务端截断边界。
视图 SHALL 遵循既有可访问性要求：主要操作键盘可达，窄窗口可读。

#### Scenario: 浏览阅读

- **GIVEN** 用户在浏览视图选中一篇笔记
- **WHEN** 内容加载
- **THEN** 界面渲染只读 Markdown 与来源锚点信息，不提供编辑入口

#### Scenario: 图谱邻域展开

- **GIVEN** 图谱视图已展示聚合画布
- **WHEN** 用户搜索并点击一个实体展开邻域
- **THEN** 画布增量展开该实体的有界邻域，超限时展示截断提示

#### Scenario: wiki 阅读与时效提示

- **GIVEN** wiki 存在已生成的条目
- **WHEN** 用户打开 wiki 视图并阅读一条
- **THEN** 界面展示条目内容与生成时间，提示可重建但不自动触发

#### Scenario: 实体联动问答

- **GIVEN** 用户在图谱视图选中一个实体
- **WHEN** 用户选择「在问答中查询」
- **THEN** 界面切换到问答视图并预填该实体相关的问题，不自动发送
