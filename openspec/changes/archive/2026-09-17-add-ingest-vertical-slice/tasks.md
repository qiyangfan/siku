# 任务清单

- [x] 先写领域模型、Extractor 协议、格式注册表与协议单测。
- [x] 先写 Markdown 投影、vault 布局、source_hash 幂等测试，再实现摄取流水线。
- [x] 先写 PDF/Word/PPT/Excel 适配器的依赖隔离与锚点测试，再实现四类适配器；补齐 EPUB/HTML/Markdown 顺手格式。
- [x] 增加 `siku ingest` CLI，覆盖单文件、目录、未知扩展名与失败退出行为。
- [x] 完成四类真实原件的最小手工冒烟，确认各自产生投影与锚点；记录依赖缺失时的明确阻塞。
- [x] 运行 pytest、ruff、mypy、pre-commit 与 OpenSpec strict 校验，完成本轮代码审查证据。
- [x] 归档 change，sync spec delta，并回写 ROADMAP 与 HANDOFF 的当前状态。
