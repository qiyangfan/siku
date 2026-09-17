"""本地模型适配器的惰性维度解析测试（不打真实模型）。

非默认模型的 dimensions 在首次访问时通过加载模型解析；若运行时缺失则必须
抛 ModelNotAvailableError（带安装指引），而不是让 0 维 schema 穿透为
lance 的非领域 RuntimeError。
"""

from __future__ import annotations

import sys
import types

import pytest

from siku.retrieve.errors import ModelNotAvailableError, ProviderError
from siku.retrieve.local_models import BGE_M3_DIMENSIONS, LocalEmbeddingProvider


def _install_fake_sentence_transformers(monkeypatch: pytest.MonkeyPatch, dims: int) -> None:
    class FakeModel:
        def get_sentence_embedding_dimension(self) -> int:
            return dims

        def encode(self, texts: list[str], **kwargs: object) -> list[list[float]]:
            return [[0.0] * dims for _ in texts]

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = lambda *args, **kwargs: FakeModel()  # type: ignore[attr-defined]
    fake_module.CrossEncoder = lambda *args, **kwargs: object()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)


def test_default_model_dimensions_from_model_card() -> None:
    provider = LocalEmbeddingProvider()
    assert provider.dimensions == BGE_M3_DIMENSIONS


def test_non_default_model_resolves_dimensions_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_sentence_transformers(monkeypatch, dims=512)
    provider = LocalEmbeddingProvider(model_id="custom/my-model")
    assert provider.dimensions == 512
    # 解析结果被缓存：后续访问不再触发加载
    assert provider.dimensions == 512


def test_missing_runtime_gives_install_hint_on_dimensions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    provider = LocalEmbeddingProvider(model_id="custom/my-model")
    with pytest.raises(ModelNotAvailableError) as excinfo:
        _ = provider.dimensions
    assert "--extra retrieval" in str(excinfo.value)


def test_modern_runtime_without_legacy_api_falls_back_to_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ModernModel:
        def encode(self, texts: list[str], **kwargs: object) -> list[list[float]]:
            return [[0.0] * 768 for _ in texts]

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = lambda *args, **kwargs: ModernModel()  # type: ignore[attr-defined]
    fake_module.CrossEncoder = lambda *args, **kwargs: object()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    provider = LocalEmbeddingProvider(model_id="custom/modern")
    assert provider.dimensions == 768


def test_legacy_dimension_api_none_falls_back_to_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    class DynamicModel:
        def get_sentence_embedding_dimension(self) -> int | None:
            return None

        def encode(self, texts: list[str], **kwargs: object) -> list[list[float]]:
            return [[0.0] * 384 for _ in texts]

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = lambda *args, **kwargs: DynamicModel()  # type: ignore[attr-defined]
    fake_module.CrossEncoder = lambda *args, **kwargs: object()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    provider = LocalEmbeddingProvider(model_id="custom/dynamic")
    assert provider.dimensions == 384


def test_dimension_resolution_failure_becomes_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenModel:
        def get_sentence_embedding_dimension(self) -> int:
            raise RuntimeError("model exploded")

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = lambda *args, **kwargs: BrokenModel()  # type: ignore[attr-defined]
    fake_module.CrossEncoder = lambda *args, **kwargs: object()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    provider = LocalEmbeddingProvider(model_id="custom/broken")
    with pytest.raises(ProviderError):
        _ = provider.dimensions
