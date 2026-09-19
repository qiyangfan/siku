# web-ui Specification（delta）

## ADDED Requirements

### Requirement: 提供桌面资料库视图

界面 SHALL 提供资料库视图：来源清单（名称、摄取与索引状态徽标）、导入入口、摄取
进度反馈与全量重建入口（先经确认对话框）。导入与进度 SHALL 全部经 localhost API
完成并展示中文反馈；界面 SHALL NOT 直接读写 vault 文件内容。视图 SHALL 遵循既有
可访问性要求：主要操作键盘可达，清单与进度在窄窗口可读。

#### Scenario: 导入并跟踪进度

- **GIVEN** 用户在资料库视图选择本地文件导入
- **WHEN** 摄取任务执行
- **THEN** 界面展示进度与逐文件结果（成功/失败中文说明），结束后刷新清单状态

#### Scenario: 空状态引导

- **GIVEN** 桌面 vault 为空
- **WHEN** 用户打开资料库视图
- **THEN** 界面展示导入引导与支持格式说明，不展示空白列表

#### Scenario: 重建确认

- **GIVEN** 用户点击全量重建索引
- **WHEN** 确认对话框被确认或取消
- **THEN** 仅确认后发起重建并展示进度反馈，取消时不产生任何请求
