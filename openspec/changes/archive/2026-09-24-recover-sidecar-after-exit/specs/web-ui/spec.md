## ADDED Requirements

### Requirement: 全局显示本地服务状态和浏览器恢复指引

React 主框架 SHALL 在所有视图显示用户可理解的本地服务连接状态。健康检查失败时 SHALL 在当前视图展示浏览器启动说明与“检查连接”操作；桌面应用的真实进程重启 SHALL 由 Tauri 恢复页提供。页面 SHALL NOT 将“内核已连接”等实现术语用作用户状态。

#### Scenario: 服务正常时显示连接状态

- **GIVEN** localhost API 健康检查成功
- **WHEN** 用户查看任意视图
- **THEN** 共享页头显示“服务正常”

#### Scenario: 服务不可用时跨视图提供可理解状态

- **GIVEN** localhost API 健康检查失败
- **WHEN** 用户查看问答、浏览、图谱、wiki、资料库或设置视图
- **THEN** 页头显示“服务未连接”，当前视图显示浏览器手动启动指引与只负责检查连接的按钮
