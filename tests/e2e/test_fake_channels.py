"""fake 三通道端点协议形状自检：不经 serve 进程，httpx 直打，快速定位协议漂移。

路径与形状对齐 `retrieve/api_providers.py` / `graph/providers.py` 的真实消费契约
（base_url 含 /v1，适配器追加 /embeddings、/rerank、/chat/completions；
响应取 data[index+embedding]、results[index+relevance_score]、
choices[0].message.content，并按三消费方 system prompt 分流）。
"""

from __future__ import annotations

import json

import httpx
import pytest
from conftest import SEED_MARKER
from fake_channels import (
    CANNED_EXTRACTION,
    EMBEDDING_DIMENSIONS,
    WIKI_SUMMARY,
    FakeChannelServer,
)

pytestmark = pytest.mark.e2e


def test_channel_protocol_shapes() -> None:
    server = FakeChannelServer(seed_marker=SEED_MARKER)
    server.start()
    try:
        base = server.base_url

        # embeddings：openai 兼容 data[index+embedding]，维度恒定且同文本恒同向量。
        body = httpx.post(
            f"{base}/embeddings", json={"model": "fake-embed", "input": ["甲文本", "乙文本"]}
        )
        assert body.status_code == 200, "embeddings 端点不可达"
        data = body.json()["data"]
        assert [row["index"] for row in data] == [0, 1], "embeddings 索引形状漂移"
        assert all(len(row["embedding"]) == EMBEDDING_DIMENSIONS for row in data), (
            "embeddings 维度与声明不符"
        )
        again = httpx.post(
            f"{base}/embeddings", json={"model": "fake-embed", "input": ["甲文本"]}
        ).json()
        assert again["data"][0]["embedding"] == data[0]["embedding"], "同文本向量不恒定"

        # rerank：results 全量按 index 对齐，相关性分对种子文本更高。
        rerank = httpx.post(
            f"{base}/rerank",
            json={
                "model": "fake-rerank",
                "query": "灵晶脉",
                "documents": ["墨丘山的灵晶脉", "完全无关的文本"],
                "top_n": 2,
            },
        )
        assert rerank.status_code == 200, "rerank 端点不可达"
        results = rerank.json()["results"]
        assert sorted(row["index"] for row in results) == [0, 1], "rerank 索引形状漂移"
        assert results[0]["relevance_score"] > results[1]["relevance_score"], (
            "rerank 相关性打分方向颠倒"
        )

        # chat 分流：图谱抽取罐头 / wiki 摘要 / ask 上下文回显；未知 prompt 响亮失败。
        extraction = _chat(base, "你是知识图谱抽取引擎。只输出 JSON。", "请从文本中抽取")
        assert json.loads(extraction) == CANNED_EXTRACTION, "图谱抽取罐头形状漂移"

        summary = _chat(base, "你是知识百科的编辑。", "请摘要")
        assert summary.strip() == WIKI_SUMMARY, "wiki 摘要罐头漂移"

        packed = f"问题：测试\n\n检索片段：\n[C1]\ntext: {SEED_MARKER}"
        ask = json.loads(_chat(base, "你是 siku 的本地知识库问答器。", packed))
        assert ask["insufficient_evidence"] is False, "ask 罐头证据判定漂移"
        assert ask["citation_ids"] == ["C1"], "ask 引用抽取漂移"
        assert SEED_MARKER in ask["answer"], "ask 未回显种子标记"

        unknown = httpx.post(
            f"{base}/chat/completions",
            json={
                "messages": [
                    {"role": "system", "content": "未知角色"},
                    {"role": "user", "content": "x"},
                ]
            },
        )
        assert unknown.status_code == 500, "未识别 prompt 未响亮失败"
    finally:
        server.stop()


def _chat(base: str, system: str, user: str) -> str:
    response = httpx.post(
        f"{base}/chat/completions",
        json={
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        },
    )
    assert response.status_code == 200, f"chat 端点不可达（{response.text[:200]}）"
    content = response.json()["choices"][0]["message"]["content"]
    assert isinstance(content, str) and content.strip(), "chat 补全内容为空"
    return content
