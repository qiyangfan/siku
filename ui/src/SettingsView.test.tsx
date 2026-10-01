import { cleanup, screen, waitFor, within } from "@testing-library/react";
import { render } from "./test-utils";
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
  invalid_config_file_overwritten: false,
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
    if (url.endsWith("/api/health")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ status: "ok", version: "0.1.0" }),
      } as Response);
    }
    if (url.includes("/api/notes")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ notes: [], total: 0, page: 1, page_size: 5 }),
      } as Response);
    }
    if (url.endsWith("/api/wiki/entries")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ entries: [] }) } as Response);
    }
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
    expect(within(groups[0]).getByRole("radiogroup", { name: "凭证来源" })).toBeInTheDocument();
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
    mockFetch(calls, { get: settings, put: { ...settings, warnings: [], invalid_config_file_overwritten: false } });
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

  it("保存覆盖了不可解析的配置文件时显式告知,不做静默替换", async () => {
    const calls: Call[] = [];
    mockFetch(calls, {
      get: settings,
      put: { ...settings, warnings: [], invalid_config_file_overwritten: true },
    });
    const user = userEvent.setup();
    render(<SettingsView />);

    await screen.findAllByRole("group");
    await user.click(screen.getByRole("button", { name: "保存设置" }));

    expect(await screen.findByText("原配置文件不可解析")).toBeInTheDocument();
    expect(screen.getByText(/以空配置为基底写入了新内容并覆盖该文件/)).toBeInTheDocument();
    // 告知是一次性的:再次正常保存必须撤下,不得滞留成常驻文案
    mockFetch(calls, {
      get: settings,
      put: { ...settings, warnings: [], invalid_config_file_overwritten: false },
    });
    await user.click(screen.getByRole("button", { name: "保存设置" }));
    await waitFor(() =>
      expect(screen.queryByText("原配置文件不可解析")).not.toBeInTheDocument(),
    );
  });

  it("配置文件不可解析(成因码可辨)时给出覆盖自救入口,确认后按空配置出图", async () => {
    // 回归钉子:读面曾把这张页堵成只剩「重试读取」,而 503 文案承诺「重新保存即可覆盖」;
    // 入口必须只出现在 invalid_config_file 这一型(权限/IO 读不到时覆盖会毁掉好配置)
    const calls: Call[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : String(input instanceof URL ? input : input.url);
      calls.push({ url, init });
      if (url.endsWith("/api/settings") && (init?.method ?? "GET") === "GET") {
        return {
          ok: false,
          status: 503,
          json: () =>
            Promise.resolve({
              code: "invalid_config_file",
              message: "模型配置文件不可解析（内容已损坏）：可重新填写并保存以覆盖。",
            }),
        } as Response;
      }
      return {
        ok: true,
        json: () =>
          Promise.resolve({
            ...settings,
            warnings: [],
            invalid_config_file_overwritten: true,
          }),
      } as Response;
    });
    const user = userEvent.setup();
    render(<SettingsView />);

    expect(await screen.findByText("设置读取失败")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "确认以空配置覆盖本机配置文件并重新填写" }),
    );

    await screen.findByText("模型供给设置");
    expect(screen.getByText("按空配置显示")).toBeInTheDocument();
    // 不伪造服务端读数:路径行不出图,表单按空值渲染
    expect(screen.queryByText(/配置写入/)).not.toBeInTheDocument();
    const llm = within(await screen.findByRole("group", { name: "LLM 通道" }));
    expect(llm.getByLabelText("base_url")).toHaveValue("");

    await user.click(screen.getByRole("button", { name: "保存设置" }));
    expect(calls.some((call) => call.init?.method === "PUT")).toBe(true);
    expect(await screen.findByText("原配置文件不可解析")).toBeInTheDocument();
  });

  it("读不到文件(内容未知)时不给覆盖入口:保存无法修好它", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      Promise.resolve({
        ok: false,
        status: 503,
        json: () =>
          Promise.resolve({
            code: "config_file_unreadable",
            message: "模型配置文件当前无法读取（权限或磁盘故障，不是内容损坏）。",
          }),
      } as Response),
    );
    render(<SettingsView />);

    expect(await screen.findByText("设置读取失败")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "确认以空配置覆盖本机配置文件并重新填写" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("模型供给设置")).not.toBeInTheDocument();
  });

  it("env 模式下已存明文 key 时提示优先生效，并可直接勾选清除", async () => {
    const calls: Call[] = [];
    mockFetch(calls, { get: settings, put: { ...settings, warnings: [], invalid_config_file_overwritten: false } });
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
    expect(body.embedding).toEqual({ base_url: "", model: "", api_key_env: "", protocol: "" });
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
    mockFetch(calls, { get: settings, put: { ...settings, warnings: [], invalid_config_file_overwritten: false } });
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
    await user.click(screen.getByRole("tab", { name: "设置" }));

    await waitFor(() =>
      expect(calls.some((call) => call.url.endsWith("/api/settings"))).toBe(true),
    );
    expect(await screen.findByRole("button", { name: "保存设置" })).toBeInTheDocument();
  });

  it("选择厂商预设自动填充端点与凭证模式，且仍可手改", async () => {
    mockFetch([], { get: settings });
    const user = userEvent.setup();
    render(<SettingsView />);

    const groups = await screen.findAllByRole("group");
    const llm = groups[0];
    await user.selectOptions(
      within(llm).getByLabelText("LLM 通道厂商预设"),
      "通义千问（阿里云百炼）",
    );

    expect(within(llm).getByLabelText("base_url")).toHaveValue(
      "https://dashscope.aliyuncs.com/compatible-mode/v1",
    );
    expect(within(llm).getByLabelText("model")).toHaveValue("qwen-max");
    expect(within(llm).getByLabelText("api_key_env（环境变量名）")).toHaveValue("DASHSCOPE_API_KEY");
    expect(within(llm).getByRole("radio", { name: "引用环境变量" })).toBeChecked();

    // 填充后仍可手改：直接改 model 不被预设霸占
    await user.clear(within(llm).getByLabelText("model"));
    await user.type(within(llm).getByLabelText("model"), "qwen-plus");
    expect(within(llm).getByLabelText("model")).toHaveValue("qwen-plus");
  });

  it("Ollama 本地预设免凭证：回到直接填写并清空后备 env", async () => {
    mockFetch([], { get: settings });
    const user = userEvent.setup();
    render(<SettingsView />);

    const groups = await screen.findAllByRole("group");
    const llm = groups[0];
    await user.selectOptions(
      within(llm).getByLabelText("LLM 通道厂商预设"),
      "Ollama 本地",
    );

    expect(within(llm).getByLabelText("base_url")).toHaveValue("http://127.0.0.1:11434/v1");
    expect(within(llm).getByRole("radio", { name: "直接填写 key" })).toBeChecked();
    await user.click(within(llm).getByRole("radio", { name: "引用环境变量" }));
    expect(within(llm).getByLabelText("api_key_env（环境变量名）")).toHaveValue("");
  });

  it("切换接口协议后保存，PUT 提交携带所选协议", async () => {
    const calls: Call[] = [];
    mockFetch(calls, { get: settings, put: savedSettings });
    const user = userEvent.setup();
    render(<SettingsView />);

    const groups = await screen.findAllByRole("group");
    await user.selectOptions(within(groups[0]).getByLabelText("LLM 通道接口协议"), "anthropic");
    await user.click(screen.getByRole("button", { name: "保存设置" }));

    await waitFor(() => expect(calls.some((call) => call.init?.method === "PUT")).toBe(true));
    const put = calls.find((call) => call.init?.method === "PUT");
    expect(JSON.parse(String(put?.init?.body)).llm.protocol).toBe("anthropic");
  });

  it("保存前点测试连接按表单当前协议探测", async () => {
    const calls: Call[] = [];
    mockFetch(calls, {
      get: settings,
      test: { ok: true, channel: "llm", latency_ms: 12 },
    });
    const user = userEvent.setup();
    render(<SettingsView />);

    const groups = await screen.findAllByRole("group");
    await user.selectOptions(within(groups[0]).getByLabelText("LLM 通道接口协议"), "anthropic");
    await user.click(within(groups[0]).getByRole("button", { name: "测试连接" }));

    await waitFor(() =>
      expect(calls.some((call) => call.url.endsWith("/api/settings/test"))).toBe(true),
    );
    const testCall = calls.find((call) => call.url.endsWith("/api/settings/test"));
    expect(JSON.parse(String(testCall?.init?.body)).protocol).toBe("anthropic");
  });

  it("选择 Anthropic 分支预设同时填充端点与协议", async () => {
    mockFetch([], { get: settings });
    const user = userEvent.setup();
    render(<SettingsView />);

    const groups = await screen.findAllByRole("group");
    const llm = groups[0];
    await user.selectOptions(
      within(llm).getByLabelText("LLM 通道厂商预设"),
      "Kimi（Anthropic 分支）",
    );
    expect(within(llm).getByLabelText("base_url")).toHaveValue("https://api.moonshot.cn/anthropic");
    expect(within(llm).getByLabelText("LLM 通道接口协议")).toHaveValue("anthropic");
    // embedding/rerank 通道不出现协议控件
    expect(within(groups[1]).queryByLabelText(/接口协议/)).not.toBeInTheDocument();
  });

  it("LLM 通道回退生效时展示来源说明，不误导为完全未配置", async () => {
    mockFetch([], {
      get: {
        ...settings,
        llm: { ...settings.llm, base_url: null, model: null, api_key_set: false },
        llm_env_fallback: {
          vendor: "dashscope",
          base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
          model: "qwen-max",
          api_key_env: "DASHSCOPE_API_KEY",
        },
      },
    });
    render(<SettingsView />);

    const note = await screen.findByText(/未显式配置 LLM 通道：当前按环境变量/);
    expect(note).toBeInTheDocument();
    expect(note).toHaveTextContent("DASHSCOPE_API_KEY");
    expect(note).toHaveTextContent("qwen-max");
  });
});
