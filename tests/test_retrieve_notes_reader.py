"""Markdown 投影解析器的行为测试：frontmatter 校验、结构块切分、异常场景。"""

from pathlib import Path

import pytest

from siku.retrieve.errors import NoteParseError
from siku.retrieve.models import derive_chunk_id
from siku.retrieve.notes_reader import read_frontmatter, read_note, scan_note_frontmatters

VAULT = "vault"


def write_note(
    path: Path,
    *,
    source_id: str = "a" * 12,
    source_hash: str = "b" * 64,
    source_name: str = "report.pdf",
    extractor: str = "PdfExtractor",
    title: str = "季度报告",
    body: str = "## page:1\n\n第一页内容\n\n## page:2\n\n第二页内容\n",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f'title: "{title}"\n'
        f'source_hash: "{source_hash}"\n'
        f'source_name: "{source_name}"\n'
        f'source_id: "{source_id}"\n'
        f'extractor: "{extractor}"\n'
        "---\n"
        f"# {title}\n\n"
        f"{body}",
        encoding="utf-8",
    )


class TestReadNote:
    def test_two_sections_become_two_chunks(self, tmp_path: Path) -> None:
        note = tmp_path / VAULT / "notes" / "report--aaaaaaaaaaaa.md"
        write_note(note)
        document, chunks = read_note(note, tmp_path / VAULT)
        assert document.source_id == "a" * 12
        assert document.source_hash == "b" * 64
        assert document.source_name == "report.pdf"
        assert document.extractor == "PdfExtractor"
        assert document.note_path == "notes/report--aaaaaaaaaaaa.md"
        assert [chunk.anchor for chunk in chunks] == ["page:1", "page:2"]
        assert [chunk.ordinal for chunk in chunks] == [0, 1]
        assert chunks[0].text == "第一页内容"

    def test_chunk_id_derived_from_stable_fields(self, tmp_path: Path) -> None:
        note = tmp_path / VAULT / "notes" / "a.md"
        write_note(note)
        _, chunks = read_note(note, tmp_path / VAULT)
        assert chunks[0].chunk_id == derive_chunk_id("a" * 12, "page:1", 0, "第一页内容")

    def test_body_without_h2_becomes_content_chunk(self, tmp_path: Path) -> None:
        note = tmp_path / VAULT / "notes" / "plain.md"
        write_note(note, body="只有一段普通正文。\n")
        _, chunks = read_note(note, tmp_path / VAULT)
        assert len(chunks) == 1
        assert chunks[0].anchor == "content"
        assert chunks[0].text == "只有一段普通正文。"

    def test_empty_sections_skipped_ordinals_compact(self, tmp_path: Path) -> None:
        note = tmp_path / VAULT / "notes" / "gaps.md"
        write_note(note, body="## page:1\n\n\n## page:2\n\n实内容\n")
        _, chunks = read_note(note, tmp_path / VAULT)
        assert [chunk.anchor for chunk in chunks] == ["page:2"]
        assert chunks[0].ordinal == 0

    def test_body_whitespace_normalized(self, tmp_path: Path) -> None:
        note = tmp_path / VAULT / "notes" / "ws.md"
        write_note(note, body="## page:1\n\n行一带   多空格\n行二\t制表\n")
        _, chunks = read_note(note, tmp_path / VAULT)
        assert chunks[0].text == "行一带 多空格 行二 制表"

    def test_h1_stripped_after_leading_blank_line(self, tmp_path: Path) -> None:
        # 投影在 frontmatter 后保留一个空行，再写 H1 标题。
        note = tmp_path / VAULT / "notes" / "blank.md"
        note.parent.mkdir(parents=True)
        note.write_text(
            "---\n"
            f'source_hash: "{"b" * 64}"\n'
            'source_name: "plain.md"\n'
            f'source_id: "{"a" * 12}"\n'
            'extractor: "MdExtractor"\n'
            "---\n"
            "\n"
            "# 裸标题\n\n这是正文段落。\n",
            encoding="utf-8",
        )
        _, chunks = read_note(note, tmp_path / VAULT)
        assert len(chunks) == 1
        assert chunks[0].anchor == "content"
        assert chunks[0].text == "这是正文段落。"

    def test_section_comment_line_stripped(self, tmp_path: Path) -> None:
        note = tmp_path / VAULT / "notes" / "cmt.md"
        note.parent.mkdir(parents=True)
        note.write_text(
            "---\n"
            f'source_hash: "{"b" * 64}"\n'
            'source_name: "x.pdf"\n'
            f'source_id: "{"a" * 12}"\n'
            'extractor: "PdfExtractor"\n'
            "---\n"
            "# t\n\n"
            "## page:1\n"
            f'<!-- source_hash: "{"b" * 64}"; anchor: "page:1" -->\n'
            "真实内容\n",
            encoding="utf-8",
        )
        _, chunks = read_note(note, tmp_path / VAULT)
        assert chunks[0].text == "真实内容"

    def test_frontmatter_only_note_yields_zero_chunks(self, tmp_path: Path) -> None:
        note = tmp_path / VAULT / "notes" / "empty.md"
        write_note(note, body="")
        _, chunks = read_note(note, tmp_path / VAULT)
        assert chunks == ()

    def test_crlf_line_endings_parse(self, tmp_path: Path) -> None:
        note = tmp_path / VAULT / "notes" / "crlf.md"
        write_note(note)
        raw = note.read_text(encoding="utf-8")
        note.write_bytes(raw.replace("\n", "\r\n").encode("utf-8"))
        document, chunks = read_note(note, tmp_path / VAULT)
        assert document.source_id == "a" * 12
        assert chunks[0].text == "第一页内容"


