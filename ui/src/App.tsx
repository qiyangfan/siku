import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  IconAffiliate,
  IconBook,
  IconDotsVertical,
  IconMessageCircle,
} from "@tabler/icons-react";
import { useMediaQuery } from "@mantine/hooks";
import {
  Alert,
  Badge,
  Button,
  Container,
  Group,
  Loader,
  Menu,
  Paper,
  Stack,
  Tabs,
  Textarea,
} from "@mantine/core";
import {
  askQuestion,
  type ApiError,
  type AskReadiness,
  type AskResponse,
  checkHealth,
  getNote,
  getNotes,
  getSettings,
  getWikiEntries,
  getWikiEntry,
} from "./api";
import { BrowseView } from "./BrowseView";
import { GraphView } from "./GraphView";
import { LibraryView } from "./LibraryView";
import { SettingsView } from "./SettingsView";
import { WikiView } from "./WikiView";
import { buildQuestionSuggestions, type QuestionSuggestion } from "./question-suggestions";
import "./styles.css";

type HealthState = "loading" | "ready" | "offline";
type AskState = "idle" | "loading" | "success" | "error";
type SuggestionState = "idle" | "loading" | "ready" | "empty" | "unavailable";
type ViewName = "ask" | "browse" | "graph" | "wiki" | "library" | "settings";

const NAV_ITEMS: Array<{ name: ViewName; label: string; icon?: ReactNode }> = [
  { name: "ask", label: "问答", icon: <IconMessageCircle size={22} stroke={1.8} aria-hidden="true" /> },
  { name: "browse", label: "浏览", icon: <IconBook size={22} stroke={1.8} aria-hidden="true" /> },
  { name: "graph", label: "图谱", icon: <IconAffiliate size={22} stroke={1.8} aria-hidden="true" /> },
  { name: "wiki", label: "wiki" },
  { name: "library", label: "资料库" },
  { name: "settings", label: "设置" },
];

