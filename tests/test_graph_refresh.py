"""图谱自动维护策略测试：资格闸门决策表、身份比对、预告与失败隔离。

对应 openspec change add-graph-auto-refresh 的 design D1/D3/D4：
自动 = 维护已存在快照；任一前提不满足即跳过（稳定码 + 中文文案）；
执行体与显式更新同一入口；刷新失败由调用方兜底，旧快照保持可读。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from graph_fakes import FakeGraphExtractor
from siku.graph.errors import LlmRateLimitError
from siku.graph.models import EntityMention, GraphExtraction, GraphExtractor
from siku.graph.refresh import (
    full_reextract_warning,
    graph_snapshot_exists,
    identity_matches,
    maybe_refresh_graph,
    read_build_identity,
)
from siku.graph.service import build_graph
from siku.graph.store import cache_file_path, graph_file_paths, load_graph
from siku.retrieve.errors import ModelNotAvailableError
from siku.retrieve.models import ChunkRecord

FIRST_NOTE_BODY = "## 段1\n\n张三在北京。\n\n## 段2\n\n李四在上海。\n"
SECOND_NOTE_BODY = "## 段1\n\n王五在广州。\n"


def _extraction_for(chunk: ChunkRecord) -> GraphExtraction:
    """任意合法抽取：供计数与产物落盘使用，不参与实体断言。"""
    return GraphExtraction(
        entities=(EntityMention(name=chunk.text[3:5], type="人物", evidence=chunk.text[:6]),),
        relations=(),
    )


def write_note(vault: Path, *, source_id: str, source_hash: str, body: str) -> None:
    note = vault / "notes" / f"note--{source_id}.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\n"
        'title: "测试文档"\n'
        f'source_hash: "{source_hash}"\n'
        'source_name: "test.md"\n'
        f'source_id: "{source_id}"\n'
        'extractor: "MdExtractor"\n'
        "---\n"
        "# 测试文档\n\n" + body,
        encoding="utf-8",
    )


def default_extractor(**overrides: object) -> FakeGraphExtractor:
    fields = {
        "extractor_id": "llm-graph",
        "model_id": "m1",
        "prompt_version": "v1",
        "respond": _extraction_for,
    }
    fields.update(overrides)
    return FakeGraphExtractor(**fields)  # type: ignore[arg-type]


def _prepare(tmp_path: Path, scenario: str) -> tuple[Path, Path]:
    """按场景准备 vault/data_dir；返回 (vault, data_dir)。"""
    vault = tmp_path / "vault"
    data_dir = tmp_path / "data"
    write_note(vault, source_id="a" * 12, source_hash="a" * 64, body=FIRST_NOTE_BODY)
    if scenario != "absent":
        build_graph(vault, data_dir, default_extractor())
    if scenario == "unknown":
        # 升级路径：删缓存库（含身份记录）但保留 parquet 快照
        cache_file_path(data_dir).unlink()
    return vault, data_dir


@pytest.mark.parametrize(
    ("scenario", "enabled", "expected_code", "factory_called"),
    [
        ("built", False, "disabled", False),
        ("absent", True, "graph_missing", False),
        ("changed", True, "identity_changed", True),
        ("unknown", True, "identity_unknown", True),
        ("channel_down", True, "channel_unavailable", True),
        ("ready", True, "refreshed", True),
    ],
)
def test_maybe_refresh_graph_decision_table(
    tmp_path: Path,
    scenario: str,
    enabled: bool,
    expected_code: str,
    factory_called: bool,
) -> None:
    vault, data_dir = _prepare(tmp_path, scenario)
    calls: list[str] = []

    def factory() -> GraphExtractor:
        calls.append("factory")
        if scenario == "channel_down":
            raise ModelNotAvailableError("fake: llm channel not configured")
        if scenario == "changed":
            return default_extractor(model_id="switched-model")
        return default_extractor()

    outcome = maybe_refresh_graph(
        vault=vault,
        data_dir=data_dir,
        extractor_factory=factory,
        auto_refresh_enabled=enabled,
    )

    assert outcome.code == expected_code
    assert outcome.refreshed is (expected_code == "refreshed")
    assert bool(calls) is factory_called
    if expected_code in ("identity_changed", "identity_unknown", "channel_unavailable"):
        assert outcome.message is not None
        assert "跳过" in outcome.message
    if expected_code == "disabled":
        assert outcome.message is None


def test_refresh_hits_cache_when_corpus_unchanged(tmp_path: Path) -> None:
    vault, data_dir = _prepare(tmp_path, "ready")
    outcome = maybe_refresh_graph(
        vault=vault,
        data_dir=data_dir,
        extractor_factory=lambda: default_extractor(),
        auto_refresh_enabled=True,
    )
    assert outcome.refreshed is True
    assert outcome.llm_calls == 0
    assert outcome.cache_hits == 2
    assert outcome.message is not None
    assert "新增抽取 0 块" in outcome.message
    # 身份记录仍在（成功后重写同值）
    recorded = read_build_identity(data_dir)
    assert recorded is not None and recorded["model_id"] == "m1"


def test_refresh_extracts_only_new_chunks(tmp_path: Path) -> None:
    vault, data_dir = _prepare(tmp_path, "ready")
    write_note(vault, source_id="b" * 12, source_hash="b" * 64, body=SECOND_NOTE_BODY)
    extractor = default_extractor()
    outcome = maybe_refresh_graph(
        vault=vault,
        data_dir=data_dir,
        extractor_factory=lambda: extractor,
        auto_refresh_enabled=True,
    )
    assert outcome.refreshed is True
    # 仅新文档的 1 个 chunk 走 LLM，旧 2 个 chunk 全命中缓存
    assert outcome.llm_calls == 1
    assert outcome.cache_hits == 2
    assert extractor.calls != []


def test_identity_matches_field_by_field() -> None:
    extractor = default_extractor()
    recorded = {
        "extractor_id": extractor.extractor_id,
        "model_id": extractor.model_id,
        "prompt_version": extractor.prompt_version,
    }
    assert identity_matches(recorded, extractor) is True
    assert identity_matches(None, extractor) is False
    for field, value in (
        ("extractor_id", "other"),
        ("model_id", "other"),
        ("prompt_version", "v2"),
    ):
        changed = dict(recorded)
        changed[field] = value
        assert identity_matches(changed, extractor) is False


def test_full_reextract_warning_only_on_identity_change(tmp_path: Path) -> None:
    vault, data_dir = _prepare(tmp_path, "ready")
    # 身份一致：无预告
    assert full_reextract_warning(vault, data_dir, default_extractor()) is None
    # 身份变更：预告全量重抽规模（2 个 chunk）
    warning = full_reextract_warning(vault, data_dir, default_extractor(model_id="m2"))
    assert warning is not None
    assert "全量重抽 2 个 chunk" in warning
    assert "LLM 调用" in warning


def test_full_reextract_warning_silent_without_record(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    data_dir = tmp_path / "data"
    write_note(vault, source_id="a" * 12, source_hash="a" * 64, body=FIRST_NOTE_BODY)
    # 首次构建前无身份记录：显式首建的固有成本，不预告
    assert full_reextract_warning(vault, data_dir, default_extractor()) is None


def test_refresh_failure_preserves_old_snapshot_and_identity(tmp_path: Path) -> None:
    vault, data_dir = _prepare(tmp_path, "ready")
    entities_before, _, _ = load_graph(data_dir)
    identity_before = read_build_identity(data_dir)
    write_note(vault, source_id="b" * 12, source_hash="b" * 64, body=SECOND_NOTE_BODY)

    class FailingExtractor(FakeGraphExtractor):
        def extract(self, chunk: ChunkRecord) -> GraphExtraction:
            if "王五" in chunk.text:
                raise LlmRateLimitError("fake: rate limited")
            return super().extract(chunk)

    failing = FailingExtractor(
        extractor_id="llm-graph", model_id="m1", prompt_version="v1", respond=_extraction_for
    )
    with pytest.raises(LlmRateLimitError):
        maybe_refresh_graph(
            vault=vault,
            data_dir=data_dir,
            extractor_factory=lambda: failing,
            auto_refresh_enabled=True,
        )
    # 失败不写半成品：旧快照原样可读，身份记录不回退
    entities_after, _, _ = load_graph(data_dir)
    assert entities_after == entities_before
    assert read_build_identity(data_dir) == identity_before
    assert graph_snapshot_exists(data_dir) is True


def test_graph_snapshot_exists_requires_all_three(tmp_path: Path) -> None:
    data_dir = _prepare(tmp_path, "ready")[1]
    assert graph_snapshot_exists(data_dir) is True
    entities_path, _, _ = graph_file_paths(data_dir)
    entities_path.unlink()
    assert graph_snapshot_exists(data_dir) is False
