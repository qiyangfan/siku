import { useCallback, useEffect, useRef, useState } from "react";
import { IconChevronDown } from "@tabler/icons-react";
import {
  Alert,
  Button,
  Checkbox,
  Group,
  Loader,
  Modal,
  NumberInput,
  Paper,
  Progress,
  SimpleGrid,
  Stack,
  Switch,
  TextInput,
} from "@mantine/core";
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
  removing: "移除未完成",
};

// 徽标 title 释义：状态词本身是内部语，悬停给可读解释（清单密集场景的轻量说明）
const INGEST_STATUS_HINT: Record<LibraryIngestStatus, string> = {
  ingested: "已摄取为本地事实层",
  stale: "来源文件已变更，等待重新抽取",
  pending: "已登记，等待摄取",
  ignored: "格式不支持或被规则忽略",
  missing: "原件文件已不存在，可清理或重新导入",
  superseded: "来源目录扫描发现同名新版本，此件已被替代",
  removing: "移除在收尾阶段失败或被中断；可按同一来源重试",
};

const INDEX_STATUS_LABEL: Record<LibraryIndexStatus, string> = {
  indexed: "已索引",
  stale: "索引待更新",
  missing: "未索引",
};

const INDEX_STATUS_HINT: Record<LibraryIndexStatus, string> = {
  indexed: "已同步检索索引",
  stale: "等待索引更新",
  missing: "尚未进入检索索引",
};

const ITEM_STATUS_LABEL: Record<LibraryJobItemStatus, string> = {
  created: "新建",
  updated: "更新",
  skipped: "跳过（内容未变化）",
  ignored: "已忽略",
  failed: "失败",
  removed: "已清理",
};

