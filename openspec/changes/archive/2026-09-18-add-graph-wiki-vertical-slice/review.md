# 评审记录：add-graph-wiki-vertical-slice

- **评审时间**：2026-09-18
- **评审方式**：五轮独立子代理审查（第 1 轮双视角并行，第 2-5 轮逐轮确认收敛，
  要求逐条溯源实证、剔除臆测），主对话交叉核验并修复全部确认缺陷后复跑门禁，
  第 5 轮判定 CLEAN
- **状态**：实现任务 1-14 完成并全部验证；**任务 15 的真实冒烟待用户 BYO key，
  归档在此之前不执行**

## 门禁证据（第 1 轮评审循环修复后终验）

| 门禁 | 结果 |
|---|---|
| `uv run pytest` | 369 passed, 0 failed（新增图谱/wiki 测试 167 个；第 4 轮后复验一致） |
| `uv run ruff check .` | All checks passed |
| `uv run pre-commit run --all-files` | 全部 Passed（权威 format 钩子在内） |
| `uv run mypy` | Success: no issues found in 74 source files |
| `openspec validate --changes --strict` / `--specs --strict` | 全部通过 |
| 幂等闸门一（同语料二次构建零 LLM 调用） | `tests/test_graph_idempotence.py` 空剧本 provider，任何多余调用直接失败 |
| 幂等闸门二（删 parquet+wiki 后重建） | 产物字节级 diff 为空；三轮构建稳定 |
| 检索基线回归（ADR-0006） | 本阶段未触碰检索链路，golden set 门禁不受影响 |

## 第 0 轮（实现期审查）发现与处置

4 项 P1 全部修复并复验：缓存损坏自愈补全、恒真测试重写、摘要缓存键单一事实源、
空语料产出空 wiki；另修复 httpx.Client 泄漏与多项 P2。详见 git 历史。

## 第 1 轮（双视角独立复审）发现与处置

评审 A（正确性/资源/契约）与评审 B（确定性/闸门强度/测试有效性）并行，
合计确认 8 项缺陷，全部修复后复验：

1. **P1 死测试**：`test_empty_graph_writes_index_only` 因此前脚本编辑被嵌进
   `_respond` 函数体，pytest 永不收集（空图谱路径零覆盖）→ 已提取为模块级测试，
   并补 index.md 落盘与空语料占位断言（`TestEmptyGraph`）。
2. **P1 文件级存储损坏裸穿透**：缓存库/parquet 为垃圾字节时用户面直接看到
   `DatabaseError`/`ArrowInvalid` 英文 traceback，违反 spec「错误经领域错误体系
   归一化」→ 新增 `GraphStoreCorruptError`，`ExtractionCache.__init__` 捕
   `sqlite3.Error`、`load_graph` 捕 `ArrowInvalid/OSError` 统一归一，CLI 给出
   「删除 data/graph 自动重建」中文指引（与检索侧 `IndexCorruptError` 同口径）。
3. **P1 摘要缓存键指纹不完整**：指纹只含 entity_id 与关系三元组，但摘要 prompt
   还消费成员展示名/类型（首见序的函数）——语料改版后同 id 不同名/型会错误复用
   陈旧摘要 → 指纹升级为 (entity_id, name, type) 全量覆盖，配套测试锚定。
4. **P1 摘要身份漂移无防护**：wiki 阶段消费 parquet 存储键但从不校验当前摘要器
   身份，换模型时静默复用旧身份摘要 → `generate_wiki` 现算键比对存储键，
   不一致抛 `GraphArtifactsStaleError`，CLI 中文指引重建图谱（显式失效语义，
   同时天然覆盖指纹升级后的旧产物迁移）。
5. **P2 双向同型边不合并**：A→B 与 B→A 同类型在无向图中是同一条边，原实现
   落 2 行、报告边数 1 → 边键按 entity_id 规范化排序合并，关系表行数与报告
   边数、wiki 渲染口径全局一致。
6. **P2 写盘失败临时文件残留**：parquet/index 写失败残留 `.tmp` → 写路径
   try/except 清理后重抛。
7. **P2 wiki 条目目录部分写入窗口**：`write_wiki` 改为条目写入 staging 目录后
   单次 `os.replace` 换装，窗口压缩至单次目录替换（剩余崩溃窗口与 parquet
   三件表同口径，见下「记录在案」）。
8. **P2 确定性闸门对 seed 丢失空转**：现有测试图有唯一最优划分，删掉
   `seed=COMMUNITY_SEED` 仍全绿 → 新增 C6 环形图种子敏感测试（实测无 seed
   300 次出现 4 种划分，固定 seed 后唯一确定划分），seed 丢失即测试失败。
