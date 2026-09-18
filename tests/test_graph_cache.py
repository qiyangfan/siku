"""抽取缓存的行为测试：键派生、命中/未命中/键变化失效、WAL 与持久化。"""

import sqlite3
from pathlib import Path

import pytest

from siku.graph.cache import (
    ExtractionCache,
    build_cache_key,
    extraction_cache_key,
)
from siku.graph.errors import GraphStoreCorruptError
from siku.graph.models import (
    EntityMention,
    GraphExtraction,
    RelationMention,
)

EXTRACTION = GraphExtraction(
    entities=(EntityMention(name="张三", type="人物", evidence="原文"),),
    relations=(
        RelationMention(source_name="张三", target_name="李四", type="同事", evidence="原文"),
    ),
)


class TestCacheKey:
    def test_key_is_deterministic(self) -> None:
        first = extraction_cache_key("hash-a", "llm-graph", "deepseek-chat", "v1")
        second = extraction_cache_key("hash-a", "llm-graph", "deepseek-chat", "v1")
        assert first == second

    def test_any_component_change_invalidates_key(self) -> None:
        base = extraction_cache_key("hash-a", "llm-graph", "deepseek-chat", "v1")
        assert build_cache_key("hash-b", "llm-graph", "deepseek-chat", "v1") != base
        assert build_cache_key("hash-a", "llm-graph-2", "deepseek-chat", "v1") != base
        assert build_cache_key("hash-a", "llm-graph", "deepseek-reasoner", "v1") != base
        assert build_cache_key("hash-a", "llm-graph", "deepseek-chat", "v2") != base

    def test_components_are_separated_unambiguously(self) -> None:
        # 组件拼接不得产生歧义：("ab","c") 与 ("a","bc") 必须是不同的键
        assert build_cache_key("ab", "c") != build_cache_key("a", "bc")


class TestExtractionCache:
    def test_put_then_get_hits(self, tmp_path: Path) -> None:
        with ExtractionCache(tmp_path / "cache.sqlite3") as cache:
            cache.put_extraction("key-1", EXTRACTION)
            assert cache.get_extraction("key-1") == EXTRACTION

    def test_missing_key_is_a_miss(self, tmp_path: Path) -> None:
        with ExtractionCache(tmp_path / "cache.sqlite3") as cache:
            assert cache.get_extraction("nope") is None

    def test_key_change_invalidates_entry(self, tmp_path: Path) -> None:
        # 换模型/prompt 版本 → 键变化 → 旧条目不再命中（显式重抽语义）
        with ExtractionCache(tmp_path / "cache.sqlite3") as cache:
            cache.put_extraction("key-model-a", EXTRACTION)
            assert cache.get_extraction("key-model-b") is None
            assert cache.get_extraction("key-model-a") == EXTRACTION

    def test_persists_across_reopen(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.sqlite3"
        with ExtractionCache(path) as cache:
            cache.put_extraction("key-1", EXTRACTION)
        with ExtractionCache(path) as reopened:
            assert reopened.get_extraction("key-1") == EXTRACTION

    def test_wal_mode_enabled(self, tmp_path: Path) -> None:
        with ExtractionCache(tmp_path / "cache.sqlite3") as cache:
            mode = cache.journal_mode()
            assert mode == "wal"

    def test_namespaces_are_isolated(self, tmp_path: Path) -> None:
        # 抽取缓存与社区摘要缓存共库但命名空间隔离，互不命中
        with ExtractionCache(tmp_path / "cache.sqlite3") as cache:
            cache.put_summary("key-1", "社区摘要文本")
            assert cache.get_extraction("key-1") is None
            assert cache.get_summary("key-1") == "社区摘要文本"

    def test_garbage_cache_file_raises_domain_error(self, tmp_path: Path) -> None:
        # 缓存文件整体损坏（垃圾字节）必须归一为领域错误，禁止裸 traceback
        path = tmp_path / "cache.sqlite3"
        path.write_bytes(b"this is not a sqlite database at all" * 16)
        with pytest.raises(GraphStoreCorruptError):
            ExtractionCache(path)

    def test_corrupt_extraction_payload_self_heals_to_miss(self, tmp_path: Path) -> None:
        # 缓存是派生物：extraction 命名空间内 payload 损坏（非法 JSON / 合法 JSON
        # 但结构残缺）一律按未命中处理（重新抽取自愈），绝不炸构建
        path = tmp_path / "cache.sqlite3"
        with ExtractionCache(path) as cache:
            cache.put_extraction("key-1", EXTRACTION)
            # 直接注入两类损坏 payload：非法 JSON 与缺字段的合法 JSON
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO cache_entries(namespace, cache_key, payload) "
                    "VALUES (?, ?, ?)",
                    ("extraction", "bad-json", "不是 JSON 的垃圾数据"),
                )
                connection.execute(
                    "INSERT OR REPLACE INTO cache_entries(namespace, cache_key, payload) "
                    "VALUES (?, ?, ?)",
                    ("extraction", "bad-structure", '{"entities": [{}], "relations": []}'),
                )
        with ExtractionCache(path) as reopened:
            assert reopened.get_extraction("key-1") == EXTRACTION
            assert reopened.get_extraction("bad-json") is None
            assert reopened.get_extraction("bad-structure") is None
