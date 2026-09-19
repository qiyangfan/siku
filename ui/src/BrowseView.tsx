import { useCallback, useEffect, useRef, useState } from "react";
import { getNote, getNotes, type ApiError, type NoteDetail, type NotesPage } from "./api";
import { handleMarkdownClick, renderMarkdown } from "./markdown";

const PAGE_SIZE = 20;

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

export function BrowseView() {
  const [page, setPage] = useState<NotesPage | null>(null);
  const [selected, setSelected] = useState<NoteDetail | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  // 各异步操作独立序号防竞态：慢响应不得覆盖同类新操作；
  // 跨操作不共用序号，避免被否决方的 loading 旗标永久卡死
  const pageSeqRef = useRef(0);
  const detailSeqRef = useRef(0);

  const loadPage = useCallback(async (target: number) => {
    const seq = ++pageSeqRef.current;
    try {
      const next = await getNotes(target, PAGE_SIZE);
      if (seq !== pageSeqRef.current) {
        return;
      }
      setPage(next);
      setListError(null);
    } catch (caught: unknown) {
      if (seq !== pageSeqRef.current) {
        return;
      }
      setListError(connectionFallback(caught));
    }
  }, []);

  useEffect(() => {
    void loadPage(1);
  }, [loadPage]);

  const openNote = useCallback(async (sourceId: string) => {
    const seq = ++detailSeqRef.current;
    setLoadingDetail(true);
    setDetailError(null);
    try {
      const detail = await getNote(sourceId);
      if (seq !== detailSeqRef.current) {
        return;
      }
      setSelected(detail);
    } catch (caught: unknown) {
      if (seq !== detailSeqRef.current) {
        return;
      }
      // 清掉旧内容：错误卡不得与上一篇正文同屏造成误读
      setSelected(null);
      setDetailError(connectionFallback(caught));
    } finally {
      if (seq === detailSeqRef.current) {
        setLoadingDetail(false);
      }
    }
  }, []);

  if (listError !== null && page === null) {
    return (
      <div className="status-card status-error" role="alert">
        <div>
          <strong>浏览清单读取失败</strong>
          <p>{listError}</p>
        </div>
        <button type="button" className="button-secondary" onClick={() => void loadPage(1)}>
          重试读取
        </button>
      </div>
    );
  }

  if (page === null) {
    return (
      <div className="settings-loading" role="status" aria-live="polite">
        正在读取笔记清单…
      </div>
    );
  }

  const totalPages = Math.max(Math.ceil(page.total / page.page_size), 1);
  const emptyLibrary = page.total === 0;
  const emptyPage = !emptyLibrary && page.notes.length === 0;

  return (
    <section className="browse-view" aria-labelledby="browse-title">
      <div className="browse-toolbar">
        <div>
          <h2 id="browse-title">浏览</h2>
          <p className="hint">
            知识库共 {page.total} 篇笔记投影；只读阅读，原文以资料库为准。
          </p>
        </div>
      </div>

      {emptyLibrary ? (
        <div className="library-empty" role="note">
          <strong>还没有可阅读的笔记</strong>
          <p>先在资料库导入文档，摄取完成后的笔记投影会出现在这里。</p>
        </div>
      ) : (
        <div className="browse-layout">
          <div className="browse-pane">
            {emptyPage ? (
              <p className="settings-loading" role="status">
                本页无内容（共 {totalPages} 页），请返回上一页。
              </p>
            ) : (
              <ul className="browse-list" aria-label="笔记清单">
                {page.notes.map((note) => (
                  <li key={note.source_id}>
                    <button
                      type="button"
                      className={
                        selected?.source_id === note.source_id
                          ? "browse-item browse-item-active"
                          : "browse-item"
                      }
                      title={note.note_path}
                      onClick={() => void openNote(note.source_id)}
                    >
                      <span className="browse-item-name">{note.source_name}</span>
                      <span className="browse-item-path">{note.note_path}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {listError !== null && (
              <p className="message message-error" role="alert">
                {listError}
              </p>
            )}
            <div className="browse-pager">
              <button
                type="button"
                className="button-secondary"
                disabled={page.page <= 1}
                onClick={() => void loadPage(page.page - 1)}
              >
                上一页
              </button>
              <span className="hint">
                第 {page.page} / {totalPages} 页
              </span>
              <button
                type="button"
                className="button-secondary"
                disabled={page.page >= totalPages}
                onClick={() => void loadPage(page.page + 1)}
              >
                下一页
              </button>
            </div>
          </div>

          <div className="browse-pane">
            {loadingDetail && (
              <p className="settings-loading" role="status" aria-live="polite">
                正在加载笔记…
              </p>
            )}
            {detailError !== null && (
              <div className="status-card status-error" role="alert">
                <div>
                  <strong>笔记读取失败</strong>
                  <p>{detailError}</p>
                </div>
              </div>
            )}
            {!loadingDetail && selected !== null && (
              <article className="browse-reader" aria-labelledby="browse-note-title">
                <header className="browse-reader-head">
                  <h3 id="browse-note-title">{selected.source_name}</h3>
                  <p className="browse-meta">
                    <span title={selected.note_path}>{selected.note_path}</span>
                    <span>抽取器：{selected.extractor}</span>
                    <span className="browse-hash" title={selected.source_hash}>
                      源 {selected.source_hash.slice(0, 8)}
                    </span>
                  </p>
                  {selected.anchors.length > 0 && (
                    <p className="browse-anchors" aria-label="结构锚点">
                      {selected.anchors.map((anchor) => (
                        <span key={anchor} className="browse-anchor-chip">
                          {anchor}
                        </span>
                      ))}
                    </p>
                  )}
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
                <strong>从左侧选择一篇笔记</strong>
                <p>笔记由摄取管线从原件投影生成，此处只读展示，不可编辑。</p>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

export default BrowseView;
