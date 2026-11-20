"""文档相对链接门禁：文档里的本地链接必须指向仓库内存在的路径。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DOC_GLOBS = ("README.md", "AGENTS.md", "docs/**/*.md", "openspec/**/*.md")
# HANDOFF.md 仅本地维护、不入库，扫描它会让本地与 CI 口径不一致
_LOCAL_ONLY = {"HANDOFF.md"}
_FENCED_CODE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_INLINE_LINK = re.compile(r"!?\[[^\]]*\]\(\s*(<[^>]+>|[^)\s]+)")
# 引用式定义：最多 3 空格缩进，排除 4 空格代码块；目标后可跟标题
_REFERENCE_DEF = re.compile(r"^ {0,3}\[[^\]]+\]:\s*(<[^>]+>|\S+)", re.MULTILINE)
_EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "#")


def _documents() -> list[Path]:
    files: set[Path] = set()
    for pattern in _DOC_GLOBS:
        files.update(ROOT.glob(pattern))
    return sorted(path for path in files if path.name not in _LOCAL_ONLY)


def _local_targets(text: str) -> list[str]:
    text = _FENCED_CODE.sub("", text)
    text = _INLINE_CODE.sub("", text)
    raw_targets = [match.group(1) for match in _INLINE_LINK.finditer(text)]
    raw_targets.extend(match.group(1) for match in _REFERENCE_DEF.finditer(text))
    targets: list[str] = []
    for raw in raw_targets:
        target = raw.strip("<>")
        if target.startswith(_EXTERNAL_PREFIXES):
            continue
        path = target.split("#", 1)[0]
        if path:
            targets.append(path)
    return targets


def test_local_targets_covers_inline_and_reference_links() -> None:
    # 引用式定义也是本地链接，漏解析会让这类断链逃过门禁
    text = (
        "[inline](docs/a.md)\n"
        "[reference]: docs/b.md\n"
        '[angled]: <docs/c d.md> "标题"\n'
        "[external]: https://example.com/x.md\n"
        "\n```\n[fenced]: docs/never.md\n```\n"
        "\n    [indented]: docs/never.md\n"
    )
    assert _local_targets(text) == ["docs/a.md", "docs/b.md", "docs/c d.md"]


def test_relative_links_resolve() -> None:
    broken = [
        f"{document.relative_to(ROOT)} -> {target}"
        for document in _documents()
        for target in _local_targets(document.read_text(encoding="utf-8"))
        if not (document.parent / target).resolve().exists()
    ]
    assert not broken, "Broken relative links:\n" + "\n".join(broken)
