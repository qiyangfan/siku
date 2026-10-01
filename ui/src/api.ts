export type ApiError = {
  code: string;
  message: string;
};

export type AskCitation = {
  citation_id: string;
  source_name: string;
  note_path: string;
  anchor: string;
  chunk_id: string;
  source_hash: string;
  text: string;
};

export type AskResponse = {
  request_id: string;
  question: string;
  answer: string;
  insufficient_evidence: boolean;
  citations: AskCitation[];
  retrieval: {
    top_k: number;
    candidate_k: number;
    result_count: number;
  };
  model: string;
};

export type HealthResponse = {
  status: string;
  version: string;
};

export type ChannelName = "llm" | "embedding" | "rerank";

export type ChannelSettingsView = {
  base_url: string | null;
  model: string | null;
  api_key_env: string | null;
  // 仅 LLM 通道有值（openai-chat / anthropic / openai-responses）；其余通道恒 null
  protocol: string | null;
  api_key_set: boolean;
  env_overrides: string[];
};

export type AskReadiness = {
  ready: boolean;
  // 稳定机器 token（如 "llm.api_key"），中文话术由界面生成
  missing: string[];
};

// LLM 通道厂商环境变量回退的端点描述（不含凭证明文）；旧内核缺失该字段时按无回退处理
export type LlmEnvFallback = {
  vendor: string;
  base_url: string;
  model: string;
  api_key_env: string;
};

export type SettingsResponse = {
  config_path: string;
  llm: ChannelSettingsView;
  embedding: ChannelSettingsView;
  rerank: ChannelSettingsView;
  ask_readiness: AskReadiness;
  llm_env_fallback: LlmEnvFallback | null;
};

export type SettingsWriteResponse = SettingsResponse & {
  warnings: string[];
  /** 本次保存前本机配置文件不可解析，已以空配置为基底原子覆盖（坏文件自救告知）。
   *  契约里该字段带 `default: false` 且不入 `required`，故按可选建模。 */
  invalid_config_file_overwritten?: boolean;
};

export type ChannelSettingsPayload = {
  base_url?: string | null;
  model?: string | null;
  api_key?: string | null;
  api_key_env?: string | null;
  protocol?: string | null;
};

export type SettingsUpdatePayload = {
  llm?: ChannelSettingsPayload;
  embedding?: ChannelSettingsPayload;
  rerank?: ChannelSettingsPayload;
};

export type SettingsTestPayload = { channel: ChannelName } & ChannelSettingsPayload;

export type SettingsTestResponse = {
  ok: boolean;
  channel: string;
  latency_ms: number;
};

export type LibraryIngestStatus =
  | "ingested"
  | "stale"
  | "pending"
  | "ignored"
  | "missing"
  | "superseded";

export type LibraryIndexStatus = "indexed" | "stale" | "missing";

export type LibrarySource = {
  name: string;
  path: string;
  source_hash: string;
  ingest_status: LibraryIngestStatus;
  index_status: LibraryIndexStatus;
  origin_path: string | null;
};

export type LibraryResponse = {
  sources: LibrarySource[];
};

export type LibraryJobItemStatus =
  | "created"
  | "updated"
  | "skipped"
  | "ignored"
  | "failed"
  | "removed";

export type LibraryJobItem = {
  name: string;
  path: string;
  status: LibraryJobItemStatus;
  detail: string | null;
};

export type LibraryJobKind = "ingest" | "rebuild" | "scan" | "purge";

export type LibraryJobState = "running" | "succeeded" | "failed" | "cancelled";

export type LibraryJobPhase = "scanning" | "ingesting" | "purging" | "indexing";

export type LibraryJob = {
  job_id: string;
  kind: LibraryJobKind;
  state: LibraryJobState;
  phase: LibraryJobPhase;
  total: number;
  done: number;
  failed: number;
  current: string | null;
  items: LibraryJobItem[];
  error: string | null;
};

export type LibrarySyncSource = {
  id: string;
  path: string;
  enabled: boolean;
  created_at: string;
  last_scan_at: string | null;
};

export type LibrarySyncSources = {
  sources: LibrarySyncSource[];
};

