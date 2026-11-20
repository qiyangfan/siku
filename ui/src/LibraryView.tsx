import { useCallback, useEffect, useRef, useState } from "react";
import { IconChevronDown } from "@tabler/icons-react";
import { Alert, Button, Group, Loader, SimpleGrid, Stack } from "@mantine/core";
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
  removeLibraryDocument,
  removeLibrarySource,
  scanLibrarySources,
  setLibrarySourceEnabled,
  updateScanSettings,
  type ApiError,
  type LibraryJob,
  type LibrarySource,
  type LibrarySyncSource,
} from "./api";
import {
  LibraryConfirmModals,
  LibraryJobStatus,
  LibrarySourcesSection,
  LibrarySyncSection,
  SUPPORTED_FORMATS,
} from "./LibraryPanels";

const POLL_INTERVAL_MS = 500;

// 文件选择器过滤与后端注册表同口径（ADR-0013）：旧二进制 Office 与扫描件不在
// 直接支持范围，选择阶段就引导转换，而不是提交后报错
const ACCEPTED_SUFFIXES =
  ".pdf,.docx,.pptx,.xlsx,.xlsm,.epub,.html,.htm,.md,.markdown";

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
    : "无法连接本地服务，请确认 siku serve --with-ui 正在运行。";
}

function jobOutcome(
  job: LibraryJob,
): { tone: "ok" | "error"; text: string } | null {
  if (job.state === "running") {
    return null;
  }
  if (job.state === "cancelled") {
    return {
      tone: "error",
      text: `任务已取消（完成 ${job.done}/${job.total}），已完成部分保留。`,
    };
  }
  if (job.state === "failed") {
    return { tone: "error", text: job.error ?? "任务执行失败，请重试。" };
  }
  if (job.kind === "rebuild") {
    return { tone: "ok", text: "索引全量重建完成。" };
  }
  if (job.kind === "remove") {
    return {
      tone: "ok",
      text: "已从资料库移除：受管副本与检索内容已清除，图谱与 Wiki 需重新构建（外部原件保留）。",
    };
  }
  if (job.kind === "purge") {
    const removed = job.items.filter(
      (item) => item.status === "removed",
    ).length;
    return { tone: "ok", text: `清理完成：已物理移除 ${removed} 项失效文档。` };
  }
  if (job.kind === "scan") {
    // 检疫移位与入库都呈现为 updated，按动作数计数。
    const failedText = job.failed > 0 ? `，${job.failed} 项失败` : "";
    return {
      tone: "ok",
      text: `扫描完成：处理 ${job.done} 项动作${failedText}。`,
    };
  }
  const succeeded = job.items.filter(
    (item) =>
      item.status === "created" ||
      item.status === "updated" ||
      item.status === "skipped",
  ).length;
  const failedText = job.failed > 0 ? `，${job.failed} 个失败` : "";
  return {
    tone: "ok",
    text: `导入完成：${succeeded} 个文件成功${failedText}。`,
  };
}

type LibraryViewProps = {
  /** 资料移除成功后派生知识（图谱/Wiki/建议缓存）已失效的向上通知 */
  onKnowledgeInvalidated?: () => void;
};

