import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Fieldset,
  Group,
  Loader,
  NativeSelect,
  PasswordInput,
  Radio,
  Stack,
  TextInput,
} from "@mantine/core";
import {
  getSettings,
  testChannel,
  updateSettings,
  type ApiError,
  type ChannelName,
  type ChannelSettingsPayload,
  type ChannelSettingsView,
  type SettingsResponse,
  type SettingsTestPayload,
} from "./api";

type KeyMode = "direct" | "env";

type ChannelForm = {
  base_url: string;
  model: string;
  key_mode: KeyMode;
  api_key: string;
  api_key_env: string;
  protocol: string;
  clearStoredKey: boolean;
};

// LLM 线协议（ADR-0012）；空串 = 未显式设置（内核按 openai-chat 执行）
const LLM_PROTOCOL_OPTIONS = [
  { value: "openai-chat", label: "OpenAI Chat 兼容（/chat/completions）" },
  { value: "anthropic", label: "Anthropic Messages 兼容（/v1/messages）" },
  { value: "openai-responses", label: "OpenAI Responses（/responses）" },
];

type SaveState = "idle" | "loading";

type ChannelTestState =
  | { kind: "loading" }
  | { kind: "done"; ok: boolean; message: string }
  | null;

// 厂商预设（静态填充表，只住 UI 层）：官方几家 + 本地 Ollama，中转站不做。
// model 为常用默认，以厂商当前列表为准可手改；api_key_env 为 null 表示本地无凭证。
type VendorPreset = {
  id: string;
  label: string;
  base_url: string;
  model: string;
  api_key_env: string | null;
  // 该预设的线协议；null = 不适用（embedding/rerank 预设）或不改动
  protocol: string | null;
};

const LLM_PRESETS: VendorPreset[] = [
  {
    id: "dashscope",
    label: "通义千问（阿里云百炼）",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: "qwen-max",
    api_key_env: "DASHSCOPE_API_KEY",
    protocol: "openai-chat",
  },
  {
    id: "dashscope-anthropic",
    label: "通义千问（Anthropic 分支）",
    base_url: "https://dashscope.aliyuncs.com/api/v2/apps/claude-code-proxy",
    model: "qwen3-max",
    api_key_env: "DASHSCOPE_API_KEY",
    protocol: "anthropic",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    base_url: "https://api.deepseek.com",
    model: "deepseek-chat",
    api_key_env: "DEEPSEEK_API_KEY",
    protocol: "openai-chat",
  },
  {
    id: "moonshot",
    label: "Kimi（月之暗面）",
    base_url: "https://api.moonshot.cn/v1",
    model: "kimi-k2-0905-preview",
    api_key_env: "MOONSHOT_API_KEY",
    protocol: "openai-chat",
  },
  {
    id: "moonshot-anthropic",
    label: "Kimi（Anthropic 分支）",
    base_url: "https://api.moonshot.cn/anthropic",
    model: "kimi-k2-0905-preview",
    api_key_env: "MOONSHOT_API_KEY",
    protocol: "anthropic",
  },
  {
    id: "zhipu",
    label: "智谱 GLM",
    base_url: "https://open.bigmodel.cn/api/paas/v4",
    model: "glm-4-plus",
    api_key_env: "ZHIPUAI_API_KEY",
    protocol: "openai-chat",
  },
  {
    id: "zhipu-anthropic",
    label: "智谱 GLM（Anthropic 分支）",
    base_url: "https://open.bigmodel.cn/api/anthropic",
    model: "glm-4-plus",
    api_key_env: "ZHIPUAI_API_KEY",
    protocol: "anthropic",
  },
  {
    id: "siliconflow",
    label: "硅基流动 SiliconFlow",
    base_url: "https://api.siliconflow.cn/v1",
    model: "deepseek-ai/DeepSeek-V3",
    api_key_env: "SILICONFLOW_API_KEY",
    protocol: "openai-chat",
  },
  {
    id: "volcengine-ark",
    label: "火山方舟（豆包）",
    base_url: "https://ark.cn-beijing.volces.com/api/v3",
    model: "doubao-seed-1.6",
    api_key_env: "ARK_API_KEY",
    protocol: "openai-chat",
  },
  {
    id: "qianfan",
    label: "百度千帆",
    base_url: "https://qianfan.baidubce.com/v2",
    model: "ernie-4.5-turbo-128k",
    api_key_env: "QIANFAN_API_KEY",
    protocol: "openai-chat",
  },
  {
    id: "openai",
    label: "OpenAI",
    base_url: "https://api.openai.com/v1",
    model: "gpt-4o-mini",
    api_key_env: "OPENAI_API_KEY",
    protocol: "openai-chat",
  },
  {
    id: "anthropic",
    label: "Anthropic Claude",
    base_url: "https://api.anthropic.com/v1",
    model: "claude-sonnet-4-5",
    api_key_env: "ANTHROPIC_API_KEY",
    protocol: "openai-chat",
  },
  {
    id: "anthropic-native",
    label: "Anthropic Claude（原生协议）",
    base_url: "https://api.anthropic.com",
    model: "claude-sonnet-4-5",
    api_key_env: "ANTHROPIC_API_KEY",
    protocol: "anthropic",
  },
  {
    id: "gemini",
    label: "Google Gemini",
    base_url: "https://generativelanguage.googleapis.com/v1beta/openai",
    model: "gemini-2.5-flash",
    api_key_env: "GEMINI_API_KEY",
    protocol: "openai-chat",
  },
  {
    id: "xai",
    label: "xAI Grok",
    base_url: "https://api.x.ai/v1",
    model: "grok-4",
    api_key_env: "XAI_API_KEY",
    protocol: "openai-chat",
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    base_url: "https://openrouter.ai/api/v1",
    model: "openai/gpt-4o-mini",
    api_key_env: "OPENROUTER_API_KEY",
    protocol: "openai-chat",
  },
  {
    id: "ollama",
    label: "Ollama 本地",
    base_url: "http://127.0.0.1:11434/v1",
    model: "qwen3:8b",
    api_key_env: null,
    protocol: "openai-chat",
  },
];