export type NoteSummary = {
  source_id: string;
  source_name: string;
  note_path: string;
  source_hash: string;
  extractor: string;
};

export type NotesPage = {
  notes: NoteSummary[];
  total: number;
  page: number;
  page_size: number;
};

export type NoteDetail = NoteSummary & {
  anchors: string[];
  content: string;
};

export type GraphStats = {
  nodes: number;
  edges: number;
  communities: number;
  types: Record<string, number>;
};

export type GraphNode = {
  entity_id: string;
  name: string;
  type: string;
  degree: number;
  community_id: number | null;
};

export type GraphEdge = {
  source: string;
  target: string;
  type: string;
};

export type GraphSubgraph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
  total_nodes: number;
  total_edges: number;
};

export type GraphSearchResult = GraphSubgraph & {
  query: string;
  limit: number;
};

export type GraphExtractorInfo = {
  id: string;
  model: string;
  prompt_version: string;
};

// 与 POST /api/graph 响应（siku graph --json）同构的构建体检报告
export type GraphBuildResponse = {
  chunks: number;
  nodes: number;
  edges: number;
  communities: number;
  ambiguous_entities: number;
  cache_hits: number;
  llm_calls: number;
  warnings: string[];
  empty_corpus: boolean;
  extractor: GraphExtractorInfo;
};

// 与 POST /api/wiki 响应（siku wiki --json）同构的生成统计
export type WikiGenerateResponse = {
  entries: number;
  cache_hits: number;
  llm_calls: number;
  empty_graph: boolean;
};

export type WikiEntrySummary = {
  community_id: number;
  title: string;
  generated_at: string;
};

export type WikiEntries = {
  entries: WikiEntrySummary[];
};

export type WikiEntryDetail = {
  community_id: number;
  title: string;
  content: string;
  generated_at: string;
};

async function parseResponse<T>(response: Response): Promise<T> {
  // 非 JSON 响应体（代理 502 HTML 等）不得让语法错误冒泡成「无法连接」：
  // 解析失败时按错误状态回退稳定错误体
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const error = typeof payload === "object" && payload !== null ? payload : {};
    throw {
      code: "code" in error && typeof error.code === "string" ? error.code : "http_error",
      message:
        "message" in error && typeof error.message === "string"
          ? error.message
          : "请求失败，请稍后重试。",
    } satisfies ApiError;
  }
  return payload as T;
}

const HEALTH_REQUEST_TIMEOUT_MS = 3_000;

export async function checkHealth(): Promise<HealthResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), HEALTH_REQUEST_TIMEOUT_MS);
  try {
    return await parseResponse<HealthResponse>(
      await fetch("/api/health", { signal: controller.signal }),
    );
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function askQuestion(question: string): Promise<AskResponse> {
  return parseResponse<AskResponse>(
    await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    }),
  );
}

export async function getSettings(): Promise<SettingsResponse> {
  return parseResponse<SettingsResponse>(await fetch("/api/settings"));
}

export async function updateSettings(
  update: SettingsUpdatePayload,
): Promise<SettingsWriteResponse> {
  return parseResponse<SettingsWriteResponse>(
    await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    }),
  );
}

