# 任务清单

- [ ] 先写健康检查与 404/405 契约测试，再实现 `src/siku/api/` 应用工厂
      `create_app()` 与 `GET /api/health`；仅绑定 127.0.0.1 的约束落在 `siku serve`。
- [ ] 先写错误映射表驱动测试（每个领域错误类 → 状态码/code/中文文案），抽取共享
      错误文案模块（CLI 反向复用，消除 `_retrieval_error_message`/`_graph_error_message`
      双份漂移面），再实现映射器。
- [ ] 先写 `POST /api/ingest` 契约测试（成功/路径不存在/投影损坏），再实现端点
      （复用 `ingest_path`，响应字段与 `siku ingest` 同构）。
- [ ] 先写 `POST /api/search` 契约测试（命中/空查询/缺索引 409），再实现端点
      （复用 `SearchService`，fake embedding/reranker 注入，CI 零网络）。
- [ ] 先写 `POST /api/graph` 契约测试（构建成功/空语料/缺 key 503/产物损坏 409），
      再实现端点（复用 `build_graph`，fake extractor 注入）。
- [ ] 先写 `POST /api/wiki` 契约测试（生成成功/图谱缺失 409/身份不一致 409），
      再实现端点（复用 `generate_wiki`）。
- [ ] 先写契约漂移测试，再生成 `contracts/openapi.json` 快照与
      `python -m siku.api.contract --refresh` 刷新命令；快照头注明生成方式。
- [ ] 先写 `siku serve` 测试（工厂启动/拒绝 0.0.0.0 缺省/CORS 仅 localhost 开发源），
      再实现命令与 CORS/静态托管挂载（`--with-ui` 挂 `ui/dist`）。
- [ ] 先写 CLI 参数透传测试（fake provider 断言收到 base_url/model_id；缺省路径
      行为不变），再给 `graph`/`wiki` 加 `--llm-base-url` / `--llm-model`。
- [ ] 部署文档：README 增补"经 muniu 网关使用"可选节（两项切换步骤 + siku 租户
      语义缓存必须关闭 + 换通道同步 `summary_identity` 告诫）。
- [ ] 依赖纪律验证：fastapi/uvicorn 已在核心依赖（Phase 0 预置），本 change 零新增
      依赖；确认 API 层不 import 领域层之外的第三方对象。
- [ ] `siku graph --json` 与 `POST /api/graph` 响应字段同构性测试（同一构建产物
      两次断言字段集合一致），防止 CLI 与 API 契约漂移。
- [ ] 用 fake provider 全链路跑 `uv run pytest`、`uv run ruff check .`、
      `uv run ruff format --check .`、`uv run mypy`、`uv run pre-commit run
      --all-files` 与 OpenSpec strict 校验（changes + specs），完成独立 review.md
      后才允许归档并同步 http-api spec。
