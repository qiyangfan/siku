import { useCallback, useEffect, useRef, useState } from "react";
import { askQuestion, type ApiError, type AskResponse, checkHealth } from "./api";
import "./styles.css";

type HealthState = "loading" | "ready" | "offline";
type AskState = "idle" | "loading" | "success" | "error";

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

function App() {
  const [question, setQuestion] = useState("");
  const [health, setHealth] = useState<HealthState>("loading");
  const [askState, setAskState] = useState<AskState>("idle");
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const refreshHealth = useCallback(async () => {
    setHealth("loading");
    try {
      await checkHealth();
      setHealth("ready");
    } catch {
      setHealth("offline");
    }
  }, []);

  useEffect(() => {
    void refreshHealth();
  }, [refreshHealth]);

  const submit = async () => {
    const normalized = question.trim();
    if (!normalized) {
      setLocalError("请输入问题后再提交。");
      inputRef.current?.focus();
      return;
    }
    setLocalError(null);
    setError(null);
    setAnswer(null);
    setAskState("loading");
    try {
      const response = await askQuestion(normalized);
      setAnswer(response);
      setAskState("success");
      setHealth("ready");
    } catch (caught: unknown) {
      setError(
        isApiError(caught)
          ? caught
          : { code: "connection_error", message: "无法连接本地内核，请确认 siku serve 已启动。" },
      );
      setAskState("error");
    }
  };

  const onQuestionKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (askState !== "loading") {
        void submit();
      }
    }
  };

  return (
    <main className="app-shell">
      <section className="workspace" aria-labelledby="page-title">
        <header className="page-header">
          <div>
            <p className="eyebrow">SIKU / LOCAL KNOWLEDGE</p>
            <h1 id="page-title">问问你的知识库</h1>
            <p className="subtitle">从本地事实层检索，再给出可核验的回答。</p>
          </div>
          <div className={`health health-${health}`} aria-live="polite">
            <span className="health-dot" aria-hidden="true" />
            <span>
              {health === "loading" && "正在连接内核"}
              {health === "ready" && "内核已连接"}
              {health === "offline" && "内核未连接"}
            </span>
          </div>
        </header>

        <form
          className="question-card"
          onSubmit={(event) => {
            event.preventDefault();
            if (askState !== "loading") void submit();
          }}
        >
          <label htmlFor="question">你的问题</label>
          <textarea
            ref={inputRef}
            id="question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={onQuestionKeyDown}
            placeholder="例如：这个项目的本地优先边界是什么？"
            rows={4}
            aria-describedby={localError ? "question-hint question-error" : "question-hint"}
            aria-invalid={localError !== null}
          />
          <div className="question-footer">
            <p id="question-hint" className="hint">
              Enter 提交 · Shift + Enter 换行
            </p>
            <button type="submit" disabled={askState === "loading"}>
              {askState === "loading" ? "检索与回答中…" : "提交问题"}
            </button>
          </div>
          {localError && (
            <p id="question-error" className="message message-error" role="alert">
              {localError}
            </p>
          )}
        </form>

        {health === "offline" && (
          <div className="status-card status-warning" role="status">
            <div>
              <strong>本地内核暂不可用</strong>
              <p>请先运行 <code>siku serve --with-ui</code>，然后重试连接。</p>
            </div>
            <button type="button" className="button-secondary" onClick={() => void refreshHealth()}>
              重试连接
            </button>
          </div>
        )}

        {askState === "loading" && (
          <div className="answer-card loading-card" role="status" aria-live="polite">
            <span className="loading-mark" aria-hidden="true" />
            <div>
              <strong>正在从本地知识库寻找依据</strong>
              <p>回答只会基于本次检索到的片段。</p>
            </div>
          </div>
        )}

        {askState === "error" && error && (
          <div className="status-card status-error" role="alert">
            <div>
              <span className="status-kicker">{error.code}</span>
              <strong>{error.message}</strong>
            </div>
            <button type="button" className="button-secondary" onClick={() => void submit()}>
              重试问答
            </button>
          </div>
        )}

        {askState === "success" && answer && (
          <article className="answer-card" aria-labelledby="answer-title">
            <div className="answer-heading">
              <div>
                <p className="eyebrow">ANSWER</p>
                <h2 id="answer-title">
                  {answer.insufficient_evidence ? "证据不足" : "回答"}
                </h2>
              </div>
              <span className="result-count">
                {answer.retrieval.result_count} 条检索片段
              </span>
            </div>
            <p className={answer.insufficient_evidence ? "answer-text answer-muted" : "answer-text"}>
              {answer.answer}
            </p>
            {!answer.insufficient_evidence && answer.citations.length > 0 && (
              <section className="sources" aria-labelledby="sources-title">
                <div className="sources-heading">
                  <h3 id="sources-title">来源依据</h3>
                  <span>{answer.citations.length} 条引用</span>
                </div>
                <div className="citation-list">
                  {answer.citations.map((citation) => (
                    <details key={citation.citation_id} className="citation">
                      <summary>
                        <span className="citation-id">{citation.citation_id}</span>
                        <span className="citation-source">{citation.source_name}</span>
                        <span className="citation-anchor">{citation.anchor}</span>
                      </summary>
                      <div className="citation-body">
                        <p className="citation-path">{citation.note_path}</p>
                        <p>{citation.text}</p>
                      </div>
                    </details>
                  ))}
                </div>
              </section>
            )}
            <footer className="answer-meta">
              <span>模型：{answer.model}</span>
              <span className="request-id" title={answer.request_id}>
                request_id：{answer.request_id}
              </span>
            </footer>
          </article>
        )}
      </section>
    </main>
  );
}

export default App;
