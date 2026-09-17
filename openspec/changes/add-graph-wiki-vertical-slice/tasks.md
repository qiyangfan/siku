# 任务清单

- [ ] 先写图谱领域模型与 `GraphExtractor` 协议的失败测试，再实现 `graph` 包的
      EntityMention/RelationMention/GraphExtraction 类型与协议；任务粒度 ≤ 2 小时。
- [ ] 先写 LLM provider 五剧本（正常/超长输入/空返回/限流/断连）的 fake 测试，再实现
      provider 协议、openai 兼容通道（httpx）与 BYO key 配置校验；缺 key 报中文指引。
- [ ] 先写抽取输出解析的表驱动测试（合法/非 JSON/缺字段/关系引用越界/空抽取），再实现
      LLM 输出到 `GraphExtraction` 的解析器与 `GraphExtractionError`。
- [ ] 先写默认 `LlmGraphExtractor` 的 prompt 组装与 chunk 映射测试，再实现抽取器主体；
      `extractor_id` 与 `prompt_version` 进入缓存键。
- [ ] 先写抽取缓存的命中/未命中/键变化失效测试（键 = sha256(chunk_hash+抽取器+模型+
      prompt 版本)），再实现 `data/graph/cache.sqlite3` 缓存层（WAL + 参数化 SQL）。
- [ ] 先写 mention 归一化合并与关系去重的测试（NFKC/大小写/空白折叠、同名实体计数），
      再实现实体合并与边构建。
- [ ] 先写 parquet 往返（entities/relations/communities 写读一致、字段稳定）的测试，
      再实现图谱落盘与加载。
- [ ] 先写社区发现确定性（固定 seed、重复执行划分一致）与空图谱边界测试，再实现
      NetworkX 内存图组装与 louvain 社区发现。
- [ ] 先写体检报告字段与量级告警的测试，再实现报告生成（节点/边/社区/同名实体/
      缓存命中/LLM 调用次数）。
- [ ] 先写社区摘要缓存的失败剧本测试（摘要失败不得落空摘要），再实现社区摘要管线
      （复用抽取缓存机制，独立 prompt 版本键）。
- [ ] 先写 wiki 条目与 index 渲染的确定性测试（无时间戳等非稳定字段、锚点回链完整），
      再实现 `wiki` 包的条目生成与 `data/wiki/` 写入（原子写）。
- [ ] 先写 `siku graph` / `siku wiki` 的 CLI runner 测试（人类/JSON 输出、缺 key、
      图谱缺失、空语料、`--rebuild` 错误路径），再接入 CLI。
- [ ] 先写幂等闸门测试（同语料二次构建 LLM 调用为 0；删本体重建 diff 为空），作为
      Phase 3 闸门的自动化证据。
- [ ] pyproject 声明 graph 包依赖（networkx、pyarrow 显式化；LLM 通道仅 httpx），验证
      核心安装不新增重依赖、不引入 server 形态组件。
- [ ] 用 BYO key 在小语料上执行一次真实抽取冒烟（不入 CI），人工复核实体/关系质量并
      记录调用成本；随后跑 `uv run pytest`、`uv run ruff check .`、
      `uv run ruff format --check .`、`uv run mypy`、`uv run pre-commit run --all-files`
      与 OpenSpec strict 校验，完成独立 review.md 后才允许归档并同步 graph-wiki spec。
