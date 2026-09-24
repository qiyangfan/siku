# 任务清单

## 约束冻结（实现前）

- [x] 冻结就绪判定口径与住址（内核 `model_supply.ask_readiness`，复用三层合并
      与 `resolve_api_key`，rerank 永不阻塞）。（决议见 design.md 决议 #1/#2）
- [x] 冻结契约载体与 missing token 形状（settings GET/PUT 响应新增
      `ask_readiness`；`<channel>.<field>` 稳定 token，OpenAPI 快照刷新）。
      （决议见 design.md 决议 #3）
- [x] 冻结 HTTP 与 CLI 文案分叉边界（`map_ask_error` 新增分支，CLI 不变）。
      （决议见 design.md 决议 #4）
- [x] 冻结 UI 门控语义（置灰 + 引导卡片 + 三个刷新时机 + fail-open）。
      （决议见 design.md 决议 #5）

## 内核（siku.model_supply / siku.api）

- [x] 先写单元测试：全空配置、env 层补齐、文件层齐备、缺单项、rerank 单独配置
      不影响就绪；再实现 `ask_readiness`。
- [x] `api/models.py` 新增 `AskReadinessView` 并挂到 `SettingsResponse`；
      `settings.masked_view` 接入判定（GET/PUT 一处生效）。
- [x] `messages.map_ask_error` 新增 `ModelNotAvailableError` 的 UI 导向分支，
      补映射测试（CLI 文案不变的守护断言）。
- [x] 刷新 `contracts/openapi.json`，契约快照无漂移测试通过。

## UI（ui/src）

- [x] `api.ts` 扩展 `SettingsResponse` 类型与 `AskReadiness` 类型。
- [x] App 问答门控：就绪状态拉取与刷新时机、置灰提交、提示语替换、引导卡片
      （缺失项中文说明 + 去设置）、`submit` 入口二次校验、fail-open。
- [x] SettingsView 增加保存回调，App 以 PUT 响应刷新就绪状态。
- [x] vitest：未就绪置灰与引导、去设置往返恢复、fail-open、保存联动刷新；
      `npm run lint/test/build` 全绿。

## 交付门禁

- [x] pytest 全量、ruff check/format、mypy、pre-commit 全绿；OpenAPI 快照变更
      仅限本 change 声明的 settings 响应字段。
- [x] 手工冒烟（DashScope 真实端点，owner 指定 DASHSCOPE_API_KEY）：env 层补齐
      三通道 → serve 启动 → `GET /api/settings` ready=true → `POST /api/ask`
      真实回答带引用（qwen-plus）；清空 env → ready=false 且 missing 三项、
      ask 返回 503 友好 UI 导向文案。冒烟过程另发现既有缺陷（见 review.md）。
- [x] 完成独立 review.md：判定与请求期解析同源、missing 无凭证泄漏、fail-open
      边界与 rerank 不阻塞的证据。
