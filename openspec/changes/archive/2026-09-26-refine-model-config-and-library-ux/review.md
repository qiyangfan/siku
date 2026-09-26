# 评审记录：refine-model-config-and-library-ux

- **评审方式**：独立子代理逐条溯源（diff + 未跟踪文件全量，规格以本 change
  proposal/design/deltas 为权威），主对话按结论修复后复验。
- **评审时间**：2026-09-26

## 结论

初评「需修复后收口」，下列各项处理后复验全绿，**可收口**。

## 修复项（评审发现 → 处置）

- [P1] `tests/test_graph_cli.py` 缺 `DASHSCOPE_API_KEY` 环境隔离：宿主导出该
  变量时「缺 key 指引」用例会走新回退打真网。已按其它供给测试同口径补
  `monkeypatch.delenv`（4 处）。
- [P2] `styles.css` 死类 `.library-file-input` 未删 → 已删。
- [P2] tasks.md 实现任务未勾选 → 实现与门禁完成后已全部勾选。
- [P2] `cli.py` `--api-key-env` 帮助文本仍写死「最终缺省 SIKU_LLM_API_KEY」
  → 已补回退说明（3 处），旗标语义未动。
- [P2] 导入投放区缺任务期禁用视觉态 → `.library-dropzone[aria-disabled]`
  降透明度 + not-allowed。
- [取舍对齐] applyPreset 现在一律丢弃未保存明文 key（原实现 Ollama 预设保留
  已输入值，与 design 决议 #3「key 留空」字面不符，且存在 A 家临时 key 连同
  B 家端点被保存的风险）。
- [取舍对齐] applySettings（读取/保存成功）后预设下拉重置为「自定义」，不再
  显示与表单不符的陈旧厂商。

## 复核通过项（摘要）

- 回退触发条件与三层显式优先各有专测；`llm_env_fallback` 计入 serve CLI 层，
  「响应说回退 ⇔ 请求走回退」闭环；embedding/rerank 不回退有专测。
- 无凭证泄漏：回退视图与响应、日志均无 key 明文（含测试断言）。
- 前端 fail-open（旧内核无新字段不报错）；就绪提示信息层不门控有断言。
- 契约一致：api.ts ↔ api/models.py ↔ openapi.json 快照一致，防漂移测试兜底。
- 红线：UI↔内核只经 localhost API；危险配色全走 danger 系 token，无裸色值；
  用户面「已标记」文案全量更名（残留命中均为后端内部 docstring）。
- jsdom 拖拽覆盖为 handler 层真实覆盖（`fireEvent.drop` → POST 断言）。

## 门禁证据

- `uv run pytest`：656 passed（含本 change 新增内核/契约用例）。
- `npx vitest run`：10 文件 101 项全绿；`npm run lint` / `npm run build` 通过。
- `uv run ruff check .` / `ruff format --check .`：全绿。
- `openspec validate refine-model-config-and-library-ux --changes --strict`：通过。
