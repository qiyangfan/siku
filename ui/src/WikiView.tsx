import { useCallback, useEffect, useRef, useState } from "react";
import {
  buildGraph,
  generateWiki,
  getWikiEntries,
  getWikiEntry,
  type ApiError,
  type WikiEntryDetail,
  type WikiEntries,
} from "./api";
import { handleMarkdownClick, renderMarkdown } from "./markdown";

function isApiError(error: unknown): error is ApiError {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    typeof error.code === "string" &&
    "message" in error &&
    typeof error.message === "string"
  );
}

function connectionFallback(caught: unknown): string {
  return isApiError(caught)
    ? caught.message
    : "无法连接本地内核，请确认 siku serve 已启动。";
}

function formatGeneratedAt(iso: string): string {
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) {
    return iso;
  }
  return moment.toLocaleString();
}

// 图谱产物缺失的稳定错误码（HTTP 层归一）：生成请求实测发现后切换为构建引导
function isGraphMissingCode(caught: unknown): boolean {
  return (
    isApiError(caught) &&
    (caught.code === "graph_artifacts_missing" || caught.code === "graph_missing")
  );
}

export function WikiView() {
  const [listing, setListing] = useState<WikiEntries | null>(null);
  const [missing, setMissing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<WikiEntryDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [buildingGraph, setBuildingGraph] = useState(false);
  // 图谱产物缺失被生成请求实测发现后置位，空态由「生成 wiki」切换为「构建图谱」两段式引导
  const [graphMissingKnown, setGraphMissingKnown] = useState(false);
  const [flowNote, setFlowNote] = useState<string | null>(null);
  const [generateError, setGenerateError] = useState<string | null>(null);
  // 各异步操作独立序号防竞态：慢响应不得覆盖同类新操作；
  // 跨操作不共用序号，避免被否决方的 loading 旗标永久卡死
  const listingSeqRef = useRef(0);
  const detailSeqRef = useRef(0);
  const generateSeqRef = useRef(0);
  const buildSeqRef = useRef(0);

  const loadListing = useCallback(async () => {
    const seq = ++listingSeqRef.current;
    try {
      const next = await getWikiEntries();
      if (seq !== listingSeqRef.current) {
        return;
      }
      setListing(next);
      setMissing(false);
      setLoadError(null);
    } catch (caught: unknown) {
      if (seq !== listingSeqRef.current) {
        return;
      }
      if (isApiError(caught) && caught.code === "wiki_missing") {
        setMissing(true);
      } else {
        setLoadError(connectionFallback(caught));
      }
    }
  }, []);

  useEffect(() => {
    void loadListing();
  }, [loadListing]);

  // wiki 生成（等价 `siku wiki`，全量幂等）；返回是否成功，供图谱构建后续跑判定。
  // 真实 LLM 摘要可达分钟级，请求期不设前端超时
  const runGenerate = useCallback(async (): Promise<boolean> => {
    const seq = ++generateSeqRef.current;
    setGenerating(true);
    setGenerateError(null);
    setFlowNote(null);
    try {
      const report = await generateWiki();
      if (seq !== generateSeqRef.current) {
        return false;
      }
      // 200 即证明图谱产物存在：无论是否 empty_graph 都先清除历史缺失旗标，
      // 防空态卡残留「图谱尚未构建」的过期引导（如构建成功但零社区的场景）
      setGraphMissingKnown(false);
      if (report.empty_graph) {
        setFlowNote("图谱中没有可摘要的社区，未产出 wiki 条目。");
        return false;
      }
      setFlowNote(`wiki 已生成：${report.entries} 个条目（LLM 调用 ${report.llm_calls} 次）。`);
      return true;
    } catch (caught: unknown) {
      if (seq !== generateSeqRef.current) {
        return false;
      }
      if (isGraphMissingCode(caught)) {
        setGraphMissingKnown(true);
      } else {
        setGenerateError(connectionFallback(caught));
      }
      return false;
    } finally {
      if (seq === generateSeqRef.current) {
        setGenerating(false);
      }
    }
  }, []);

  // 生成成功后刷新清单并清空旧选中条目：重新生成可能改写内容，防新旧同屏误读
  const runGenerateAndRefresh = useCallback(async () => {
    const ok = await runGenerate();
    if (!ok) {
      return;
    }
    setSelected(null);
    await loadListing();
  }, [runGenerate, loadListing]);

  // 空态两段式后半段：图谱构建成功后自动续跑 wiki 生成（用户意图就是要 wiki）
  const runBuildGraphThenGenerate = useCallback(async () => {
    const seq = ++buildSeqRef.current;
    setBuildingGraph(true);
    setGenerateError(null);
    setFlowNote(null);
    try {
      const report = await buildGraph();
      if (seq !== buildSeqRef.current) {
        return;
      }
      if (report.empty_corpus) {
        // 空语料已落空产物，继续生成 wiki 只会得到 empty_graph，
        // 就地停在可行动的引导上（导入笔记）比报「无可摘要社区」更有用
        setFlowNote("语料为空：图谱为空、无可生成内容；请先在「资料库」导入笔记。");
        return;
      }
    } catch (caught: unknown) {
      if (seq === buildSeqRef.current) {
        setGenerateError(connectionFallback(caught));
      }
      return;
    } finally {
      if (seq === buildSeqRef.current) {
        setBuildingGraph(false);
      }
    }
    await runGenerateAndRefresh();
  }, [runGenerateAndRefresh]);

  const openEntry = useCallback(async (communityId: number) => {
    const seq = ++detailSeqRef.current;
    setLoadingDetail(true);
    setDetailError(null);
    try {
      const detail = await getWikiEntry(communityId);
      if (seq !== detailSeqRef.current) {
        return;
      }
      setSelected(detail);
    } catch (caught: unknown) {
      if (seq !== detailSeqRef.current) {
        return;
      }
      // 清掉旧内容：错误卡不得与上一条正文同屏造成误读
      setSelected(null);
      setDetailError(connectionFallback(caught));
    } finally {
      if (seq === detailSeqRef.current) {
        setLoadingDetail(false);
      }
    }
  }, []);

  if (missing) {
    return (
      <section className="wiki-view" aria-labelledby="wiki-title">
        <div className="wiki-header">
          <div>
            <h2 id="wiki-title">wiki</h2>
            <p className="hint">LLM 生成的社区总目，只读阅读。</p>
          </div>
        </div>
        <div className="library-empty" role="note">
          <strong>wiki 尚未生成</strong>
          {graphMissingKnown ? (
            <p>
              wiki 由图谱社区摘要生成，而图谱尚未构建；先构建图谱（使用「设置」中配置的
              LLM 通道，可能需要几分钟），完成后自动继续生成 wiki。
            </p>
          ) : (
            <p>
              wiki 由图谱社区摘要生成，使用「设置」中配置的 LLM 通道；生成可能需要几分钟。
            </p>
          )}
          {flowNote !== null && (
            <p className="hint" role="status">
              {flowNote}
            </p>
          )}
          {generateError !== null && (
            <p className="message message-error" role="alert">
              {generateError}
            </p>
          )}
          {/* 生成成功但清单刷新失败（loadListing 内部吞错）不得静默 */}
          {loadError !== null && (
            <p className="message message-error" role="alert">
              {loadError}
            </p>
          )}
          {loadError !== null && (
            <button
              type="button"
              className="button-secondary"
              disabled={generating || buildingGraph}
              onClick={() => void loadListing()}
            >
              重试读取
            </button>
          )}
          {graphMissingKnown ? (
            <button
              type="button"
              className="button-secondary"
              disabled={buildingGraph || generating}
              onClick={() => void runBuildGraphThenGenerate()}
            >
              {buildingGraph
                ? "构建中…（可能需要几分钟）"
                : generating
                  ? "生成中…（可能需要几分钟）"
                  : "构建图谱"}
            </button>
          ) : (
            <button
              type="button"
              className="button-secondary"
              disabled={generating || buildingGraph}
              onClick={() => void runGenerateAndRefresh()}
            >
              {generating ? "生成中…（可能需要几分钟）" : "生成 wiki"}
            </button>
          )}
        </div>
      </section>
    );
  }

  if (loadError !== null && listing === null) {
    return (
      <div className="status-card status-error" role="alert">
        <div>
          <strong>wiki 清单读取失败</strong>
          <p>{loadError}</p>
        </div>
        <button type="button" className="button-secondary" onClick={() => void loadListing()}>
          重试读取
        </button>
      </div>
    );
  }

  if (listing === null) {
    return (
      <div className="settings-loading" role="status" aria-live="polite">
        正在读取 wiki 条目…
      </div>
    );
  }

  return (
    <section className="wiki-view" aria-labelledby="wiki-title">
      <div className="wiki-header">
        <div>
          <h2 id="wiki-title">wiki</h2>
          <p className="hint">共 {listing.entries.length} 个社区条目；内容由模型基于语料生成。</p>
        </div>
        <div className="wiki-header-actions">
          <button
            type="button"
            className="button-secondary"
            disabled={generating || buildingGraph}
            onClick={() => void runGenerateAndRefresh()}
          >
            {generating ? "生成中…（可能需要几分钟）" : "重新生成 wiki"}
          </button>
        </div>
      </div>

      {flowNote !== null && (
        <p className="hint" role="status">
          {flowNote}
        </p>
      )}
      {generateError !== null && (
        <p className="message message-error" role="alert">
          {generateError}
        </p>
      )}
      {/* 已建态重新生成遇图谱产物缺失：graphMissingKnown 只驱动空态卡片切换，
          此处若不显式给出反馈就是静默失败（违反「失败 SHALL 展示 message」） */}
      {graphMissingKnown && listing !== null && (
        <p className="message message-error" role="alert">
          图谱产物缺失：请先在「图谱」视图构建图谱，再重新生成 wiki。
        </p>
      )}
      {/* 已建态数据保留时 loadError 无渲染落点（全屏错误卡仅在 listing===null）：
          生成成功但清单刷新失败必须显式告警，防清单静默陈旧 */}
      {loadError !== null && (
        <div className="status-card status-error" role="alert">
          <div>
            <strong>wiki 清单刷新失败</strong>
            <p>{loadError}</p>
          </div>
          <button type="button" className="button-secondary" onClick={() => void loadListing()}>
            重试读取
          </button>
        </div>
      )}

      {listing.entries.length === 0 ? (
        <div className="library-empty" role="note">
          <strong>还没有 wiki 条目</strong>
          <p>
            图谱中没有可摘要的社区；导入更多笔记并「更新图谱」后，点击上方
            「重新生成 wiki」再试。
          </p>
        </div>
      ) : (
        <div className="wiki-layout">
          <ul className="wiki-list" aria-label="wiki 条目清单">
            {listing.entries.map((entry) => (
              <li key={entry.community_id}>
                <button
                  type="button"
                  className={
                    selected?.community_id === entry.community_id
                      ? "wiki-item wiki-item-active"
                      : "wiki-item"
                  }
                  onClick={() => void openEntry(entry.community_id)}
                >
                  <span className="wiki-item-title">{entry.title}</span>
                  <span className="wiki-item-time">生成于 {formatGeneratedAt(entry.generated_at)}</span>
                </button>
              </li>
            ))}
          </ul>

          <div className="wiki-pane">
            {loadingDetail && (
              <p className="settings-loading" role="status" aria-live="polite">
                正在加载条目…
              </p>
            )}
            {detailError !== null && (
              <div className="status-card status-error" role="alert">
                <div>
                  <strong>条目读取失败</strong>
                  <p>{detailError}</p>
                </div>
              </div>
            )}
            {!loadingDetail && selected !== null && (
              <article className="wiki-reader" aria-labelledby="wiki-entry-title">
                <header className="wiki-reader-head">
                  <h3 id="wiki-entry-title">{selected.title}</h3>
                  <p className="wiki-freshness" role="note">
                    生成于 {formatGeneratedAt(selected.generated_at)} ·
                    图谱更新后可点击「重新生成 wiki」刷新总目
                  </p>
                </header>
                <div
                  className="markdown-body"
                  onClick={handleMarkdownClick}
                  // 内容经 renderMarkdown（DOMPurify 清洗）产出安全只读 HTML，
                  // 链接导航经 handleMarkdownClick 拦截（只读视图不跳转）
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(selected.content) }}
                />
              </article>
            )}
            {!loadingDetail && selected === null && detailError === null && (
              <div className="library-empty" role="note">
                <strong>从左侧选择一个条目</strong>
                <p>条目按社区编号排列，汇总该社区实体的摘要与关键关系。</p>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

export default WikiView;
