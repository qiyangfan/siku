import { useCallback, useEffect, useRef, useState } from "react";
import {
  cancelLibraryJob,
  getLibrary,
  getLibraryJob,
  ingestFiles,
  rebuildIndex,
  type ApiError,
  type LibraryIndexStatus,
  type LibraryIngestStatus,
  type LibraryJob,
  type LibraryJobItemStatus,
  type LibrarySource,
} from "./api";

const POLL_INTERVAL_MS = 500;

const INGEST_STATUS_LABEL: Record<LibraryIngestStatus, string> = {
  ingested: "已摄取",
  stale: "待重抽",
  pending: "待摄取",
  ignored: "已忽略",
};

const INDEX_STATUS_LABEL: Record<LibraryIndexStatus, string> = {
  indexed: "已索引",
  stale: "索引待更新",
  missing: "未索引",
};

const ITEM_STATUS_LABEL: Record<LibraryJobItemStatus, string> = {
  created: "新建",
  updated: "更新",
  skipped: "跳过（内容未变化）",
  ignored: "已忽略",
  failed: "失败",
};

const SUPPORTED_FORMATS = "PDF、Word、PPT、Excel、EPUB、HTML、Markdown";

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

function jobOutcome(job: LibraryJob): { tone: "ok" | "error"; text: string } | null {
  if (job.state === "running") {
    return null;
  }
  if (job.state === "cancelled") {
    return { tone: "error", text: `任务已取消（完成 ${job.done}/${job.total}），已完成部分保留。` };
  }
  if (job.state === "failed") {
    return { tone: "error", text: job.error ?? "任务执行失败，请重试。" };
  }
  if (job.kind === "rebuild") {
    return { tone: "ok", text: "索引全量重建完成。" };
  }
  const succeeded = job.items.filter((item) =>
    item.status === "created" || item.status === "updated" || item.status === "skipped",
  ).length;
  const failedText = job.failed > 0 ? `，${job.failed} 个失败` : "";
  return { tone: "ok", text: `导入完成：${succeeded} 个文件成功${failedText}。` };
}

