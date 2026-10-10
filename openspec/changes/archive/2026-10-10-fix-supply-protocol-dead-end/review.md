# 评审记录：fix-supply-protocol-dead-end

## 实现范围

待裁项收口（归档件 `2026-10-01-settings-error-cause-codes` 末项，owner 2026-10-10
授权本轮定案）：`ask_readiness` 协议越界转数据（`invalid` token 集，判定与请求期
同一解析函数同源）；`GET /api/settings` 文件层可读时恒 200；`PUT` 落盘成功返回 200
成功形状；`siku serve` 对上层协议越界容忍启动（与坏文件收敛为同一规则：供给配置
错误不堵启动面）；请求面（ask/probe/CLI 一次性）503 `invalid_settings` 零漂移；
设置页 invalid 警示条（不提供保存可修入口）。顺带完成 5 处主规格超长 Requirement
正文收敛（4 处本就在本件 delta 内，1 处纯文本随行），恢复 `--specs --strict` 全绿。

## 验证证据（2026-10-10，本机）

- 全量 pytest **834 通过**（上批 830 + 本件净增 4），ruff check 与 format 双清；
  ui vitest **131 通过**（+3）、`npm run build`（含 tsc -b）绿、eslint 绿。
- `openspec validate --changes --strict` 通过；归档后 `--specs --strict` **9/9 全绿**
  （五条正文 473–499，按 openspec 逐行 trim 语义实测）。
- 契约快照再生成：diff 仅 `AskReadinessView.invalid`（`default_factory=list` 不产
  default、不入 required），快照漂移测试通过。
- 真机冒烟（临时 HOME + `SIKU_LLM_PROTOCOL=totally-bogus-protocol`，serve :8211）：
  serve 启动成功，stderr 告警点名 `SIKU_LLM_PROTOCOL`，横幅 `llm=invalid`；
  `/api/health` 200；`GET /api/settings` **200** + `invalid=["llm.protocol"]`
  （原死路 1 收口）；`PUT /api/settings` **200** 成功形状（原死路 2 收口）；
  `POST /api/ask` **503 invalid_settings**（请求面归一不变）。

## 评审循环

独立子代理评审（A–G 七组，含逐场景名核对与 spec 长度实测）：结论「需修复后合入」，
P0=0、**P1=1**、P2=8。全部修复并复验：

| 级别 | 发现 | 修复 |
|---|---|---|
| P1 | 4/5 需求正文按 openspec 逐行 trim 语义实测 503–599 字符（初版目测估长失准），archive 后 strict 门禁仍红且 tasks/design 声明失实 | 逐条收敛至 473–499 并实测复核 |
| P2 | design 场景计数 9→10、常量名与实现不一致、LlmReadinessHint 判定口径文本失真 | design 三处回写 |
| P2 | `llm=None` 降级时 `api_key_env` 回落忽略显式 `--api-key-env` | 改为 `llm_cli.api_key_env` 优先 |
| P2 | 新增代码 ruff format 飘逸 | `ruff format` 清零并纳入复验 |
| P2 | ask 端点对 env 越界的 503 只有映射级单测 | 补 TestClient e2e（真实解析路径，不注入 fake） |
| P2 | LlmReadinessHint 无效变体无测试 | 新建组件测试 3 例 |

评审「副产物」提示经核实为误报：`benchmarks/baselines/dashscope-text-embedding-v3.json`
是 owner 指令的基线补录产物（同轮执行），保留入库。

## 决策留痕（owner 授权本轮定案）

方案取舍：①「ProtocolConfigError 携带来源层 + 设置页『仅修正协议』控件」被否——控件
写的是被 env 层压制的文件层，是死控件，且保留「文件层容忍/上层 fail-fast」双规则；
采纳②变体并收敛根因：解析结果在判定面是数据（同源不谎报），serve 统一容忍启动，
请求面保持归一失败。旧否决（「200 + 空文件层」）针对的是数据伪造与误就绪；本件视图
不伪造任何值，`invalid` token 由请求期同一解析路径产出。

## 已知边界

- `ask_readiness` 不检查 rerank 通道 protocol（请求期会拒）；三层实际都进不来该字段，
  理论缝隙，既有非本改，不动。
- 场景名「坏文件叠加上层协议越界时归一化失败」按硬规则原样保留（名字中的「失败」
  已与 THEN 的「明示后继续启动」不再字面一致，场景内已注记语义收敛）。
- 本地 Ollama 通道基线仍缺（本机 Ollama 不在线），云端 DashScope 通道已补录。

## 上报项

无新增。既有上报项（Windows/Linux 实机冒烟、Phase 6 签名）维持 owner 豁免/缓滞口径。
