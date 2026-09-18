# 提案：完成 Tauri 桌面壳与无签名分发纵切面

## Why

Phase 4 已完成 localhost HTTP API、检索驱动的单轮问答和 React 最小界面，但用户仍需
安装 uv/Node、启动 `siku serve` 并理解工作目录。ROADMAP 的下一唯一排序项是 Phase 5：
把既有 UI 与 Python 内核封装为可双击启动的桌面应用，降低早期用户的安装门槛。

本 change 只解决桌面壳、内核进程生命周期和无签名分发，不重写 Python 内核，也不把检索、
问答、图谱或数据访问逻辑迁入 Rust。桌面壳的业务数据仍经既有 localhost HTTP API 流转，
从而保持 Phase 6 签名与更新、以及未来 UI 形态替换的独立性。

## What Changes

- 新增 Tauri 2.x 桌面壳，承载现有 `ui/dist`，只负责窗口、配置路径、sidecar 启停和
  健康检查。
- 将现有 Python CLI/API 内核构建为按目标平台提供的 sidecar；sidecar 仅监听 loopback，
  使用显式的 vault、data 和 UI 资源路径，不依赖用户的当前工作目录。
- 为 `siku serve` 增加向后兼容的路径/静态资源参数，使桌面壳可以传入绝对路径；既有
  localhost API、`siku serve --with-ui` 和开发期 Vite 流程保持可用。
- 建立 macOS、Windows、Linux 的构建与 GitHub Release 产物流程；提供 Homebrew Cask
  分发入口，但不在本 change 内签名、公证或实现自动更新。
- 增加 sidecar 生命周期、健康检查、路径隔离、构建产物和三平台安装后问答冒烟门禁。

## 受影响决策

- ADR-0001：Rust 只用于 Tauri 壳，Python 继续承载全部内核业务，TypeScript/React 继续
  承载界面。
- ADR-0002：落实阶段二 Tauri 壳、localhost 边界和本地优先；不引入账号、遥测、云端存储，
  也不提前做阶段三签名与自动更新。
- ADR-0008：Tauri 构建会使 Python 解释器随产品固定，完成后复核 3.14 CI 哨兵触发器的
  必要性，但本 change 不删除现有 CI 覆盖。

## 与项目路线的关系

这是 ROADMAP Phase 5，位于 Phase 4 之后、Phase 6 之前。它只包装已经完成的问答纵切面；
浏览、图谱画布、wiki 阅读仍不属于本期功能扩展。

## Non-goals

- 不迁移或重写 Python 内核，不在 Rust 中实现摄取、索引、检索、问答、图谱、wiki 或数据
  访问逻辑。
- 不改变 `/api/*` 响应字段、错误码、OpenAPI 契约或问答引用语义；新增 CLI 路径参数必须
  保持旧默认值和旧开发流程兼容。
- 不实现账号、登录、远程鉴权、云端存储、遥测、跨设备同步、协作、多租户或支付。
- 不实现资料导入向导、完整设置中心、浏览/图谱/wiki UI；桌面数据目录选择策略先冻结，
  复杂的资料管理另行立项。
- 不实现代码签名、Apple 公证、Windows 签名、自动更新、更新回滚或增量更新；这些属于
  Phase 6。
- 不把 Tauri `invoke`、事件或文件 API 当作业务数据通道；业务数据必须继续走 localhost
  HTTP API。

## 边界裁决

桌面壳是进程与窗口适配层，不是第二个应用内核。Tauri 只可启动/停止 sidecar、等待
`GET /api/health`、传递非敏感路径和渲染 UI；问题、答案、引用、索引状态和错误仍由既有
HTTP API 提供。sidecar 的 API key 继续只从用户配置的进程环境变量读取，不进入 Tauri
配置、前端状态或安装包。

Tauri 官方文档支持通过 `bundle.externalBin` 携带按 target triple 命名的外部二进制，
并支持用 GitHub Actions 构建和上传 release 产物；实现时以官方文档和锁文件中的兼容版本
为准，不在本提案中凭空冻结 Rust/Node 版本：

- <https://v2.tauri.app/develop/sidecar/>
- <https://v2.tauri.app/reference/config/#bundleconfig>
- <https://v2.tauri.app/distribute/pipelines/github/>
