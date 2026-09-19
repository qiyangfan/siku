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
  api_key_set: boolean;
  env_overrides: string[];
};

export type SettingsResponse = {
  config_path: string;
  llm: ChannelSettingsView;
  embedding: ChannelSettingsView;
  rerank: ChannelSettingsView;
};

export type SettingsWriteResponse = SettingsResponse & {
  warnings: string[];
};

export type ChannelSettingsPayload = {
  base_url?: string | null;
  model?: string | null;
  api_key?: string | null;
  api_key_env?: string | null;
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

export type LibraryIngestStatus = "ingested" | "stale" | "pending" | "ignored";

export type LibraryIndexStatus = "indexed" | "stale" | "missing";

export type LibrarySource = {
  name: string;
  path: string;
  source_hash: string;
  ingest_status: LibraryIngestStatus;
  index_status: LibraryIndexStatus;
};

export type LibraryResponse = {
  sources: LibrarySource[];
};

export type LibraryJobItemStatus = "created" | "updated" | "skipped" | "ignored" | "failed";

export type LibraryJobItem = {
  name: string;
  path: string;
  status: LibraryJobItemStatus;
  detail: string | null;
};

export type LibraryJobKind = "ingest" | "rebuild";

export type LibraryJobState = "running" | "succeeded" | "failed" | "cancelled";

export type LibraryJobPhase = "ingesting" | "indexing";

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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

async function parseResponse<T>(response: Response): Promise<T> {
  const payload: unknown = await response.json();
  if (!response.ok) {
    const error = isRecord(payload) ? payload : {};
    throw {
      code: typeof error.code === "string" ? error.code : "http_error",
      message: typeof error.message === "string" ? error.message : "请求失败，请稍后重试。",
    } satisfies ApiError;
  }
  return payload as T;
}

export async function checkHealth(): Promise<HealthResponse> {
  return parseResponse<HealthResponse>(await fetch("/api/health"));
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
