"""文档链接门禁的单测：解析器与锚点推导的边界，全仓扫描由 scripts/check_md_links.py 承担。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_md_links as links  # noqa: E402


def test_targets_cover_inline_reference_and_parenthesized() -> None:
    # 引用式定义也是本地链接；目标含一层括号（如 x(1).md）不能被截断
    text = (
        "[inline](docs/a.md)\n"
        "[reference]: docs/b.md\n"
        '[angled]: <docs/c d.md> "标题"\n'
        "[parenthesized](docs/d(1).md)\n"
        "[external]: https://example.com/x.md\n"
        "\n```\n[fenced]: docs/never.md\n```\n"
        "\n    [indented]: docs/never.md\n"
    )
    assert [target for _, target in links.link_targets(text)] == [
        "docs/a.md",
        "docs/d(1).md",
        "docs/b.md",
        "docs/c d.md",
        "https://example.com/x.md",
    ]


def test_code_blocks_with_nested_fences_are_ignored() -> None:
    # 4 反引号围栏内允许出现 3 反引号;内部链接仍是示例,不是真链接
    text = "````md\n```\n[fenced](docs/never.md)\n```\n````\n"
    assert links.link_targets(text) == []


def test_indented_code_link_is_ignored_but_nested_list_link_is_kept() -> None:
    # 块起始的 4 空格缩进是代码;列表项内的 4 空格续行仍是正文链接
    text = "\n    [code](docs/never.md)\n\n- 列表项\n    [list](docs/keep.md)\n"
    assert [target for _, target in links.link_targets(text)] == ["docs/keep.md"]


def test_anchors_follow_github_slug_rules() -> None:
    text = (
        "# 标题 Title\n"
        "## 重复\n## 重复\n"
        "## 带标点：冒号、括号（示例）##\n"
        "## 显式 {#custom-id}\n"
        '<a name="legacy"></a>\n'
        "```md\n## 围栏内标题\n```\n"
    )
    anchors = links.anchors_of(text)
    assert {"标题-title", "重复", "重复-1", "带标点冒号括号示例", "custom-id", "legacy"} <= anchors
    assert "围栏内标题" not in anchors


def test_check_documents_reports_missing_files_and_anchors(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (tmp_path / "README.md").write_text("# 顶层\n", encoding="utf-8")
    (docs / "a.md").write_text(
        "# A\n\n[ok](../README.md#顶层)\n[missing](gone.md)\n[bad anchor](../README.md#no-such)\n",
        encoding="utf-8",
    )
    broken = links.check_documents(tmp_path, sorted(docs.rglob("*.md")), ())
    assert [(item.target, item.line) for item in broken] == [
        ("gone.md", 4),
        ("../README.md#no-such", 5),
    ]


def test_excluded_documents_are_not_scanned(tmp_path: Path) -> None:
    # 本地维护、不入库的文档（如 HANDOFF）必须可排除，否则本机与 CI 口径不一致
    (tmp_path / "HANDOFF.md").write_text("[x](gone.md)\n", encoding="utf-8")
    assert links.check_documents(tmp_path, [tmp_path / "HANDOFF.md"], ("HANDOFF.md",)) == []