9. **P2 CLI 空语料分支内联 summarizer 不关闭** → 变量接管并在 finally 释放。

评审剔除的臆测（溯源否证，留档）：零宽字符归一化（契约即 NFKC+casefold+空白）、
httpx 解码异常穿透（HTTPError 基类已兜）、louvain 孤立节点崩溃（空图短路+测试）、
缓存键用 chunk_id 属缺陷（chunk_id 内嵌正文，等价且更强，有注释）、跨进程
PYTHONHASHSEED 影响产物字节（4 种 seed 实测一致）、pyarrow 拦截移除不正当
（核心依赖，移除是必需的）。

## 记录在案（非缺陷，明确不处置）

- **跨文件原子性**：三件 parquet 逐文件原子、wiki 条目目录单次换装，但无跨文件
  事务——崩溃窗口理论可新旧混版；`load_graph` 现已校验三件表引用完整性（混版
  显式报损坏），且全部派生物可删除重跑自愈。真实需要时再引入构建标记。
- **历史遗留**：HEAD 上 `ruff format --check .` 对已提交 design.md 的代码块缩进报
  would-reformat（pre-commit 权威钩子通过）。属 change 创建时的既有状态，
  归档提交时顺带处理。

## 第 2 轮（确认评审）发现与处置

第 1 轮 8 项修复全部确认正确、无行为回归。确认评审新发现 6 P2 + 2 P3，
逐项核验后全部处置：

1. **P2 有向谓词展示方向被 id 排序反转**（上轮修复 5 的显示语义副作用，
   实证「张三 居住于 北京」可渲染为「北京 —[居住于]→ 张三」）→ 边去重身份
   仍按规范化端点对，但 `Relation` 的方向与展示字段改存**首见提及方向**
   （顺序稳定 → 结果确定），有向谓词不再被人读出反向事实。
2. **P2 摘要器协议契约与键实现不符**：协议 docstring 承诺身份字段进键，
   实现只透传 model_id（可插拔摘要器换 prompt 版本会静默复用旧缓存）→
   新增 `SummaryIdentity`（summarizer_id/model_id/prompt_version 三元组）
   完整进键，`build_graph`/`generate_wiki` 共用，任一维度变化即换键；
   测试锚定三元维度各自失效。
3. **P2 缓存库 mkdir/connect 在 try 之外**（路径不可写时裸 OperationalError
   穿透）→ `sqlite3.connect` 移入归一化 try 块。
4. **P2 修复 6/7 的失败路径零测试**（清理分支被删仍全绿）→ 新增 3 个写失败
   注入测试（`_write_parquet`/`_atomic_write`/`write_wiki` staging 清理 +
   旧条目不破坏）。
5. **P2 HANDOFF 文档数字过期**（153/355 → 实测 165/367）→ 已同步重写。
6. **P2 弱断言复发**：「失败摘要不入缓存」名义承诺但未查缓存 → 补缓存查询
   断言（失败后 summary 命名空间为空、按存储键逐社区断言 None）。
7. **P3 测试死分支残留**（`if False else` 编辑残渣）→ 重写为直白构造。
8. **P3 `scale_warnings` 未用形参 `node_count`** → 移除并更新调用点。

## 第 3 轮（确认评审）发现与处置

第 2 轮 8 项处置全部验证正确（含实证：展示方向不因 id 排序反转、SummaryIdentity
三维度各自失效、写失败清理分支均有测试钉住、门禁数字与文档精确一致）。确认评审
新发现 3 项，逐项核验后全部处置：

1. **P1 非空总目 index 嵌入条目全文**（链接文本被塞入整篇 Markdown 导致总目
   断裂；根因是 tuple 第二元素被 write_wiki 当正文、render_index 当标题的一物
   两用）→ 彻底拆分：`write_wiki` 改收 (条目文件名 → 全文) 映射，`render_index`
   行改为 (短标题, 文件名, 实体数, 关系数)；新增真实链路回归测试锚定 index 单行
   bullet 且正文只落条目文件。
2. **P2 缓存连接失败时 UnboundLocalError**（上轮 connect 移入 try 后，except
   分支无条件 close 未绑定变量，"路径不可写"场景实际未归一化）→ connection
   预初始化为 None，except 分支判空后关闭。
3. **P3 单行代码围栏不剥离**（```` ```json {...}``` ```` 无换行形态剥不掉语言
   标签）→ `_strip_code_fence` 支持单行形态并剥语言标签，补表驱动用例。

