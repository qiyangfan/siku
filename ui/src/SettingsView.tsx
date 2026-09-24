import { useCallback, useEffect, useState } from "react";
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
  clearStoredKey: boolean;
};

type SaveState = "idle" | "loading";

type ChannelTestState =
  | { kind: "loading" }
  | { kind: "done"; ok: boolean; message: string }
  | null;

const EMPTY_FORM: ChannelForm = {
  base_url: "",
  model: "",
  key_mode: "direct",
  api_key: "",
  api_key_env: "",
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
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [testStates, setTestStates] = useState<Record<ChannelName, ChannelTestState>>({
    llm: null,
    embedding: null,
    rerank: null,
  });

  const applySettings = useCallback((settings: SettingsResponse) => {
    setViews(settings);
    setForms(formsFrom(settings));
  }, []);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      applySettings(await getSettings());
    } catch (caught: unknown) {
      setLoadError(
        isApiError(caught)
          ? caught.message
          : "无法连接本地内核，请确认 siku serve 已启动。",
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

  const save = async () => {
    setSaveState("loading");
    setSaveMessage(null);
    setSaveError(null);
    setWarnings([]);
    try {
      const response = await updateSettings({
        llm: payloadFrom(forms.llm),
        embedding: payloadFrom(forms.embedding),
        rerank: payloadFrom(forms.rerank),
      });
      applySettings(response);
      setSaveMessage("设置已保存，无需重启即可生效。");
      setWarnings(response.warnings);
      onSaved?.(response);
    } catch (caught: unknown) {
      setSaveError(
        isApiError(caught)
          ? caught.message
          : "无法连接本地内核，请确认 siku serve 已启动。",
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
            : "无法连接本地内核，请确认 siku serve 已启动。",
        },
      }));
    }
  };

  if (loadError !== null) {
    return (
      <div className="status-card status-error" role="alert">
        <div>
          <strong>设置读取失败</strong>
          <p>{loadError}</p>
        </div>
        <button type="button" className="button-secondary" onClick={() => void load()}>
          重试读取
        </button>
      </div>
    );
  }

  if (views === null) {
    return (
      <div className="settings-loading" role="status" aria-live="polite">
        正在读取设置…
      </div>
    );
  }

  return (
    <form
      className="settings-form"
      aria-labelledby="settings-title"
      onSubmit={(event) => {
        event.preventDefault();
        if (saveState !== "loading") void save();
      }}
    >
      <h2 id="settings-title">模型供给设置</h2>
      <p className="hint settings-path">
        配置写入 <code>{views.config_path}</code>，保存后免重启生效；环境变量层仍优先于文件层。
      </p>

      {saveMessage !== null && (
        <div className="status-card status-saved" role="status">
          <strong>{saveMessage}</strong>
        </div>
      )}
      {saveError !== null && (
        <p className="message message-error" role="alert">
          {saveError}
        </p>
      )}
      {warnings.map((warning) => (
        <div key={warning} className="status-card status-warning" role="alert">
          <div>
            <strong>需要重建索引</strong>
            <p>{warning}</p>
          </div>
        </div>
      ))}

      {CHANNEL_META.map(({ key, title, description }) => {
        const view = views[key];
        const form = forms[key];
        const testState = testStates[key];
        return (
          <fieldset key={key} className="channel-card">
            <legend>{title}</legend>
            <p className="hint">{description}</p>
            {view.env_overrides.length > 0 && (
              <p className="hint hint-warning" role="note">
                以下字段当前由环境变量层覆盖，保存的文件值在其移除前不会生效：
                {view.env_overrides.join("、")}。
              </p>
            )}
            <div className="field-grid">
              <div className="field">
                <label htmlFor={`${key}-base-url`}>base_url</label>
                <input
                  id={`${key}-base-url`}
                  type="text"
                  value={form.base_url}
                  onChange={(event) => setField(key, "base_url", event.target.value)}
                  placeholder="http://127.0.0.1:11434/v1"
                  autoComplete="off"
                  spellCheck={false}
                />
              </div>
              <div className="field">
                <label htmlFor={`${key}-model`}>model</label>
                <input
                  id={`${key}-model`}
                  type="text"
                  value={form.model}
                  onChange={(event) => setField(key, "model", event.target.value)}
                  placeholder={key === "rerank" ? "留空 = 不启用重排" : "模型名称"}
                  autoComplete="off"
                  spellCheck={false}
                />
              </div>
            </div>
            <div className="credential-group">
              <div className="credential-head">
                <span className="credential-title" id={`${key}-credential-label`}>
                  凭证（二选一）
                </span>
                <div
                  className="segmented"
                  role="radiogroup"
                  aria-labelledby={`${key}-credential-label`}
                >
                  <label className="segmented-option">
                    <input
                      type="radio"
                      name={`${key}-key-mode`}
                      checked={form.key_mode === "direct"}
                      onChange={() => setKeyMode(key, "direct")}
                    />
                    直接填写 key
                  </label>
                  <label className="segmented-option">
                    <input
                      type="radio"
                      name={`${key}-key-mode`}
                      checked={form.key_mode === "env"}
                      onChange={() => setKeyMode(key, "env")}
                    />
                    引用环境变量
                  </label>
                </div>
              </div>
              {form.key_mode === "direct" ? (
                <div className="field">
                  <label htmlFor={`${key}-api-key`}>api_key（只写不回显）</label>
                  <input
                    id={`${key}-api-key`}
                    type="password"
                    value={form.api_key}
                    onChange={(event) => {
                      setField(key, "api_key", event.target.value);
                      if (event.target.value !== "") {
                        setField(key, "clearStoredKey", false);
                      }
                    }}
                    placeholder={view.api_key_set ? "已设置——留空保持不变" : "未设置"}
                    autoComplete="new-password"
                  />
                  <p className="hint">明文保存在本机 config.toml（0600）；与环境变量同时存在时，明文优先。</p>
                  {view.api_key_set && (
                    <label className="field-check">
                      <input
                        type="checkbox"
                        checked={form.clearStoredKey}
                        onChange={(event) => {
                          setField(key, "clearStoredKey", event.target.checked);
                          if (event.target.checked) {
                            setField(key, "api_key", "");
                          }
                        }}
                      />
                      清除已保存的 key（保存后生效）
                    </label>
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
                  <label htmlFor={`${key}-api-key-env`}>api_key_env（环境变量名）</label>
                  <input
                    id={`${key}-api-key-env`}
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
                      <label className="field-check">
                        <input
                          type="checkbox"
                          checked={form.clearStoredKey}
                          onChange={(event) => {
                            setField(key, "clearStoredKey", event.target.checked);
                            if (event.target.checked) {
                              setField(key, "api_key", "");
                            }
                          }}
                        />
                        清除已保存的 key（保存后生效）
                      </label>
                    </>
                  )}
                </div>
              )}
            </div>
            <div className="channel-footer">
              <button
                type="button"
                className="button-secondary"
                disabled={testState?.kind === "loading"}
                onClick={() => void runTest(key)}
              >
                {testState?.kind === "loading" ? "测试中…" : "测试连接"}
              </button>
              {testState?.kind === "done" && (
                <p
                  className={`message ${testState.ok ? "message-ok" : "message-error"}`}
                  role="status"
                >
                  {testState.message}
                </p>
              )}
            </div>
          </fieldset>
        );
      })}

      <div className="settings-footer">
        <button type="submit" disabled={saveState === "loading"}>
          {saveState === "loading" ? "保存中…" : "保存设置"}
        </button>
      </div>
    </form>
  );
}

export default SettingsView;