export async function testChannel(payload: SettingsTestPayload): Promise<SettingsTestResponse> {
  return parseResponse<SettingsTestResponse>(
    await fetch("/api/settings/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function getLibrary(): Promise<LibraryResponse> {
  return parseResponse<LibraryResponse>(await fetch("/api/library"));
}

export async function ingestFiles(files: File[]): Promise<LibraryJob> {
  const body = new FormData();
  for (const file of files) {
    body.append("files", file, file.name);
  }
  return parseResponse<LibraryJob>(
    await fetch("/api/library/ingest", { method: "POST", body }),
  );
}

export async function getLibraryJob(jobId: string): Promise<LibraryJob> {
  return parseResponse<LibraryJob>(await fetch(`/api/library/jobs/${encodeURIComponent(jobId)}`));
}

export async function cancelLibraryJob(jobId: string): Promise<LibraryJob> {
  return parseResponse<LibraryJob>(
    await fetch(`/api/library/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }),
  );
}

export async function rebuildIndex(): Promise<LibraryJob> {
  return parseResponse<LibraryJob>(
    await fetch("/api/library/rebuild", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    }),
  );
}

export async function getLibrarySources(): Promise<LibrarySyncSources> {
  return parseResponse<LibrarySyncSources>(await fetch("/api/library/sources"));
}

export async function addLibrarySource(path: string, enabled: boolean): Promise<LibrarySyncSource> {
  return parseResponse<LibrarySyncSource>(
    await fetch("/api/library/sources", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, enabled }),
    }),
  );
}

export async function setLibrarySourceEnabled(
  sourceId: string,
  enabled: boolean,
): Promise<LibrarySyncSource> {
  return parseResponse<LibrarySyncSource>(
    await fetch(`/api/library/sources/${encodeURIComponent(sourceId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  );
}

export async function removeLibrarySource(sourceId: string): Promise<{ removed: boolean }> {
  return parseResponse<{ removed: boolean }>(
    await fetch(`/api/library/sources/${encodeURIComponent(sourceId)}`, { method: "DELETE" }),
  );
}

export async function scanLibrarySources(full: boolean): Promise<LibraryJob> {
  return parseResponse<LibraryJob>(
    await fetch("/api/library/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ full }),
    }),
  );
}

export type LibraryScanSettings = { interval_secs: number };

export async function getScanSettings(): Promise<LibraryScanSettings> {
  return parseResponse<LibraryScanSettings>(await fetch("/api/library/scan-settings"));
}

export async function updateScanSettings(intervalSecs: number): Promise<LibraryScanSettings> {
  return parseResponse<LibraryScanSettings>(
    await fetch("/api/library/scan-settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ interval_secs: intervalSecs }),
    }),
  );
}

export async function purgeLibrary(): Promise<LibraryJob> {
  return parseResponse<LibraryJob>(
    await fetch("/api/library/purge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    }),
  );
}

export async function getNotes(page: number, pageSize: number): Promise<NotesPage> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  return parseResponse<NotesPage>(await fetch(`/api/notes?${params.toString()}`));
}

export async function getNote(sourceId: string): Promise<NoteDetail> {
  return parseResponse<NoteDetail>(await fetch(`/api/notes/${encodeURIComponent(sourceId)}`));
}

export async function getGraphStats(): Promise<GraphStats> {
  return parseResponse<GraphStats>(await fetch("/api/graph/stats"));
}

// 走服务端默认幂等缓存路径（等价 `siku graph` 默认行为），不暴露 rebuild/目录覆写
export async function buildGraph(): Promise<GraphBuildResponse> {
  return parseResponse<GraphBuildResponse>(
    await fetch("/api/graph", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }),
  );
}

export async function getGraphOverview(limit: number): Promise<GraphSubgraph> {
  return parseResponse<GraphSubgraph>(await fetch(`/api/graph/overview?limit=${limit}`));
}

export async function searchGraphEntities(query: string, limit: number): Promise<GraphSearchResult> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  return parseResponse<GraphSearchResult>(await fetch(`/api/graph/search?${params.toString()}`));
}

export async function getGraphNeighbors(
  entityId: string,
  limit: number,
  depth: number,
): Promise<GraphSubgraph> {
  const params = new URLSearchParams({ limit: String(limit), depth: String(depth) });
  return parseResponse<GraphSubgraph>(
    await fetch(`/api/graph/neighbors/${encodeURIComponent(entityId)}?${params.toString()}`),
  );
}

export async function getWikiEntries(): Promise<WikiEntries> {
  return parseResponse<WikiEntries>(await fetch("/api/wiki/entries"));
}

export async function getWikiEntry(communityId: number): Promise<WikiEntryDetail> {
  return parseResponse<WikiEntryDetail>(await fetch(`/api/wiki/entries/${communityId}`));
}

// 全量幂等生成（等价 `siku wiki`），图谱产物缺失时后端返回 graph_artifacts_missing
export async function generateWiki(): Promise<WikiGenerateResponse> {
  return parseResponse<WikiGenerateResponse>(
    await fetch("/api/wiki", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }),
  );
}
