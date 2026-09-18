"""HTTP API 与 CLI 共享契约的测试。"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from fastapi import FastAPI
from typer.testing import CliRunner

from graph_fakes import FakeGraphExtractor
from siku.api.app import create_app
from siku.cli import _install_stdin_watchdog, _run_with_stdin_watchdog, app
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


def test_serve_keeps_legacy_vault_data_and_ui_defaults(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    """旧默认值回归：不传新路径参数时，行为与 Phase 4 完全一致。"""
    captured: dict[str, object] = {}

    def fake_create_app(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("siku.cli.create_app", fake_create_app)  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "siku.cli.uvicorn.run",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    (tmp_path / "ui" / "dist").mkdir(parents=True)

    result = runner.invoke(app, ["serve", "--with-ui"])

    assert result.exit_code == 0
    assert captured["vault"] == Path("vault")
    assert captured["data_dir"] == Path("data")
    assert captured["ui_dir"] == Path("ui") / "dist"


def test_serve_without_ui_keeps_no_mount_default(monkeypatch: object) -> None:
    captured: dict[str, object] = {}

    def fake_create_app(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("siku.cli.create_app", fake_create_app)  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "siku.cli.uvicorn.run",
        lambda *_args, **_kwargs: None,
    )

    result = runner.invoke(app, ["serve"])

    assert result.exit_code == 0
    assert captured["vault"] == Path("vault")
    assert captured["data_dir"] == Path("data")
    assert captured["ui_dir"] is None


def test_serve_accepts_explicit_absolute_paths_for_desktop_sidecar(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    """桌面 sidecar 依赖绝对路径启动，且不受当前工作目录影响。"""
    captured: dict[str, object] = {}
    vault = tmp_path / "vault"
    data_dir = tmp_path / "data"
    ui_dir = tmp_path / "ui" / "dist"
    for directory in (vault, data_dir, ui_dir):
        directory.mkdir(parents=True)

    def fake_create_app(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("siku.cli.create_app", fake_create_app)  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "siku.cli.uvicorn.run",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]

    result = runner.invoke(
        app,
        [
            "serve",
            "--with-ui",
            "--vault",
            str(vault),
            "--data-dir",
            str(data_dir),
            "--ui-dir",
            str(ui_dir),
        ],
    )

    assert result.exit_code == 0
    assert captured["vault"] == vault
    assert captured["data_dir"] == data_dir
    assert captured["ui_dir"] == ui_dir


def test_serve_rejects_ui_dir_without_with_ui(monkeypatch: object, tmp_path: Path) -> None:
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "siku.cli.uvicorn.run",
        lambda *_args, **_kwargs: None,
    )

    result = runner.invoke(app, ["serve", "--ui-dir", str(tmp_path)])

    assert result.exit_code == 1
    assert "--with-ui" in result.output


def test_serve_fails_when_custom_ui_dir_missing(monkeypatch: object, tmp_path: Path) -> None:
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "siku.cli.uvicorn.run",
        lambda *_args, **_kwargs: None,
    )

    result = runner.invoke(app, ["serve", "--with-ui", "--ui-dir", str(tmp_path / "missing")])

    assert result.exit_code == 1
    assert "UI 静态目录不存在" in result.output


def test_serve_watch_stdin_shuts_down_on_eof() -> None:
    """桌面壳孤儿防线：stdin EOF 必须触发受控关停回调。"""
    read_fd, write_fd = os.pipe()
    done = threading.Event()
    with os.fdopen(read_fd, "rb", closefd=True) as reader:
        thread = _install_stdin_watchdog(done.set, stream=reader)
        assert thread is not None
        os.close(write_fd)
        thread.join(timeout=5)

    assert done.is_set()


def test_serve_watch_stdin_ignores_when_stdin_missing(monkeypatch: object) -> None:
    monkeypatch.setattr("sys.stdin", None)  # type: ignore[attr-defined]

    assert _install_stdin_watchdog(lambda: None) is None


def test_serve_watch_stdin_wiring_marks_uvicorn_server_on_eof(
    monkeypatch: object,
) -> None:
    """接线测试：EOF 必须落到 uvicorn Server 的 should_exit，而非仅回调层。"""
    captured: dict[str, object] = {}

    class FakeServer:
        def __init__(self, _config: object) -> None:
            self.should_exit = False

        def run(self) -> None:
            captured["should_exit_after_run"] = self.should_exit

    monkeypatch.setattr("siku.cli.uvicorn.Server", FakeServer)  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "siku.cli.uvicorn.Config",
        lambda application, *, host, port: (application, host, port),
    )

    read_fd, write_fd = os.pipe()
    with os.fdopen(read_fd, "rb", closefd=True) as reader:
        monkeypatch.setattr(  # type: ignore[attr-defined]
            "sys.stdin", type("FakeStdin", (), {"buffer": reader})()
        )
        threading.Thread(target=os.close, args=(write_fd,), name="close-stdin-writer").start()
        _run_with_stdin_watchdog(FastAPI(), host="127.0.0.1", port=8000)

    assert captured["should_exit_after_run"] is True
