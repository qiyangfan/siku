"""检索用确定性中文预分词器。

中文连续汉字同时产出单字与相邻二元 token；英文、数字与型号保留整体并转小写。
查询与索引必须经过同一 tokenizer（ADR-0003：禁止裸 FTS5 上中文）。词典分词的
语义召回由向量通道承担；若 bigram 成为瓶颈，再按 ROADMAP 触发器重选。
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections.abc import Sequence

from siku.retrieve.errors import FtsUnavailableError, InvalidQueryError

# 预分词方案版本：进入索引元数据，变更即要求重建索引
TOKENIZER_VERSION = "cjk-uni-bigram-v1"

# CJK 统一表意文字（含扩展 A 与兼容区）；假名/谚文等暂不在 BM25 分词范围
_CJK_RANGES = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
# 单次批量扫描取代逐字符 match：CJK 连续段与 ASCII token 各有独立分支
_SCAN_RE = re.compile(rf"(?P<cjk>[{_CJK_RANGES}]+)|(?P<token>[0-9A-Za-z][0-9A-Za-z._/@-]*)")
# token 尾部允许出现的连接符，剥除避免把句尾标点吸进 token
_TOKEN_TRAILING = "._/@-"  # noqa: S105  # 名为 token 尾字符集合，与密码无关


def normalize_text(text: str) -> str:
    """归一化文本：全角转半角、空白折叠为单空格。"""
    normalized = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", normalized)


def _normalize_for_tokenize(text: str) -> str:
    """tokenize 专用归一化：ASCII 直接返回，其余仅做 NFKC。

    扫描器本就跳过空白，空白折叠不改变 token 流；ASCII 在 NFKC 下是恒等映射。
    差分测试保证与 ``normalize_text`` + 逐字符扫描的 v1 输出逐 token 一致。
    """
    if text.isascii():
        return text
    return unicodedata.normalize("NFKC", text)


def tokenize(text: str) -> list[str]:
    """把任意文本切分为 FTS5 可检索 token 序列（保留重复以维持词频）。

    CJK 连续段一次匹配后统一产出单字与相邻二元；ASCII 段整段取出后剥除尾连接符
    并小写。批量扫描与逐字符扫描（v1 参考实现）逐 token 等价，由差分测试守护。
    """
    normalized = _normalize_for_tokenize(text)
    tokens: list[str] = []
    for match in _SCAN_RE.finditer(normalized):
        # 1=cjk 连续段，2=ASCII token；位置取值比命名组略快
        run = match[1]
        if run is not None:
            tokens.extend(run)
            tokens.extend([run[start : start + 2] for start in range(len(run) - 1)])
            continue
        token = (match[2] or "").rstrip(_TOKEN_TRAILING).lower()
        if token:
            tokens.append(token)
    return tokens


def tokenize_query(query: str) -> list[str]:
    """切分用户查询；无有效 token 属于用户输入错误而非空结果。"""
    tokens = tokenize(query)
    if not tokens:
        raise InvalidQueryError(f"Query contains no searchable tokens: {query!r}")
    return tokens


def build_fts_match(tokens: Sequence[str]) -> str:
    """把 token 序列转为 FTS5 MATCH 表达式（OR 召回，引号防语法注入）。"""
    seen: dict[str, None] = dict.fromkeys(tokens)
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in seen)


def ensure_fts5_available() -> None:
    """探测当前 SQLite 构建是否带 FTS5；缺失时给出用户可读错误。"""
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE VIRTUAL TABLE fts5_probe USING fts5(content)")
    except sqlite3.OperationalError as exc:
        raise FtsUnavailableError(
            "The SQLite build in use lacks FTS5 support; "
            "full-text retrieval is unavailable. "
            "Install a Python build compiled with SQLITE_ENABLE_FTS5."
        ) from exc
    finally:
        if connection is not None:
            connection.close()
