import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MantineProvider } from "@mantine/core";
import "@mantine/core/styles.css";
import App from "./App";
import { cssVariablesResolver, theme } from "./theme";

const previewMode = new URLSearchParams(window.location.search).get("mode");
const showSampleContent = previewMode === "sample" || previewMode === "sample-long";
let healthFailuresRemaining = previewMode === "offline" ? 2 : 0;
const longPreviewTitle = "跨团队本地优先知识治理、自动化研发协作与长期服务恢复完整实践指南";
const longPreviewSection = "导入资料版本变更与冲突处理、旧内容清理以及索引重建的完整操作流程";

const sampleNotes = [
  {
    source_id: "guide-01",
    source_name: "研发协作指南.md",
    note_path: "notes/guide-01.md",
    source_hash: "a".repeat(64),
    extractor: "MarkdownExtractor",
  },
  {
    source_id: "skill-01",
    source_name: "SKILL.md",
    note_path: "notes/skill-01.md",
    source_hash: "b".repeat(64),
    extractor: "MarkdownExtractor",
  },
];

window.fetch = async (input) => {
  const url = input instanceof Request ? input.url : String(input);
  const path = new URL(url, window.location.origin).pathname;
  if (path === "/api/health" && healthFailuresRemaining > 0) {
    healthFailuresRemaining -= 1;
    return new Response("service unavailable", { status: 503 });
  }
  const payload = path === "/api/health"
    ? { status: "ok", version: "0.1.0" }
    : path === "/api/settings"
      ? {
          config_path: "~/Library/Application Support/siku/config.toml",
          llm: { base_url: null, model: null, api_key_env: null, api_key_set: false, env_overrides: [] },
          embedding: { base_url: null, model: null, api_key_env: null, api_key_set: false, env_overrides: [] },
          rerank: { base_url: null, model: null, api_key_env: null, api_key_set: false, env_overrides: [] },
          ask_readiness: { ready: true, missing: [] },
        }
      : path === "/api/notes"
        ? {
            notes: showSampleContent ? sampleNotes : [],
            total: showSampleContent ? sampleNotes.length : 0,
            page: 1,
            page_size: 5,
          }
      : path === "/api/notes/guide-01"
          ? {
              ...sampleNotes[0],
              source_name: previewMode === "sample-long" ? `${longPreviewTitle}.md` : "研发协作指南.md",
              anchors: [previewMode === "sample-long" ? longPreviewSection : "需求到变更的闭环"],
              content: previewMode === "sample-long"
                ? `# ${longPreviewTitle}\n\n## ${longPreviewSection}\n样例内容。`
                : "# 研发协作指南\n\n## 需求到变更的闭环\n样例内容。",
            }
          : path === "/api/notes/skill-01"
            ? {
                ...sampleNotes[1],
                anchors: ["提交前的质量门禁"],
                content: "# Python 工程检查\n\n## 提交前的质量门禁\n样例内容。",
              }
            : path === "/api/wiki/entries"
              ? {
                  entries: showSampleContent
                    ? [{ community_id: 2, title: "社区 0002", generated_at: "now" }]
                    : [],
                }
              : path === "/api/wiki/entries/2"
                ? {
                    community_id: 2,
                    title: "社区 0002",
                    content: "# 社区 0002\n\n## 成员实体\n\n- 异步任务（能力）\n- 故障恢复（流程）\n",
                    generated_at: "now",
                  }
                : path === "/api/library"
                  ? { sources: [] }
                  : path === "/api/library/sources"
                    ? { sources: [] }
                    : path === "/api/library/scan-settings"
                      ? { interval_secs: 86_400 }
        : path === "/api/graph/stats"
        ? { nodes: 0, edges: 0, communities: 0, types: {} }
        : path === "/api/graph/overview"
          ? { nodes: [], edges: [], truncated: false, total_nodes: 0, total_edges: 0 }
          : { total: 0, page: 1, page_size: 20, notes: [] };
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
};

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MantineProvider theme={theme} cssVariablesResolver={cssVariablesResolver} forceColorScheme="light">
      <App />
    </MantineProvider>
  </StrictMode>,
);