const EMBEDDING_PRESETS: VendorPreset[] = [
  {
    id: "dashscope-embedding",
    label: "通义千问（阿里云百炼）",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: "text-embedding-v4",
    api_key_env: "DASHSCOPE_API_KEY",
    protocol: null,
  },
  {
    id: "siliconflow-embedding",
    label: "硅基流动 SiliconFlow",
    base_url: "https://api.siliconflow.cn/v1",
    model: "BAAI/bge-m3",
    api_key_env: "SILICONFLOW_API_KEY",
    protocol: null,
  },
  {
    id: "openai-embedding",
    label: "OpenAI",
    base_url: "https://api.openai.com/v1",
    model: "text-embedding-3-small",
    api_key_env: "OPENAI_API_KEY",
    protocol: null,
  },
  {
    id: "zhipu-embedding",
    label: "智谱 GLM",
    base_url: "https://open.bigmodel.cn/api/paas/v4",
    model: "embedding-3",
    api_key_env: "ZHIPUAI_API_KEY",
    protocol: null,
  },
  {
    id: "ollama-embedding",
    label: "Ollama 本地",
    base_url: "http://127.0.0.1:11434/v1",
    model: "bge-m3",
    api_key_env: null,
    protocol: null,
  },
];

const RERANK_PRESETS: VendorPreset[] = [
  {
    id: "siliconflow-rerank",
    label: "硅基流动 SiliconFlow",
    base_url: "https://api.siliconflow.cn/v1",
    model: "BAAI/bge-reranker-v2-m3",
    api_key_env: "SILICONFLOW_API_KEY",
    protocol: null,
  },
];

const CHANNEL_PRESETS: Record<ChannelName, VendorPreset[]> = {
  llm: LLM_PRESETS,
  embedding: EMBEDDING_PRESETS,
  rerank: RERANK_PRESETS,
};