class TestReadNoteErrors:
    @pytest.mark.parametrize(
        "missing_field",
        ["source_hash", "source_name", "source_id", "extractor"],
    )
    def test_missing_required_field_raises_named(self, tmp_path: Path, missing_field: str) -> None:
        note = tmp_path / VAULT / "notes" / "bad.md"
        note.parent.mkdir(parents=True)
        frontmatter = {
            "source_hash": "b" * 64,
            "source_name": "x.pdf",
            "source_id": "a" * 12,
            "extractor": "PdfExtractor",
        }
        frontmatter.pop(missing_field)
        lines = (
            ["---"]
            + [f'{k}: "{v}"' for k, v in frontmatter.items()]
            + [
                "---",
                "# t",
                "## page:1",
                "内容",
            ]
        )
        note.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(NoteParseError) as excinfo:
            read_note(note, tmp_path / VAULT)
        assert missing_field in str(excinfo.value)

    def test_invalid_source_hash_raises(self, tmp_path: Path) -> None:
        note = tmp_path / VAULT / "notes" / "badhash.md"
        write_note(note, source_hash="xyz")
        with pytest.raises(NoteParseError):
            read_note(note, tmp_path / VAULT)

    def test_missing_frontmatter_raises(self, tmp_path: Path) -> None:
        note = tmp_path / VAULT / "notes" / "nofm.md"
        note.parent.mkdir(parents=True)
        note.write_text("# 纯笔记\n\n没有 frontmatter。\n", encoding="utf-8")
        with pytest.raises(NoteParseError):
            read_note(note, tmp_path / VAULT)

    def test_invalid_json_frontmatter_value_raises(self, tmp_path: Path) -> None:
        note = tmp_path / VAULT / "notes" / "badjson.md"
        note.parent.mkdir(parents=True)
        note.write_text(
            "---\n"
            "source_hash: " + "b" * 64 + "\n"
            "source_name: 未加引号的值\n"
            'source_id: "' + "a" * 12 + '"\n'
            'extractor: "PdfExtractor"\n'
            "---\n",
            encoding="utf-8",
        )
        with pytest.raises(NoteParseError):
            read_note(note, tmp_path / VAULT)


class TestScan:
    def test_scan_only_md_sorted_by_path(self, tmp_path: Path) -> None:
        notes_dir = tmp_path / VAULT / "notes"
        write_note(notes_dir / "b.md", source_id="b" * 12)
        write_note(notes_dir / "a.md", source_id="a" * 12)
        (notes_dir / "ignored.txt").write_text("not a projection", encoding="utf-8")
        (notes_dir / "sub").mkdir()
        write_note(notes_dir / "sub" / "c.md", source_id="c" * 12)
        metas = scan_note_frontmatters(tmp_path / VAULT)
        assert [meta.source_id for meta in metas] == ["a" * 12, "b" * 12, "c" * 12]

    def test_missing_notes_dir_raises_readable_error(self, tmp_path: Path) -> None:
        with pytest.raises(NoteParseError):
            scan_note_frontmatters(tmp_path / VAULT)

    def test_read_frontmatter_returns_document_record(self, tmp_path: Path) -> None:
        note = tmp_path / VAULT / "notes" / "a.md"
        write_note(note)
        meta = read_frontmatter(note, tmp_path / VAULT)
        assert meta.source_id == "a" * 12
        assert meta.source_hash == "b" * 64
        assert meta.note_path == "notes/a.md"
