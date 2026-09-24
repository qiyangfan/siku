import { useCallback, useEffect, useRef, useState } from "react";
import {
  askQuestion,
  type ApiError,
  type AskReadiness,
  type AskResponse,
  checkHealth,
  getSettings,
} from "./api";
import { BrowseView } from "./BrowseView";
import { GraphView } from "./GraphView";
import { LibraryView } from "./LibraryView";
import { SettingsView } from "./SettingsView";
import { WikiView } from "./WikiView";
import "./styles.css";

type HealthState = "loading" | "ready" | "offline";
type AskState = "idle" | "loading" | "success" | "error";
type ViewName = "ask" | "browse" | "graph" | "wiki" | "library" | "settings";

const NAV_ITEMS: Array<{ name: ViewName; label: string }> = [
  { name: "ask", label: "问答" },
  { name: "browse", label: "浏览" },
  { name: "graph", label: "图谱" },
  { name: "wiki", label: "wiki" },
  { name: "library", label: "资料库" },
  { name: "settings", label: "设置" },
];

// ask_readiness.missing 的稳定 token → 中文说明（展示层职责，内核只出机器 token）
const MISSING_LABELS: Record<string, string> = {
  "llm.api_key": "LLM 通道的 API key",
  "embedding.base_url": "embedding 通道的 base_url",
  "embedding.model": "embedding 通道的 model",
};

function describeMissing(missing: string[]): string {
  const parts = missing.map((token) => MISSING_LABELS[token] ?? token);
  return `还差：${parts.join("、")}。`;
}

// 就绪字段缺失或形状非法（旧内核、代理改写）一律按「不可得」处理：fail-open。
// ready=false 但 missing 为空属后端不应产生的矛盾形状，同样按不可得对待，
// 避免置灰后展示「还差：。」的空指引。
function normalizeReadiness(value: unknown): AskReadiness | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const candidate = value as Partial<AskReadiness>;
  if (typeof candidate.ready !== "boolean" || !Array.isArray(candidate.missing)) {
    return null;
  }
  if (!candidate.ready && candidate.missing.length === 0) {
    return null;
  }
  return { ready: candidate.ready, missing: candidate.missing };
}

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
  const [view, setView] = useState<ViewName>("ask");
  const [question, setQuestion] = useState("");
  const [health, setHealth] = useState<HealthState>("loading");
  const [readiness, setReadiness] = useState<AskReadiness | null>(null);
  const [askState, setAskState] = useState<AskState>("idle");
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [focusQuestion, setFocusQuestion] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // 问答请求序号：实体联动预填时递增，使在途旧回答作废（防旧答案挂新问题下）
  const askSeqRef = useRef(0);

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

  // 就绪判定在内核（ask_readiness），问答视图可见时拉取：覆盖初次进入与
  // 从设置页/手工编辑 config.toml 回到问答的场景。获取失败置 null → fail-open
  // 不置灰，保留提交后错误提示的既有兜底路径。
  const refreshReadiness = useCallback(async () => {
    try {
      const settings = await getSettings();
      setReadiness(normalizeReadiness(settings.ask_readiness));
    } catch {
      setReadiness(null);
    }
  }, []);

  useEffect(() => {
    if (view === "ask") {
      void refreshReadiness();
    }
  }, [view, refreshReadiness]);

  useEffect(() => {
    if (focusQuestion && view === "ask") {
      inputRef.current?.focus();
      setFocusQuestion(false);
    }
  }, [focusQuestion, view]);

  const askEntity = useCallback((name: string) => {
    setQuestion(`请介绍「${name}」。`);
    // 预填新问题必须清掉上一轮答案与状态：旧回答卡挂在下方会被误读为新问题的答案；
    // 递增序号使在途旧回答的响应作废，防止其迟到后挂在新问题下
    askSeqRef.current += 1;
    setAnswer(null);
    setAskState("idle");
    setError(null);
    setLocalError(null);
    setView("ask");
    setFocusQuestion(true);
  }, []);

  // 未就绪门控：置灰提交 + 引导卡片；readiness 为 null（加载中/获取失败）不阻塞
  const askBlocked = readiness !== null && !readiness.ready;

  const submit = async () => {
    // 置灰之外的第二道校验：拦截 Enter 键等绕过按钮的提交路径
    if (askBlocked) {
      return;
    }
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
    const seq = ++askSeqRef.current;
    try {
      const response = await askQuestion(normalized);
      if (seq !== askSeqRef.current) {
        return;
      }
      setAnswer(response);
      setAskState("success");
      setHealth("ready");
    } catch (caught: unknown) {
      if (seq !== askSeqRef.current) {
        return;
      }
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

        <nav className="view-nav" aria-label="视图切换">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.name}
              type="button"
              className={view === item.name ? "nav-tab nav-tab-active" : "nav-tab"}
              aria-pressed={view === item.name}
              onClick={() => setView(item.name)}
            >
              {item.label}
            </button>
          ))}
        </nav>

        {view === "settings" && (
          <SettingsView
            onSaved={(settings) => setReadiness(normalizeReadiness(settings.ask_readiness))}
          />
        )}

        {view === "library" && <LibraryView />}

        {view === "browse" && <BrowseView />}

        {view === "graph" && <GraphView onAskEntity={askEntity} />}

        {view === "wiki" && <WikiView />}

        {view === "ask" && (
        <>
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
              {askBlocked ? "配置模型端点后即可提问" : "Enter 提交 · Shift + Enter 换行"}
            </p>
            <button type="submit" disabled={askState === "loading" || askBlocked}>
              {askState === "loading" ? "检索与回答中…" : "提交问题"}
            </button>
          </div>
          {localError && (
            <p id="question-error" className="message message-error" role="alert">
              {localError}
            </p>
          )}
        </form>

        {askBlocked && readiness && (
          <div className="status-card status-warning" role="status">
            <div>
              <strong>问答尚未就绪——模型端点未配置</strong>
              <p>
                {describeMissing(readiness.missing)}
                配置保存后免重启生效，回到本页即可提交问题。
              </p>
            </div>
            <button
              type="button"
              className="button-secondary"
              onClick={() => setView("settings")}
            >
              去设置
            </button>
          </div>
        )}

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
        </>
        )}
      </section>
    </main>
  );
}

export default App;
