import { useCallback, useEffect, useRef, useState } from "react";
import {
  addLibrarySource,
  cancelLibraryJob,
  getLibrary,
  getLibraryJob,
  getLibrarySources,
  getScanSettings,
  ingestFiles,
  purgeLibrary,
  rebuildIndex,
  removeLibrarySource,
  scanLibrarySources,
  setLibrarySourceEnabled,
  updateScanSettings,
  type ApiError,
  type LibraryIndexStatus,
  type LibraryIngestStatus,
  type LibraryJob,
  type LibraryJobItemStatus,
  type LibrarySource,
  type LibrarySyncSource,
} from "./api";

const POLL_INTERVAL_MS = 500;

const INGEST_STATUS_LABEL: Record<LibraryIngestStatus, string> = {
  ingested: "已摄取",
  stale: "待重抽",
  pending: "待摄取",
  ignored: "已忽略",
  missing: "来源缺失",
  superseded: "已被替代",
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
  removed: "已清理",
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
  if (job.kind === "purge") {
    const removed = job.items.filter((item) => item.status === "removed").length;
    return { tone: "ok", text: `清理完成：已物理移除 ${removed} 项标记文档。` };
  }
  if (job.kind === "scan") {
    // 检疫移位等动作与入库动作都以 updated 呈现，按「动作数」诚实计数
    const failedText = job.failed > 0 ? `，${job.failed} 项失败` : "";
    return { tone: "ok", text: `扫描完成：处理 ${job.done} 项动作${failedText}。` };
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

  // 来源目录管理区：默认折叠，首次展开才请求（避免干扰主清单的首屏）
  const [syncSectionOpen, setSyncSectionOpen] = useState(false);
  const [syncSources, setSyncSources] = useState<LibrarySyncSource[] | null>(null);
  const [syncLoadFailed, setSyncLoadFailed] = useState(false);
  const [newSourcePath, setNewSourcePath] = useState("");
  const [scanFull, setScanFull] = useState(false);
  const [intervalText, setIntervalText] = useState<string | null>(null);
  const [confirmingPurge, setConfirmingPurge] = useState(false);

  const refreshListing = useCallback(async () => {
    try {
      const view = await getLibrary();
      setSources(view.sources);
      setLoadError(null);
    } catch (caught: unknown) {
      setLoadError(connectionFallback(caught));
    }
  }, []);

  const refreshSyncSources = useCallback(async () => {
    try {
      const view = await getLibrarySources();
      setSyncSources(view.sources);
      setSyncLoadFailed(false);
    } catch {
      // 来源清单读不到时置空并标记失败，避免与「尚未登记来源目录」混排误导
      setSyncSources([]);
      setSyncLoadFailed(true);
    }
  }, []);

  const refreshScanSettings = useCallback(async () => {
    try {
      const settings = await getScanSettings();
      setIntervalText(String(settings.interval_secs));
    } catch {
      // 间隔读取失败不阻塞来源管理：输入留空即不展示保存
      setIntervalText(null);
    }
  }, []);

  useEffect(() => {
    void refreshListing();
  }, [refreshListing]);

  useEffect(() => {
    // 每次展开都重取：任务可能在收起期间结束，「上次扫描」等状态需保持新鲜
    if (syncSectionOpen) {
      void refreshSyncSources();
      void refreshScanSettings();
    }
  }, [syncSectionOpen, refreshSyncSources, refreshScanSettings]);

  const pollJob = useCallback(
    async (jobId: string) => {
      try {
        const snapshot = await getLibraryJob(jobId);
        setJob(snapshot);
        if (snapshot.state !== "running") {
          void refreshListing();
          // 扫描/清理任务可能改变了来源登记的 last_scan 等状态
          if (snapshot.kind === "scan" || snapshot.kind === "purge") {
            void refreshSyncSources();
          }
        }
      } catch (caught: unknown) {
        setJob(null);
        setActionError(connectionFallback(caught));
      }
    },
    [refreshListing, refreshSyncSources],
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

  const startScan = async () => {
    setActionError(null);
    setJob(null);
    try {
      setJob(await scanLibrarySources(scanFull));
    } catch (caught: unknown) {
      setActionError(connectionFallback(caught));
    }
  };

  const startPurge = async () => {
    setConfirmingPurge(false);
    setActionError(null);
    setJob(null);
    try {
      setJob(await purgeLibrary());
    } catch (caught: unknown) {
      setActionError(connectionFallback(caught));
    }
  };

  const submitNewSource = async () => {
    const trimmed = newSourcePath.trim();
    if (!trimmed) {
      return;
    }
    setActionError(null);
    try {
      await addLibrarySource(trimmed, true);
      setNewSourcePath("");
      await refreshSyncSources();
    } catch (caught: unknown) {
      setActionError(connectionFallback(caught));
    }
  };

  const toggleSyncSource = async (source: LibrarySyncSource) => {
    setActionError(null);
    try {
      await setLibrarySourceEnabled(source.id, !source.enabled);
      await refreshSyncSources();
    } catch (caught: unknown) {
      setActionError(connectionFallback(caught));
    }
  };

  const deleteSyncSource = async (source: LibrarySyncSource) => {
    setActionError(null);
    try {
      await removeLibrarySource(source.id);
      await refreshSyncSources();
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

  const saveInterval = async () => {
    const parsed = Number.parseInt(intervalText ?? "", 10);
    if (Number.isNaN(parsed) || parsed < 0) {
      setActionError("扫描间隔必须是不小于 0 的整数秒；0 表示关闭自动扫描。");
      return;
    }
    setActionError(null);
    try {
      const saved = await updateScanSettings(parsed);
      setIntervalText(String(saved.interval_secs));
    } catch (caught: unknown) {
      setActionError(connectionFallback(caught));
    }
  };

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
  const markedCount = sources.filter(
    (source) => source.ingest_status === "missing" || source.ingest_status === "superseded",
  ).length;
  const cancellable =
    running && (job.kind === "ingest" || job.kind === "scan" || job.kind === "purge");

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
            disabled={running || markedCount === 0}
            title={markedCount === 0 ? "没有已标记（缺失/已替代）的文档" : undefined}
            onClick={() => setConfirmingPurge(true)}
          >
            清理已标记文档{markedCount > 0 ? `（${markedCount}）` : ""}
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

      <div className="library-sync-header">
        <button
          type="button"
          className="button-secondary"
          aria-expanded={syncSectionOpen}
          onClick={() => setSyncSectionOpen((open) => !open)}
        >
          {syncSectionOpen ? "收起来源目录" : "来源目录与自动扫描"}
        </button>
        <p className="hint">
          登记本地目录后，内核定时扫描并把新增/变更文档单向复制入库；来源目录只读，永不写回。
        </p>
      </div>

      {syncSectionOpen && (
        <div className="library-sync-panel">
          <div className="library-sync-add">
            <input
              type="text"
              value={newSourcePath}
              onChange={(event) => setNewSourcePath(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void submitNewSource();
                }
              }}
              placeholder="本地目录绝对路径，例如 /Users/you/Documents/notes"
              aria-label="来源目录路径"
              spellCheck={false}
            />
            <button
              type="button"
              className="button-secondary"
              disabled={!newSourcePath.trim() || running}
              onClick={() => void submitNewSource()}
            >
              添加来源
            </button>
            <label className="library-sync-full">
              <input
                type="checkbox"
                checked={scanFull}
                onChange={(event) => setScanFull(event.target.checked)}
              />
              全量校验
            </label>
            <button
              type="button"
              className="button-secondary"
              disabled={running || syncSources === null}
              onClick={() => void startScan()}
            >
              立即扫描
            </button>
          </div>
          {intervalText !== null && (
            <div className="library-sync-add">
              <label className="library-sync-full" htmlFor="scan-interval-input">
                自动扫描间隔（秒，0 = 关闭）
              </label>
              <input
                id="scan-interval-input"
                type="number"
                min={0}
                value={intervalText}
                onChange={(event) => setIntervalText(event.target.value)}
                aria-label="自动扫描间隔秒数"
              />
              <button
                type="button"
                className="button-secondary"
                disabled={running}
                onClick={() => void saveInterval()}
              >
                保存间隔
              </button>
            </div>
          )}
          {syncSources === null ? (
            <p className="hint" role="status">
              正在读取来源目录…
            </p>
          ) : syncLoadFailed ? (
            <p className="hint" role="note">
              来源目录清单读取失败，请确认内核连接后重试。
            </p>
          ) : syncSources.length === 0 ? (
            <p className="hint" role="note">
              尚未登记来源目录。添加后内核按下方设定的间隔自动扫描，也可点击「立即扫描」。
            </p>
          ) : (
            <ul className="library-sync-list" aria-label="来源目录清单">
              {syncSources.map((source) => (
                <li key={source.id} className="library-sync-row">
                  <span className="library-sync-path" title={source.path}>
                    {source.path}
                  </span>
                  <span className={`library-badge library-badge-sync-${source.enabled ? "on" : "off"}`}>
                    {source.enabled ? "已启用" : "已停用"}
                  </span>
                  <span className="library-sync-time">
                    {source.last_scan_at === null
                      ? "从未扫描"
                      : `上次扫描 ${new Date(source.last_scan_at).toLocaleString()}`}
                  </span>
                  <button
                    type="button"
                    className="button-secondary"
                    disabled={running}
                    onClick={() => void toggleSyncSource(source)}
                  >
                    {source.enabled ? "停用" : "启用"}
                  </button>
                  <button
                    type="button"
                    className="button-secondary"
                    disabled={running}
                    onClick={() => void deleteSyncSource(source)}
                  >
                    移除
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

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
                  : job.kind === "scan"
                    ? `正在扫描（${job.done}/${job.total}）`
                    : job.kind === "purge"
                      ? `正在清理（${job.done}/${job.total}）`
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
                aria-label={`任务进度 ${job.done}/${job.total}`}
              />
            )}
          </div>
          {cancellable && (
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
          <p className="hint">支持格式：{SUPPORTED_FORMATS}。也可以展开「来源目录与自动扫描」登记一个本地目录，之后新文档会自动入库。</p>
        </div>
      ) : (
        <ul className="library-list" aria-label="资料库来源清单">
          {sources.map((source) => (
            <li key={source.path} className="library-row">
              <span className="library-name" title={source.path}>
                {source.name}
              </span>
              {source.origin_path !== null && (
                <span className="library-origin" title={source.origin_path}>
                  来自 {source.origin_path}
                </span>
              )}
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

      {confirmingPurge && (
        <div className="library-dialog-backdrop">
          <div
            className="status-card library-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="purge-confirm-title"
          >
            <div>
              <strong id="purge-confirm-title">确认清理 {markedCount} 项已标记文档？</strong>
              <p>
                将物理删除全部「来源缺失」与「已被替代」文档的原件与投影，并从索引中移除；此操作不可撤销。
              </p>
            </div>
            <div className="library-dialog-actions">
              <button
                type="button"
                className="button-secondary"
                onClick={() => setConfirmingPurge(false)}
              >
                取消
              </button>
              <button type="button" onClick={() => void startPurge()}>
                确认清理
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

export default LibraryView;
