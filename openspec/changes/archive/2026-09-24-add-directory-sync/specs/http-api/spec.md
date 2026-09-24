# http-api Specification（delta）

## MODIFIED Requirements

### Requirement: 提供桌面资料库清单与状态

系统 SHALL 提供 `GET /api/library` 返回桌面 vault 的来源级清单：每条 SHALL 含来源
名、相对路径、`source_hash` 与摄取状态（至少区分已摄取/待重抽/已忽略/原件缺失/
已替代），以及该来源的索引状态；由来源目录同步而来的条目 SHALL 附登记的上游路径
（`origin_path`），手动导入条目该字段为 null。清单 SHALL 派生自既有摄取
元数据与库域登记，SHALL NOT 复制第二份事实存储。

#### Scenario: 展示来源状态

- **GIVEN** vault 内含已摄取、原件被修改、原件缺失与已替代四类文档
- **WHEN** 客户端请求 `GET /api/library`
- **THEN** 返回 200，四类文档分别标记为已摄取/待重抽/原件缺失/已替代，字段与
  既有摄取元数据及库域登记同源

#### Scenario: 清单为只读派生

- **WHEN** 客户端重复请求清单
- **THEN** 清单内容随既有摄取元数据与库域登记变化，系统不因清单查询产生任何写入

#### Scenario: 展示喂养来源

- **GIVEN** 某文档由来源目录同步入库，另一文档由手动导入
- **WHEN** 客户端请求 `GET /api/library`
- **THEN** 前者条目附来源目录中的上游路径，后者该字段为 null

## ADDED Requirements

### Requirement: 提供来源目录管理端点

系统 SHALL 提供来源目录的列举、注册、启停与移除端点。注册 SHALL 校验路径存在且
为目录（否则 422），同一真实路径 SHALL NOT 重复登记（否则 409）；移除 SHALL 仅
删除登记与检测缓存，SHALL NOT 影响已入库文档与既有 tombstone。

#### Scenario: 注册、启停与移除不触及语料

- **GIVEN** 某来源目录已登记且其文档已入库
- **WHEN** 客户端将该源停用后移除登记
- **THEN** 端点返回成功，已入库文档与清单状态保持不变，后续扫描不再遍历该目录

### Requirement: 提供扫描与清理端点

系统 SHALL 提供 `POST /api/library/scan` 立即执行一轮扫描（复用既有任务进度机制，
支持全量哈希校验选项）；任务槽被占用时 SHALL 返回 409 `library_job_busy`。系统
SHALL 提供自动扫描间隔的读写端点（0 表示关闭自动扫描，负值 SHALL 拒绝为 422），
间隔更新 SHALL 免重启生效。系统 SHALL 提供 `POST /api/library/purge` 确认式清理
端点：未携带确认标记 SHALL 返回 422 `purge_confirm_required`；携带后 SHALL 以任务
进度反馈清理过程。

#### Scenario: 手动扫描无变更时瞬时完成

- **GIVEN** 来源目录与登记内容一致
- **WHEN** 客户端请求 `POST /api/library/scan`
- **THEN** 返回 succeeded 任务快照且条目为空，无摄取与索引动作发生

#### Scenario: 间隔更新写入注册表

- **GIVEN** 自动扫描间隔为缺省值
- **WHEN** 客户端请求 `PUT` 更新间隔为 60 秒
- **THEN** 返回 200 与新值，后续读取与调度均按 60 秒执行；负值更新返回 422

#### Scenario: 清理需确认

- **WHEN** 客户端请求 `POST /api/library/purge` 且未携带确认标记
- **THEN** 返回 422 与 `{code, message}` 中文提示，任何文件未被删除
