"""确定性 tokenizer 的表驱动测试与 FTS5 能力检查测试。"""

import pytest

from siku.retrieve.errors import FtsUnavailableError, InvalidQueryError
from siku.retrieve.tokenizer import (
    TOKENIZER_VERSION,
    build_fts_match,
    ensure_fts5_available,
    tokenize,
    tokenize_query,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # 中文：unigram + bigram 双覆盖
        ("知识图谱", ["知", "识", "图", "谱", "知识", "识图", "图谱"]),
        # 单个汉字：仅 unigram
        ("图", ["图"]),
        # 英文小写化并保留为整体 token
        ("Retrieval", ["retrieval"]),
        # 数字序列保留
        ("2026", ["2026"]),
        # 连字符型号保留为单 token
        ("RTX-4090", ["rtx-4090"]),
        # 点分版本号保留
        ("v1.2.3", ["v1.2.3"]),
        # 下划线标识符保留
        ("source_hash", ["source_hash"]),
        # 中文与英文/数字混合：各归各类
        ("BAAI/bge-m3 模型", ["baai/bge-m3", "模", "型", "模型"]),
        # 标点被剥离
        ("你好，世界！", ["你", "好", "你好", "世", "界", "世界"]),
        # 多余空白归一化
        ("  空白   测试\t文本 \n", ["空", "白", "空白", "测", "试", "测试", "文", "本", "文本"]),
        # 全角拉丁/数字归一化为半角
        ("ＡＢＣ１２３", ["abc123"]),
        # 长十六进制 hash 保留为单 token
        ("a" * 64, ["a" * 64]),
        # 仅标点/空白：无 token
        ("。！？ 、、", []),
        # 空输入
        ("", []),
    ],
)
def test_tokenize_table_driven(text: str, expected: list[str]) -> None:
    assert tokenize(text) == expected


def test_same_input_deterministic_output() -> None:
    text = "混合 Corpus：PPT slide:3 与 bug-2024 报告"
    assert tokenize(text) == tokenize(text)


def test_tokenizer_version_constant_defined() -> None:
    assert TOKENIZER_VERSION


class TestBuildFtsMatch:
    def test_match_expr_joins_tokens_with_or_quoted(self) -> None:
        match_expr = build_fts_match(["知识", "图谱"])
        assert match_expr == '"知识" OR "图谱"'

    def test_duplicate_tokens_deduped_order_kept(self) -> None:
        assert build_fts_match(["图", "图谱", "图"]) == '"图" OR "图谱"'

    def test_empty_tokens_return_empty_match_expr(self) -> None:
        assert build_fts_match([]) == ""

    def test_quotes_escaped_in_match_expr(self) -> None:
        assert build_fts_match(['a"b']) == '"a""b"'


class TestQueryTokenization:
    def test_valid_query_extracts_tokens(self) -> None:
        from siku.retrieve.tokenizer import tokenize_query

        assert tokenize_query("知识 图谱") == ["知", "识", "知识", "图", "谱", "图谱"]

    def test_empty_query_is_user_error(self) -> None:
        with pytest.raises(InvalidQueryError):
            tokenize_query("   ")

    def test_punctuation_only_query_is_user_error(self) -> None:
        with pytest.raises(InvalidQueryError):
            tokenize_query("！！？？")


class TestFts5Capability:
    def test_current_env_has_fts5(self) -> None:
        ensure_fts5_available()

    def test_missing_fts5_raises_readable_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sqlite3

        class BrokenCursor:
            def execute(self, sql: str, *args: object) -> "BrokenCursor":
                if "VIRTUAL TABLE" in sql.upper():
                    raise sqlite3.OperationalError("no such module: fts5")
                raise AssertionError("unexpected execute")

        class BrokenConnection:
            def execute(self, sql: str, *args: object) -> "BrokenCursor":
                return self.cursor().execute(sql, *args)

            def cursor(self) -> "BrokenCursor":
                return BrokenCursor()

            def close(self) -> None:
                pass

        def fake_connect(*args: object, **kwargs: object) -> "BrokenConnection":
            return BrokenConnection()

        monkeypatch.setattr(sqlite3, "connect", fake_connect)
        with pytest.raises(FtsUnavailableError) as excinfo:
            ensure_fts5_available()
        assert "FTS5" in str(excinfo.value)
