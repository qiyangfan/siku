# 评审记录：add-llm-protocol-adapters

- **评审方式**：独立子代理逐条溯源（对照 proposal/design/deltas），主对话修复后复验。
- **评审时间**：2026-09-26

## 结论

初评「需修复后收口」，下列各项处理后门禁全绿（pytest 677 / vitest 104 /
lint / build / ruff / openspec strict），**可收口**。

## 修复项（评审发现 → 处置）

- [P1] 探测不携带表单协议，违背决议 #5（保存前测 Anthropic 分支必 404 误导）
  → `SettingsTestRequest.protocol` + `resolve_probe_target` 表单协议覆盖
  （枚举校验、仅 llm 通道）+ UI `runTest` 携带表单协议；补两条回归用例。
- [P1] 手改 config.toml 的非法 protocol 使 GET/PUT 设置面 500（GET 的
  masked_view 在 try 外；PUT 先落盘后抛错）→ GET 捕获 `ModelNotAvailableError`
  并给可行动中文指引（503 invalid_settings）；PUT 写入前
  `validate_channel_protocols` 整体校验，越界 422 且不落盘。修复过程中一并
  消除探测 except 块引用未绑定 `protocol` 的 NameError 逃逸，并保住既有
  「损坏 TOML → 503」语义。
- [P1] 预设 hint「均非 Anthropic 分支」与三个分支预设自相矛盾 → 文案改为
  「含 OpenAI 兼容与 Anthropic 分支（联动协议）」。
- [P1] CLI `--llm-protocol` 非法值裸 traceback → 三命令统一 `_fail` 中文指引
  （`_llm_config_error_message`），实测 exit 1 + 中文。
- [P2] 探测失败指引协议感知（anthropic 提示 `/v1/messages` 端点）。
- [P2] 视图 docstring「embedding/rerank 恒 None」过度声明 → 改为如实描述。
- [P2] tasks.md 误写 ask 子命令 → 修正为 serve/graph/wiki。
- [P2] Responses 超长措辞「input is too long」并入 hints。
- [P2] ADR/proposal「Compatiblations」笔误 → Completions。
- [取舍①落地] `{base}/v1/messages` 与 /v1 结尾端点的 foot-gun：协议选择 hint
  明示「base_url 需填分支根地址」，并新增「Anthropic Claude（原生协议）」预设
  给出正确 base 样例。
- [取舍②] 决议 #5 维持「按表单当前协议」，实现已与设计对齐，无需回写。

## 复核通过项（摘要）

- 幂等闸门三协议俱全（temperature=0 / stream=false，均有形状断言）。
- 凭证红线：x-api-key 仅进请求头，错误面只有状态码 + body 前 200 字符。
- 分层合并（toml/env/CLI）、空白归一、缺省零漂移、DashScope 回退恒 openai-chat、
  任一字段（含 protocol）显式即不回退，均有专测。
- 链路无断点：serve→app→factory→provider、graph/wiki CLI、探测全部携带协议。
- 契约三方一致（api.ts ↔ models.py ↔ openapi.json，防漂移测试兜底）。

## 门禁证据

- `uv run pytest`：677 passed；`npx vitest run`：104 passed；lint/build 全绿。
- `uv run ruff check/format`：全绿。
- `openspec validate add-llm-protocol-adapters --changes --strict`：通过。
