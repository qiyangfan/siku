import { useCallback, useEffect, useRef, useState } from "react";
import {
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

export function WikiView() {
  const [listing, setListing] = useState<WikiEntries | null>(null);
  const [missing, setMissing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<WikiEntryDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  // 各异步操作独立序号防竞态：慢响应不得覆盖同类新操作；
  // 跨操作不共用序号，避免被否决方的 loading 旗标永久卡死
  const listingSeqRef = useRef(0);
  const detailSeqRef = useRef(0);

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
          <p>
            wiki 由图谱社区摘要生成；请先在终端执行 <code>siku graph</code> 与{" "}
            <code>siku wiki</code>，完成后回到本视图。
          </p>
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
      </div>

      {listing.entries.length === 0 ? (
        <div className="library-empty" role="note">
          <strong>还没有 wiki 条目</strong>
          <p>
            构建图谱后执行 <code>siku wiki</code> 即可生成社区总目。
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
                    图谱更新后可在终端执行 <code>siku wiki</code> 重新生成
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