export function LibraryView({ onKnowledgeInvalidated }: LibraryViewProps) {
  const [sources, setSources] = useState<LibrarySource[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [job, setJob] = useState<LibraryJob | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmingRebuild, setConfirmingRebuild] = useState(false);
  // 导入投放区：原生 input[type=file] 承载系统文件选择器，拖拽经原生事件接收
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 来源目录管理区：默认折叠，展开才请求（避免干扰主清单的首屏）
  const [syncSectionOpen, setSyncSectionOpen] = useState(false);
  const [syncSources, setSyncSources] = useState<LibrarySyncSource[] | null>(
    null,
  );
  const [syncLoadFailed, setSyncLoadFailed] = useState(false);
  const [newSourcePath, setNewSourcePath] = useState("");
  const [scanFull, setScanFull] = useState(false);
  const [intervalText, setIntervalText] = useState<string | null>(null);
  const [graphAutoRefresh, setGraphAutoRefresh] = useState<boolean | null>(
    null,
  );
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

  // 单项移除确认框：仅服务端标记 removable（或移除未完成待重试）的条目进入
  const [removalTarget, setRemovalTarget] = useState<LibrarySource | null>(
    null,
  );

  const startRemoval = async (source: LibrarySource) => {
    if (source.source_id === null) {
      return;
    }
    setRemovalTarget(null);
    setActionError(null);
    setJob(null);
    try {
      setJob(await removeLibraryDocument(source.source_id));
    } catch (caught: unknown) {
      setActionError(connectionFallback(caught));
    }
  };

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
      setGraphAutoRefresh(settings.graph_auto_refresh ?? false);
    } catch {
      // 间隔读取失败不阻塞来源管理：输入留空即不展示保存
      setIntervalText(null);
      setGraphAutoRefresh(null);
    }
  }, []);

  useEffect(() => {
    // 取数落到异步续体：effect 体内不直接触发 setState，避免提交阶段级联渲染
    void Promise.resolve().then(refreshListing);
  }, [refreshListing]);

  useEffect(() => {
    // 每次展开都重取：任务可能在收起期间结束，「上次扫描」等状态需保持新鲜
    if (syncSectionOpen) {
      void Promise.resolve().then(refreshSyncSources);
      void Promise.resolve().then(refreshScanSettings);
    }
  }, [syncSectionOpen, refreshSyncSources, refreshScanSettings]);

  const pollJob = useCallback(
    async (jobId: string) => {
      try {
        const snapshot = await getLibraryJob(jobId);
        setJob(snapshot);
        if (snapshot.state !== "running") {
          void refreshListing();
          // 扫描/清理/移除任务可能改变来源登记与派生知识状态
          if (
            snapshot.kind === "scan" ||
            snapshot.kind === "purge" ||
            snapshot.kind === "remove"
          ) {
            void refreshSyncSources();
          }
          if (snapshot.kind === "remove" && snapshot.state === "succeeded") {
            // 旧图谱/Wiki/建议缓存已随移除失效：通知上层清理派生缓存
            onKnowledgeInvalidated?.();
          }
        }
      } catch (caught: unknown) {
        setJob(null);
        setActionError(connectionFallback(caught));
      }
    },
    [refreshListing, refreshSyncSources, onKnowledgeInvalidated],
  );

  useEffect(() => {
    if (job === null || job.state !== "running") {
      return;
    }
    const handle = window.setTimeout(
      () => void pollJob(job.job_id),
      POLL_INTERVAL_MS,
    );
    return () => window.clearTimeout(handle);
  }, [job, pollJob]);

  const startImport = async (files: File[]) => {
    if (files.length === 0) {
      return;
    }
    setActionError(null);
    setJob(null);
    try {
      setJob(await ingestFiles(files));
    } catch (caught: unknown) {
      setActionError(connectionFallback(caught));
    }
  };

  const startFilePickerImport = (files: FileList | null) => {
    // onChange 路径必须重置 input.value：同名文件再次选择不触发 change 事件
    if (files !== null && files.length > 0) {
      void startImport(Array.from(files));
    }
    if (fileInputRef.current !== null) {
      fileInputRef.current.value = "";
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
      <Alert
        className="status-card"
        color="red"
        role="alert"
        title="资料库读取失败"
      >
        <p>{loadError}</p>
        <Button
          variant="default"
          type="button"
          className="button-secondary"
          onClick={() => void refreshListing()}
        >
          重试读取
        </Button>
      </Alert>
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
      const saved = await updateScanSettings({ interval_secs: parsed });
      setIntervalText(String(saved.interval_secs));
    } catch (caught: unknown) {
      setActionError(connectionFallback(caught));
    }
  };

  const saveGraphAutoRefresh = async (enabled: boolean) => {
    setActionError(null);
    try {
      const saved = await updateScanSettings({ graph_auto_refresh: enabled });
      setGraphAutoRefresh(saved.graph_auto_refresh ?? false);
    } catch (caught: unknown) {
      setActionError(connectionFallback(caught));
    }
  };

  if (sources === null) {
    return (
      <Group
        className="settings-loading"
        role="status"
        aria-live="polite"
        gap="sm"
      >
        <Loader size="sm" />
        正在读取资料库…
      </Group>
    );
  }

  const outcome = job === null ? null : jobOutcome(job);
  const running = job !== null && job.state === "running";
  const indexing = running && job.phase === "indexing";
  const itemCountOk = job !== null && job.total > 0;
  const markedCount = sources.filter(
    (source) =>
      source.ingest_status === "missing" ||
      source.ingest_status === "superseded",
  ).length;
  const cancellable =
    running &&
    (job.kind === "ingest" ||
      job.kind === "scan" ||
      job.kind === "purge" ||
      job.kind === "remove");

  return (
    <Stack
      component="section"
      className="library-view"
      gap="lg"
      aria-labelledby="library-title"
    >
      <Group
        component="header"
        className="library-toolbar"
        align="flex-start"
        justify="space-between"
        wrap="wrap"
      >
        <div>
          <h2 id="library-title">资料库</h2>
          <p className="hint">导入即摄取为本地事实层，并自动同步检索索引。</p>
        </div>
        <Stack className="library-actions" gap="sm">
          <div
            className={`library-dropzone${dragActive ? " library-dropzone-active" : ""}`}
            role="button"
            tabIndex={0}
            aria-disabled={running}
            onClick={() => {
              if (!running) {
                fileInputRef.current?.click();
              }
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                if (!running) {
                  fileInputRef.current?.click();
                }
              }
            }}
            onDragOver={(event) => {
              event.preventDefault();
              if (!running) {
                setDragActive(true);
              }
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragActive(false);
              if (!running) {
                startFilePickerImport(event.dataTransfer.files);
              }
            }}
          >
            <strong className="library-dropzone-title">
              点击选择文件，或把文档拖到这里
            </strong>
            <span className="hint">
              {SUPPORTED_FORMATS}，可多选；导入即摄取，原文件保持不变。扫描件
              PDF 请先 OCR 为含文字版，旧 .doc/.ppt/.xls 请另存为现代格式。
            </span>
          </div>
          <input
            ref={fileInputRef}
            className="library-drop-input"
            type="file"
            multiple
            accept={ACCEPTED_SUFFIXES}
            tabIndex={-1}
            aria-label="选择要导入的文件"
            disabled={running}
            onChange={(event) => startFilePickerImport(event.target.files)}
          />
          <SimpleGrid
            className="library-action-buttons"
            cols={{ base: 1, sm: 2 }}
            spacing="sm"
          >
            <Button
              variant="default"
              type="button"
              className="button-danger"
              fullWidth
              disabled={running || markedCount === 0}
              title={
                markedCount === 0
                  ? "没有可清理的失效文档（来源缺失/已被替代）"
                  : `物理删除 ${markedCount} 项「来源缺失」或「已被替代」文档的原件与索引数据，不可撤销`
              }
              onClick={() => setConfirmingPurge(true)}
            >
              清理失效文档{markedCount > 0 ? `（${markedCount}）` : ""}
            </Button>
            <Button
              variant="default"
              type="button"
              className="button-secondary"
              fullWidth
              disabled={running}
              title="按当前 embedding 配置重算全部向量并替换现有索引；语料原件不受影响"
              onClick={() => setConfirmingRebuild(true)}
            >
              全量重建索引
            </Button>
          </SimpleGrid>
        </Stack>
      </Group>

      <div className="library-sync-header">
        <Button
          variant="subtle"
          type="button"
          className="library-sync-toggle"
          aria-expanded={syncSectionOpen}
          onClick={() => setSyncSectionOpen((open) => !open)}
        >
          {/* 折叠指示用图标组件而非几何字符：▾ 依赖系统字体，裸渲染环境会画成横线伪影 */}
          <span className="library-sync-chevron" aria-hidden="true">
            <IconChevronDown size={16} stroke={1.8} />
          </span>
          来源目录与自动扫描
        </Button>
        <p className="hint">
          登记本地目录后，本地服务定时扫描并把新增/变更文档单向复制入库；来源目录只读，永不写回。
        </p>
      </div>

      {syncSectionOpen && (
        <LibrarySyncSection
          newSourcePath={newSourcePath}
          onNewSourcePathChange={setNewSourcePath}
          onAddSource={() => void submitNewSource()}
          running={running}
          onStartScan={() => void startScan()}
          scanFull={scanFull}
          onScanFullChange={setScanFull}
          intervalText={intervalText}
          onIntervalTextChange={setIntervalText}
          onSaveInterval={() => void saveInterval()}
          graphAutoRefresh={graphAutoRefresh}
          onGraphAutoRefreshChange={(checked) =>
            void saveGraphAutoRefresh(checked)
          }
          syncSources={syncSources}
          syncLoadFailed={syncLoadFailed}
          onToggleSource={(source) => void toggleSyncSource(source)}
          onDeleteSource={(source) => void deleteSyncSource(source)}
        />
      )}

      {actionError !== null && (
        <Alert color="red" role="alert">
          {actionError}
        </Alert>
      )}

      <LibraryJobStatus
        job={job}
        running={running}
        outcome={outcome}
        indexing={indexing}
        itemCountOk={itemCountOk}
        cancellable={cancellable}
        onCancel={() => void cancelCurrentJob()}
        onClose={() => setJob(null)}
      />

      <LibrarySourcesSection
        sources={sources}
        running={running}
        onRemove={setRemovalTarget}
      />

      <LibraryConfirmModals
        removalTarget={removalTarget}
        confirmingRebuild={confirmingRebuild}
        confirmingPurge={confirmingPurge}
        markedCount={markedCount}
        onCloseRemoval={() => setRemovalTarget(null)}
        onConfirmRemoval={() => {
          if (removalTarget !== null) {
            void startRemoval(removalTarget);
          }
        }}
        onCloseRebuild={() => setConfirmingRebuild(false)}
        onConfirmRebuild={() => void startRebuild()}
        onClosePurge={() => setConfirmingPurge(false)}
        onConfirmPurge={() => void startPurge()}
      />
    </Stack>
  );
}
