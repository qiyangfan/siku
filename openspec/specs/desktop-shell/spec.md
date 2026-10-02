# desktop-shell Specification

## Purpose
提供一个无签名的 Tauri 桌面壳，将现有 React UI 与 Python localhost 内核封装为可双击
启动的应用；桌面壳只负责进程和窗口生命周期，业务数据仍经 HTTP API 访问。

## Requirements

### Requirement: 启动并管理本地内核 sidecar

桌面应用 SHALL 启动一个 loopback-only Python sidecar，向其传入显式的绝对 vault、data、
UI 资源路径和未占用端口，并在 `GET /api/health` 成功后才展示问答界面。sidecar 启动失败、
提前退出或健康检查超时 SHALL 展示可行动的中文错误状态，不得展示空白窗口或 traceback。

#### Scenario: 首次启动完成健康检查

- **GIVEN** 安装包完整且 sidecar 可执行
- **WHEN** 用户双击打开应用
- **THEN** 应用在超时前启动 sidecar，健康检查返回成功后展示现有问答界面，且问答请求
  仍通过 localhost HTTP API 发送

#### Scenario: sidecar 启动失败

- **GIVEN** sidecar 不存在、不可执行或健康检查超时
- **WHEN** 用户打开应用
- **THEN** 应用展示启动失败原因和重试/退出操作，不显示 Python traceback、异常类名或
  API key

#### Scenario: 关闭应用回收内核

- **GIVEN** sidecar 已运行
- **WHEN** 用户关闭最后一个应用窗口
- **THEN** 应用先请求优雅退出，必要时强制回收 sidecar，关闭后不得遗留由本应用启动的
  sidecar 或端口占用

### Requirement: 保持 localhost HTTP 与数据主权边界

桌面 UI SHALL 只通过既有 localhost HTTP API 获取健康状态、问题、答案、引用和错误；
Tauri Rust 层 SHALL NOT 实现检索、提示词、回答校验、图谱、wiki 或直接读取 vault、
SQLite、LanceDB、parquet。sidecar SHALL 仅监听 loopback，API key SHALL 继续从用户配置的
环境变量读取，不得写入安装包、Tauri 配置或前端状态。

#### Scenario: 桌面问答不绕过内核

- **GIVEN** 用户在桌面 UI 提交问题或展开引用
- **WHEN** 应用加载回答内容
- **THEN** 数据来自 `/api/ask` 响应，前端和 Rust 不自行读取知识库或重建引用

#### Scenario: sidecar 使用显式数据目录

- **GIVEN** 应用从任意工作目录启动
- **WHEN** sidecar 启动
- **THEN** vault、派生 data 和 UI 资源均使用壳传入的绝对路径，不因当前工作目录变化而
  写入用户目录之外的隐式位置

### Requirement: 保持 CLI 与开发期 Web UI 兼容

桌面适配 SHALL 为 `siku serve` 增加可选的 vault、data 和 UI 资源路径参数，未提供参数时
保持现有默认行为。既有 `siku serve --with-ui`、Vite 开发代理、`/api/*` 契约和问答 API
字段 SHALL 保持兼容。

#### Scenario: 旧命令行为不变

- **GIVEN** 用户执行现有的 `siku serve --with-ui`
- **WHEN** `ui/dist` 存在且服务启动
- **THEN** 服务仍在默认 localhost 地址提供原有 UI 和 API，新增路径参数不是必填项

### Requirement: 生成可追溯的三平台 unsigned 发布产物

发布流程 SHALL 能为 macOS、Windows、Linux 的冻结目标矩阵构建 Tauri 安装产物，并将版本、
target 和 checksum 与 GitHub Release 关联；Homebrew Cask SHALL 指向同一版本的 Release
资产。Phase 5 产物 SHALL 明确标注未签名，不得宣称已完成签名、公证或自动更新。

#### Scenario: 版本 tag 触发发布构建

- **GIVEN** 仓库创建符合约定的版本 tag
- **WHEN** GitHub Actions 执行发布工作流
- **THEN** 每个平台目标生成可下载产物并上传到对应 Release，产物命名、版本和 checksum
  可追溯，构建失败不会生成不完整的“成功发布”标记

#### Scenario: Homebrew Cask 安装

- **GIVEN** Homebrew tap 和 Release 资产已按冻结配置发布
- **WHEN** 用户执行 Cask 安装
- **THEN** Homebrew 下载与 Release 版本匹配的 unsigned 安装包；安装说明明确系统安全
  提示以及 Phase 6 尚未提供签名/自动更新

### Requirement: 桌面安装后可完成问答全链路

在每个冻结目标平台上，安装后的应用 SHALL 能在准备好的小型 fixture vault 和派生索引上
完成“启动 → 健康检查 → 提问 → 返回带引用回答 → 关闭并回收 sidecar”全链路；测试 SHALL
使用 fake provider 或已配置的测试 LLM，不得把真实 key 写入仓库或 CI 日志。

#### Scenario: 三平台问答冒烟

- **GIVEN** 安装包已安装，fixture vault 已建立索引，测试 provider 已配置
- **WHEN** 用户打开应用并提交一个可由 fixture 支持的问题
- **THEN** 应用返回既有问答响应和引用，且引用来自 fixture；关闭应用后无残留 sidecar

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

### Requirement: 桌面包具备常用格式摄取运行时

桌面构建产物 SHALL 携带默认 PDF、DOCX、PPTX、XLSX/XLSM 摄取所需的轻量解析模块与格式转换工具，并从随包资源定位，不依赖用户的开发环境或系统转换工具。构建 SHALL 固定转换工具版本、目标平台与完整性校验，保留许可说明；运行时 SHALL NOT 下载解析依赖、识别模型或模型权重。本变更 SHALL 保持现有发布禁用、签名边界及实机冒烟豁免。

#### Scenario: 干净环境中的四类格式抽取

- **GIVEN** 用户只安装桌面包，系统 PATH 没有转换工具，网络不可达且没有模型缓存
- **WHEN** 导入含文字 PDF、DOCX、PPTX、XLSX
- **THEN** 包内运行时可完成抽取与投影，后续索引仍遵守既有模型端点前提

#### Scenario: 包内转换工具不需要系统安装

- **GIVEN** 冻结 sidecar 已携带目标平台的转换工具
- **WHEN** 从安装目录启动并解析 DOCX
- **THEN** 使用包内资源的绝对路径，与当前工作目录、系统 PATH 和开发工具无关

#### Scenario: 构建缺资源不能伪装交付

- **GIVEN** 某平台构建缺少必需解析模块，或转换工具校验/架构不符
- **WHEN** 执行该平台构建检查
- **THEN** 构建检查失败并指出资源问题，不以开发机抽取通过代替该产物可用
