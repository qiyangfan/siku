"""wiki 生成编排：加载图谱三件表 → 逐社区摘要（缓存优先）→ 渲染写盘。

摘要失败（五剧本任一）即中止且不写任何 wiki 文件；
成功摘要逐社区入缓存（summary 命名空间，键含独立 prompt 版本），
wiki 全量重建时零次 LLM 调用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from siku.graph.cache import ExtractionCache
from siku.graph.community import SummaryIdentity, internal_relation_triples, summary_cache_key
from siku.graph.errors import GraphArtifactsStaleError
from siku.graph.store import cache_file_path, load_graph
from siku.wiki.render import entry_file_name, render_entry, render_index, write_wiki
from siku.wiki.summarizer import Summarizer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WikiResult:
    """一次 wiki 生成的统计；全部字段进 CLI `--json` 稳定输出。"""

    entry_count: int
    cache_hits: int
    llm_calls: int
    empty_graph: bool


def generate_wiki(data_dir: Path, summarizer: Summarizer) -> WikiResult:
    """依据图谱产物与社区摘要缓存生成 wiki 总目；图谱缺失抛领域错误。"""
    entities, relations, communities = load_graph(data_dir)
    entity_by_id = {entity.entity_id: entity for entity in entities}
    cache = ExtractionCache(cache_file_path(data_dir))
    index_rows: list[tuple[str, str, int, int]] = []
    entry_files: dict[str, str] = {}
    cache_hits = 0
    llm_calls = 0
    try:
        for community in communities:
            member_ids = set(community.member_entity_ids)
            members = [
                entity_by_id[entity_id]
                for entity_id in community.member_entity_ids
                if entity_id in entity_by_id
            ]
            internal_relations = [
                relation
                for relation in relations
                if relation.source_entity_id in member_ids
                and relation.target_entity_id in member_ids
            ]
            # 缓存键以图谱构建阶段写入 parquet 的为准（单一事实源）；
            # wiki 阶段用同一函数现算键做一致性校验：摘要身份与图谱构建时
            # 不一致（换摘要模型/旧版本产物）时显式失效，禁止静默复用旧缓存
            triples = internal_relation_triples(relations, member_ids)
            identity = SummaryIdentity(
                summarizer_id=summarizer.summarizer_id,
                model_id=summarizer.model_id,
                prompt_version=summarizer.prompt_version,
            )
            expected_key = summary_cache_key(members, triples, identity)
            if expected_key != community.summary_cache_key:
                raise GraphArtifactsStaleError(
                    f"Community {community.community_id} summary key was built with "
                    "a different summarizer identity; run 'siku graph' to rebuild "
                    "the graph artifacts"
                )
            cache_key = community.summary_cache_key
            summary = cache.get_summary(cache_key)
            if summary is not None:
                cache_hits += 1
            else:
                logger.info(
                    "summarizing community via LLM: community_id=%d model=%s",
                    community.community_id,
                    summarizer.model_id,
                )
                summary = summarizer.summarize(tuple(members), tuple(internal_relations))
                llm_calls += 1
                # 只缓存成功摘要：失败剧本绝不留下空摘要
                cache.put_summary(cache_key, summary)
            file_name = entry_file_name(community.community_id)
            entry_files[file_name] = render_entry(
                community_id=community.community_id,
                summary=summary,
                members=members,
                relations=internal_relations,
            )
            # index 链接文本用短标题，条目全文经 entry_files 落到条目文件
            index_rows.append(
                (
                    f"社区 {community.community_id:04d}",
                    file_name,
                    len(members),
                    len(internal_relations),
                )
            )
    finally:
        cache.close()

    index_content = render_index(index_rows)
    write_wiki(data_dir, entry_files, index_content)
    logger.info(
        "wiki generated: entries=%d cache_hits=%d llm_calls=%d",
        len(entry_files),
        cache_hits,
        llm_calls,
    )
    return WikiResult(
        entry_count=len(entry_files),
        cache_hits=cache_hits,
        llm_calls=llm_calls,
        empty_graph=not communities,
    )
