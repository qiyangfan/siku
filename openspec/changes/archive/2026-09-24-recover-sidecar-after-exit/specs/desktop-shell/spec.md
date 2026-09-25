## ADDED Requirements

### Requirement: sidecar 运行期中断后可手动恢复

桌面壳在 sidecar 启动健康检查通过后 SHALL 继续监测它管理的 sidecar 进程及本地健康接口。当进程退出或健康接口持续无响应时，壳 SHALL 停止残留进程并展示本地恢复页；恢复页 SHALL 提供重新启动与退出操作。重新启动 SHALL 经由壳的既有启动编排重新拉起 sidecar，并仅在健康检查通过后返回应用。React 业务页 SHALL NOT 获得进程控制 IPC。

#### Scenario: sidecar 在应用运行期间退出

- **GIVEN** 桌面应用已显示 UI，且壳启动的 sidecar 随后退出
- **WHEN** 壳检测到 sidecar 退出
- **THEN** 壳显示本地服务已停止的恢复页，并提供“重新启动本地服务”和“退出”操作

#### Scenario: 用户从恢复页重新启动

- **GIVEN** 应用处于 sidecar 运行期中断后的恢复页
- **WHEN** 用户选择“重新启动本地服务”
- **THEN** 壳回收可能残留的 sidecar、重新启动服务并轮询健康状态，健康检查通过后再显示应用 UI

#### Scenario: sidecar 健康接口持续不可用

- **GIVEN** sidecar 进程仍在运行但健康接口连续五次检查失败
- **WHEN** 壳认定本地服务不可用
- **THEN** 壳回收该 sidecar 并展示可手动重启的恢复页

#### Scenario: 浏览器模式无法连接服务

- **GIVEN** 用户通过普通浏览器/Vite 查看 UI，且本地服务未运行
- **WHEN** 页面健康检查失败
- **THEN** 页面提供 `siku serve --with-ui` 启动说明和“检查连接”操作，不宣称能从浏览器启动系统进程