export function LibraryView() {
  const [sources, setSources] = useState<LibrarySource[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [job, setJob] = useState<LibraryJob | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmingRebuild, setConfirmingRebuild] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refreshListing = useCallback(async () => {
    try {
      const view = await getLibrary();
      setSources(view.sources);
      setLoadError(null);
    } catch (caught: unknown) {
      setLoadError(connectionFallback(caught));
    }
  }, []);

  useEffect(() => {
    void refreshListing();
  }, [refreshListing]);

  const pollJob = useCallback(
    async (jobId: string) => {
      try {
        const snapshot = await getLibraryJob(jobId);
        setJob(snapshot);
        if (snapshot.state !== "running") {
          void refreshListing();
        }
      } catch (caught: unknown) {
        setJob(null);
        setActionError(connectionFallback(caught));
      }
    },
    [refreshListing],
  );

  useEffect(() => {
    if (job === null || job.state !== "running") {
      return;
    }
    const handle = window.setTimeout(() => void pollJob(job.job_id), POLL_INTERVAL_MS);
    return () => window.clearTimeout(handle);
  }, [job, pollJob]);

  const startImport = async (fileList: FileList | null) => {
    const files = fileList === null ? [] : Array.from(fileList);
    if (files.length === 0) {
      return;
    }
    setActionError(null);
    setJob(null);
    try {
      setJob(await ingestFiles(files));
    } catch (caught: unknown) {
      setActionError(connectionFallback(caught));
    } finally {
      if (fileInputRef.current !== null) {
        fileInputRef.current.value = "";
      }
    }
  };

  const cancelCurrentJob = async () => {
    if (job === null) {
      return;
    }
    setActionError(null);
    try {
      setJob(await cancelLibraryJob(job.job_id));
    } catch (caught: unknown) {
      setActionError(connectionFallback(caught));
    }
  };

  const startRebuild = async () => {
    setConfirmingRebuild(false);
    setActionError(null);
    setJob(null);
    try {
      setJob(await rebuildIndex());
    } catch (caught: unknown) {
      setActionError(connectionFallback(caught));
    }
  };

  if (loadError !== null && sources === null) {
    return (
      <div className="status-card status-error" role="alert">
        <div>
          <strong>资料库读取失败</strong>
          <p>{loadError}</p>
        </div>
        <button type="button" className="button-secondary" onClick={() => void refreshListing()}>
          重试读取
        </button>
      </div>
    );
  }

  if (sources === null) {
    return (
      <div className="settings-loading" role="status" aria-live="polite">
        正在读取资料库…
      </div>
    );
  }

  const outcome = job === null ? null : jobOutcome(job);
  const running = job !== null && job.state === "running";
  const indexing = running && job.phase === "indexing";
  const itemCountOk = job !== null && job.total > 0;

  return (
    <section className="library-view" aria-labelledby="library-title">
      <div className="library-toolbar">
        <div>
          <h2 id="library-title">资料库</h2>
          <p className="hint">导入即摄取为本地事实层，并自动同步检索索引。</p>
        </div>
        <div className="library-actions">
          <input
            ref={fileInputRef}
            id="library-file-input"
            className="visually-hidden"
            type="file"
            multiple
            aria-label="选择要导入的文件"
            disabled={running}
            onChange={(event) => void startImport(event.target.files)}
          />
          <button
            type="button"
            disabled={running}
            onClick={() => fileInputRef.current?.click()}
          >
            {running ? "任务进行中…" : "导入文件"}
          </button>
          <button
            type="button"
            className="button-secondary"
            disabled={running}
            onClick={() => setConfirmingRebuild(true)}
          >
            全量重建索引
          </button>
        </div>
      </div>

      {actionError !== null && (
        <p className="message message-error" role="alert">
          {actionError}
        </p>
      )}

      {job !== null && running && (
        <div className="status-card status-running" role="status" aria-live="polite">
          <div className="library-progress">
            <strong>
              {indexing
                ? "正在同步检索索引…"
                : job.kind === "rebuild"
                  ? "正在全量重建索引…"
                  : `正在摄取（${job.done}/${job.total}）`}
            </strong>
            {indexing === false && job.current !== null && (
              <p className="library-current-file">{job.current}</p>
            )}
            {itemCountOk && !indexing && (
              <progress
                className="library-progress-bar"
                value={job.done}
                max={job.total}
                aria-label={`摄取进度 ${job.done}/${job.total}`}
              />
            )}
          </div>
          {job.kind === "ingest" && !indexing && (
            <button type="button" className="button-secondary" onClick={() => void cancelCurrentJob()}>
              取消任务
            </button>
          )}
        </div>
      )}

      {outcome !== null && job !== null && (
        <div
          className={`status-card ${outcome.tone === "ok" ? "status-saved" : "status-error"}`}
          role={outcome.tone === "ok" ? "status" : "alert"}
        >
          <div>
            <strong>{outcome.text}</strong>
            {job.items.some((item) => item.status === "failed" || item.status === "ignored") && (
              <ul className="library-item-results">
                {job.items
                  .filter((item) => item.status === "failed" || item.status === "ignored")
                  .map((item) => (
                    <li key={`${item.status}-${item.name}`}>
                      {item.name}：{ITEM_STATUS_LABEL[item.status]}
                      {item.detail !== null && `——${item.detail}`}
                    </li>
                  ))}
              </ul>
            )}
          </div>
          <button type="button" className="button-secondary" onClick={() => setJob(null)}>
            关闭
          </button>
        </div>
      )}

      {sources.length === 0 ? (
        <div className="library-empty" role="note">
          <strong>资料库还是空的</strong>
          <p>点击「导入文件」把本地文档加入知识库；导入的文件会被复制进资料库并抽取为可检索的知识，原文件保持不变。</p>
          <p className="hint">支持格式：{SUPPORTED_FORMATS}。</p>
        </div>
      ) : (
        <ul className="library-list" aria-label="资料库来源清单">
          {sources.map((source) => (
            <li key={source.path} className="library-row">
              <span className="library-name" title={source.path}>
                {source.name}
              </span>
              <span className={`library-badge library-badge-ingest-${source.ingest_status}`}>
                {INGEST_STATUS_LABEL[source.ingest_status]}
              </span>
              <span className={`library-badge library-badge-index-${source.index_status}`}>
                {INDEX_STATUS_LABEL[source.index_status]}
              </span>
            </li>
          ))}
        </ul>
      )}

      {confirmingRebuild && (
        <div className="library-dialog-backdrop">
          <div
            className="status-card library-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="rebuild-confirm-title"
          >
            <div>
              <strong id="rebuild-confirm-title">确认全量重建索引？</strong>
              <p>
                重建会按当前 embedding 配置重算全部向量并替换现有索引；语料原件与投影不受影响。
                资料库较大时耗时较长。
              </p>
            </div>
            <div className="library-dialog-actions">
              <button
                type="button"
                className="button-secondary"
                onClick={() => setConfirmingRebuild(false)}
              >
                取消
              </button>
              <button type="button" onClick={() => void startRebuild()}>
                确认重建
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

export default LibraryView;
