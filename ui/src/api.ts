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
