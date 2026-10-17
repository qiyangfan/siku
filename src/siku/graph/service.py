"""图谱构建编排：扫描 chunk → 缓存优先抽取 → 合并 → 社区发现 → parquet 落盘。

编排纪律（design.md）：
- 逐 chunk 抽取成功即写缓存，中断后重跑自动续传；
- 全部产物在抽取完成后一次性落盘，失败不写半成品图谱；
- `--rebuild` 忽略缓存强制重抽；换模型/换 prompt 版本由缓存键变化显式失效。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from siku.graph.cache import ExtractionCache, extraction_cache_key
from siku.graph.community import (
    DEFAULT_SUMMARY_IDENTITY,
    SummaryIdentity,
    build_memory_graph,
    detect_communities,
    internal_relation_triples,
    summary_cache_key,
)
from siku.graph.merge import merge_extractions
from siku.graph.models import Community, GraphExtraction, GraphExtractor
from siku.graph.report import GraphHealthReport, scale_warnings
from siku.graph.store import cache_file_path, save_graph
from siku.retrieve.errors import NotesDirMissingError
from siku.retrieve.models import ChunkRecord
from siku.retrieve.notes_reader import read_note

logger = logging.getLogger(__name__)

VAULT_NOTES_DIR = "notes"


@dataclass(frozen=True)
class GraphBuildResult:
    """一次图谱构建的产出：体检报告 + 语料是否为空的标记。"""

    report: GraphHealthReport
    empty_corpus: bool


def load_chunks(vault: Path) -> tuple[ChunkRecord, ...]:
    """扫描 `vault/notes/` 全部投影并解析为 chunk 序列（阅读顺序）。

    复用 `retrieve.notes_reader` 的解析器，本模块不重复实现投影解析。
    """
    notes_dir = vault / VAULT_NOTES_DIR
    if not notes_dir.is_dir():
        raise NotesDirMissingError(f"No notes directory under vault: {notes_dir}")
    chunks: list[ChunkRecord] = []
    for note in sorted(path for path in notes_dir.rglob("*.md") if path.is_file()):
        _, note_chunks = read_note(note, vault)
        chunks.extend(note_chunks)
    return tuple(chunks)


def build_graph(
    vault: Path,
    data_dir: Path,
    extractor: GraphExtractor,
    *,
    rebuild: bool = False,
    summary_identity: SummaryIdentity = DEFAULT_SUMMARY_IDENTITY,
) -> GraphBuildResult:
    """构建图谱并落盘三件 parquet，返回体检报告。

    `summary_identity` 是社区摘要缓存键的摘要器身份，必须与后续 `siku wiki`
    所用摘要器一致（CLI 两命令均默认 DeepSeek，常量同源）；
    wiki 阶段直接消费 parquet 中存储的键并校验身份一致性。
    """
    chunks = load_chunks(vault)
    cache = ExtractionCache(cache_file_path(data_dir))
    pairs: list[tuple[ChunkRecord, GraphExtraction]] = []
    cache_hits = 0
    llm_calls = 0
    try:
        for chunk in chunks:
            cache_key = extraction_cache_key(
                chunk.chunk_id,
                extractor.extractor_id,
                extractor.model_id,
                extractor.prompt_version,
            )
            extraction = None if rebuild else cache.get_extraction(cache_key)
            if extraction is not None:
                cache_hits += 1
            else:
                logger.info(
                    "extracting chunk via LLM: chunk_id=%s extractor=%s model=%s",
                    chunk.chunk_id,
                    extractor.extractor_id,
                    extractor.model_id,
                )
                extraction = extractor.extract(chunk)
                llm_calls += 1
                # 逐 chunk 落缓存：中断重跑自动续传，不重复烧 key
                cache.put_extraction(cache_key, extraction)
            pairs.append((chunk, extraction))

        merged = merge_extractions(pairs)
        memory_graph = build_memory_graph(merged.entities, merged.relations)
        member_groups = detect_communities(memory_graph)
        entity_by_id = {entity.entity_id: entity for entity in merged.entities}
        communities = tuple(
            Community(
                community_id=community_id,
                member_entity_ids=members,
                level=0,
                # 键指纹须覆盖摘要 prompt 全部输入（成员展示名/类型在内），
                # 与 wiki 阶段的过期校验共用同一函数（community.py 单一定义点）
                summary_cache_key=summary_cache_key(
                    [entity_by_id[member] for member in members],
                    internal_relation_triples(merged.relations, set(members)),
                    identity=summary_identity,
                ),
            )
            for community_id, members in enumerate(member_groups)
        )
        save_graph(data_dir, merged.entities, merged.relations, communities)
        # 产物发布成功才记录抽取器身份：自动维护的资格闸门据此比对（design D3）；
        # 构建失败不落身份，避免把旧产物的身份误记为当前通道
        cache.put_build_identity(
            extractor.extractor_id, extractor.model_id, extractor.prompt_version
        )
    finally:
        cache.close()

    report = GraphHealthReport(
        extractor_id=extractor.extractor_id,
        model_id=extractor.model_id,
        prompt_version=extractor.prompt_version,
        chunk_count=len(chunks),
        node_count=memory_graph.number_of_nodes(),
        edge_count=memory_graph.number_of_edges(),
        community_count=len(communities),
        ambiguous_entity_count=len(merged.ambiguous_entity_names),
        cache_hits=cache_hits,
        llm_calls=llm_calls,
        warnings=scale_warnings(edge_count=memory_graph.number_of_edges()),
    )
    logger.info(
        "graph built: nodes=%d edges=%d communities=%d cache_hits=%d llm_calls=%d",
        report.node_count,
        report.edge_count,
        report.community_count,
        cache_hits,
        llm_calls,
    )
    return GraphBuildResult(report=report, empty_corpus=not chunks)
