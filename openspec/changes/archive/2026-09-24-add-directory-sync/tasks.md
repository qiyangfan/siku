# 任务清单

## 约束冻结（实现前）

- [x] 冻结库域状态库形状与位置（`library.sqlite3` 表结构；与 `retrieval.sqlite3`
      物理分离、重建不清除的依据）。（决议见 design.md 决议 #1）
- [x] 冻结扫描算法与护栏（stat 快选 + SHA-256、改名识别、源不可达顺延、白名单、
      身份与去重语义）。（决议见 design.md 决议 #2）
- [x] 冻结调度与任务槽语义（自动顺延 vs 手动 409、间隔免重启生效、kind/phase
      扩展、full 校验选项）。（决议见 design.md 决议 #3）
- [x] 冻结 API 契约、清单字段扩展与新增稳定错误码；OpenAPI 快照刷新方式。
      （决议见 design.md 决议 #4）
- [x] 冻结重算事件边界（SHALL NOT 周期重算）。（决议见 design.md 决议 #5）

## 内核（siku.sync）

- [x] `registry.py`：建表 / WAL / 参数化 SQL；来源 CRUD、entries 缓存、tombstone、
      间隔读写；补"索引与图谱重建不清除库域状态"的守护测试。
- [x] 先写契约测试：快选+哈希 diff、同内容同名幂等跳过、改名识别为移动、内容变更
      超替、源不可达顺延、白名单忽略；再实现 `scanner.py`。
- [x] `service.py`：scan / purge 任务体（单任务槽、进度、协作取消、重启后幂等
      恢复）；purge 物理删除与索引即时消减的测试。
- [x] 调度线程：间隔免重启生效、`≤0` 关闭、槽忙自动顺延（无用户可见错误）。

## API 与 CLI

- [x] 先写契约测试：sources CRUD（422/409/404 路径）、scan 无变更瞬时成功、
      purge 未确认 422、清单 `missing`/`superseded` 状态与 `origin_path` 字段。
- [x] 端点挂载与请求/响应模型；刷新 OpenAPI 快照（仅含本 change 显式新增与清单
      字段扩展）。
- [x] `siku scan` 一次性命令（支持 `--full`），中文报告输出。

## UI

- [x] 资料库视图来源目录区：添加（目录路径）、启停、移除、最后扫描时间展示。
- [x] 立即扫描入口（含全量校验勾选）与进度反馈（复用任务轮询），结束后刷新清单。
- [x] `missing`/`superseded` 徽标与 `origin_path` 展示；清理入口：待清理数量提示、
      二次确认对话框、结果反馈。
- [x] 可访问性与窄窗口（来源区、徽标、进度）；`npm run lint/test/build` 全绿。

## 交付门禁

- [x] pytest 全量、ruff check/format、mypy、pre-commit、openspec strict 全绿；
      OpenAPI 快照变更仅限本 change 显式声明。
- [x] 手工冒烟（serve 级，uvicorn + curl）：注册来源 → 间隔改 2 秒自动扫描
      入库 → 改内容自动超替（检疫分层正确）→ purge 未确认 422 / 确认后清理；
      冒烟暴露并修复「间隔改小需等满旧周期」缺陷，复验通过（review.md）。
- [x] 完成独立 review.md：喂养只读边界、tombstone 生命周期、重建不清除库域状态、
      定时扫描无重算调用的证据。
