## ADDED Requirements

### Requirement: 资料移除后旧可读派生物失效

手动资料移除完整成功前，系统 SHALL 使包含旧语料的可读图谱与 Wiki 快照失效，保留可复用的抽取缓存，SHALL NOT 自动调用模型重建。后续读取 SHALL 沿未构建语义给出重建提示；图谱显式重建 SHALL 仅使用当前剩余 Markdown 事实层及其派生块，Wiki SHALL 使用当前重建图谱，SHALL NOT 从旧缓存恢复已移除资料，也 SHALL NOT 新增检索索引或向量端点的前置条件。

#### Scenario: 移除后已有快照不能继续读取

- **GIVEN** 一个已构建图谱/Wiki 的手动来源被完整移除
- **WHEN** 新请求读取图谱或 Wiki
- **THEN** 不返回旧可读产物，提示需重新构建，移除本身没有自动模型调用

#### Scenario: 缓存复用不能复活删除块

- **GIVEN** 抽取缓存仍包含已移除来源的历史条目
- **WHEN** 用户显式重建图谱与 Wiki
- **THEN** 只按当前 Markdown 事实层来源和 chunk 集合复用缓存，移除内容不进入新实体、关系、社区或条目

#### Scenario: 无检索索引仍按剩余事实层构建

- **GIVEN** 资料已移除，剩余 Markdown 投影存在但检索索引不存在，图谱模型前提已满足
- **WHEN** 用户显式构建图谱并生成 Wiki
- **THEN** 图谱使用剩余事实层，Wiki 使用当前图谱，不因缺少检索索引遗漏语料
