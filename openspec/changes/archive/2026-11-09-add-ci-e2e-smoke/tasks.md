# 任务清单

每批独立验证、独立提交；闸门命令见 design.md 验证策略。

## 批次 A：fake 三通道端点服务

- [x] `tests/e2e/fake_channels.py`：FastAPI + uvicorn 线程服务，绑 ephemeral 端口。
  chat completions 罐头（抽取/wiki 固定 JSON；ask 从 prompt 检索上下文抽种子标记回显）、
  embeddings 确定性向量（复用 `tests/fakes.py` hash 思路）、rerank 固定序。
- [x] 端点自检：pytest 进程内 httpx 直打三端点，协议形状与 ADR-0012 对齐（含错误路径
  之外的正常路径即可，协议容错归单测领地）。—— `tests/e2e/test_fake_channels.py`，
  未识别 prompt 断言 500 响亮失败。

## 批次 B：serve 进程夹具与 marker

- [x] `pyproject.toml` 注册 `e2e` marker + `addopts -m "not e2e"`；确认既有全量
  `python -m pytest` 收集数不变、时长不变。——全量跑 862 passed + 1 deselected。
- [x] `tests/e2e/conftest.py`：serve 子进程夹具——ephemeral 端口、三通道
  `--*-base-url` 注入、`/api/health` 轮询（60s timeout）、teardown 进程组终结
  （失败路径同样不留孤儿）；tmp vault/data 用 `tmp_path`。

## 批次 C：五段编排冒烟

- [x] 种子语料：markdown（种子事实唯一来源）+ 小 PDF，走 `tests/document_fixtures.py`
  既有生成器思路。——`make_text_pdf` 复用。
- [x] `tests/e2e/test_pipeline_smoke.py`：boot → ingest（作业轮询 + 幂等重摄取抽查）→
  search → graph/wiki → ask 五段断言，按 design.md 断言清单逐条落地；每段独立断言、
  失败指明所在段。
- [x] 确定性自检：本地 `python -m pytest -m e2e` 连续 3 次逐字段一致；`python -m pytest`
  全量绿（默认排除生效）。——3 连绿（21.9/23.8/30.2s，仅时长抖动）；五段编排累计
  6 次全绿。

## 批次 D：CI 门禁接线

- [x] `ci.yml` `changes` job 新增 `e2e` 输出（`^src/|^tests/e2e/|^pyproject\.toml$|^uv\.lock$`，
  fail-open）；新增 `e2e` job（ubuntu、Python 3.12 单版本、timeout 15min）。
  ——actionlint + YAML 解析双验；顺带把两处连续重定向收敛为分组单次重定向（新增第三行
  触发 shellcheck SC2129，按其建议修）。
- [ ] CI 首跑修通；两面验证：改动 `src/` 时 e2e job 触发，纯文档改动时被门控跳过。
  ——【待确认】需推送远端触发，本轮未经授权不执行 git push；推送后首跑若红按
  design.md 降级预案处置。

## 批次 E：观察期与收尾

- [x] 人为断线演练：临时改错 fake 端点路径确认 e2e 变红，恢复后回绿（门禁自证）。
  ——打断 `/v1/embeddings` 路径，e2e 精确红在段 2（作业 failed，error=模型端点调用
  失败）；恢复后回绿。
- [x] 首周 flake 观察纪律与降级预案落 review.md；HANDOFF 重写、ROADMAP 勾稽回写准备。
  ——ROADMAP 勾稽回写按纪律在归档时执行，本件未归档，仅做准备。
