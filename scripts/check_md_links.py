"""文档相对链接与锚点门禁：Markdown 里的仓内链接必须指向存在的文件与标题。

零网络：http(s)/mailto 等外部目标一律跳过，只校验仓内相对路径与 ``#锚点``。
锚点按 GitHub 的标题 slug 规则推导（小写、去标点、空格转连字符、重名加 ``-N``），
并接受标题内显式 ``<a id="...">`` / ``name="..."`` 与 ``{#id}`` 后缀。
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

# 扫描面：各类文档根。目录不存在时静默跳过（例如未检出 docs/ 的精简副本）。
DEFAULT_ROOTS = ("docs", "openspec", "benchmarks", "ui", "src", "scripts")
DEFAULT_FILES = ("README.md", "AGENTS.md", "CONSTITUTION.md", "SECURITY.md")
# 本地维护、不入库的文档：扫它会让本机与 CI 口径不一致
DEFAULT_EXCLUDES = ("docs/HANDOFF.md",)
# 独立环境/构建缓存里的第三方文档不属于本仓
SKIPPED_PARTS = {".git", ".venv", "node_modules", ".mypy_cache", ".ruff_cache", "target", "dist"}
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_INLINE_CODE = re.compile(r"(`+)(?:(?!\1).)+?\1", re.DOTALL)
_INLINE_LINK = re.compile(r"!?\[[^\]]*\]\(\s*(<[^>]*>|(?:[^\s()]|\([^\s()]*\))*)")
_REFERENCE_DEF = re.compile(r"^ {0,3}\[[^\]]+\]:\s*(<[^>]+>|\S*)", re.MULTILINE)
_HTML_ID = re.compile(r"""<a\s[^>]*?(?:id|name)=["']([^"']+)["']""", re.IGNORECASE)
_ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*$")
_CLOSING_HASHES = re.compile(r"[ \t]+#+$")
_EXPLICIT_SLUG = re.compile(r"[ \t]*\{#([^}\s]+)\}$")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
# 代码围栏前面的语言标记（```python）也会被识别为行内代码，需在锚点推导时剔除
_FENCE_LINE = re.compile(r"^ {0,3}(```|~~~)")


@dataclass(frozen=True)
class BrokenLink:
    """一条失效链接：来源文件、行号与原始目标。"""

    source: str
    line: int
    target: str
    reason: str

    def __str__(self) -> str:
        return f"{self.source}:{self.line}: {self.target}（{self.reason}）"


def _strip_code(text: str) -> str:
    """去掉围栏代码块、缩进代码块与行内代码，行号保持不变。

    围栏按 CommonMark 的「等长或更长闭合」处理；4 空格缩进仅在块起始（前一非空行
    为空或仍处于缩进块）时剔除，避免误删列表项内的合法链接。
    """
    out: list[str] = []
    fence: tuple[str, int] | None = None
    indented = False
    previous_blank = True
    for raw in text.splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        if fence is not None:
            out.append(_blank(raw))
            match = _FENCE_OPEN.match(line)
            if (
                match is not None
                and match.group(1)[0] == fence[0]
                and len(match.group(1)) >= fence[1]
                and not match.group(2).strip()
            ):
                fence = None
            previous_blank = False
            continue
        match = _FENCE_OPEN.match(line)
        if match is not None and not (match.group(1)[0] == "`" and "`" in match.group(2)):
            fence = (match.group(1)[0], len(match.group(1)))
            out.append(_blank(raw))
            previous_blank = False
            continue
        blank = not line.strip()
        current_indented = line.startswith("    ") or line.startswith("\t")
        if current_indented and (previous_blank or indented):
            indented = True
            out.append(_blank(raw))
            previous_blank = False
            continue
        if not blank:
            indented = False
        out.append(raw)
        previous_blank = blank
    return _INLINE_CODE.sub(lambda match: " " * len(match.group(0)), "".join(out))


def _blank(segment: str) -> str:
    """把一段文本替换成等行数的空白，维持后续行号不变。"""
    return "".join("\n" if char == "\n" else " " for char in segment)


def github_slug(heading: str) -> str:
    """按 GitHub 规则把标题文本转成锚点 slug。

    CJK 字符保留原文；标点与符号丢弃；空白串折叠为单个连字符。
    """
    text = unicodedata.normalize("NFC", heading).strip().lower()
    kept = [
        char
        for char in text
        if char in {" ", "-", "_"} or not unicodedata.category(char).startswith(("P", "S", "C"))
    ]
    return "".join(kept).replace(" ", "-")


def anchors_of(text: str) -> set[str]:
    """收集一个 Markdown 文件内全部可用锚点（标题 slug + HTML id/name + 显式 {#id}）。"""
    anchors: set[str] = set()
    seen: dict[str, int] = {}
    for line in _strip_code(text).splitlines():
        if _FENCE_LINE.match(line):
            continue
        for explicit in _HTML_ID.findall(line):
            anchors.add(explicit)
        heading = _ATX_HEADING.match(line)
        if heading is None:
            continue
        title = _CLOSING_HASHES.sub("", heading.group(2))
        explicit_slug = _EXPLICIT_SLUG.search(title)
        if explicit_slug is not None:
            anchors.add(explicit_slug.group(1))
            title = title[: explicit_slug.start()]
        # 同名标题依次得到裸 slug、slug-1、slug-2……
        base = github_slug(title)
        anchors.add(base if base not in seen else f"{base}-{seen[base]}")
        seen[base] = seen.get(base, 0) + 1
    return anchors


def link_targets(text: str) -> list[tuple[int, str]]:
    """提取正文与引用式定义中的链接目标，附行号。"""
    stripped = _strip_code(text)
    results: list[tuple[int, str]] = []
    starts = [0]
    for index, char in enumerate(stripped):
        if char == "\n":
            starts.append(index + 1)
    for pattern in (_INLINE_LINK, _REFERENCE_DEF):
        for match in pattern.finditer(stripped):
            line = _line_of(starts, match.start())
            results.append((line, match.group(1).strip("<>")))
    return results


def _line_of(starts: list[int], offset: int) -> int:
    """把字符偏移换算成 1 起算的行号。"""
    low, high = 0, len(starts) - 1
    while low < high:
        mid = (low + high + 1) // 2
        if starts[mid] <= offset:
            low = mid
        else:
            high = mid - 1
    return low + 1


def _split(target: str) -> tuple[str, str]:
    """拆出（路径, 锚点）；整体锚点返回空路径。"""
    path, _, fragment = target.partition("#")
    return unquote(path), unquote(fragment)


def check_documents(
    root: Path, documents: list[Path], excludes: tuple[str, ...] = ()
) -> list[BrokenLink]:
    """逐文档校验仓内链接：文件存在性与锚点可达性。"""
    excluded = {root / item for item in excludes}
    anchor_cache: dict[Path, set[str]] = {}
    broken: list[BrokenLink] = []
    for document in documents:
        if document in excluded:
            continue
        source = document.relative_to(root).as_posix()
        text = document.read_text(encoding="utf-8")
        for line, target in link_targets(text):
            if not target or target.startswith("#"):
                path, fragment = "", target.removeprefix("#")
            elif _SCHEME.match(target) or target.startswith("//"):
                continue
            else:
                path, fragment = _split(target)
            resolved = _resolve(root, document, path)
            if resolved is None:
                broken.append(BrokenLink(source, line, target, "目标不存在"))
                continue
            if fragment and resolved.suffix == ".md":
                anchors = anchor_cache.setdefault(resolved, anchors_of(resolved.read_text("utf-8")))
                if fragment.lower() not in {anchor.lower() for anchor in anchors}:
                    broken.append(BrokenLink(source, line, target, f"锚点不存在：#{fragment}"))
    return broken


def _resolve(root: Path, document: Path, path: str) -> Path | None:
    """把链接路径解析为仓内文件；目录链接允许指向其中的 README.md。"""
    if not path:
        return document
    base = root if path.startswith("/") else document.parent
    candidate = (base / path.lstrip("/")).resolve()
    for option in (candidate, candidate / "README.md"):
        if option.is_file():
            return option
    return None


def discover(root: Path, roots: tuple[str, ...], files: tuple[str, ...]) -> list[Path]:
    """枚举扫描面内的 Markdown 文件，跳过缓存与依赖目录。"""
    found: set[Path] = set()
    for name in files:
        candidate = root / name
        if candidate.is_file():
            found.add(candidate)
    # 根目录文档不止 README/AGENTS(如 CONSTITUTION/CHANGELOG),统一纳入;
    # HANDOFF 等本地维护文件由 DEFAULT_EXCLUDES 排除。
    for pattern in ("*.md", "*.MD"):
        found.update(path for path in root.glob(pattern) if path.is_file())
    for directory in roots:
        base = root / directory
        if base.is_dir():
            found.update(path for path in base.rglob("*.md") if not SKIPPED_PARTS & set(path.parts))
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    """命令行入口：无失效链接返回 0，否则打印清单并返回 1。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."), help="仓库根目录")
    parser.add_argument("--dir", action="append", default=[], help="额外扫描目录（可重复）")
    parser.add_argument("--exclude", action="append", default=[], help="排除的仓内路径（可重复）")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    documents = discover(root, DEFAULT_ROOTS + tuple(args.dir), DEFAULT_FILES)
    broken = check_documents(root, documents, DEFAULT_EXCLUDES + tuple(args.exclude))
    for item in broken:
        print(item)
    print(f"checked {len(documents)} markdown files, {len(broken)} broken links")
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
