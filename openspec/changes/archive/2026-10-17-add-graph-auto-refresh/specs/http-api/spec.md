## MODIFIED Requirements

### Requirement: 提供扫描与清理端点

系统 SHALL 提供 `POST /api/library/scan` 立即执行一轮扫描（复用既有任务进度机制，
支持全量哈希校验选项）；任务槽被占用时 SHALL 返回 409 `library_job_busy`。系统
SHALL 提供自动扫描间隔与图谱自动刷新开关的读写端点（间隔 0 表示关闭自动扫描，
负值 SHALL 拒绝为 422；开关缺省为关闭），二者更新 SHALL 免重启生效。系统 SHALL
提供 `POST /api/library/purge` 确认式清理端点：未携带确认标记 SHALL 返回 422
`purge_confirm_required`；携带后 SHALL 以任务进度反馈清理过程。

#### Scenario: 手动扫描无变更时瞬时完成

- **GIVEN** 来源目录与登记内容一致
- **WHEN** 客户端请求 `POST /api/library/scan`
- **THEN** 返回 succeeded 任务快照且条目为空，无摄取与索引动作发生

#### Scenario: 间隔更新写入注册表

- **GIVEN** 自动扫描间隔为缺省值
- **WHEN** 客户端请求 `PUT` 更新间隔为 60 秒
- **THEN** 返回 200 与新值，后续读取与调度均按 60 秒执行；负值更新返回 422

#### Scenario: 图谱自动刷新开关读写

- **GIVEN** 图谱自动刷新开关为缺省关闭
- **WHEN** 客户端请求 `PUT` 开启该开关并重新读取
- **THEN** 返回 200 与新值，后续内容变更任务按开关语义执行；再次关闭后行为回到
  只同步索引

#### Scenario: 清理需确认

- **WHEN** 客户端请求 `POST /api/library/purge` 且未携带确认标记
- **THEN** 返回 422 与 `{code, message}` 中文提示，任何文件未被删除

## ADDED Requirements

### Requirement: 资料库任务通知派生维护结果

资料库任务（摄取/扫描/清理）的终态快照 SHALL 可携带中文通知字段，说明收尾阶段
派生维护的结果或跳过原因（含图谱自动刷新的抽取与缓存命中计数、因抽取身份变更
跳过的原因、因端点失败跳过的事实）。通知 SHALL NOT 改变任务终态语义（成功/失败/
取消）；通知字段缺失 SHALL 按无附加信息处理，既有客户端解析不受影响。

#### Scenario: 自动刷新计数进通知

- **GIVEN** 开关已开启且自动刷新实际执行
- **WHEN** 客户端轮询该任务快照
- **THEN** 响应携带通知字段，说明本次新增抽取数与缓存命中数

#### Scenario: 跳过与失败同样可见

- **GIVEN** 开关已开启但抽取身份不符，或抽取端点失败
- **WHEN** 客户端轮询该任务快照
- **THEN** 通知分别说明跳过原因或失败事实，任务终态分别为 succeeded（摄取成功）
  与既有终态语义，不因图谱刷新失败改写

#### Scenario: 无通知时保持兼容

- **GIVEN** 开关为关闭，或任务未发生任何可通知的派生维护
- **WHEN** 客户端轮询任务快照
- **THEN** 通知字段缺失或为空，旧客户端按既有契约正常解析
