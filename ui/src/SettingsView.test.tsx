import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { SettingsView } from "./SettingsView";

const settings = {
  config_path: "/Users/tester/Library/Application Support/siku/config.toml",
  llm: {
    base_url: "https://api.deepseek.com",
    model: "deepseek-chat",
    api_key_env: null,
    api_key_set: true,
    env_overrides: [],
  },
  embedding: {
    base_url: null,
    model: null,
    api_key_env: null,
    api_key_set: false,
    env_overrides: [],
  },
  rerank: {
    base_url: null,
    model: null,
    api_key_env: null,
    api_key_set: false,
    env_overrides: ["base_url"],
  },
};

const savedSettings = {
  ...settings,
  llm: { ...settings.llm, model: "deepseek-chat-new" },
  warnings: [] as string[],
};

type Call = { url: string; init?: RequestInit };

function mockFetch(calls: Call[], handlers: {
  get?: unknown;
  put?: unknown;
  putOk?: boolean;
  test?: unknown;
  testOk?: boolean;
}) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = typeof input === "string" ? input : String(input instanceof URL ? input : input.url);
    calls.push({ url, init });
    if (url.endsWith("/api/settings/test")) {
      return Promise.resolve({
        ok: handlers.testOk ?? true,
        json: () => Promise.resolve(handlers.test),
      } as Response);
    }
    if (init?.method === "PUT") {
      return Promise.resolve({
        ok: handlers.putOk ?? true,
        json: () => Promise.resolve(handlers.put),
      } as Response);
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(handlers.get) } as Response);
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("设置中心", () => {
  it("回填文件层配置，key 以占位标识且不回显", async () => {
    mockFetch([], { get: settings });
    render(<SettingsView />);

    const groups = await screen.findAllByRole("group");
    expect(groups).toHaveLength(3);
    expect(within(groups[0]).getByLabelText("base_url")).toHaveValue("https://api.deepseek.com");
    expect(within(groups[0]).getByLabelText("model")).toHaveValue("deepseek-chat");
    const keyInput = within(groups[0]).getByLabelText("api_key（只写不回显）");
    expect(keyInput).toHaveValue("");
    expect(within(groups[0]).getByPlaceholderText("已设置——留空保持不变")).toBeInTheDocument();
    // 已存明文 key 的通道默认停在「直接填写」
    expect(within(groups[0]).getByRole("radio", { name: "直接填写 key" })).toBeChecked();
    expect(
      within(groups[2]).getByText(/以下字段当前由环境变量层覆盖.*base_url/),
    ).toBeInTheDocument();
  });

  it("凭证方式按已存配置推导：仅存环境变量名的通道选中「引用环境变量」", async () => {
    mockFetch([], {
      get: {
        ...settings,
        llm: { ...settings.llm, api_key_set: false, api_key_env: "SIKU_LLM_API_KEY" },
      },
    });
    render(<SettingsView />);

    const groups = await screen.findAllByRole("group");
    const llm = within(groups[0]);
    expect(llm.getByRole("radio", { name: "引用环境变量" })).toBeChecked();
    expect(llm.getByLabelText("api_key_env（环境变量名）")).toHaveValue("SIKU_LLM_API_KEY");
    expect(llm.queryByLabelText("api_key（只写不回显）")).not.toBeInTheDocument();
    // 未设置任何凭证的通道默认「直接填写」
    expect(within(groups[1]).getByRole("radio", { name: "直接填写 key" })).toBeChecked();
  });

  it("切换到「引用环境变量」丢弃未保存明文，按环境变量方式保存", async () => {
    const calls: Call[] = [];
    mockFetch(calls, { get: settings, put: { ...settings, warnings: [] } });
    const user = userEvent.setup();
    render(<SettingsView />);

    const groups = await screen.findAllByRole("group");
    const llm = within(groups[0]);
    await user.type(llm.getByLabelText("api_key（只写不回显）"), "sk-tmp");
    await user.click(llm.getByRole("radio", { name: "引用环境变量" }));
    await user.type(llm.getByLabelText("api_key_env（环境变量名）"), "SIKU_LLM_API_KEY");
    await user.click(screen.getByRole("button", { name: "保存设置" }));

    expect(await screen.findByText("设置已保存，无需重启即可生效。")).toBeInTheDocument();
    const body = JSON.parse(
      String(calls.find((call) => call.init?.method === "PUT")?.init?.body),
    );
    expect(body.llm.api_key_env).toBe("SIKU_LLM_API_KEY");
    expect(body.llm).not.toHaveProperty("api_key");
  });

  it("env 模式下已存明文 key 时提示优先生效，并可直接勾选清除", async () => {
    const calls: Call[] = [];
    mockFetch(calls, { get: settings, put: { ...settings, warnings: [] } });
    const user = userEvent.setup();
    render(<SettingsView />);

    const groups = await screen.findAllByRole("group");
    const llm = within(groups[0]);
    await user.click(llm.getByRole("radio", { name: "引用环境变量" }));
    expect(llm.getByText(/已保存的明文 key 优先生效/)).toBeInTheDocument();
    await user.click(llm.getByLabelText("清除已保存的 key（保存后生效）"));
    await user.click(screen.getByRole("button", { name: "保存设置" }));

    expect(await screen.findByText("设置已保存，无需重启即可生效。")).toBeInTheDocument();
    const body = JSON.parse(
      String(calls.find((call) => call.init?.method === "PUT")?.init?.body),
    );
    expect(body.llm.api_key).toBeNull();
    expect(body.llm.api_key_env).toBe("");
  });

  it("保存时未触碰的 key 不上传，输入新 key 才提交", async () => {
    const calls: Call[] = [];
    mockFetch(calls, { get: settings, put: savedSettings });
    const user = userEvent.setup();
    render(<SettingsView />);

    const groups = await screen.findAllByRole("group");
    await user.type(within(groups[0]).getByLabelText("model"), "-new");
    await user.click(screen.getByRole("button", { name: "保存设置" }));

    expect(await screen.findByText("设置已保存，无需重启即可生效。")).toBeInTheDocument();
    const putCall = calls.find((call) => call.init?.method === "PUT");
    expect(putCall).toBeDefined();
    const body = JSON.parse(String(putCall?.init?.body));
    expect(body.llm.model).toBe("deepseek-chat-new");
    expect(body.llm).not.toHaveProperty("api_key");
    expect(body.llm.base_url).toBe("https://api.deepseek.com");
    expect(body.embedding).toEqual({ base_url: "", model: "", api_key_env: "" });
    // 保存后表单以服务端掩码视图为准：key 输入框仍为空
    expect(within(groups[0]).getByLabelText("api_key（只写不回显）")).toHaveValue("");
  });

  it("保存成功后显著呈现重建索引告警，不误导为失败", async () => {
    const calls: Call[] = [];
    const warningText =
      "embedding 模型身份已变更（model-a → model-b）：请执行 `siku index --rebuild` 全量重建索引。";
    mockFetch(calls, {
      get: settings,
      put: { ...savedSettings, warnings: [warningText] },
    });
    const user = userEvent.setup();
    render(<SettingsView />);

    await screen.findAllByRole("group");
    await user.click(screen.getByRole("button", { name: "保存设置" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("需要重建索引");
    expect(alert).toHaveTextContent("全量重建");
    expect(screen.getByText("设置已保存，无需重启即可生效。")).toBeInTheDocument();
  });

  it("显式勾选清除已保存的 key 时提交 null", async () => {
    const calls: Call[] = [];
    mockFetch(calls, { get: settings, put: { ...settings, warnings: [] } });
    const user = userEvent.setup();
    render(<SettingsView />);

    const groups = await screen.findAllByRole("group");
    await user.click(within(groups[0]).getByLabelText("清除已保存的 key（保存后生效）"));
    await user.click(screen.getByRole("button", { name: "保存设置" }));

    expect(await screen.findByText("设置已保存，无需重启即可生效。")).toBeInTheDocument();
    const body = JSON.parse(
      String(calls.find((call) => call.init?.method === "PUT")?.init?.body),
    );
    expect(body.llm.api_key).toBeNull();
  });

  it("保存失败时展示 API 中文信息并保留已输入内容", async () => {
    const calls: Call[] = [];
    mockFetch(calls, {
      get: settings,
      put: { code: "invalid_settings", message: "LLM 通道的 base_url 非法：请填写完整 URL。" },
      putOk: false,
    });
    const user = userEvent.setup();
    render(<SettingsView />);

    const groups = await screen.findAllByRole("group");
    await user.clear(within(groups[0]).getByLabelText("base_url"));
    await user.type(within(groups[0]).getByLabelText("base_url"), "not-a-url");
    await user.click(screen.getByRole("button", { name: "保存设置" }));

    expect(await screen.findByText("LLM 通道的 base_url 非法：请填写完整 URL。")).toBeInTheDocument();
    expect(within(groups[0]).getByLabelText("base_url")).toHaveValue("not-a-url");
  });

  it("连通性测试期间禁用按钮，完成后展示耗时", async () => {
    const calls: Call[] = [];
    let resolveTest!: (value: Response) => void;
    const spy = mockFetch(calls, { get: settings, test: { ok: true, channel: "llm", latency_ms: 42 } });
    spy.mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : String(input instanceof URL ? input : input.url);
      calls.push({ url, init });
      if (url.endsWith("/api/settings/test")) {
        return new Promise<Response>((resolve) => {
          resolveTest = resolve;
        });
      }
      if (init?.method === "PUT") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(savedSettings) } as Response);
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve(settings) } as Response);
    });
    const user = userEvent.setup();
    render(<SettingsView />);

    const groups = await screen.findAllByRole("group");
    const testButton = within(groups[0]).getByRole("button", { name: "测试连接" });
    await user.click(testButton);
    expect(within(groups[0]).getByRole("button", { name: "测试中…" })).toBeDisabled();

    resolveTest({ ok: true, json: () => Promise.resolve({ ok: true, channel: "llm", latency_ms: 42 }) } as Response);
    expect(await screen.findByText("连接成功，耗时 42 ms。")).toBeInTheDocument();
    expect(
      within(groups[0]).getByRole("button", { name: "测试连接" }),
    ).toBeEnabled();
  });

  it("连通性测试失败展示中文指引", async () => {
    const calls: Call[] = [];
    mockFetch(calls, {
      get: settings,
      test: { code: "model_not_available", message: "LLM 端点拒绝了当前凭证或配置不完整。" },
      testOk: false,
    });
    const user = userEvent.setup();
    render(<SettingsView />);

    const groups = await screen.findAllByRole("group");
    await user.click(within(groups[0]).getByRole("button", { name: "测试连接" }));

    expect(
      await screen.findByText("LLM 端点拒绝了当前凭证或配置不完整。"),
    ).toBeInTheDocument();
  });

  it("App 内设置入口可达并加载设置视图", async () => {
    const calls: Call[] = [];
    mockFetch(calls, { get: settings });
    const user = userEvent.setup();

    render(<App />);
    await user.click(screen.getByRole("button", { name: "设置" }));

    await waitFor(() =>
      expect(calls.some((call) => call.url.endsWith("/api/settings"))).toBe(true),
    );
    expect(await screen.findByRole("button", { name: "保存设置" })).toBeInTheDocument();
  });
});
