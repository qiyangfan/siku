import { cleanup, screen } from "@testing-library/react";
import { render } from "./test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LlmReadinessHint } from "./LlmReadinessHint";

function mockSettings(askReadiness: unknown) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = typeof input === "string" ? input : String(input);
    if (url.includes("/api/settings")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            config_path: "/tmp/config.toml",
            ask_readiness: askReadiness,
          }),
      } as Response);
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response);
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("LlmReadinessHint", () => {
  it("llm 通道 invalid 时给无效变体与去设置入口，不说已就绪", async () => {
    mockSettings({ ready: false, missing: [], invalid: ["llm.protocol"] });
    render(<LlmReadinessHint onGoToSettings={() => {}} />);

    const note = await screen.findByText(/配置无效/);
    expect(note).toHaveTextContent("环境变量层");
    expect(screen.getByRole("button", { name: "去设置" })).toBeInTheDocument();
    expect(screen.queryByText(/模型通道已就绪/)).not.toBeInTheDocument();
  });

  it("仅缺凭证时保持既有缺失变体", async () => {
    mockSettings({ ready: false, missing: ["llm.api_key"], invalid: [] });
    render(<LlmReadinessHint onGoToSettings={() => {}} />);

    expect(await screen.findByText(/API key 未配置/)).toBeInTheDocument();
  });

  it("就绪且无 invalid 时展示就绪文案", async () => {
    mockSettings({ ready: true, missing: [], invalid: [] });
    render(<LlmReadinessHint onGoToSettings={() => {}} />);

    expect(await screen.findByText(/模型通道已就绪/)).toBeInTheDocument();
  });
});