// 通道视图不可得（配置文件未能读取）时的显示基底：按「未设置」渲染，不伪造服务端读数
const BLANK_CHANNEL_VIEW: ChannelSettingsView = {
  base_url: null,
  model: null,
  api_key_env: null,
  protocol: null,
  api_key_set: false,
  env_overrides: [],
};

const EMPTY_FORM: ChannelForm = {
  base_url: "",
  model: "",
  key_mode: "direct",
  api_key: "",
  api_key_env: "",
  protocol: "",
  clearStoredKey: false,
};

const CHANNEL_META: { key: ChannelName; title: string; description: string }[] = [
  { key: "llm", title: "LLM 通道", description: "问答、图谱与 wiki 总目使用的生成模型。" },
  { key: "embedding", title: "embedding 通道", description: "检索的向量化通道；更换模型后需全量重建索引。" },
  { key: "rerank", title: "rerank 通道（可选）", description: "留空即不启用重排，检索按 RRF 融合分数直接排序。" },
];

// 与内核 SIKU_LLM_* / SIKU_EMBEDDING_* / SIKU_RERANK_* 前缀一致，用于占位示例
const CHANNEL_KEY_ENV_PREFIX: Record<ChannelName, string> = {
  llm: "SIKU_LLM",
  embedding: "SIKU_EMBEDDING",
  rerank: "SIKU_RERANK",
};

