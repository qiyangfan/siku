"""HTTP API 与 CLI 共享契约的测试。"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from graph_fakes import FakeGraphExtractor
from siku.api.app import create_app
from siku.cli import app
from siku.graph.community import SummaryIdentity
from siku.graph.report import GraphHealthReport
from siku.graph.service import GraphBuildResult
from siku.wiki.service import WikiResult

runner = CliRunner()


def graph_result() -> GraphBuildResult:
    return GraphBuildResult(
        report=GraphHealthReport(
            extractor_id="fake-extractor",
            model_id="custom-model",
            prompt_version="v1",
            chunk_count=1,
            node_count=1,
            edge_count=0,
            community_count=1,
            ambiguous_entity_count=0,
            cache_hits=0,
            llm_calls=1,
            warnings=(),
        ),
        empty_corpus=False,
    )


def test_serve_defaults_to_loopback_and_warns_on_explicit_public_bind(
    monkeypatch: object,
) -> None:
    calls: list[tuple[object, str, int]] = []
    monkeypatch.setattr("siku.cli.create_app", lambda **_kwargs: object())  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "siku.cli.uvicorn.run",
        lambda application, *, host, port: calls.append((application, host, port)),
    )

    default = runner.invoke(app, ["serve", "--port", "8123"])
    assert default.exit_code == 0
    assert calls[-1][1:] == ("127.0.0.1", 8123)

    public = runner.invoke(app, ["serve", "--host", "0.0.0.0"])
    assert public.exit_code == 0
    assert "警告" in public.output
    assert calls[-1][1:] == ("0.0.0.0", 8000)


def test_serve_passes_shared_llm_configuration_to_api(
    monkeypatch: object,
) -> None:
    captured: dict[str, object] = {}

    def fake_create_app(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("siku.cli.create_app", fake_create_app)  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "siku.cli.uvicorn.run",
        lambda *_args, **_kwargs: None,
    )

    result = runner.invoke(
        app,
        [
            "serve",
            "--api-key-env",
            "CUSTOM_KEY",
            "--llm-base-url",
            "http://127.0.0.1:8787/v1",
            "--llm-model",
            "custom-model",
        ],
    )

    assert result.exit_code == 0
    assert captured["api_key_env"] == "CUSTOM_KEY"
    assert captured["llm_base_url"] == "http://127.0.0.1:8787/v1"
    assert captured["llm_model"] == "custom-model"


def test_cli_llm_options_reach_provider_and_summary_identity(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    provider_calls: list[dict[str, str]] = []
    build_calls: list[dict[str, object]] = []

    class FakeProvider:
        def __init__(self, **kwargs: str) -> None:
            provider_calls.append(kwargs)
            self.model_id = kwargs["model_id"]

        def close(self) -> None:
            """测试 provider 的资源释放接口。"""

    extractor = FakeGraphExtractor(model_id="custom-model")
    summarizer = type(
        "FakeSummarizer",
        (),
        {
            "summarizer_id": "llm-community-summary",
            "model_id": "custom-model",
            "prompt_version": "v1",
            "close": lambda self: None,
        },
    )()

    monkeypatch.setattr("siku.cli.HttpxLlmProvider", FakeProvider)  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "siku.cli.LlmGraphExtractor", lambda **_kwargs: extractor
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "siku.cli.CommunitySummarizer", lambda **_kwargs: summarizer
    )

    def build(*_args: object, **kwargs: object) -> GraphBuildResult:
        build_calls.append(kwargs)
        return graph_result()

    monkeypatch.setattr("siku.cli.build_graph", build)  # type: ignore[attr-defined]
    graph = runner.invoke(
        app,
        [
            "graph",
            "--vault",
            str(tmp_path / "vault"),
            "--data-dir",
            str(tmp_path / "data"),
            "--llm-base-url",
            "http://127.0.0.1:8787/v1",
            "--llm-model",
            "muniu-alias",
            "--json",
        ],
    )
    assert graph.exit_code == 0
    assert provider_calls[0]["base_url"] == "http://127.0.0.1:8787/v1"
    assert provider_calls[0]["model_id"] == "muniu-alias"
    summary_identity = build_calls[0]["summary_identity"]
    assert isinstance(summary_identity, SummaryIdentity)
    assert summary_identity.model_id == "muniu-alias"


def test_graph_api_and_cli_json_fields_are_identical(monkeypatch: object, tmp_path: Path) -> None:
    result = graph_result()
    extractor = FakeGraphExtractor(model_id="custom-model")
    monkeypatch.setattr("siku.cli.HttpxLlmProvider", lambda **_kwargs: object())  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "siku.cli.LlmGraphExtractor", lambda **_kwargs: extractor
    )
    monkeypatch.setattr("siku.cli.build_graph", lambda *_args, **_kwargs: result)  # type: ignore[attr-defined]
    cli_result = runner.invoke(app, ["graph", "--json"])
    assert cli_result.exit_code == 0

    api = create_app(
        graph_extractor_factory=lambda: FakeGraphExtractor(model_id="custom-model"),
        graph_builder=lambda *_args, **_kwargs: result,
    )
    from fastapi.testclient import TestClient

    api_result = TestClient(api).post("/api/graph", json={})
    assert api_result.status_code == 200
    assert set(json.loads(cli_result.output)) == set(api_result.json())


def test_wiki_cli_accepts_llm_options(monkeypatch: object, tmp_path: Path) -> None:
    provider_calls: list[dict[str, str]] = []

    class FakeProvider:
        def __init__(self, **kwargs: str) -> None:
            provider_calls.append(kwargs)
            self.model_id = kwargs["model_id"]

        def close(self) -> None:
            """测试 provider 的资源释放接口。"""

    summarizer = type(
        "FakeSummarizer",
        (),
        {
            "summarizer_id": "llm-community-summary",
            "model_id": "custom-model",
            "prompt_version": "v1",
            "close": lambda self: None,
        },
    )()
    monkeypatch.setattr("siku.cli.HttpxLlmProvider", FakeProvider)  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "siku.cli.CommunitySummarizer", lambda **_kwargs: summarizer
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "siku.cli.generate_wiki", lambda *_args: WikiResult(0, 0, 0, True)
    )
    result = runner.invoke(
        app,
        [
            "wiki",
            "--data-dir",
            str(tmp_path / "data"),
            "--llm-base-url",
            "http://127.0.0.1:8787/v1",
            "--llm-model",
            "muniu-alias",
            "--json",
        ],
    )
    assert result.exit_code == 0
    assert provider_calls[0] == {
        "base_url": "http://127.0.0.1:8787/v1",
        "model_id": "muniu-alias",
        "api_key_env": "SIKU_LLM_API_KEY",
    }
