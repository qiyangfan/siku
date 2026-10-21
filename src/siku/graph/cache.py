"""LLM 抽取缓存：SQLite（WAL）持久层，支撑幂等重建。

缓存键含 chunk_id、extractor_id、model_id 与 prompt_version；源或配置变化即换键重抽。
抽取缓存与社区摘要缓存按命名空间隔离。SQL 全部参数化。
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path

from siku.graph.errors import GraphExtractionError, GraphStoreCorruptError
from siku.graph.models import GraphExtraction, extraction_from_payload, extraction_to_payload

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
NAMESPACE_EXTRACTION = "extraction"
NAMESPACE_SUMMARY = "summary"
# 最近一次成功构建的抽取器身份，供自动维护检查配置是否匹配。
GRAPH_IDENTITY_KEY = "graph_build_identity"
GRAPH_IDENTITY_FIELDS = ("extractor_id", "model_id", "prompt_version")

# 字段分隔符使用控制字符，杜绝内容拼接歧义（与 chunk_id 派生同款）
_KEY_SEPARATOR = "\x1f"

_SCHEMA_SQL = (
    """
    CREATE TABLE IF NOT EXISTS cache_meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cache_entries (
        namespace TEXT NOT NULL,
        cache_key TEXT NOT NULL,
        payload   TEXT NOT NULL,
        PRIMARY KEY (namespace, cache_key)
    )
    """,
)


def build_cache_key(*parts: str) -> str:
    """由身份组件派生确定性缓存键；组件经控制字符分隔避免拼接歧义。"""
    payload = _KEY_SEPARATOR.join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def extraction_cache_key(
    chunk_key: str,
    extractor_id: str,
    model_id: str,
    prompt_version: str,
) -> str:
    """一个 chunk 的抽取缓存键；chunk_id 已内嵌源与正文指纹，内容变化即换键。"""
    return build_cache_key(chunk_key, extractor_id, model_id, prompt_version)


class ExtractionCache:
    """`cache.sqlite3` 的读写句柄；抽取与社区摘要共用，按命名空间隔离。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # 数据目录被文件占位或不可写时归一为领域错误，不裸抛 FileExistsError。
            raise GraphStoreCorruptError(
                f"Cannot create graph data directory {path.parent}: {exc}; "
                "check filesystem permissions or remove the blocking file"
            ) from exc
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(path)
            connection.execute("PRAGMA journal_mode=WAL")
            for statement in _SCHEMA_SQL:
                connection.execute(statement)
            connection.execute(
                "INSERT OR REPLACE INTO cache_meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            connection.commit()
        except sqlite3.Error as exc:
            # 缓存是派生物；文件损坏时归一为领域错误，删除 data/graph 即可重建。
            if connection is not None:
                connection.close()
            raise GraphStoreCorruptError(
                f"Extraction cache at {path} is not a readable siku cache: {exc}; "
                "delete the graph data directory to rebuild it"
            ) from exc
        except BaseException:
            if connection is not None:
                connection.close()
            raise
        self._connection = connection

    def __enter__(self) -> ExtractionCache:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def journal_mode(self) -> str:
        """返回当前 journal 模式（测试与运维诊断用）。"""
        row = self._connection.execute("PRAGMA journal_mode").fetchone()
        return str(row[0]) if row is not None else ""

    def get_extraction(self, cache_key: str) -> GraphExtraction | None:
        """取缓存抽取结果；未命中或 payload 损坏一律返回 None（自愈重抽）。"""
        payload = self._get(NAMESPACE_EXTRACTION, cache_key)
        if payload is None:
            return None
        try:
            return extraction_from_payload(payload)
        except GraphExtractionError:
            logger.warning(
                "corrupt extraction cache payload ignored, will re-extract: key=%s",
                cache_key,
            )
            return None

    def put_extraction(self, cache_key: str, extraction: GraphExtraction) -> None:
        self._put(NAMESPACE_EXTRACTION, cache_key, extraction_to_payload(extraction))

    def get_summary(self, cache_key: str) -> str | None:
        """取缓存社区摘要（纯文本）；未命中返回 None。"""
        return self._get(NAMESPACE_SUMMARY, cache_key)

    def put_summary(self, cache_key: str, summary: str) -> None:
        self._put(NAMESPACE_SUMMARY, cache_key, summary)

    def get_build_identity(self) -> dict[str, str] | None:
        """上次成功构建记录的抽取器身份；无记录或损坏返回 None（自愈重抽）。"""
        row = self._connection.execute(
            "SELECT value FROM cache_meta WHERE key = ?", (GRAPH_IDENTITY_KEY,)
        ).fetchone()
        if row is None:
            return None
        try:
            parsed = json.loads(str(row[0]))
        except ValueError:
            logger.warning("corrupt graph build identity ignored, will re-extract")
            return None
        if not isinstance(parsed, dict):
            return None
        identity: dict[str, str] = {}
        for field in GRAPH_IDENTITY_FIELDS:
            value = parsed.get(field)
            if not isinstance(value, str):
                return None
            identity[field] = value
        return identity

    def put_build_identity(self, extractor_id: str, model_id: str, prompt_version: str) -> None:
        """构建成功落盘后记录抽取器身份；构建失败不得调用（产物未变则身份未变）。"""
        self._set_meta(
            GRAPH_IDENTITY_KEY,
            json.dumps(
                {
                    "extractor_id": extractor_id,
                    "model_id": model_id,
                    "prompt_version": prompt_version,
                },
                ensure_ascii=False,
            ),
        )

    def _set_meta(self, key: str, value: str) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO cache_meta(key, value) VALUES (?, ?)", (key, value)
            )

    def _get(self, namespace: str, cache_key: str) -> str | None:
        row = self._connection.execute(
            "SELECT payload FROM cache_entries WHERE namespace = ? AND cache_key = ?",
            (namespace, cache_key),
        ).fetchone()
        return str(row[0]) if row is not None else None

    def _put(self, namespace: str, cache_key: str, payload: str) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO cache_entries(namespace, cache_key, payload) "
                "VALUES (?, ?, ?)",
                (namespace, cache_key, payload),
            )
