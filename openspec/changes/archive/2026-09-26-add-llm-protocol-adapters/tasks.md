# 任务清单

## 约束冻结（实现前）

- [x] 冻结协议枚举与缺省（openai-chat / anthropic / openai-responses，缺省零
      漂移）。（决议见 design.md 决议 #1）
- [x] 冻结协议差异收敛点（provider 请求/响应两端；幂等语义三协议一致）。
      （决议见 design.md 决议 #2）
- [x] 冻结自建网关平级口径（不内置/不默认/不强制中转）。（决议见 design.md
      决议 #3，owner 2026-09-26 插话定调）
- [x] 冻结预设组织（厂商 × 协议分支；embedding/rerank 无协议控件）。（决议见
      design.md 决议 #4）
- [x] 冻结不做协议自动探测。（design.md 风险与边界 + proposal Non-goals）

## 内核（src/siku）

- [x] `model_supply.py`：`ChannelValues.protocol`（枚举校验）、env 层
      `SIKU_LLM_PROTOCOL`、embedding/rerank 拒绝非空 protocol。
- [x] `graph/providers.py`：`HttpxLlmProvider` 按协议分发端点/凭证头/请求体/
      响应抽取；超长 hints 并入 anthropic 措辞。
- [x] `cli.py`：`--llm-protocol` 旗标（serve/graph/wiki）并入 CLI 层。
- [x] `api/settings.py` / `api/models.py` / `api/app.py`：视图与提交值携带
      `protocol`、枚举 422、探测按协议发起；openapi.json 再生成。
- [x] pytest：三协议请求/响应形状（MockTransport 五剧本）、分层解析与缺省
      零漂移、embedding 拒绝、非法枚举、settings 契约。

## UI（ui/src）

- [x] `api.ts`：`protocol` 类型与提交字段。
- [x] `SettingsView.tsx`：LLM 通道「接口协议」NativeSelect；预设表带 protocol
      并新增 Anthropic 分支预设；hint 补自建网关平级说明；vitest。
- [x] 既有测试回归与快照同步。

## 交付门禁

- [x] `uv run ruff check .` / `ruff format --check .` 全绿。
- [x] `uv run pytest` 全绿。
- [x] `npm run lint` / `npm run test` / `npm run build` 全绿。
- [x] `openspec validate --changes --strict` 通过。
- [x] UI 闸门 B 走查（增量：协议控件与预设联动）。
