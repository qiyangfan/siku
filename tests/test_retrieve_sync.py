"""索引同步编排测试：跳过/替换/清理/重建失败保旧/凭证校验/临时产物清理。"""

from pathlib import Path

import pytest

from fakes import FakeEmbeddingProvider
from siku.retrieve.errors import (
    IndexCorruptError,
    ModelConfigMismatchError,
    NoteParseError,
    ProviderError,
)
from siku.retrieve.indexer import database_path, sync_index, vectors_dir_path
from siku.retrieve.notes_reader import read_note
from siku.retrieve.store import SqliteIndex
from siku.retrieve.tokenizer import tokenize

VAULT = "vault"


def write_projection(
    vault: Path,
    name: str,
    source_id: str,
    source_hash: str,
    body: str,
) -> Path:
    note = vault / "notes" / name
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\n"
        f'source_hash: "{source_hash}"\n'
        f'source_name: "{name}"\n'
        f'source_id: "{source_id}"\n'
        'extractor: "FakeExtractor"\n'
        "---\n"
        f"# {name}\n\n"
        f"{body}",
        encoding="utf-8",
    )
    return note


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    root = tmp_path / VAULT
    write_projection(
        root,
        "a--aaaaaaaaaaaa.md",
        "a" * 12,
        "1" * 64,
        "## page:1\n\n检索增强生成 RAG 架构\n",
    )
    write_projection(
        root,
        "b--bbbbbbbbbbbb.md",
        "b" * 12,
        "2" * 64,
        "## sheet:预算\n\nRTX-4090 采购清单 128GB\n",
    )
    return root


def bm25_hits(data_dir: Path, query: str, limit: int = 10) -> list[str]:
    index = SqliteIndex.open(database_path(data_dir))
    try:
        return [chunk_id for chunk_id, _ in index.bm25_search(tokenize(query), limit)]
    finally:
        index.close()


def temp_artifacts(data_dir: Path) -> list[str]:
    return sorted(
        path.name
        for path in data_dir.iterdir()
        if path.name.endswith(".tmp") or ".tmp-" in path.name or path.name.endswith(".tmp-wal")
    )


class TestFreshSync:
    def test_first_sync_counts_and_queryable(self, vault: Path, tmp_path: Path) -> None:
        provider = FakeEmbeddingProvider()
        data_dir = tmp_path / "data"
        report = sync_index(vault, data_dir, provider)
        assert report.created == 2
        assert report.updated == 0
        assert report.skipped == 0
        assert report.removed == 0
        assert report.index_version == 1
        assert report.total_chunks == 2
        assert bm25_hits(data_dir, "检索增强")
        assert bm25_hits(data_dir, "RTX-4090")

    def test_embed_receives_all_fresh_chunk_texts(self, vault: Path, tmp_path: Path) -> None:
        provider = FakeEmbeddingProvider()
        data_dir = tmp_path / "data"
        sync_index(vault, data_dir, provider)
        assert len(provider.calls) == 1
        embedded_texts = provider.calls[0]
        assert any("检索增强生成" in text for text in embedded_texts)
        assert any("RTX-4090" in text for text in embedded_texts)