// 已存明文 key 优先生效（与内核 resolve_api_key 口径一致），故默认停在「直接填写」
function keyModeFrom(view: ChannelSettingsView): KeyMode {
  if (view.api_key_set) {
    return "direct";
  }
  return view.api_key_env ? "env" : "direct";
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

function formFrom(view: ChannelSettingsView): ChannelForm {
  return {
    base_url: view.base_url ?? "",
    model: view.model ?? "",
    key_mode: keyModeFrom(view),
    api_key: "",
    api_key_env: view.api_key_env ?? "",
    protocol: view.protocol ?? "",
    clearStoredKey: false,
  };
}

function formsFrom(settings: SettingsResponse): Record<ChannelName, ChannelForm> {
  return {
    llm: formFrom(settings.llm),
    embedding: formFrom(settings.embedding),
    rerank: formFrom(settings.rerank),
  };
}

function payloadFrom(form: ChannelForm): ChannelSettingsPayload {
  // 契约（design.md 决议 #1）：base_url/model/api_key_env 恒提交，空白 = 清空；
  // api_key 只在用户输入新值或显式勾选清除时提交，未触碰不上传（保持已存 key）
  const payload: ChannelSettingsPayload = {
    base_url: form.base_url.trim(),
    model: form.model.trim(),
    api_key_env: form.api_key_env.trim(),
    protocol: form.protocol.trim(),
  };
  const typedKey = form.api_key.trim();
  if (typedKey) {
    payload.api_key = typedKey;
  } else if (form.clearStoredKey) {
    payload.api_key = null;
  }
  return payload;
}

export function SettingsView({
  onSaved,
}: {
  // 保存成功后回调最新设置（含 ask_readiness）：父级可免二次请求刷新问答门控
  onSaved?: (settings: SettingsResponse) => void;
}) {
  const [views, setViews] = useState<SettingsResponse | null>(null);
  const [forms, setForms] = useState<Record<ChannelName, ChannelForm>>({
    llm: EMPTY_FORM,
    embedding: EMPTY_FORM,
    rerank: EMPTY_FORM,
  });
  const [loadError, setLoadError] = useState<string | null>(null);
  // GET 失败但服务可达(拿到了 {code,message})：PUT 同样可达，坏配置文件的覆盖自救
  // 必须由这里进去——读取失败页只留「重试读取」会让服务端文案里「重新保存即可覆盖」
  // 的承诺落空。连接失败(没拿到响应)不适用：那时保存也无处可去。
  const [loadFailedButReachable, setLoadFailedButReachable] = useState(false);
  // 用户显式确认后，以空的文件层渲染表单（views 为 null 时的唯一出图路径）
  const [blankFormConfirmed, setBlankFormConfirmed] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  // 本次保存是否覆盖了「内容不可解析」的配置文件(坏文件自救的显式告知,不做静默替换)
  const [overwrittenInvalidConfig, setOverwrittenInvalidConfig] = useState(false);
  const [testStates, setTestStates] = useState<Record<ChannelName, ChannelTestState>>({
    llm: null,
    embedding: null,
    rerank: null,
  });
  // 预设下拉的选中值（仅记录选择，填充后的字段仍可自由编辑；清除选择不回滚已填字段）
  const [presetIds, setPresetIds] = useState<Record<ChannelName, string | null>>({
    llm: null,
    embedding: null,
    rerank: null,
  });

  const applySettings = useCallback((settings: SettingsResponse) => {
    setViews(settings);
    setForms(formsFrom(settings));
    setLoadError(null);
    setLoadFailedButReachable(false);
    setBlankFormConfirmed(false);
    // 表单已被服务端视图覆盖：预设下拉同步回到「自定义」，避免显示陈旧厂商
    setPresetIds({ llm: null, embedding: null, rerank: null });
  }, []);

  const load = useCallback(async () => {
    setLoadError(null);
    setLoadFailedButReachable(false);
    try {
      applySettings(await getSettings());
    } catch (caught: unknown) {
      setLoadFailedButReachable(isApiError(caught));
      setLoadError(
        isApiError(caught)
          ? caught.message
          : "无法连接本地服务，请确认 siku serve --with-ui 正在运行。",
      );
    }
  }, [applySettings]);

  useEffect(() => {
    void load();
  }, [load]);

  const setField = (channel: ChannelName, field: keyof ChannelForm, value: string | boolean) => {
    setForms((prev) => ({
      ...prev,
      [channel]: { ...prev[channel], [field]: value },
    }));
  };

  const setKeyMode = (channel: ChannelName, mode: KeyMode) => {
    setForms((prev) => {
      const form = prev[channel];
      if (form.key_mode === mode) {
        return prev;
      }
      return {
        ...prev,
        [channel]: {
          ...form,
          key_mode: mode,
          // 切走「直接填写」时丢弃尚未保存的明文输入，避免用户已改选
          // 环境变量、表单却仍把密文框里的临时值提交上去
          api_key: mode === "env" ? "" : form.api_key,
          clearStoredKey: mode === "env" ? false : form.clearStoredKey,
        },
      };
    });
  };

  // 厂商预设填充：云端预设切换到「引用环境变量」并预填变量名（key 需自备）；
  // 本地预设（Ollama）无需凭证，回到「直接填写」。两种切换都丢弃尚未保存的
  // 明文输入，防止切厂商后把 A 家临时 key 连同 B 家端点一起保存
  const applyPreset = (channel: ChannelName, presetId: string | null) => {
    setPresetIds((prev) => ({ ...prev, [channel]: presetId }));
    if (presetId === null) {
      return;
    }
    const preset = CHANNEL_PRESETS[channel].find((item) => item.id === presetId);
    if (!preset) {
      return;
    }
    setForms((prev) => {
      const form = prev[channel];
      return {
        ...prev,
        [channel]: {
          ...form,
          base_url: preset.base_url,
          model: preset.model,
          api_key_env: preset.api_key_env ?? "",
          // 厂商分支决定线协议：Anthropic 分支预设直接切协议，普通预设回到缺省
          protocol: preset.protocol ?? "",
          key_mode: preset.api_key_env ? "env" : "direct",
          api_key: "",
          clearStoredKey: false,
        },
      };
    });
  };

  const save = async () => {
    setSaveState("loading");
    setSaveMessage(null);
    setSaveError(null);
    setWarnings([]);
    setOverwrittenInvalidConfig(false);
    try {
      const response = await updateSettings({
        llm: payloadFrom(forms.llm),
        embedding: payloadFrom(forms.embedding),
        rerank: payloadFrom(forms.rerank),
      });
      applySettings(response);
      setSaveMessage("设置已保存，无需重启即可生效。");
      setWarnings(response.warnings);
      setOverwrittenInvalidConfig(response.invalid_config_file_overwritten ?? false);
      onSaved?.(response);
    } catch (caught: unknown) {
      setSaveError(
        isApiError(caught)
          ? caught.message
          : "无法连接本地服务，请确认 siku serve --with-ui 正在运行。",
      );
    } finally {
      setSaveState("idle");
    }
  };

  const runTest = async (channel: ChannelName) => {
    setTestStates((prev) => ({ ...prev, [channel]: { kind: "loading" } }));
    const form = forms[channel];
    const request: SettingsTestPayload = { channel };
    if (form.base_url.trim()) {
      request.base_url = form.base_url.trim();
    }
    if (form.model.trim()) {
      request.model = form.model.trim();
    }
    if (form.api_key.trim()) {
      request.api_key = form.api_key.trim();
    }
    if (form.api_key_env.trim()) {
      request.api_key_env = form.api_key_env.trim();
    }
    if (channel === "llm" && form.protocol.trim()) {
      request.protocol = form.protocol.trim();
    }
    try {
      const result = await testChannel(request);
      setTestStates((prev) => ({
        ...prev,
        [channel]: {
          kind: "done",
          ok: true,
          message: `连接成功，耗时 ${result.latency_ms} ms。`,
        },
      }));
    } catch (caught: unknown) {
      setTestStates((prev) => ({
        ...prev,
        [channel]: {
          kind: "done",
          ok: false,
          message: isApiError(caught)
            ? caught.message
            : "无法连接本地服务，请确认 siku serve --with-ui 正在运行。",
        },
      }));
    }
  };

  if (loadError !== null && !blankFormConfirmed) {
    return (
      <Alert className="status-card" color="red" role="alert" title="设置读取失败">
        <p>{loadError}</p>
        <Group gap="sm">
          <Button
            type="button"
            className="button-secondary"
            variant="default"
            onClick={() => void load()}
          >
            重试读取
          </Button>
          {loadFailedButReachable && (
            // 破坏性动作要显式同意：这条按钮唯一的作用是放弃文件层、以空配置重填，
            // 服务端只在「内容确证不可解析」时接受覆盖（权限/IO 读不到会被拒绝并说明原因）
            <Button
              type="button"
              color="red"
              variant="filled"
              onClick={() => setBlankFormConfirmed(true)}
            >
              确认以空配置覆盖本机配置文件并重新填写
            </Button>
          )}
        </Group>
      </Alert>
    );
  }

  if (views === null && !blankFormConfirmed) {
    return (
      <Group className="settings-loading" role="status" aria-live="polite" gap="sm">
        <Loader size="sm" />
        正在读取设置…
      </Group>
    );
  }

  return (
    <Stack
      component="form"
      className="settings-form"
      gap="lg"
      aria-labelledby="settings-title"
      onSubmit={(event) => {
        event.preventDefault();
        if (saveState !== "loading") void save();
      }}
    >
      <h2 id="settings-title">模型供给设置</h2>
      {views === null ? (
        <Alert className="status-card" color="yellow" role="status" title="按空配置显示">
          <p>{loadError}</p>
          <p>
            下方表单不含任何已存值。保存只会覆盖「内容确证不可解析」的文件；若因权限或磁盘故障读不到，
            保存会被拒绝并说明原因，不会动原文件。
          </p>
        </Alert>
      ) : (
        <p className="hint settings-path">
          配置写入 <code>{views.config_path}</code>，保存后免重启生效；环境变量层仍优先于文件层。
        </p>
      )}

      {saveMessage !== null && (
        <Alert color="green" role="status">{saveMessage}</Alert>
      )}
      {saveError !== null && (
        <Alert color="red" role="alert" title="设置保存失败">{saveError}</Alert>
      )}
      {overwrittenInvalidConfig && (
        <Alert color="yellow" role="status" title="原配置文件不可解析">
          本机配置文件内容已损坏、无法读取，本次保存以空配置为基底写入了新内容并覆盖该文件。
          若此前还配置过其他通道，请在下方重新填写后再次保存。
        </Alert>
      )}
      {warnings.map((warning) => (
        <Alert key={warning} color="yellow" role="alert" title="需要重建索引">{warning}</Alert>
      ))}

      {CHANNEL_META.map(({ key, title, description }) => {
        const view = views?.[key] ?? BLANK_CHANNEL_VIEW;
        const llmFallback = views?.llm_env_fallback ?? null;
        const form = forms[key];
        const testState = testStates[key];
        return (
          <Fieldset key={key} legend={title} className="channel-card">
            <p className="hint">{description}</p>
            {view.env_overrides.length > 0 && (
              <p className="hint hint-warning" role="note">
                以下字段当前由环境变量层覆盖，保存的文件值在其移除前不会生效：
                {view.env_overrides.join("、")}。
              </p>
            )}
            {key === "llm" && llmFallback && (
              <Alert className="llm-fallback-note" role="note">
                未显式配置 LLM 通道：当前按环境变量{" "}
                <code>{llmFallback.api_key_env}</code> 回退使用{" "}
                <code>{llmFallback.base_url}</code>（{llmFallback.model}）。
                在下方显式配置并保存后即可覆盖。
              </Alert>
            )}
            {key === "llm" && (
              <div className="field-preset">
                <NativeSelect
                  id={`${key}-protocol`}
                  label="接口协议"
                  aria-label="LLM 通道接口协议"
                  value={form.protocol || "openai-chat"}
                  onChange={(event) => setField(key, "protocol", event.currentTarget.value)}
                  data={LLM_PROTOCOL_OPTIONS}
                />
                <p className="hint">
                  协议决定请求路径与凭证头：anthropic 的请求发往
                  {" "}<code>{"{base_url}/v1/messages"}</code>，base_url 需填分支根地址
                  （不要带 /v1 结尾的 OpenAI 兼容路径）；自建网关反代与官方端点平级，
                  按其协议直接手填即可。
                </p>
              </div>
            )}
            <div className="field-preset">
              <NativeSelect
                id={`${key}-preset`}
                label="厂商预设"
                aria-label={`${title}厂商预设`}
                value={presetIds[key] ?? ""}
                onChange={(event) => applyPreset(key, event.currentTarget.value || null)}
                data={[
                  { value: "", label: "自定义（不自动填充）" },
                  ...CHANNEL_PRESETS[key].map((preset) => ({
                    value: preset.id,
                    label: preset.label,
                  })),
                ]}
              />
              <p className="hint">
                {key === "llm"
                  ? "预设含各厂商 OpenAI 兼容端点与 Anthropic 分支（选中即联动接口协议），模型为常用默认、可手改；自建网关反代（muniu / one-api 等）与官方端点平级，选「自定义」手填即可。"
                  : "预设填入常用端点与模型，可手改。"}
                {" "}云端 key 需自备，Ollama 本地无需凭证。
              </p>
            </div>
            <div className="field-grid">
              <div className="field">
                <TextInput
                  id={`${key}-base-url`}
                  label="base_url"
                  type="text"
                  value={form.base_url}
                  onChange={(event) => setField(key, "base_url", event.target.value)}
                  placeholder="http://127.0.0.1:11434/v1"
                  autoComplete="off"
                  spellCheck={false}
                />
              </div>
              <div className="field">
                <TextInput
                  id={`${key}-model`}
                  label="model"
                  type="text"
                  value={form.model}
                  onChange={(event) => setField(key, "model", event.target.value)}
                  placeholder={key === "rerank" ? "留空 = 不启用重排" : "模型名称"}
                  autoComplete="off"
                  spellCheck={false}
                />
              </div>
            </div>
            <Stack className="credential-group" gap="md">
              <Radio.Group
                className="credential-mode"
                label="凭证来源"
                value={form.key_mode}
                onChange={(value) => setKeyMode(key, value as KeyMode)}
              >
                <Group className="credential-options" gap="lg" mt="xs" wrap="wrap">
                  <Radio value="direct" label="直接填写 key" />
                  <Radio value="env" label="引用环境变量" />
                </Group>
              </Radio.Group>
              {form.key_mode === "direct" ? (
                <div className="field">
                  <PasswordInput
                    id={`${key}-api-key`}
                    label="api_key（只写不回显）"
                    value={form.api_key}
                    onChange={(event) => {
                      setField(key, "api_key", event.target.value);
                      if (event.target.value !== "") {
                        setField(key, "clearStoredKey", false);
                      }
                    }}
                    placeholder={view.api_key_set ? "已设置——留空保持不变" : "未设置"}
                    autoComplete="new-password"
                    visibilityToggleButtonProps={{
                      className: "password-visibility-toggle",
                      "aria-label": "显示或隐藏 API key",
                    }}
                  />
                  <p className="hint">明文保存在本机 config.toml（0600）；与环境变量同时存在时，明文优先。</p>
                  {view.api_key_set && (
                    <Checkbox
                      className="field-check"
                      label="清除已保存的 key（保存后生效）"
                      checked={form.clearStoredKey}
                      onChange={(event) => {
                        setField(key, "clearStoredKey", event.target.checked);
                        if (event.target.checked) {
                            setField(key, "api_key", "");
                        }
                      }}
                    />
                  )}
                  {form.api_key_env.trim() !== "" && (
                    <p className="hint">
                      已填写后备 api_key_env：<code>{form.api_key_env}</code>
                      ，继续生效；切换「引用环境变量」可修改。
                    </p>
                  )}
                </div>
              ) : (
                <div className="field">
                  <TextInput
                    id={`${key}-api-key-env`}
                    label="api_key_env（环境变量名）"
                    type="text"
                    value={form.api_key_env}
                    onChange={(event) => setField(key, "api_key_env", event.target.value)}
                    placeholder={`例如 ${CHANNEL_KEY_ENV_PREFIX[key]}_API_KEY`}
                    autoComplete="off"
                    spellCheck={false}
                  />
                  <p className="hint">key 从该环境变量读取，需在启动 siku 的环境中已设置。</p>
                  {view.api_key_set && (
                    <>
                      <p className="hint hint-warning" role="note">
                        已保存的明文 key 优先生效，需清除后环境变量才会启用：
                      </p>
                      <Checkbox
                        className="field-check"
                        label="清除已保存的 key（保存后生效）"
                        checked={form.clearStoredKey}
                        onChange={(event) => {
                          setField(key, "clearStoredKey", event.target.checked);
                          if (event.target.checked) {
                              setField(key, "api_key", "");
                          }
                        }}
                      />
                    </>
                  )}
                </div>
              )}
            </Stack>
            <div className="channel-footer">
              <Button
                type="button"
                className="button-secondary"
                variant="default"
                disabled={testState?.kind === "loading"}
                onClick={() => void runTest(key)}
              >
                {testState?.kind === "loading" ? "测试中…" : "测试连接"}
              </Button>
              {testState?.kind === "done" && (
                <Alert color={testState.ok ? "green" : "red"} role={testState.ok ? "status" : "alert"}>
                  {testState.message}
                </Alert>
              )}
            </div>
          </Fieldset>
        );
      })}

      <Group className="settings-footer" justify="flex-end">
        <Button type="submit" loading={saveState === "loading"}>
          {saveState === "loading" ? "保存中…" : "保存设置"}
        </Button>
      </Group>
      </Stack>
  );
}

export default SettingsView;
