# 代码评审：HTTP API 契约纵切面

## 评审结论

通过。实现严格落在本 change 的边界内：新增 localhost FastAPI 契约层、CLI `serve` 与
LLM 参数透传、共享错误映射、OpenAPI 快照和 muniu 使用文档；未修改 ingest/retrieve/
graph/wiki 领域行为，未实现 React UI、对话编排、鉴权、多租户、HTTPS 或 muniu 代码级
集成。

本轮复审确认并修复了三项问题：OpenAPI 快照测试改为精确序列化比较；graph/wiki 工厂
异常纳入统一领域错误映射；共享错误文案恢复既有 CLI 默认提示语义。

## 重点检查

- `src/siku/api/` 仅负责请求校验、既有服务调用、响应模型和错误归一；测试通过工厂注入
  fake，CI 不访问真实模型或网络。
- 默认 `siku serve` 绑定 `127.0.0.1:8000`；显式监听 `0.0.0.0` 时输出警告；CORS 只允许
  `localhost:5173` 与 `127.0.0.1:5173`，静态 UI 仅在 `--with-ui` 时挂载。
- 领域错误覆盖 ingest、retrieve、graph 全部错误类，返回稳定英文 `code`、中文 `message`
  和三类状态码；异常详情仅进入 debug 日志，不进入 HTTP 响应。
- graph/wiki 的自定义模型身份进入摘要缓存键；CLI 与 API graph JSON 字段集合保持一致。
- `contracts/openapi.json` 由显式 `uv run python -m siku.api.contract --refresh` 生成，漂移
  测试逐字节比较序列化结果。
- `pyproject.toml` 未新增依赖；FastAPI、uvicorn、httpx、pydantic 均为现有核心依赖。

## 验证证据

- `uv run pytest`：408 passed。
- `uv run ruff check .`：通过。
- `uv run ruff format --check .`：通过。
- `uv run mypy`：81 个源/测试文件无错误。
- `uv run pre-commit run --all-files`：全部通过。
- `openspec validate --changes --strict`：1/1 通过。
- `openspec validate --specs --strict`：3/3 通过。
- `git diff --check`：通过。

测试运行仅有 FastAPI/Starlette 与当前 httpx 组合产生的弃用警告，不影响结果，也未由本
change 修改依赖版本。