## 第 4 轮（确认评审）发现与处置

第 3 轮 3 项修复全部验证正确（含真实链路与 7 种围栏形态实证、幂等闸门三轮字节
diff、摘要 prompt 跨构建字节一致）。扫尾仅余 2 项 P3，处置：

1. **P3 HANDOFF 数字/轮次滞后**（165/两轮 → 实测 167/三轮）→ 已同步重写。
2. **P3 缓存 mkdir 在归一化 try 之外**（data/graph 被文件占位时 `siku graph`
   裸抛 FileExistsError，同场景 `siku wiki` 已中文归一，口径不一致）→ mkdir
   移入独立归一化分支捕 `OSError`，CliRunner 实证用户面为「图谱派生产物已损坏…
   自动全量重建」中文指引、无 traceback。

## 第 5 轮（收敛判定）：CLEAN

第 4 轮 2 项 P3 处置全部验证正确：mkdir 归一化经 4 场景实证（目录占位/父目录
只读/只读 graph 目录/正常路径回归）均归一为领域错误且无 UnboundLocal 复发可能；
HANDOFF 数字经逐文件收集求和精确核对（167/369）。全量门禁复跑通过、评审全程
零仓库改动。**自本轮起无可检出缺陷，评审循环收敛终止。**

## spec Scenario 覆盖

18 个 Scenario 全部有自动化测试覆盖，本轮补齐空图谱空总目（`TestEmptyGraph`）
与存储损坏/完整性错误路径（`TestCorruptArtifacts` 等）。对应测试文件
`tests/test_graph_*.py`、`tests/test_wiki_*.py`。

## 真实抽取冒烟记录（任务 15，2026-09-18 执行）

- **通道**：DeepSeek 默认 BYO 通道（`api.deepseek.com`，deepseek-chat，temperature=0）。
  **补充（同日）**：用户更换 `QWEN_API_KEY` 后 Qwen 通道复跑通过
  （DashScope 兼容端点，qwen-plus：21 实体/14 关系/8 社区，11 次调用；
  二轮构建与 wiki 零调用全缓存命中，幂等闸门在 Qwen 通道同样成立；
  期间冒烟脚本漏传 summary_identity 被 GraphArtifactsStaleError 正确拦截，
  身份一致性防护在真实场景首次实证有效）。
- **语料**：单文件 3 chunk 中文语料（公司简介 + 技术架构）。
- **调用成本**：抽取 3 次 + 社区摘要 7 次，共 10 次 LLM 调用（deepseek-chat
  计价下成本可忽略）；二轮构建将全缓存命中（0 调用）。
- **质量复核结论（人工）**：抽取实体 21、关系 17、社区 7。实体类型合理
  （人物/组织/地点/技术/概念），17 条关系全部忠实原文且方向正确（创始人、
  任职于、联合创始人、使用、包含、总部位于等），每条携带 chunk/anchor/
  source_hash 完整回链锚点；7 篇社区条目摘要准确（如社区 0000 正确综合
  "李娜-联合创始人-四库科技-2027 发布计划"）。唯一观察项：孤立单实体社区
  （标题"冒烟语料"被抽为实体）的摘要存在模型自由发挥倾向——属模型行为而非
  管线缺陷，单例空关系社区为合法产物，体检报告的社区数指标已暴露该量级。
- **判定**：真实链路（摄取→抽取→缓存→图构建→社区发现→摘要→wiki 渲染）
  全部打通，质量合格，任务 15 闭环。

## 归档前状态（原「待用户完成」一节，已闭环）

任务 15 的真实抽取冒烟（显式命令，不入 CI）需要用户提供 BYO key 并人工复核
实体/关系质量：

```bash
export SIKU_LLM_API_KEY=sk-你的key   # openai 兼容端点，默认 DeepSeek
printf '## page:1\n\n（粘贴一段真实文档片段）\n' > /tmp/smoke-src.md
uv run siku ingest /tmp/smoke-src.md --vault /tmp/smoke-vault
uv run siku graph --vault /tmp/smoke-vault --data-dir /tmp/smoke-data
uv run siku wiki --data-dir /tmp/smoke-data
```

复核要点：实体/关系是否忠实于原文、evidence 是否可回链、记录 LLM 调用次数
（graph `--json` 的 `llm_calls`）与调用成本。完成后勾选 tasks.md 第 15 项，
执行归档（archive + 同步 graph-wiki spec + ROADMAP 勾稽回写）。
