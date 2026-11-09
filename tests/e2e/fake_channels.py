"""CI E2E 的 fake 三通道端点：openai 兼容 chat / embeddings / rerank 全罐头应答。

确定性是入闸前提（change add-ci-e2e-smoke/design.md）：所有响应都是请求内容的纯
函数，无状态、无外呼、无密钥。chat 按 system prompt 特征分流三消费方
（图谱抽取 / wiki 摘要 / grounded ask）——特征串漂移会让端点 500，这正是该层
要抓的跨段契约漂移。ask 从检索上下文回显种子标记：标记出现在答案里 = 检索
上下文确实喂到了 LLM，是接线证明而非内容证明。
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request

# 复用单测既有确定性向量（同文本恒同向量）；测试资产内部复用，不视作跨层私有泄漏。
from tests.fakes import _deterministic_vector

EMBEDDING_DIMENSIONS = 8

# 图谱抽取罐头：固定实体与关系，段 4 按 nodes/edges 精确对账。
CANNED_EXTRACTION = {
    "entities": [
        {"name": "锡库星", "type": "地点", "evidence": "锡库星是种子文档记载的核心地点"},
        {"name": "墨丘山", "type": "地点", "evidence": "锡库星北麓的墨丘山藏有灵晶脉"},
    ],
    "relations": [
        {"source": 0, "target": 1, "type": "包含", "evidence": "锡库星北麓的墨丘山藏有灵晶脉"}
    ],
}

# wiki 摘要罐头：内容无关紧要，非空即可（摘要质量不是本层职责）。
WIKI_SUMMARY = "锡库星是种子文档记载的核心地点，其北麓墨丘山以灵晶脉闻名。"

# system prompt 分流特征（与三消费方的 SYSTEM_PROMPT 锚定）。
_EXTRACT_MARKER = "知识图谱抽取引擎"
_WIKI_MARKER = "知识百科的编辑"
_ASK_MARKER = "本地知识库问答器"

_CITATION_RE = re.compile(r"\[(C\d+)\]")


def _create_app(seed_marker: str) -> FastAPI:
    """构造 fake 端点应用；种子标记由夹具注入，本模块不持有语料常量。"""
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> dict[str, Any]:
        payload = await request.json()
        messages = payload.get("messages") or []
        system = _message_content(messages, "system")
        user = _message_content(messages, "user")
        content = _resolve_chat_content(seed_marker, system, user)
        return {
            "id": "chatcmpl-e2e",
            "object": "chat.completion",
            "model": payload.get("model", "fake-llm"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    @app.post("/v1/embeddings")
    async def embeddings(request: Request) -> dict[str, Any]:
        payload = await request.json()
        raw_input = payload.get("input", "")
        texts = raw_input if isinstance(raw_input, list) else [raw_input]
        data = [
            {
                "index": index,
                # 只按文本内容派生，不区分 model：e2e 单通道单模型，无混用场景。
                "embedding": _deterministic_vector(str(text), EMBEDDING_DIMENSIONS),
            }
            for index, text in enumerate(texts)
        ]
        return {
            "object": "list",
            "model": payload.get("model", "fake-embed"),
            "data": data,
            "usage": {"prompt_tokens": 0, "total_tokens": 0},
        }

    @app.post("/v1/rerank")
    async def rerank(request: Request) -> dict[str, Any]:
        payload = await request.json()
        query = str(payload.get("query", ""))
        documents = [str(doc) for doc in payload.get("documents") or []]
        results = [
            {"index": index, "relevance_score": _bigram_hit_ratio(query, document)}
            for index, document in enumerate(documents)
        ]
        return {"object": "list", "model": payload.get("model", "fake-rerank"), "results": results}

    return app


def _message_content(messages: list[Any], role: str) -> str:
    for message in messages:
        if isinstance(message, dict) and message.get("role") == role:
            content = message.get("content")
            return content if isinstance(content, str) else ""
    return ""


def _resolve_chat_content(seed_marker: str, system: str, user: str) -> str:
    if _EXTRACT_MARKER in system:
        return json.dumps(CANNED_EXTRACTION, ensure_ascii=False)
    if _WIKI_MARKER in system:
        return WIKI_SUMMARY
    if _ASK_MARKER in system:
        return json.dumps(_ask_answer(seed_marker, user), ensure_ascii=False)
    # 未识别的 prompt 形状：宁可响亮失败也不静默糊弄——漂移必须让 e2e 变红。
    raise HTTPException(status_code=500, detail="fake endpoint: unrecognized prompt shape")


def _ask_answer(seed_marker: str, user_content: str) -> dict[str, Any]:
    """从打包上下文取第一个引用 id 并回显种子标记；找不到引用即如实报证据不足。"""
    citation_ids = _CITATION_RE.findall(user_content)
    if not citation_ids:
        return {
            "answer": "上下文里没有任何引用块。",
            "citation_ids": [],
            "insufficient_evidence": True,
        }
    found = seed_marker in user_content
    answer = (
        f"根据检索片段：{seed_marker}——种子事实已从检索上下文原样抵达 LLM。"
        if found
        else "检索上下文未包含种子标记，接线疑似断裂。"
    )
    return {"answer": answer, "citation_ids": [citation_ids[0]], "insufficient_evidence": False}


def _bigram_hit_ratio(query: str, document: str) -> float:
    """查询二元组在文档中的命中比例；确定性且对种子文档给出更高分。"""
    grams = [query[index : index + 2] for index in range(max(len(query) - 1, 0))] or (
        [query] if query else []
    )
    if not grams:
        return 0.0
    return sum(1 for gram in grams if gram in document) / len(grams)


class FakeChannelServer:
    """进程内 uvicorn 线程承载 fake 端点；serve 子进程经 localhost 访问。"""

    def __init__(self, seed_marker: str) -> None:
        self._seed_marker = seed_marker
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.base_url = ""

    def start(self) -> None:
        config = uvicorn.Config(
            _create_app(self._seed_marker),
            host="127.0.0.1",
            port=0,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 10.0
        while self._server is None or not self._server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("fake channel server failed to start within 10s")
            time.sleep(0.05)
        assert self._server.servers, "uvicorn exposed no sockets after startup"
        port = self._server.servers[0].sockets[0].getsockname()[1]
        self.base_url = f"http://127.0.0.1:{int(port)}/v1"

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
