"""serve 默认供给装配测试：create_app 无注入工厂时的 BYOK 行为。

默认走真实分层解析与 provider 装配，覆盖未配置指引、装配缓存与 reranker=none 路径。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fakes import FakeEmbeddingProvider, FakeRerankerProvider
from siku.api.app import create_app
from siku.model_supply import ChannelValues
from siku.retrieve.indexer import sync_index

_SUPPLY = ChannelValues(base_url="http://127.0.0.1:11434/v1", model="fake-embed")


def write_note(vault: Path) -> None:
    note = vault / "notes" / "a--aaaaaaaaaaaa.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\n"
        f'source_hash: "{"1" * 64}"\n'
        'source_name: "a.md"\n'
        'source_id: "aaaaaaaaaaaa"\n'
        'extractor: "FakeExtractor"\n'
        "---\n"
        "# a.md\n\n"
        "## content\n\n"
        "检索增强生成与知识图谱说明\n",
        encoding="utf-8",
    )


@dataclass
class _RecordingFakes:
    embedding: FakeEmbeddingProvider
    reranker: FakeRerankerProvider
    embedding_builds: list[int] = field(default_factory=list)
    reranker_builds: list[int] = field(default_factory=list)
    dimension_arg: list[int | None] = field(default_factory=list)


@pytest.fixture()
def supply_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _RecordingFakes:
    """清理环境与 config 指向；替换 provider 构造点并建好可查询索引。"""
    for name in list(os.environ):
        if name.startswith(("SIKU_LLM_", "SIKU_EMBEDDING_", "SIKU_RERANK_")):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "siku.model_supply.config_file_path", lambda: Path("/nonexistent/config.toml")
    )
    fakes = _RecordingFakes(
        embedding=FakeEmbeddingProvider(dimensions=4), reranker=FakeRerankerProvider()
    )

    def fake_build_embedding(
        _channel: object, dimensions: int | None = None
    ) -> FakeEmbeddingProvider:
        fakes.embedding_builds.append(1)
        fakes.dimension_arg.append(dimensions)
        return fakes.embedding

    def fake_build_reranker(_channel: object) -> FakeRerankerProvider:
        fakes.reranker_builds.append(1)
        return fakes.reranker

    monkeypatch.setattr("siku.api.app.build_embedding_provider", fake_build_embedding)
    monkeypatch.setattr("siku.api.app.build_reranker_provider", fake_build_reranker)

    write_note(tmp_path / "vault")
    sync_index(tmp_path / "vault", tmp_path / "data", fakes.embedding)
    return fakes


def test_unconfigured_embedding_returns_actionable_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未配置 embedding 时默认工厂给出指向设置页的指引，不静默降级。"""
    for name in list(os.environ):
        if name.startswith(("SIKU_LLM_", "SIKU_EMBEDDING_", "SIKU_RERANK_")):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "siku.model_supply.config_file_path", lambda: Path("/nonexistent/config.toml")
    )
    client = TestClient(create_app())
    response = client.post("/api/search", json={"query": "检索"})
    assert response.status_code == 503
    payload = response.json()
    assert payload["code"] == "model_not_available"
    assert "设置" in payload["message"]
    assert "config.toml" not in payload["message"]
    assert "--embedding-base-url" not in payload["message"]


def test_default_factory_builds_service_from_supply(
    supply_env: _RecordingFakes, tmp_path: Path
) -> None:
    """默认工厂按供给配置装配 provider，并使用真实索引和 fake 端点。"""
    client = TestClient(create_app(data_dir=tmp_path / "data", embedding_supply=_SUPPLY))
    response = client.post("/api/search", json={"query": "知识图谱"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["results"], "默认装配链路应能返回命中结果"
    assert payload["results"][0]["rerank_score"] == pytest.approx(
        payload["results"][0]["hybrid_score"]
    )


def test_default_factory_is_cached_across_requests(
    supply_env: _RecordingFakes, tmp_path: Path
) -> None:
    """多次请求复用 provider，避免重复创建连接池。"""
    client = TestClient(
        create_app(
            data_dir=tmp_path / "data",
            embedding_supply=_SUPPLY,
            rerank_supply=ChannelValues(base_url="http://127.0.0.1:4000/v1", model="fake-rerank"),
        )
    )
    for _ in range(3):
        assert client.post("/api/search", json={"query": "知识图谱"}).status_code == 200
    assert len(supply_env.embedding_builds) == 1
    assert len(supply_env.reranker_builds) == 1


def test_rerank_channel_absent_falls_back_to_rrf_only(
    supply_env: _RecordingFakes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rerank 通道缺失时默认工厂自动走 reranker=none，不构造 reranker。"""

    def fail_build(_channel: object) -> FakeRerankerProvider:
        raise AssertionError("rerank 通道未配置时不应构造 reranker")

    monkeypatch.setattr("siku.api.app.build_reranker_provider", fail_build)
    client = TestClient(create_app(data_dir=tmp_path / "data", embedding_supply=_SUPPLY))
    response = client.post("/api/search", json={"query": "知识图谱"})
    assert response.status_code == 200


def test_embedding_dimensions_reaches_provider(supply_env: _RecordingFakes, tmp_path: Path) -> None:
    """create_app 的 embedding_dimensions 覆盖透传到 provider 构造。"""
    client = TestClient(
        create_app(data_dir=tmp_path / "data", embedding_supply=_SUPPLY, embedding_dimensions=7)
    )
    assert client.post("/api/search", json={"query": "知识图谱"}).status_code == 200
    assert supply_env.dimension_arg == [7]
