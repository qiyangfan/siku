# 任务清单

验证一律用 `env -u DASHSCOPE_API_KEY -u NO_PROXY -u no_proxy uv run ...`（NO_PROXY 的
`[::1]` 会让 httpx 假红，见 design.md D6）。

## 1. 拆热点函数（先做）

- [x] 1.1 `retrieve/indexer.py::sync_index`（22/91）：拆出复用、写入、版本、元数据、
  原子切换助手——验证：`ruff --select C901,PLR0912,PLR0915` 清零 + tests/test_retrieve_sync.py 全绿。
- [x] 1.2 `cli` 的 `evaluate_retrieval`（16/76）与 `scan`（11）：拆出评测执行/对比/输出
  与扫描收尾助手——验证：tests/test_retrieve_cli.py tests/test_cli.py 全绿。
- [x] 1.3 `ingest/pipeline.py::ingest_path`（15/59）、`sync/scanner.py::plan_source`（14）、
  `sync/service.py::_run_plan`（12）——验证：对应测试全绿。
- [x] 1.4 `retrieve/evaluation.py::load_golden_set`（14）、`entity_join.py::plan_join`（11）、
  `reduction.py::stage_index_reduction`（11/60）——验证：对应测试全绿。
- [x] 1.5 `graph/providers.py::_extract_content`（12）、`retrieve/notes_reader.py::_parse_frontmatter`（11）、
  `api/settings.py::map_probe_error`（12）——验证：对应测试全绿 + 旧/新差分零差异。
- [x] 1.6 `api/library.py::build_library_view`（16）、`api/messages.py::map_domain_error`（46）
  与同文件两处 return 超限、`scripts/smoke_clean_env.py` 两处语句超限、两个测试文件热点
  ——验证：`ruff --select C901,PLR0912,PLR0915 .` 清零；map_domain_error 逐异常等价。

## 2. 拆超长模块

- [x] 2.1 `cli.py` → `siku/cli/` 包（app/core/commands/* + `__main__.py`），`siku.cli:app`
  与 `python -m siku.cli` 入口不变；测试 monkeypatch 目标同步——验证：全量 887 passed、
  与 HEAD 失败集合一致、每文件 <1000 行。
- [x] 2.2 `api/app.py` → `api/routes_library.py` + `api/routes_graph_wiki.py` + `api/http_help.py`，
  注册函数按路由组拆分、注册顺序按 HEAD 恢复——验证：api 测试全绿、OpenAPI 快照无漂移、
  app.py 702 行、复杂度清零。
- [x] 2.3 tests 纳入体积门禁：`test_api_settings.py`(1081 行) 拆出
  `test_api_settings_probe.py`，共享常量/fixture 抽到 `settings_helpers.py` 与
  `tests/conftest.py`；`TestGetSettings`(21 公有方法) 拆出 `TestLlmEnvFallback`
  ——验证：pylint 扫描 `src/siku tests scripts benchmarks` 0 命中、设置测试 62 passed。

## 3. 开闸（默认参数，零豁免）

- [x] 3.1 `pyproject.toml`：ruff select 增加 `C901`/`PLR0912`/`PLR0915`；dev 依赖增加
  `pylint`、`import-linter`；`[tool.importlinter]` 写入三条 forbidden 契约
  ——验证：`ruff check .` 0、pylint 10.00/10、`lint-imports` 3 kept。
- [x] 3.2 `ci.yml` 测试 job 3.12 桶追加 pylint + lint-imports（阻断），pylint 扫描面
  `src/siku tests scripts benchmarks`——验证：actionlint 通过。
- [x] 3.3 ruff select 追加 `PERF`/`RET`/`TID`/`ICN`/`PLR0402`（全部默认参数）并修掉
  5 处命中（`routes_library`/`wiki/render`/`test_api_reading` 的 append 循环、`community`
  多余赋值、`vector_store` pyarrow 别名）——验证：`ruff check .` 0。

- [x] 3.4 pylint 追加 `too-many-return-statements`(6) 与 `too-many-instance-attributes`(7)：
  修掉 2 处返回数、8 处属性数（报告/任务/计划/检索模型按语义分组）；`api/library.py`
  的只读清单拆到 `api/library_view.py`——验证：pylint 四条规则全库 0、全量 887 passed。
  参数/局部变量三条不启用，理由与实测见 design.md D1b。

## 4. 负向验收（逐类）

- [x] 4.1 植入复杂度 11 的函数：ruff 退出 1（`C901 (11 > 10)`），移除后回 0。
- [x] 4.2 临时生成 1009 行模块：pylint 退出 16（`C0302 (1009/1000)`），移除后回 0。
- [x] 4.3 在 `siku/extractors/` 植入 `from siku.api...`：`lint-imports` 退出 1（1 broken），
  移除后 `3 kept, 0 broken`。
- [x] 4.4 临时探针同时植入 PERF401/RET504/ICN001/TID252/PLR0402 五种违规：ruff 退出 1
  （逐条命中），移除后回 0。
- [x] 4.5 临时探针植入 7 个 return 的函数与 8 个实例属性的类：pylint 退出 8
  （`R0911 (7/6)`、`R0902 (8/7)`），移除后 10.00/10、退出 0。

## 5. 收尾

- [x] 5.1 `openspec validate 2026-11-19-add-python-quality-gates --strict` 通过。
- [x] 5.2 `docs/HANDOFF.md` 整体重写：本批状态、push/billing 结论、秘密扫描保留结论、遗留。
- [ ] 5.3 提交/推送按用户逐次授权；CI 全绿后再归档（账号级 Actions 锁定未解除）。

## Workflow follow-up

- Archive this change after merge and record the gate matrix in `docs/HANDOFF.md`.