const MOBILE_MORE_NAV: Array<{ name: ViewName; label: string }> = [
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
  const isMobileViewport = useMediaQuery("(max-width: 40rem)", false, {
    getInitialValueInEffect: false,
  });
  const [question, setQuestion] = useState("");
  const [health, setHealth] = useState<HealthState>("loading");
  const [readiness, setReadiness] = useState<AskReadiness | null>(null);
  const [questionSuggestions, setQuestionSuggestions] = useState<QuestionSuggestion[]>([]);
  const [suggestionState, setSuggestionState] = useState<SuggestionState>("idle");
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

  useEffect(() => {
    const timer = window.setInterval(() => {
      void checkHealth()
        .then(() => setHealth("ready"))
        .catch(() => setHealth("offline"));
    }, 10_000);
    return () => window.clearInterval(timer);
  }, []);

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
    if (view !== "ask") {
      return;
    }
    if (health !== "ready") {
      setQuestionSuggestions([]);
      setSuggestionState("idle");
      return;
    }

    let current = true;
    setQuestionSuggestions([]);
    setSuggestionState("loading");

    const loadSuggestions = async () => {
      const [notesResult, wikiResult] = await Promise.allSettled([
        getNotes(1, 5),
        getWikiEntries(),
      ]);
      if (!current) {
        return;
      }

      const notesPage = notesResult.status === "fulfilled" ? notesResult.value : null;
      const notes = Array.isArray(notesPage?.notes) ? notesPage.notes : [];
      const wikiEntries =
        wikiResult.status === "fulfilled" && Array.isArray(wikiResult.value?.entries)
          ? wikiResult.value.entries
          : [];
      const [noteDetails, wikiDetails] = await Promise.all([
        Promise.allSettled(notes.slice(0, 2).map((note) => getNote(note.source_id))),
        wikiEntries[0] ? Promise.allSettled([getWikiEntry(wikiEntries[0].community_id)]) : [],
      ]);
      if (!current) {
        return;
      }

      const resolvedNotes = noteDetails.flatMap((result) =>
        result.status === "fulfilled" ? [result.value] : [],
      );
      const wikiEntry = wikiDetails[0]?.status === "fulfilled" ? wikiDetails[0].value : undefined;
      const suggestions = buildQuestionSuggestions(notes, resolvedNotes, wikiEntry);
      const wikiNotGenerated =
        wikiResult.status === "rejected" &&
        isApiError(wikiResult.reason) &&
        wikiResult.reason.code === "wiki_missing";
      const wikiIsEmpty =
        (wikiResult.status === "fulfilled" && wikiEntries.length === 0) || wikiNotGenerated;
      setQuestionSuggestions(suggestions);
      if (suggestions.length > 0) {
        setSuggestionState("ready");
      } else if (
        notesResult.status === "fulfilled" &&
        wikiIsEmpty &&
        notesPage?.total === 0
      ) {
        setSuggestionState("empty");
      } else {
        setSuggestionState("unavailable");
      }
    };

    void loadSuggestions().catch(() => {
      if (current) {
        setQuestionSuggestions([]);
        setSuggestionState("unavailable");
      }
    });
    return () => {
      current = false;
    };
  }, [health, view]);

  useEffect(() => {
    if (focusQuestion && view === "ask") {
      inputRef.current?.focus();
      setFocusQuestion(false);
    }
  }, [focusQuestion, view]);

  const prefillQuestion = useCallback((nextQuestion: string) => {
    setQuestion(nextQuestion);
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

  const askEntity = useCallback(
    (name: string) => prefillQuestion(`请介绍「${name}」。`),
    [prefillQuestion],
  );

  // 未就绪门控：置灰提交 + 引导卡片；readiness 为 null（加载中/获取失败）不阻塞
  const askBlocked = readiness !== null && !readiness.ready;
  const moreView = MOBILE_MORE_NAV.some((item) => item.name === view);
  const visibleNavItems = isMobileViewport ? NAV_ITEMS.slice(0, 3) : NAV_ITEMS;
  const serviceStatus = health === "ready" ? "服务正常" : health === "offline" ? "服务未连接" : "检查服务中";
  const serviceStatusColor = health === "ready" ? "green" : health === "offline" ? "red" : "gray";

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
      if (!isApiError(caught) || caught.code === "connection_error") {
        setHealth("offline");
      }
      setError(
        isApiError(caught)
          ? caught
          : { code: "connection_error", message: "无法连接本地服务，请确认 siku serve --with-ui 正在运行。" },
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
    <main className="app-shell" data-view={view}>
      <Container component="section" size="md" className="workspace" aria-labelledby="page-title">
        <Stack component="header" className="page-header" gap="sm">
          <Group className="page-status" justify="space-between" align="center" wrap="nowrap">
            <p className="eyebrow">SIKU / LOCAL KNOWLEDGE</p>
            <Group className="header-actions" gap="sm" wrap="nowrap">
              <Badge
                className="service-status"
                color={serviceStatusColor}
                variant="light"
                aria-live="polite"
              >
                {serviceStatus}
              </Badge>
              <div className="mobile-more-menu">
                <Menu position="bottom-end" offset={6} withinPortal>
                  <Menu.Target>
                    <Button
                      type="button"
                      variant="subtle"
                      className="mobile-more-trigger"
                      aria-label="更多视图"
                      aria-current={moreView ? "page" : undefined}
                      data-active={moreView || undefined}
                    >
                      <IconDotsVertical size={20} stroke={1.8} aria-hidden="true" />
                    </Button>
                  </Menu.Target>
                  <Menu.Dropdown className="mobile-more-dropdown" aria-label="更多视图">
                    <Menu.Label>其他视图</Menu.Label>
                    {MOBILE_MORE_NAV.map((item) => (
                      <Menu.Item key={item.name} onClick={() => setView(item.name)}>
                        {item.label}
                      </Menu.Item>
                    ))}
                  </Menu.Dropdown>
                </Menu>
              </div>
            </Group>
          </Group>
          <div className="page-intro">
            <h1 id="page-title">问问你的知识库</h1>
            <p className="subtitle">从本地事实层检索，再给出可核验的回答。</p>
          </div>
        </Stack>

        {health === "offline" && (
          <Alert className="status-card status-warning service-offline-alert" color="yellow" role="status" title="无法连接本地服务">
            <p>
              浏览器页面无法启动本地进程。浏览器模式请在终端运行 <code>siku serve --with-ui</code>；桌面应用可在恢复页选择“重新启动本地服务”。
            </p>
            <Button type="button" className="button-secondary" variant="default" onClick={() => void refreshHealth()}>
              检查连接
            </Button>
          </Alert>
        )}

        <Tabs
          className="view-tabs"
          value={view}
          variant="pills"
          color="siku"
          onChange={(nextView) => {
            const selectedView = NAV_ITEMS.find((item) => item.name === nextView);
            if (selectedView) {
              setView(selectedView.name);
            }
          }}
        >
          <nav className="view-navigation" aria-label="视图导航">
            <Tabs.List className="view-nav" aria-label="视图切换">
              {visibleNavItems.map((item) => (
                <Tabs.Tab key={item.name} className="nav-tab" value={item.name}>
                  {item.icon && <span className="mobile-nav-icon">{item.icon}</span>}
                  <span>{item.label}</span>
                </Tabs.Tab>
              ))}
            </Tabs.List>
          </nav>

          <Tabs.Panel value="settings" className="view-panel">
            {view === "settings" && (
              <SettingsView
                onSaved={(settings) => setReadiness(normalizeReadiness(settings.ask_readiness))}
              />
            )}
          </Tabs.Panel>

          <Tabs.Panel value="library" className="view-panel">
            {view === "library" && <LibraryView />}
          </Tabs.Panel>

          <Tabs.Panel value="browse" className="view-panel">
            {view === "browse" && <BrowseView />}
          </Tabs.Panel>

          <Tabs.Panel value="graph" className="view-panel">
            {view === "graph" && <GraphView onAskEntity={askEntity} />}
          </Tabs.Panel>

          <Tabs.Panel value="wiki" className="view-panel">
            {view === "wiki" && <WikiView />}
          </Tabs.Panel>

          <Tabs.Panel value="ask" className="view-panel">
            {view === "ask" && (
          <Stack gap={0}>
        <Paper
          component="form"
          className="question-card"
          withBorder
          shadow="xs"
          radius="lg"
          p="lg"
          onSubmit={(event) => {
            event.preventDefault();
            if (askState !== "loading") void submit();
          }}
        >
          <Textarea
            label="你的问题"
            ref={inputRef}
            id="question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={onQuestionKeyDown}
            placeholder="输入你想了解的内容"
            rows={4}
            className="question-input"
            aria-describedby={localError ? "question-hint question-error" : "question-hint"}
            aria-invalid={localError !== null}
          />
          {health === "ready" && (
            <section className="question-suggestions" aria-label="基于内容的提问建议">
              <p className="question-suggestions-title">来自你的知识库</p>
              {(suggestionState === "idle" || suggestionState === "loading") && (
                <Group className="suggestions-loading" role="status" aria-live="polite" gap="xs">
                  <Loader size="xs" />
                  <span className="hint">正在读取推荐问题…</span>
                </Group>
              )}
              {suggestionState === "ready" && (
                <div className="question-suggestion-list">
                  {questionSuggestions.map((suggestion) => (
                    <Button
                      key={suggestion.question}
                      type="button"
                      variant="default"
                      className="question-suggestion"
                      aria-label={suggestion.question}
                      title={suggestion.question}
                      onClick={() => prefillQuestion(suggestion.question)}
                    >
                      {suggestion.label}
                    </Button>
                  ))}
                </div>
              )}
              {suggestionState === "empty" && (
                <p className="hint">导入资料或生成 wiki 后，会根据已有内容推荐问题。</p>
              )}
              {suggestionState === "unavailable" && (
                <p className="hint">暂时无法读取推荐内容，你仍可以直接输入问题。</p>
              )}
            </section>
          )}
          <Group className="question-footer" justify="space-between" align="center" wrap="wrap">
            <p id="question-hint" className="hint">
              {askBlocked ? "配置模型端点后即可提问" : "Enter 提交 · Shift + Enter 换行"}
            </p>
            <Button type="submit" loading={askState === "loading"} disabled={askBlocked}>
              {askState === "loading" ? "检索与回答中…" : "提交问题"}
            </Button>
          </Group>
          {localError && (
            <Alert id="question-error" color="red" role="alert" title="无法提交">
              {localError}
            </Alert>
          )}
        </Paper>

        {askBlocked && readiness && (
          <Alert className="status-card status-warning" color="yellow" role="status" title="问答尚未就绪——模型端点未配置">
              <div>
                <p>
                {describeMissing(readiness.missing)}
                配置保存后免重启生效，回到本页即可提交问题。
              </p>
              </div>
            <Button
              type="button"
              className="button-secondary"
              variant="default"
              onClick={() => setView("settings")}
            >
              去设置
            </Button>
          </Alert>
            )}

        {askState === "loading" && (
          <Alert
            className="answer-card loading-card"
            color="blue"
            role="status"
            aria-live="polite"
            title="正在从本地知识库寻找依据"
            icon={<Loader size="sm" aria-hidden="true" />}
          >
            <p>回答只会基于本次检索到的片段。</p>
          </Alert>
        )}

        {askState === "error" && error && (
          <Alert className="status-card status-error" color="red" role="alert" title={error.code}>
              <strong>{error.message}</strong>
            <Button type="button" className="button-secondary" variant="default" onClick={() => void submit()}>
              重试问答
            </Button>
          </Alert>
        )}

        {askState === "success" && answer && (
          <Paper component="article" withBorder shadow="xs" radius="lg" p="xl" className="answer-card" aria-labelledby="answer-title">
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
          </Paper>
        )}
          </Stack>
        )}
          </Tabs.Panel>
        </Tabs>
      </Container>
    </main>
  );
}

export default App;