const SUPPORTED_FORMATS = "PDF（需含文字层）、Word、PPT、Excel 现代格式，及 EPUB、HTML、Markdown";

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
  if (job.kind === "remove") {
    return {
      tone: "ok",
      text: "已从资料库移除：受管副本与检索内容已清除，图谱与 Wiki 需重新构建（外部原件保留）。",
    };
  }
  if (job.kind === "purge") {
    const removed = job.items.filter((item) => item.status === "removed").length;
    return { tone: "ok", text: `清理完成：已物理移除 ${removed} 项失效文档。` };
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

  // 单项移除确认框：仅服务端标记 removable（或移除未完成待重试）的条目进入
  const [removalTarget, setRemovalTarget] = useState<LibrarySource | null>(null);

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
    const handle = window.setTimeout(() => void pollJob(job.job_id), POLL_INTERVAL_MS);
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
      <Alert className="status-card" color="red" role="alert" title="资料库读取失败">
        <p>{loadError}</p>
        <Button variant="default" type="button" className="button-secondary" onClick={() => void refreshListing()}>
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
      const saved = await updateScanSettings(parsed);
      setIntervalText(String(saved.interval_secs));
    } catch (caught: unknown) {
      setActionError(connectionFallback(caught));
    }
  };

  if (sources === null) {
    return (
      <Group className="settings-loading" role="status" aria-live="polite" gap="sm">
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
    (source) => source.ingest_status === "missing" || source.ingest_status === "superseded",
  ).length;
  const cancellable =
    running && (job.kind === "ingest" || job.kind === "scan" || job.kind === "purge" || job.kind === "remove");

  return (
    <Stack component="section" className="library-view" gap="lg" aria-labelledby="library-title">
      <Group component="header" className="library-toolbar" align="flex-start" justify="space-between" wrap="wrap">
        <div>
          <h2 id="library-title">资料库</h2>
          <p className="hint">导入即摄取为本地事实层，并自动同步检索索引。</p>
        </div>
        <Stack className="library-actions" gap="sm">
          <div
            className={`library-dropzone${dragActive ? " library-dropzone-active" : ""}`}
            role="button"
            tabIndex={0}
            aria-label="导入文件：点击选择或拖入文档"
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
            <strong className="library-dropzone-title">点击选择文件，或把文档拖到这里</strong>
            <span className="hint">
              {SUPPORTED_FORMATS}，可多选；导入即摄取，原文件保持不变。扫描件 PDF 请先
              OCR 为含文字版，旧 .doc/.ppt/.xls 请另存为现代格式。
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
          <SimpleGrid className="library-action-buttons" cols={{ base: 1, sm: 2 }} spacing="sm">
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
        <Button variant="subtle"
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
        <div className="library-sync-panel">
          <div className="library-sync-add">
            <TextInput
              value={newSourcePath}
              aria-label="来源目录路径"
              onChange={(event) => setNewSourcePath(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void submitNewSource();
                }
              }}
              placeholder="本地目录绝对路径，例如 /Users/you/Documents/notes"
              spellCheck={false}
            />
            <Button variant="default"
              type="button"
              className="button-secondary"
              disabled={!newSourcePath.trim() || running}
              onClick={() => void submitNewSource()}
            >
              添加来源
            </Button>
          </div>
          <div className="library-sync-controls">
            <div className="library-sync-group">
              <Button variant="default"
                type="button"
                className="button-secondary"
                disabled={running || syncSources === null}
                onClick={() => void startScan()}
              >
                立即扫描
              </Button>
              <Checkbox
                className="library-sync-check"
                checked={scanFull}
                onChange={(event) => setScanFull(event.target.checked)}
                label="全量校验"
              />
            </div>
            {intervalText !== null && (
              <div className="library-sync-group">
                <NumberInput
                  id="scan-interval-input"
                  label="自动扫描间隔（秒，0 = 关闭）"
                  inputMode="numeric"
                  min={0}
                  value={intervalText}
                  allowDecimal={false}
                  allowNegative={false}
                  onChange={(value) => setIntervalText(String(value))}
                  aria-label="自动扫描间隔秒数"
                />
                <Button variant="default"
                  type="button"
                  className="button-secondary"
                  disabled={running}
                  onClick={() => void saveInterval()}
                >
                  保存间隔
                </Button>
              </div>
            )}
          </div>
          {syncSources === null ? (
            <Alert role="status">
              正在读取来源目录…
            </Alert>
          ) : syncLoadFailed ? (
            <Alert color="red" role="alert">
              来源目录清单读取失败，请检查本地服务连接后重试。
            </Alert>
          ) : syncSources.length === 0 ? (
            <Alert color="gray" role="note">
              尚未登记来源目录。添加后本地服务按设定的间隔自动扫描，也可点击「立即扫描」。
            </Alert>
          ) : (
            <ul className="library-sync-list" aria-label="来源目录清单">
              {syncSources.map((source) => (
                <li key={source.id} className="library-sync-row">
                  <span className="library-sync-path" title={source.path}>
                    {source.path}
                  </span>
                  <Switch
                    checked={source.enabled}
                    onChange={() => void toggleSyncSource(source)}
                    disabled={running}
                    label={source.enabled ? "已启用" : "已停用"}
                    aria-label={`${source.enabled ? "停用" : "启用"}来源目录 ${source.path}`}
                  />
                  <span className="library-sync-time">
                    {source.last_scan_at === null
                      ? "从未扫描"
                      : `上次扫描 ${new Date(source.last_scan_at).toLocaleString()}`}
                  </span>
                  <Button variant="default"
                    type="button"
                    className="button-secondary"
                    disabled={running}
                    onClick={() => void deleteSyncSource(source)}
                  >
                    移除
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {actionError !== null && <Alert color="red" role="alert">{actionError}</Alert>}

      {job !== null && running && (
        <Paper withBorder shadow="xs" radius="md" p="lg" className="status-running" role="status" aria-live="polite">
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
                      : job.kind === "remove"
                        ? "正在从资料库移除…"
                        : `正在摄取（${job.done}/${job.total}）`}
            </strong>
            {indexing === false && job.current !== null && (
              <p className="library-current-file">{job.current}</p>
            )}
            {itemCountOk && !indexing && (
              <Progress
                className="library-progress-bar"
                value={(job.done / job.total) * 100}
                size="sm"
                aria-label={`任务进度 ${job.done}/${job.total}`}
              />
            )}
          </div>
          {cancellable && (
            <Button variant="default" type="button" className="button-secondary" onClick={() => void cancelCurrentJob()}>
              取消任务
            </Button>
          )}
        </Paper>
      )}

      {outcome !== null && job !== null && (
        <Alert
          color={outcome.tone === "ok" ? "green" : "red"}
          role={outcome.tone === "ok" ? "status" : "alert"}
          title={outcome.text}
        >
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
          <Button variant="default" type="button" className="button-secondary" onClick={() => setJob(null)}>
            关闭
          </Button>
        </Alert>
      )}

      {sources.length === 0 ? (
        <Alert className="library-empty" color="gray" role="note" title="资料库还是空的">
          <p>把文档拖入上方导入区，或点击选择文件；导入的文件会被复制进资料库并抽取为可检索的知识，原文件保持不变。</p>
          <p className="hint">支持格式：{SUPPORTED_FORMATS}。也可以展开「来源目录与自动扫描」登记一个本地目录，之后新文档会自动入库。</p>
        </Alert>
      ) : (
        <Paper component="ul" withBorder radius="md" shadow="xs" p="xs" className="library-list" aria-label="资料库来源清单">
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
              <span
                className={`library-badge library-badge-ingest-${source.ingest_status}`}
                title={INGEST_STATUS_HINT[source.ingest_status]}
              >
                {INGEST_STATUS_LABEL[source.ingest_status]}
              </span>
              <span
                className={`library-badge library-badge-index-${source.index_status}`}
                title={INDEX_STATUS_HINT[source.index_status]}
              >
                {INDEX_STATUS_LABEL[source.index_status]}
              </span>
              {source.removable && source.source_id !== null && (
                <Button
                  variant="default"
                  type="button"
                  className="button-danger library-remove-action"
                  disabled={running}
                  title={
                    source.ingest_status === "removing"
                      ? "上一次移除未完成：重试将接续清理该来源"
                      : "从资料库移除该文档的受管副本与派生知识；外部原件保留"
                  }
                  onClick={() => setRemovalTarget(source)}
                >
                  {source.ingest_status === "removing" ? "重试移除" : "从资料库移除"}
                </Button>
              )}
            </li>
          ))}
        </Paper>
      )}

      <Modal
        opened={removalTarget !== null}
        onClose={() => setRemovalTarget(null)}
        title={`确认从资料库移除「${removalTarget?.name ?? ""}」？`}
        centered
      >
        <p>
          将清除该文档在资料库中的受管副本、投影与检索内容，并使图谱与 Wiki
          失效（需重新构建）。你选择导入时的外部原件不会被删除，可随时重新导入。
        </p>
        <p className="hint">
          {removalTarget?.ingest_status === "removing"
            ? "该来源上一次移除未完成，本次为接续重试。"
            : "此操作不可撤销；来源目录同步管理的文档不提供该操作。"}
        </p>
        <Group className="library-dialog-actions" justify="flex-end">
          <Button type="button" variant="default" onClick={() => setRemovalTarget(null)}>
            取消
          </Button>
          <Button
            type="button"
            className="button-danger-solid"
            disabled={removalTarget === null}
            onClick={() => {
              if (removalTarget !== null) {
                void startRemoval(removalTarget);
              }
            }}
          >
            确认移除
          </Button>
        </Group>
      </Modal>

      <Modal
        opened={confirmingRebuild}
        onClose={() => setConfirmingRebuild(false)}
        title="确认全量重建索引？"
        centered
      >
        <p>
          重建会按当前 embedding 配置重算全部向量并替换现有索引；语料原件与投影不受影响。
          资料库较大时耗时较长。
        </p>
        <Group className="library-dialog-actions" justify="flex-end">
          <Button type="button" variant="default" onClick={() => setConfirmingRebuild(false)}>取消</Button>
          <Button type="button" onClick={() => void startRebuild()}>确认重建</Button>
        </Group>
      </Modal>

      <Modal
        opened={confirmingPurge}
        onClose={() => setConfirmingPurge(false)}
        title={`确认清理 ${markedCount} 项失效文档？`}
        centered
      >
        <p>
          将物理删除全部「来源缺失」与「已被替代」文档的原件与投影，并从索引中移除；此操作不可撤销。
        </p>
        <Group className="library-dialog-actions" justify="flex-end">
          <Button type="button" variant="default" onClick={() => setConfirmingPurge(false)}>取消</Button>
          <Button type="button" className="button-danger-solid" onClick={() => void startPurge()}>确认清理</Button>
        </Group>
      </Modal>
    </Stack>
  );
}

export default LibraryView;
