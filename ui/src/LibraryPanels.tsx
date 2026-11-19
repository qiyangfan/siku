import {
  Alert,
  Button,
  Checkbox,
  Group,
  Modal,
  NumberInput,
  Paper,
  Progress,
  Switch,
  Text,
  TextInput,
} from "@mantine/core";
import {
  type LibraryIndexStatus,
  type LibraryIngestStatus,
  type LibraryJob,
  type LibraryJobItemStatus,
  type LibrarySource,
  type LibrarySyncSource,
} from "./api";
import { formatDateTime } from "./datetime";

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

export const SUPPORTED_FORMATS =
  "PDF（需含文字层）、Word、PPT、Excel 现代格式，及 EPUB、HTML、Markdown";

export function LibrarySyncSection({
  newSourcePath,
  onNewSourcePathChange,
  onAddSource,
  running,
  onStartScan,
  scanFull,
  onScanFullChange,
  intervalText,
  onIntervalTextChange,
  onSaveInterval,
  graphAutoRefresh,
  onGraphAutoRefreshChange,
  syncSources,
  syncLoadFailed,
  onToggleSource,
  onDeleteSource,
}: {
  newSourcePath: string;
  onNewSourcePathChange: (value: string) => void;
  onAddSource: () => void;
  running: boolean;
  onStartScan: () => void;
  scanFull: boolean;
  onScanFullChange: (checked: boolean) => void;
  intervalText: string | null;
  onIntervalTextChange: (value: string) => void;
  onSaveInterval: () => void;
  graphAutoRefresh: boolean | null;
  onGraphAutoRefreshChange: (checked: boolean) => void;
  syncSources: LibrarySyncSource[] | null;
  syncLoadFailed: boolean;
  onToggleSource: (source: LibrarySyncSource) => void;
  onDeleteSource: (source: LibrarySyncSource) => void;
}) {
  return (
    <div className="library-sync-panel">
      <div className="library-sync-add">
        <TextInput
          value={newSourcePath}
          aria-label="来源目录路径"
          onChange={(event) => onNewSourcePathChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              onAddSource();
            }
          }}
          placeholder="本地目录绝对路径，例如 /Users/you/Documents/notes"
          spellCheck={false}
        />
        <Button
          variant="default"
          type="button"
          className="button-secondary"
          disabled={!newSourcePath.trim() || running}
          onClick={onAddSource}
        >
          添加来源
        </Button>
      </div>
      <div className="library-sync-controls">
        <div className="library-sync-group">
          <Button
            variant="default"
            type="button"
            className="button-secondary"
            disabled={running || syncSources === null}
            onClick={onStartScan}
          >
            立即扫描
          </Button>
          <Checkbox
            className="library-sync-check"
            checked={scanFull}
            onChange={(event) => onScanFullChange(event.target.checked)}
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
              onChange={(value) => onIntervalTextChange(String(value))}
              aria-label="自动扫描间隔秒数"
            />
            <Button
              variant="default"
              type="button"
              className="button-secondary"
              disabled={running}
              onClick={onSaveInterval}
            >
              保存间隔
            </Button>
          </div>
        )}
        {graphAutoRefresh !== null && (
          <div className="library-sync-group">
            <Switch
              id="graph-auto-refresh-switch"
              className="library-sync-check"
              checked={graphAutoRefresh}
              disabled={running}
              onChange={(event) =>
                onGraphAutoRefreshChange(event.target.checked)
              }
              label="摄取/扫描后自动增量更新图谱"
            />
            <Text size="xs" c="dimmed">
              缺省关闭。仅在图谱已构建时增量维护（不会自动创建）；更换模型或
              prompt 后需显式更新图谱。任务完成后在下方通知区显示抽取计数。
            </Text>
          </div>
        )}
      </div>
      {syncSources === null ? (
        <Alert role="status">正在读取来源目录…</Alert>
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
                onChange={() => onToggleSource(source)}
                disabled={running}
                label={source.enabled ? "已启用" : "已停用"}
                aria-label={`${source.enabled ? "停用" : "启用"}来源目录 ${source.path}`}
              />
              <span className="library-sync-time">
                {source.last_scan_at === null
                  ? "从未扫描"
                  : `上次扫描 ${formatDateTime(source.last_scan_at)}`}
              </span>
              <Button
                variant="default"
                type="button"
                className="button-secondary"
                disabled={running}
                onClick={() => onDeleteSource(source)}
              >
                移除
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function LibraryJobStatus({
  job,
  running,
  outcome,
  indexing,
  itemCountOk,
  cancellable,
  onCancel,
  onClose,
}: {
  job: LibraryJob | null;
  running: boolean;
  outcome: { tone: "ok" | "error"; text: string } | null;
  indexing: boolean;
  itemCountOk: boolean;
  cancellable: boolean;
  onCancel: () => void;
  onClose: () => void;
}) {
  return (
    <>
      <LibraryRunningStatus
        job={job}
        running={running}
        indexing={indexing}
        itemCountOk={itemCountOk}
        cancellable={cancellable}
        onCancel={onCancel}
      />

      {outcome !== null && job !== null && (
        <Alert
          color={outcome.tone === "ok" ? "green" : "red"}
          role={outcome.tone === "ok" ? "status" : "alert"}
          title={outcome.text}
        >
          {job.items.some(
            (item) => item.status === "failed" || item.status === "ignored",
          ) && (
            <ul className="library-item-results">
              {job.items
                .filter(
                  (item) =>
                    item.status === "failed" || item.status === "ignored",
                )
                .map((item) => (
                  <li key={`${item.status}-${item.name}`}>
                    {item.name}：{ITEM_STATUS_LABEL[item.status]}
                    {item.detail !== null && `——${item.detail}`}
                  </li>
                ))}
            </ul>
          )}
          <Button
            variant="default"
            type="button"
            className="button-secondary"
            onClick={onClose}
          >
            关闭
          </Button>
        </Alert>
      )}
      {job !== null && job.notice != null && job.notice !== "" && (
        <Alert role="status" color="blue" title="派生维护通知">
          {job.notice}
        </Alert>
      )}
    </>
  );
}

export function LibrarySourcesSection({
  sources,
  running,
  onRemove,
}: {
  sources: LibrarySource[];
  running: boolean;
  onRemove: (source: LibrarySource) => void;
}) {
  return (
    <>
      {sources.length === 0 ? (
        <Alert
          className="library-empty"
          color="gray"
          role="note"
          title="资料库还是空的"
        >
          <p>
            把文档拖入上方导入区，或点击选择文件；导入的文件会被复制进资料库并抽取为可检索的知识，原文件保持不变。
          </p>
          <p className="hint">
            支持格式：{SUPPORTED_FORMATS}
            。也可以展开「来源目录与自动扫描」登记一个本地目录，之后新文档会自动入库。
          </p>
        </Alert>
      ) : (
        <Paper
          component="ul"
          withBorder
          radius="md"
          shadow="xs"
          p="xs"
          className="library-list"
          aria-label="资料库来源清单"
        >
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
                  onClick={() => onRemove(source)}
                >
                  {source.ingest_status === "removing"
                    ? "重试移除"
                    : "从资料库移除"}
                </Button>
              )}
            </li>
          ))}
        </Paper>
      )}
    </>
  );
}

