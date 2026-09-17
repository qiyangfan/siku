"""检索领域模型的契约测试。"""

import pytest

from siku.retrieve.errors import RetrievalError
from siku.retrieve.models import (
    CHUNK_ID_VERSION,
    ChunkRecord,
    DocumentRecord,
    IndexReport,
    SearchOptions,
    SearchResult,
    derive_chunk_id,
)


class TestDeriveChunkId:
    def test_same_input_same_id(self) -> None:
        first = derive_chunk_id("abc123", "page:1", 0, "正文内容")
        second = derive_chunk_id("abc123", "page:1", 0, "正文内容")
        assert first == second

    def test_no_wall_clock_multiple_calls_stable(self) -> None:
        ids = {derive_chunk_id("abc123", "content", 0, "text") for _ in range(5)}
        assert len(ids) == 1

    @pytest.mark.parametrize(
        ("changed_field", "source_id", "anchor", "ordinal", "text"),
        [
            ("source_id", "other1", "page:1", 0, "正文内容"),
            ("anchor", "abc123", "page:2", 0, "正文内容"),
            ("ordinal", "abc123", "page:1", 1, "正文内容"),
            ("text", "abc123", "page:1", 0, "正文内容改"),
        ],
    )
    def test_any_stable_field_change_changes_id(
        self,
        changed_field: str,
        source_id: str,
        anchor: str,
        ordinal: int,
        text: str,
    ) -> None:
        del changed_field
        assert derive_chunk_id(source_id, anchor, ordinal, text) != derive_chunk_id(
            source_id="abc123", anchor="page:1", ordinal=0, text="正文内容"
        )

    def test_separator_prevents_concatenation_ambiguity(self) -> None:
        # 字段内容包含本可能造成拼接歧义的字符，分隔符保证仍可区分
        left = derive_chunk_id("a\x1fb", "c", 0, "d")
        right = derive_chunk_id("a", "b\x1fc\x1f0\x1fd", 0, "")
        assert left != right

    def test_output_is_hex_sha256_length(self) -> None:
        chunk_id = derive_chunk_id("abc123", "content", 0, "text")
        assert len(chunk_id) == 64
        int(chunk_id, 16)

    def test_version_participates_in_derivation(self) -> None:
        payload = f"{CHUNK_ID_VERSION}\x1fabc123\x1f0\x1fcontent\x1ftext"
        import hashlib

        expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        assert derive_chunk_id("abc123", "content", 0, "text") == expected


class TestRecords:
    def test_document_record_is_frozen(self) -> None:
        record = DocumentRecord(
            source_id="abc123",
            source_hash="0" * 64,
            source_name="report.pdf",
            note_path="notes/report--abc123.md",
            extractor="PdfExtractor",
        )
        with pytest.raises(Exception):  # noqa: B017 - frozen dataclass 禁止赋值
            record.source_id = "changed"  # type: ignore[misc]

    def test_chunk_record_carries_provenance(self) -> None:
        record = ChunkRecord(
            chunk_id="c" * 64,
            source_id="abc123",
            source_hash="0" * 64,
            source_name="slides.pptx",
            note_path="notes/slides--abc123.md",
            anchor="slide:2",
            ordinal=1,
            text="本页要点",
        )
        assert record.anchor == "slide:2"
        assert record.ordinal == 1


class TestIndexReport:
    def test_report_counts_kept_as_given(self) -> None:
        report = IndexReport(
            created=2,
            updated=1,
            skipped=3,
            removed=0,
            total_chunks=42,
            index_version=7,
            rebuilt=False,
        )
        assert report.created == 2
        assert report.updated == 1
        assert report.skipped == 3
        assert report.removed == 0
        assert report.total_chunks == 42
        assert report.index_version == 7

    def test_rebuilt_flag_distinguishes_full_rebuild(self) -> None:
        report = IndexReport(0, 0, 0, 0, 0, 1, rebuilt=True)
        assert report.rebuilt is True


class TestSearchOptions:
    def test_defaults_match_design(self) -> None:
        options = SearchOptions()
        assert options.top_k == 10
        assert options.candidate_k == 50
        assert options.rrf_k == 60


class TestSearchResult:
    def test_single_channel_candidate_allows_missing_score(self) -> None:
        result = SearchResult(
            chunk_id="c" * 64,
            source_name="doc.docx",
            note_path="notes/doc--abc123.md",
            source_hash="0" * 64,
            anchor="content",
            text="段落",
            bm25_score=None,
            vector_score=0.83,
            hybrid_score=1 / 62,
            rerank_score=0.9,
        )
        assert result.bm25_score is None
        assert result.vector_score == pytest.approx(0.83)

    def test_error_hierarchy(self) -> None:
        from siku.retrieve.errors import IndexUnavailableError

        assert issubclass(IndexUnavailableError, RetrievalError)
