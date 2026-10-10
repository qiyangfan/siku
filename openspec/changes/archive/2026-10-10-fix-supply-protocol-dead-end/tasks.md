# 实施任务

每项 ≤ 2h；先写失败测试，再实现对应步骤。验证证据见 review.md。

## 1. 内核

- [x] 1.1 失败测试先行：`SIKU_LLM_PROTOCOL=garbage` 下 `ask_readiness` 不抛、返回
  `invalid=("llm.protocol",)`、`ready=false`；程序层 embedding protocol 非空 →
  `invalid=("embedding.protocol",)`；无越界时 `invalid` 为空、既有 missing 语义零漂移。
- [x] 1.2 实现 `AskReadiness.invalid` 与 ask_readiness 数据化改造（D1），常量预定义。

## 2. HTTP 面

- [x] 2.1 失败测试先行：GET 恒 200（文件层可读时）+ 视图含 invalid；PUT 落盘成功返回
  200 成功形状（含 `invalid_config_file_overwritten`/`warnings` 既有事实）；
  probe 与 `/api/ask` 对同一故障仍 503 `invalid_settings` 同文案；文件层两型 503 语义不变。
- [x] 2.2 实现 `AskReadinessView.invalid` 透传与 serve 容忍分支（D2/D3）：stderr 告警、
  横幅播报 invalid、`api_key_env` 回落、健康检查可达、ask 仍归一 503。
- [x] 2.3 契约快照 `--refresh` 再生成并 diff 审查（新增字段 default/optional）。

## 3. UI

- [x] 3.1 失败测试先行（vitest）：invalid 非空 → 警示条渲染 + 无任何「保存可修」入口；
  LlmReadinessHint 无效变体；invalid 为空不渲染。
- [x] 3.2 实现 api.ts 类型、SettingsView 警示条（token→话术映射）、LlmReadinessHint 适配。

## 4. 规格

- [x] 4.1 三份 MODIFIED delta：五个需求正文 ≤500、场景名全保留、行为场景按 D1–D4 更新。
- [x] 4.2 运行全量 pytest、ruff、ui 四门禁、`openspec validate --changes --strict` 与
  `--specs --strict`（应 9/9）。
- [x] 4.3 真机冒烟：临时 HOME + `SIKU_LLM_PROTOCOL=garbage` 起 serve，逐一复核原三处
  死路（设置页可渲染、保存返回成功形状、sidecar 可达）与请求面 503 归一。
- [x] 4.4 独立评审、review.md、归档件待裁项销号、ROADMAP/HANDOFF 回写、同步主规格并归档。

## 执行注记（评审循环留痕）

- 独立评审结论「需修复后合入」：P1×1（4/5 需求正文按 openspec 的逐行 trim 语义实测
  仍 503–599 字符，初版按目测估长失准）+ P2×8，全部修复后复验：五条正文 473–499；
  api_key_env 降级回落尊重显式 --api-key-env；ruff format 回归清零；补 ask 端点 e2e
  与 LlmReadinessHint 组件测试（3 例）；design 三处文本失真（场景计数、常量名、
  ready 判定口径）回写。
- 评审「副产物」提示有误：`benchmarks/baselines/dashscope-text-embedding-v3.json`
  是 owner 指令下的基线补录产物，非测试副产物，保留入库。
