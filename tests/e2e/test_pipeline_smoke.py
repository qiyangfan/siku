"""五段接线回归冒烟：boot → ingest → search → graph/wiki → ask，全走真实 serve 进程。

断言边界（change add-ci-e2e-smoke/design.md）：只断「管道通、产物在、答案含种子
标记且引用指向种子文档」；检索/生成质量归 golden set，本文件零越界。
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
from conftest import (
    SEED_MARKER,
    SEED_MD_NAME,
    SEED_MD_TEXT,
    SEED_PDF_NAME,
    SEED_QUERY,
    SEED_QUESTION,
    ServeProcess,
)

pytestmark = pytest.mark.e2e

JOB_POLL_TIMEOUT_SECS = 120.0
MODEL_CALL_TIMEOUT_SECS = 120.0


def test_five_stage_pipeline_wiring(serve: ServeProcess, seed_files: dict[str, Path]) -> None:
    """五段逐段断言；每段独立，失败即指明断在哪段。"""
    base = serve.base_url

    # ---- 段 1 boot：健康面与就绪字段 ----
    health = httpx.get(f"{base}/api/health", timeout=10.0)
    assert health.status_code == 200, "段1 boot：/api/health 不可达"
    assert health.json()["status"] == "ok", "段1 boot：健康面状态异常"

    # ---- 段 2 ingest：上传 → 作业轮询 → 清单与索引状态 ----
    job = _start_ingest(base, seed_files)
    assert job["state"] in ("running", "succeeded"), "段2 ingest：作业未启动即异常"
    finished = _await_job(base, str(job["job_id"]))
    assert finished["state"] == "succeeded", f"段2 ingest：作业未成功（{finished}）"
    assert not finished["failed"], "段2 ingest：存在失败条目"

    sources = _library_sources(base)
    markdown_source = _seed_source(sources, SEED_MD_NAME, "段2 ingest")
    assert markdown_source["ingest_status"] == "ingested", "段2 ingest：markdown 未入库"
    assert markdown_source["index_status"] == "indexed", "段2 ingest：markdown 未入索引"
    assert markdown_source["source_hash"], "段2 ingest：source_hash 缺失"

    # 幂等抽查（红线 2）：同文件重摄取不翻倍、哈希稳定。
    rerun = _await_job(base, str(_start_ingest(base, seed_files)["job_id"]))
    assert rerun["state"] == "succeeded", f"段2 幂等：重摄取作业未成功（{rerun}）"
    rerun_sources = _library_sources(base)
    rerun_markdown = _seed_source(rerun_sources, SEED_MD_NAME, "段2 幂等")
    assert len(rerun_sources) == len(sources), "段2 幂等：来源清单翻倍，幂等契约破裂"
    assert rerun_markdown["source_hash"] == markdown_source["source_hash"], (
        "段2 幂等：同内容 source_hash 漂移"
    )

    # ---- 段 3 search：embedding + rerank 通道接线 ----
    search = httpx.post(
        f"{base}/api/search",
        json={"query": SEED_QUERY, "top_k": 6, "candidate_k": 30},
        timeout=MODEL_CALL_TIMEOUT_SECS,
    )
    assert search.status_code == 200, f"段3 search：检索请求失败（{search.text[:200]}）"
    results = search.json()["results"]
    assert results, "段3 search：检索零命中"
    assert SEED_MD_NAME in {item["source_name"] for item in results}, (
        "段3 search：种子文档未命中（embedding/rerank 接线断裂）"
    )

    # ---- 段 4 graph + wiki：摄取 → LLM 抽取 → parquet → serve 读回 ----
    graph = httpx.post(f"{base}/api/graph", json={"rebuild": True}, timeout=MODEL_CALL_TIMEOUT_SECS)
    assert graph.status_code == 200, f"段4 graph：构建失败（{graph.text[:200]}）"
    graph_body = graph.json()
    assert not graph_body["empty_corpus"], "段4 graph：图谱构建读到空语料"
    assert graph_body["nodes"] >= 2, f"段4 graph：罐头实体未全部成点（{graph_body}）"
    assert graph_body["edges"] >= 1, f"段4 graph：罐头关系未成边（{graph_body}）"
    assert graph_body["communities"] >= 1, f"段4 graph：社区划分缺位（{graph_body}）"
    assert graph_body["llm_calls"] >= 1, "段4 graph：LLM 抽取调用数为 0"
    assert graph_body["extractor"]["id"] == "llm-graph", "段4 graph：抽取器身份漂移"

    wiki = httpx.post(f"{base}/api/wiki", json={}, timeout=MODEL_CALL_TIMEOUT_SECS)
    assert wiki.status_code == 200, f"段4 wiki：生成失败（{wiki.text[:200]}）"
    wiki_body = wiki.json()
    assert not wiki_body["empty_graph"], "段4 wiki：wiki 生成读到空图谱"
    assert wiki_body["entries"] >= 1, f"段4 wiki：零条目（{wiki_body}）"
    assert wiki_body["llm_calls"] >= 1, "段4 wiki：摘要调用数为 0"

    entries = httpx.get(f"{base}/api/wiki/entries", timeout=30.0)
    assert entries.status_code == 200, "段4 wiki：条目清单不可读"
    assert entries.json()["entries"], "段4 wiki：条目清单为空"

    # ---- 段 5 ask：检索 → 上下文 → LLM → 引用全链 ----
    ask = httpx.post(
        f"{base}/api/ask", json={"question": SEED_QUESTION}, timeout=MODEL_CALL_TIMEOUT_SECS
    )
    assert ask.status_code == 200, f"段5 ask：请求失败（{ask.text[:200]}）"
    ask_body = ask.json()
    assert not ask_body["insufficient_evidence"], (
        f"段5 ask：被判定证据不足（检索上下文未抵达 LLM）\n{ask_body}"
    )
    assert SEED_MARKER in ask_body["answer"], (
        f"段5 ask：答案未回显种子标记（上下文回显断裂）\n{ask_body}"
    )
    assert any(citation["source_name"] == SEED_MD_NAME for citation in ask_body["citations"]), (
        f"段5 ask：引用未指向种子文档\n{ask_body}"
    )
    assert ask_body["retrieval"]["result_count"] >= 1, "段5 ask：检索计数为零"


def _start_ingest(base: str, seed_files: dict[str, Path]) -> dict[str, object]:
    """multipart 上传种子语料并启动摄取作业。"""
    files = [
        ("files", (SEED_MD_NAME, SEED_MD_TEXT.encode("utf-8"), "text/markdown")),
        ("files", (SEED_PDF_NAME, seed_files["pdf"].read_bytes(), "application/pdf")),
    ]
    response = httpx.post(f"{base}/api/library/ingest", files=files, timeout=60.0)
    assert response.status_code == 200, f"段2 ingest：上传被拒（{response.text[:200]}）"
    return dict(response.json())


def _await_job(base: str, job_id: str) -> dict[str, object]:
    deadline = time.monotonic() + JOB_POLL_TIMEOUT_SECS
    while time.monotonic() < deadline:
        response = httpx.get(f"{base}/api/library/jobs/{job_id}", timeout=10.0)
        assert response.status_code == 200, f"段2 ingest：作业轮询失败（{response.text[:200]}）"
        snapshot = dict(response.json())
        if snapshot["state"] != "running":
            return snapshot
        time.sleep(0.3)
    raise AssertionError(f"段2 ingest：作业 {job_id} 在 {JOB_POLL_TIMEOUT_SECS}s 内未结束")


def _library_sources(base: str) -> list[dict[str, object]]:
    response = httpx.get(f"{base}/api/library", timeout=30.0)
    assert response.status_code == 200, f"段2 ingest：清单不可读（{response.text[:200]}）"
    return list(response.json()["sources"])


def _seed_source(sources: list[dict[str, object]], name: str, stage: str) -> dict[str, object]:
    for source in sources:
        if source["name"] == name:
            return source
    listed = [source["name"] for source in sources]
    raise AssertionError(f"{stage}：清单里找不到种子文档 {name}（实际：{listed}）")