class TestIncrementalSync:
    def test_unchanged_hash_skips_parse_tokenize_embed(
        self, vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = FakeEmbeddingProvider()
        data_dir = tmp_path / "data"
        sync_index(vault, data_dir, provider)
        calls_after_first = len(provider.calls)

        # 未变化来源（frontmatter 相同）即使正文损坏也不得触发重新解析
        note = vault / "notes" / "a--aaaaaaaaaaaa.md"
        original = note.read_text(encoding="utf-8")
        frontmatter = original.split("---\n")[1]
        note.write_text(
            f"---\n{frontmatter}---\n\n## page:1\n\n正文被替换成垃圾内容\n", encoding="utf-8"
        )

        def boom(*args: object, **kwargs: object) -> None:
            raise AssertionError("unchanged source must not be re-parsed")

        monkeypatch.setattr("siku.retrieve.indexer.read_note", boom)
        report = sync_index(vault, data_dir, provider)
        assert report.skipped == 2
        assert len(provider.calls) == calls_after_first
        assert report.index_version == 2

    def test_hash_change_replaces_only_that_source(self, vault: Path, tmp_path: Path) -> None:
        provider = FakeEmbeddingProvider()
        data_dir = tmp_path / "data"
        sync_index(vault, data_dir, provider)
        old_hits = bm25_hits(data_dir, "检索增强")
        assert old_hits

        write_projection(
            vault,
            "a--aaaaaaaaaaaa.md",
            "a" * 12,
            "9" * 64,
            "## page:1\n\n替换后的全新内容 深度学习\n",
        )
        report = sync_index(vault, data_dir, provider)
        assert report.updated == 1
        assert report.skipped == 1
        new_hits = bm25_hits(data_dir, "检索增强")
        assert new_hits == []
        assert bm25_hits(data_dir, "深度学习")
        index = SqliteIndex.open(database_path(data_dir))
        try:
            assert index.chunk_count() == 2
        finally:
            index.close()

    def test_vectors_reused_for_unchanged_sources(self, vault: Path, tmp_path: Path) -> None:
        provider = FakeEmbeddingProvider()
        data_dir = tmp_path / "data"
        sync_index(vault, data_dir, provider)
        first_call_texts = list(provider.calls[0])
        write_projection(
            vault,
            "a--aaaaaaaaaaaa.md",
            "a" * 12,
            "9" * 64,
            "## page:1\n\n替换后的全新内容\n",
        )
        sync_index(vault, data_dir, provider)
        second_call_texts = provider.calls[1]
        # 第二次同步只嵌入变化的来源块，未变化来源的向量被复用
        assert len(second_call_texts) == 1
        assert second_call_texts[0] not in first_call_texts

    def test_renamed_projection_treated_as_updated(self, vault: Path, tmp_path: Path) -> None:
        provider = FakeEmbeddingProvider()
        data_dir = tmp_path / "data"
        sync_index(vault, data_dir, provider)
        # 改名（frontmatter 原样拷贝）：旧索引中的 note_path 已失效
        note = vault / "notes" / "b--bbbbbbbbbbbb.md"
        renamed = vault / "notes" / "renamed--bbbbbbbbbbbb.md"
        renamed.write_text(note.read_text(encoding="utf-8"), encoding="utf-8")
        note.unlink()
        report = sync_index(vault, data_dir, provider)
        assert report.updated == 1
        assert report.skipped == 1
        index = SqliteIndex.open(database_path(data_dir))
        try:
            document = index.get_document("b" * 12)
            assert document is not None
            assert document.note_path == "notes/renamed--bbbbbbbbbbbb.md"
            chunks = index.chunks_of_sources(["b" * 12])
            assert all(chunk.note_path == "notes/renamed--bbbbbbbbbbbb.md" for chunk in chunks)
        finally:
            index.close()

    def test_removed_source_cleans_old_chunks(self, vault: Path, tmp_path: Path) -> None:
        provider = FakeEmbeddingProvider()
        data_dir = tmp_path / "data"
        sync_index(vault, data_dir, provider)
        (vault / "notes" / "b--bbbbbbbbbbbb.md").unlink()
        report = sync_index(vault, data_dir, provider)
        assert report.removed == 1
        assert report.total_chunks == 1
        assert bm25_hits(data_dir, "RTX-4090") == []

    def test_duplicate_source_id_rejected(self, vault: Path, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        write_projection(
            vault,
            "dup--aaaaaaaaaaaa.md",
            "a" * 12,
            "3" * 64,
            "## page:1\n\n重复来源\n",
        )
        with pytest.raises(NoteParseError):
            sync_index(vault, data_dir, FakeEmbeddingProvider())
        if data_dir.exists():
            assert temp_artifacts(data_dir) == []


class TestFailurePreservesOld:
    def test_provider_failure_keeps_old_version_queryable(
        self, vault: Path, tmp_path: Path
    ) -> None:
        provider = FakeEmbeddingProvider()
        data_dir = tmp_path / "data"
        sync_index(vault, data_dir, provider)
        old_hits = bm25_hits(data_dir, "检索增强")
        assert old_hits

        write_projection(
            vault,
            "a--aaaaaaaaaaaa.md",
            "a" * 12,
            "9" * 64,
            "## page:1\n\n替换后的全新内容\n",
        )
        provider.script = "error"
        with pytest.raises(ProviderError):
            sync_index(vault, data_dir, provider)
        # 旧索引仍然可查询
        assert bm25_hits(data_dir, "检索增强") == old_hits
        # 临时产物已清理
        assert temp_artifacts(data_dir) == []

    def test_provider_empty_return_writes_no_partial_index(
        self, vault: Path, tmp_path: Path
    ) -> None:
        provider = FakeEmbeddingProvider()
        data_dir = tmp_path / "data"
        sync_index(vault, data_dir, provider)
        write_projection(
            vault,
            "a--aaaaaaaaaaaa.md",
            "a" * 12,
            "9" * 64,
            "## page:1\n\n替换后的全新内容\n",
        )
        provider.script = "empty"
        with pytest.raises(ProviderError):
            sync_index(vault, data_dir, provider)
        assert bm25_hits(data_dir, "检索增强")
        assert temp_artifacts(data_dir) == []


class TestModelConsistency:
    def test_model_mismatch_rejects_incremental_sync(self, vault: Path, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        sync_index(vault, data_dir, FakeEmbeddingProvider(dimensions=4, model_id="fake-a"))
        other = FakeEmbeddingProvider(dimensions=4, model_id="fake-b")
        with pytest.raises(ModelConfigMismatchError):
            sync_index(vault, data_dir, other)

    def test_rebuild_allows_model_switch_and_updates_meta(
        self, vault: Path, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        sync_index(vault, data_dir, FakeEmbeddingProvider(dimensions=4, model_id="fake-a"))
        other = FakeEmbeddingProvider(dimensions=8, model_id="fake-b")
        report = sync_index(vault, data_dir, other, rebuild=True)
        assert report.rebuilt is True
        assert report.created == 2
        assert bm25_hits(data_dir, "检索增强")
        index = SqliteIndex.open(database_path(data_dir))
        try:
            meta = index.model_metadata()
            assert meta["embedding_model_id"] == "fake-b"
            assert meta["embedding_dimensions"] == "8"
        finally:
            index.close()

    def test_missing_marker_corrupt_then_rebuild_fixes(self, vault: Path, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        sync_index(vault, data_dir, FakeEmbeddingProvider())
        marker = vectors_dir_path(data_dir) / ".commit"
        marker.unlink()
        with pytest.raises(IndexCorruptError):
            sync_index(vault, data_dir, FakeEmbeddingProvider())
        report = sync_index(vault, data_dir, FakeEmbeddingProvider(), rebuild=True)
        assert report.total_chunks == 2


class TestRebuild:
    def test_rebuild_ignores_old_data_full_regen(self, vault: Path, tmp_path: Path) -> None:
        provider = FakeEmbeddingProvider()
        data_dir = tmp_path / "data"
        sync_index(vault, data_dir, provider)
        sync_index(vault, data_dir, provider)
        report = sync_index(vault, data_dir, provider, rebuild=True)
        assert report.rebuilt is True
        assert report.created == 2
        assert report.index_version == 3
        assert bm25_hits(data_dir, "RTX-4090")

    def test_corrupt_index_version_becomes_index_corrupt(self, vault: Path, tmp_path: Path) -> None:
        provider = FakeEmbeddingProvider()
        data_dir = tmp_path / "data"
        sync_index(vault, data_dir, provider)
        index = SqliteIndex.open(database_path(data_dir))
        index.set_meta("index_version", "not-a-number")
        index.checkpoint_and_close()
        # 存量版本号损坏必须在提交前暴露，旧索引保持可查询
        with pytest.raises(IndexCorruptError):
            sync_index(vault, data_dir, provider)
        assert bm25_hits(data_dir, "检索增强")
        assert temp_artifacts(data_dir) == []

    def test_empty_notes_dir_readable_error(self, tmp_path: Path) -> None:
        empty_vault = tmp_path / "empty_vault"
        empty_vault.mkdir()
        with pytest.raises(NoteParseError):
            sync_index(empty_vault, tmp_path / "data", FakeEmbeddingProvider())


class TestNotesReaderIntegration:
    def test_read_note_parses_projection(self, vault: Path, tmp_path: Path) -> None:
        document, chunks = read_note(vault / "notes" / "a--aaaaaaaaaaaa.md", vault)
        assert document.source_id == "a" * 12
        assert chunks[0].anchor == "page:1"
