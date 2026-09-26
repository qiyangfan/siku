# 任务清单

## 约束冻结（实现前）

- [x] 冻结回退语义：仅 llm 通道、四字段全空才回退、key 与端点/模型绑定、
      `qwen-max` 选型。（决议见 design.md 决议 #1）
- [x] 冻结契约增量：`llm_env_fallback` 可选字段 + OpenAPI 快照再生成 +
      前端 fail-open。（决议见 design.md 决议 #2）
- [x] 冻结预设边界：UI 静态表、官方精选 + Ollama、不自动保存。（决议见
      design.md 决议 #3）
- [x] 冻结导入区形态：原生 input + 拖拽、不新增依赖、选完即传。（决议见
      design.md 决议 #4）
- [x] 冻结危险分级：purge 危险配色 + 确认保留；rebuild 中性 + 确认保留；
      移除来源登记不加确认。（决议见 design.md 决议 #5）
- [x] 冻结就绪提示：信息层不门控、fail-open。（决议见 design.md 决议 #6）

## 内核（src/siku）

- [x] `model_supply.py`：`DASHSCOPE_*` 常量、`llm_env_fallback_channel()`
      公开判定（含 CLI 层）、`resolve_llm_channel` 接入回退。
- [x] `api/models.py`：`LlmEnvFallbackView` + `SettingsResponse.llm_env_fallback`。
- [x] `api/settings.py`：`masked_view` 渲染回退字段；`api/app.py` 两个 settings
      端点传入运行期判定（含 `llm_supply`）。
- [x] `contracts/openapi.json` 按新模型再生成。
- [x] pytest：回退生效/显式配置不回退/环境缺失保持缺省/embedding 不回退；
      settings 响应字段；相关用例 `monkeypatch.delenv` 隔离外部环境。

## UI（ui/src）

- [x] `api.ts`：`LlmEnvFallback` 类型 + `SettingsResponse` 增字段（fail-open）。
- [x] `SettingsView.tsx`：厂商预设 Select（按通道可用名单）+ 填充逻辑；
      LLM 回退 Alert；预设相关 vitest。
- [x] `LibraryView.tsx`：导入投放区（点击 + 键盘 + 拖拽，立即摄取）；「清理
      失效文档」更名 + `.button-danger` + 常显 tooltip + 弹窗文案与确认键
      同步；徽标 title 释义；空态引导与结果文案同步；vitest 更新。
- [x] `styles.css`：`.library-dropzone` 系（含 dragover 高亮、窄屏）、
      `.button-danger` / `.button-danger-solid`，移除废弃类。
- [x] `GraphView.tsx` / `WikiView.tsx`：空态就绪提示 + 「去设置」（新 prop）；
      `App.tsx` 传入视图切换；vitest 补提示两态与 fail-open。

## 交付门禁

- [x] `uv run ruff check .` / `uv run ruff format --check .` 全绿。
- [x] `uv run pytest -DskipTests=false` 全绿（见 AGENTS：`-DskipTests=false`
      为 Java 口径，本仓直接 `uv run pytest`）。
- [x] `npm run lint` / `npm run test` / `npm run build` 全绿。
- [x] `openspec validate --changes --strict` 通过。
- [x] UI 闸门 B（7 类缺陷）走查通过并留验收报告。