function LibraryRunningStatus({
  job,
  running,
  indexing,
  itemCountOk,
  cancellable,
  onCancel,
}: {
  job: LibraryJob | null;
  running: boolean;
  indexing: boolean;
  itemCountOk: boolean;
  cancellable: boolean;
  onCancel: () => void;
}) {
  if (job === null || !running) {
    return null;
  }
  return (
    <Paper
      withBorder
      shadow="xs"
      radius="md"
      p="lg"
      className="status-running"
      role="status"
      aria-live="polite"
    >
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
        <Button
          variant="default"
          type="button"
          className="button-secondary"
          onClick={onCancel}
        >
          取消任务
        </Button>
      )}
    </Paper>
  );
}

export function LibraryConfirmModals({
  removalTarget,
  confirmingRebuild,
  confirmingPurge,
  markedCount,
  onCloseRemoval,
  onConfirmRemoval,
  onCloseRebuild,
  onConfirmRebuild,
  onClosePurge,
  onConfirmPurge,
}: {
  removalTarget: LibrarySource | null;
  confirmingRebuild: boolean;
  confirmingPurge: boolean;
  markedCount: number;
  onCloseRemoval: () => void;
  onConfirmRemoval: () => void;
  onCloseRebuild: () => void;
  onConfirmRebuild: () => void;
  onClosePurge: () => void;
  onConfirmPurge: () => void;
}) {
  return (
    <>
      <Modal
        opened={removalTarget !== null}
        onClose={onCloseRemoval}
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
          <Button type="button" variant="default" onClick={onCloseRemoval}>
            取消
          </Button>
          <Button
            type="button"
            className="button-danger-solid"
            disabled={removalTarget === null}
            onClick={onConfirmRemoval}
          >
            确认移除
          </Button>
        </Group>
      </Modal>

      <Modal
        opened={confirmingRebuild}
        onClose={onCloseRebuild}
        title="确认全量重建索引？"
        centered
      >
        <p>
          重建会按当前 embedding
          配置重算全部向量并替换现有索引；语料原件与投影不受影响。
          资料库较大时耗时较长。
        </p>
        <Group className="library-dialog-actions" justify="flex-end">
          <Button type="button" variant="default" onClick={onCloseRebuild}>
            取消
          </Button>
          <Button type="button" onClick={onConfirmRebuild}>
            确认重建
          </Button>
        </Group>
      </Modal>

      <Modal
        opened={confirmingPurge}
        onClose={onClosePurge}
        title={`确认清理 ${markedCount} 项失效文档？`}
        centered
      >
        <p>
          将物理删除全部「来源缺失」与「已被替代」文档的原件与投影，并从索引中移除；此操作不可撤销。
        </p>
        <Group className="library-dialog-actions" justify="flex-end">
          <Button type="button" variant="default" onClick={onClosePurge}>
            取消
          </Button>
          <Button
            type="button"
            className="button-danger-solid"
            onClick={onConfirmPurge}
          >
            确认清理
          </Button>
        </Group>
      </Modal>
    </>
  );
}
