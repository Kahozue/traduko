import { useRef, useState } from "react";
import { t } from "../../i18n";
import type { ProviderConfigDoc, ProviderTestResult } from "../../lib/api/types";
import { Section } from "./Section";
import styles from "./settings.module.css";

interface Row {
  uid: number;
  name: string;
  config: ProviderConfigDoc;
}

const OPTIONAL_FIELDS = ["api_key", "api_key_env", "model", "base_url"] as const;

// Named presets. openai_compat presets speak the OpenAI protocol against a
// required base_url; Claude and Gemini switch to their native adapters where
// base_url is optional (empty means the adapter default). Every field stays
// editable — selecting a preset is a shortcut, not a lock.
interface Preset {
  id: string;
  label: string;
  baseUrl: string;
  model: string;
  type: string;
}

const PRESETS: Preset[] = [
  {
    id: "openai",
    label: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    model: "gpt-5.4-mini",
    type: "openai_compat",
  },
  {
    id: "claude",
    label: "Claude",
    baseUrl: "https://api.anthropic.com/v1",
    model: "claude-haiku-4-5",
    type: "anthropic",
  },
  {
    id: "gemini",
    label: "Gemini",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta",
    model: "gemini-3.1-flash-lite",
    type: "gemini",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    baseUrl: "https://api.deepseek.com/v1",
    model: "deepseek-v4-flash",
    type: "openai_compat",
  },
  {
    id: "glm",
    label: "GLM",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    model: "glm-4.7-flash",
    type: "openai_compat",
  },
  {
    id: "kimi",
    label: "Kimi",
    baseUrl: "https://api.moonshot.ai/v1",
    model: "kimi-k2.7-code",
    type: "openai_compat",
  },
  { id: "custom", label: t("settings.provider.custom"), baseUrl: "", model: "", type: "openai_compat" },
];

// Model suggestions per preset, offered through a datalist so the field
// stays free-text (any model the endpoint supports) while giving one-click
// common choices.
const MODEL_SUGGESTIONS: Record<string, string[]> = {
  openai: ["gpt-5.4-mini", "gpt-5.4", "gpt-5.4-nano", "gpt-5.2", "gpt-5-mini"],
  claude: [
    "claude-haiku-4-5",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-opus-4-8",
  ],
  gemini: [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.1-pro-preview",
    "gemini-2.5-flash",
  ],
  deepseek: ["deepseek-v4-flash", "deepseek-v4-pro"],
  glm: ["glm-4.7-flash", "glm-4.7"],
  kimi: ["kimi-k2.7-code", "kimi-k2.7-code-highspeed", "kimi-k3"],
};

// Vendor-documented ceilings per model: context window and max output
// tokens. Picking a known model pre-fills both fields at the ceiling; the
// numbers stay editable for private deployments with different limits.
const MODEL_LIMITS: Record<string, { context: number; output: number }> = {
  "gpt-5.4-mini": { context: 400000, output: 128000 },
  "gpt-5.4": { context: 400000, output: 128000 },
  "gpt-5.4-nano": { context: 400000, output: 128000 },
  "claude-haiku-4-5": { context: 200000, output: 64000 },
  "claude-sonnet-5": { context: 1000000, output: 128000 },
  "claude-sonnet-4-6": { context: 1000000, output: 128000 },
  "claude-opus-4-8": { context: 1000000, output: 128000 },
  "gemini-3.1-flash-lite": { context: 1048576, output: 65536 },
  "gemini-3.5-flash": { context: 1048576, output: 65536 },
  "gemini-3.1-pro-preview": { context: 1048576, output: 65536 },
  "gemini-2.5-flash": { context: 1048576, output: 65536 },
  "deepseek-v4-flash": { context: 1048576, output: 393216 },
  "glm-4.7-flash": { context: 200000, output: 131072 },
  "glm-4.7": { context: 200000, output: 131072 },
  "kimi-k2.7-code": { context: 1048576, output: 262144 },
  "kimi-k2.7-code-highspeed": { context: 1048576, output: 262144 },
};

// Which preset a stored row matches, so an edited config re-opens on the
// right preset instead of always "custom".
function presetForConfig(config: ProviderConfigDoc): string {
  const type = String(config.type ?? "openai_compat");
  // Native adapters map one-to-one onto their preset regardless of base_url.
  const byType = PRESETS.find((preset) => preset.type === type && type !== "openai_compat");
  if (byType) return byType.id;
  const baseUrl = String(config.base_url ?? "").replace(/\/$/, "");
  const match = PRESETS.find(
    (preset) => preset.baseUrl !== "" && preset.baseUrl.replace(/\/$/, "") === baseUrl,
  );
  return match?.id ?? "custom";
}

function requiresBaseUrl(config: ProviderConfigDoc): boolean {
  return String(config.type ?? "openai_compat") === "openai_compat";
}

function limitInvalid(value: unknown): boolean {
  if (value === undefined || value === null) return false;
  return !(typeof value === "number" && Number.isInteger(value) && value > 0);
}

function normalize(rows: Row[]): Record<string, ProviderConfigDoc> | null {
  const out: Record<string, ProviderConfigDoc> = {};
  for (const row of rows) {
    const name = row.name.trim();
    if (!name || name in out) return null;
    if (requiresBaseUrl(row.config) && String(row.config.base_url ?? "").trim() === "") {
      return null;
    }
    if (limitInvalid(row.config.context_window)) return null;
    if (limitInvalid(row.config.max_output_tokens)) return null;
    out[name] = row.config;
  }
  return out;
}

export function ProvidersSection({
  providers,
  defaultProvider,
  onChange,
  onDefaultProvider,
  onTest,
}: {
  providers: Record<string, ProviderConfigDoc>;
  defaultProvider?: string;
  onChange: (providers: Record<string, ProviderConfigDoc> | null) => void;
  onDefaultProvider?: (name: string) => void;
  // Injected by SettingsView (api.testProvider); optional so the section can
  // render without a live connection, and the test row hides when absent.
  onTest?: (config: ProviderConfigDoc) => Promise<ProviderTestResult>;
}) {
  const [rows, setRows] = useState<Row[]>(() =>
    Object.entries(providers).map(([name, config], index) => ({
      uid: index,
      name,
      config,
    })),
  );
  const nextUid = useRef(rows.length);
  const [revealed, setRevealed] = useState<Set<number>>(new Set());
  // The chosen preset per row is view state, not saved config: it only
  // decides which suggestions and base_url pre-fill runs.
  const [presetByUid, setPresetByUid] = useState<Record<number, string>>(() => {
    const initial: Record<number, string> = {};
    for (const row of rows) initial[row.uid] = presetForConfig(row.config);
    return initial;
  });
  // Raw text of a limits field while it holds an invalid value, so typing
  // isn't fought by the number round-trip; keyed by `${uid}:${field}`.
  const [limitText, setLimitText] = useState<Record<string, string>>({});

  function apply(next: Row[]) {
    setRows(next);
    onChange(normalize(next));
  }

  function setRow(uid: number, patch: Partial<Row>) {
    apply(rows.map((row) => (row.uid === uid ? { ...row, ...patch } : row)));
  }

  function setField(uid: number, key: string, value: string) {
    const row = rows.find((item) => item.uid === uid);
    if (!row) return;
    const config = { ...row.config, [key]: value };
    if (value === "" && (OPTIONAL_FIELDS as readonly string[]).includes(key)) {
      delete config[key];
    }
    // A recognized model carries its vendor ceilings along, so the limits
    // follow the model instead of silently keeping the previous model's.
    if (key === "model") {
      const limits = MODEL_LIMITS[value.trim()];
      if (limits) {
        config.context_window = limits.context;
        config.max_output_tokens = limits.output;
        setLimitText((prev) => {
          const next = { ...prev };
          delete next[`${uid}:context_window`];
          delete next[`${uid}:max_output_tokens`];
          return next;
        });
      }
    }
    setRow(uid, { config });
  }

  function setLimitField(uid: number, key: "context_window" | "max_output_tokens", text: string) {
    const row = rows.find((item) => item.uid === uid);
    if (!row) return;
    const trimmed = text.trim();
    const config = { ...row.config };
    if (trimmed === "") {
      delete config[key];
      setLimitText((prev) => {
        const next = { ...prev };
        delete next[`${uid}:${key}`];
        return next;
      });
    } else if (/^\d+$/.test(trimmed) && Number(trimmed) > 0) {
      config[key] = Number(trimmed);
      setLimitText((prev) => {
        const next = { ...prev };
        delete next[`${uid}:${key}`];
        return next;
      });
    } else {
      // Keep the invalid text visible and mark the draft invalid via a
      // non-integer sentinel the validator rejects.
      config[key] = trimmed as unknown as number;
      setLimitText((prev) => ({ ...prev, [`${uid}:${key}`]: text }));
    }
    setRow(uid, { config });
  }

  function choosePreset(uid: number, presetId: string) {
    setPresetByUid((prev) => ({ ...prev, [uid]: presetId }));
    const preset = PRESETS.find((item) => item.id === presetId);
    if (!preset || preset.id === "custom") return;
    const row = rows.find((item) => item.uid === uid);
    if (!row) return;
    // Fill a field when it is empty or still holds another preset's default
    // (i.e. it was auto-filled, like a fresh row's OpenAI pre-fill), but
    // never clobber a value the user typed. type follows the preset so
    // Claude/Gemini switch to their native adapter.
    const config: ProviderConfigDoc = { ...row.config, type: preset.type };
    const baseUrl = String(config.base_url ?? "").trim().replace(/\/$/, "");
    if (
      baseUrl === "" ||
      PRESETS.some((item) => item.baseUrl !== "" && item.baseUrl.replace(/\/$/, "") === baseUrl)
    ) {
      config.base_url = preset.baseUrl;
    }
    const model = String(config.model ?? "").trim();
    if (model === "" || PRESETS.some((item) => item.model !== "" && item.model === model)) {
      if (preset.model) {
        config.model = preset.model;
        const limits = MODEL_LIMITS[preset.model];
        if (limits) {
          config.context_window = limits.context;
          config.max_output_tokens = limits.output;
        }
      }
    }
    setRow(uid, { config });
  }

  function add() {
    const uid = nextUid.current;
    nextUid.current += 1;
    setPresetByUid((prev) => ({ ...prev, [uid]: "openai" }));
    const preset = PRESETS[0];
    const limits = MODEL_LIMITS[preset.model];
    apply([
      ...rows,
      {
        uid,
        name: "",
        config: {
          type: "openai_compat",
          base_url: preset.baseUrl,
          model: preset.model,
          ...(limits
            ? { context_window: limits.context, max_output_tokens: limits.output }
            : {}),
        },
      },
    ]);
  }

  function toggleReveal(uid: number) {
    setRevealed((prev) => {
      const next = new Set(prev);
      if (next.has(uid)) next.delete(uid);
      else next.add(uid);
      return next;
    });
  }

  function limitValue(row: Row, key: "context_window" | "max_output_tokens"): string {
    const raw = limitText[`${row.uid}:${key}`];
    if (raw !== undefined) return raw;
    const value = row.config[key];
    return value === undefined || value === null ? "" : String(value);
  }

  const trimmedNames = rows.map((row) => row.name.trim());

  return (
    <Section
      title={t("settings.providers")}
      action={
        <button
          type="button"
          className={`${styles.secondary} ${styles.headAction}`}
          onClick={add}
        >
          {t("settings.addProvider")}
        </button>
      }
    >
      {rows.length === 0 && <p className={styles.emptyBox}>{t("settings.providersEmpty")}</p>}
      {rows.length > 0 && onDefaultProvider && (
        <div className={styles.card}>
          <label className={styles.field}>
            <span className={styles.label}>{t("settings.defaultProvider")}</span>
            <select
              className={styles.input}
              aria-label={t("settings.defaultProvider")}
              value={defaultProvider ?? ""}
              onChange={(event) => onDefaultProvider(event.target.value)}
            >
              <option value="">{t("settings.defaultProvider.auto")}</option>
              {trimmedNames
                .filter((name) => name !== "")
                .map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
            </select>
            <span className={styles.hintNote}>{t("settings.defaultProvider.hint")}</span>
          </label>
        </div>
      )}
      {rows.map((row) => {
        const name = row.name.trim();
        const nameInvalid =
          !name || trimmedNames.filter((candidate) => candidate === name).length > 1;
        const baseUrl = String(row.config.base_url ?? "");
        const baseUrlRequired = requiresBaseUrl(row.config);
        const presetId = presetByUid[row.uid] ?? presetForConfig(row.config);
        const preset = PRESETS.find((item) => item.id === presetId);
        const suggestions = MODEL_SUGGESTIONS[presetId] ?? [];
        return (
          <div key={row.uid} className={styles.card}>
            <div className={styles.cardHeader}>
              <label className={styles.field}>
                <span className={styles.label}>{t("settings.providerName")}</span>
                <input
                  className={styles.input}
                  aria-label={t("settings.providerName")}
                  value={row.name}
                  onChange={(event) => setRow(row.uid, { name: event.target.value })}
                />
                {nameInvalid && (
                  <span className={styles.error}>{t("settings.providerNameInvalid")}</span>
                )}
              </label>
              <label className={styles.field}>
                <span className={styles.label}>{t("settings.providerPreset")}</span>
                <select
                  className={styles.input}
                  aria-label={t("settings.providerPreset")}
                  value={presetId}
                  onChange={(event) => choosePreset(row.uid, event.target.value)}
                >
                  {PRESETS.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className={styles.secondary}
                onClick={() => apply(rows.filter((item) => item.uid !== row.uid))}
              >
                {t("settings.remove")}
              </button>
            </div>
            <label className={styles.field}>
              <span className={styles.label}>{t("settings.baseUrl")}</span>
              <input
                className={styles.input}
                aria-label={t("settings.baseUrl")}
                value={baseUrl}
                placeholder={baseUrlRequired ? undefined : preset?.baseUrl}
                onChange={(event) => setField(row.uid, "base_url", event.target.value)}
              />
              {baseUrlRequired && baseUrl.trim() === "" && (
                <span className={styles.error}>{t("settings.baseUrlRequired")}</span>
              )}
            </label>
            <div className={styles.fieldRow}>
              <label className={styles.field}>
                <span className={styles.label}>{t("settings.apiKey")}</span>
                <span className={styles.inline}>
                  <input
                    className={styles.input}
                    type={revealed.has(row.uid) ? "text" : "password"}
                    value={String(row.config.api_key ?? "")}
                    onChange={(event) => setField(row.uid, "api_key", event.target.value)}
                  />
                  <button
                    type="button"
                    className={styles.secondary}
                    onClick={() => toggleReveal(row.uid)}
                  >
                    {revealed.has(row.uid) ? t("settings.hide") : t("settings.reveal")}
                  </button>
                </span>
              </label>
              <label className={styles.field}>
                <span className={styles.label}>{t("settings.apiKeyEnv")}</span>
                <input
                  className={styles.input}
                  value={String(row.config.api_key_env ?? "")}
                  onChange={(event) =>
                    setField(row.uid, "api_key_env", event.target.value)
                  }
                />
              </label>
            </div>
            <div className={styles.fieldRow}>
              <label className={styles.field}>
                <span className={styles.label}>{t("settings.defaultModel")}</span>
                <input
                  className={styles.input}
                  list={`models-${row.uid}`}
                  value={String(row.config.model ?? "")}
                  onChange={(event) => setField(row.uid, "model", event.target.value)}
                />
                {suggestions.length > 0 && (
                  <datalist id={`models-${row.uid}`}>
                    {suggestions.map((model) => (
                      <option key={model} value={model} />
                    ))}
                  </datalist>
                )}
              </label>
              <label className={`${styles.field} ${styles.limitField}`}>
                <span className={styles.label}>{t("settings.contextWindow")}</span>
                <input
                  className={styles.input}
                  inputMode="numeric"
                  value={limitValue(row, "context_window")}
                  onChange={(event) =>
                    setLimitField(row.uid, "context_window", event.target.value)
                  }
                />
                {limitInvalid(row.config.context_window) && (
                  <span className={styles.error}>{t("settings.tokenLimitInvalid")}</span>
                )}
              </label>
              <label className={`${styles.field} ${styles.limitField}`}>
                <span className={styles.label}>{t("settings.maxOutputTokens")}</span>
                <input
                  className={styles.input}
                  inputMode="numeric"
                  value={limitValue(row, "max_output_tokens")}
                  onChange={(event) =>
                    setLimitField(row.uid, "max_output_tokens", event.target.value)
                  }
                />
                {limitInvalid(row.config.max_output_tokens) && (
                  <span className={styles.error}>{t("settings.tokenLimitInvalid")}</span>
                )}
              </label>
            </div>
            <ProviderTestRow config={row.config} onTest={onTest} />
          </div>
        );
      })}
    </Section>
  );
}

// Per-provider connectivity probe: a minimal chat call through the core, so
// the panel reports the real failure (bad key, unknown model, unreachable)
// before a task ever runs. Failures are data, never thrown.
function ProviderTestRow({
  config,
  onTest,
}: {
  config: ProviderConfigDoc;
  onTest?: (config: ProviderConfigDoc) => Promise<ProviderTestResult>;
}) {
  const [state, setState] = useState<
    { kind: "idle" | "testing" } | { kind: "done"; result: ProviderTestResult }
  >({ kind: "idle" });
  if (!onTest) return null;

  async function run() {
    setState({ kind: "testing" });
    try {
      const result = await onTest!(config);
      setState({ kind: "done", result });
    } catch (error) {
      setState({ kind: "done", result: { ok: false, error: String(error) } });
    }
  }

  const result = state.kind === "done" ? state.result : null;
  return (
    <div className={styles.providerTest}>
      <button
        type="button"
        className={styles.secondary}
        disabled={state.kind === "testing"}
        onClick={run}
      >
        {state.kind === "testing" ? t("settings.provider.testing") : t("settings.provider.test")}
      </button>
      {result?.ok && <span className={styles.testResult}>{t("settings.provider.testOk")}</span>}
      {result && !result.ok && (
        <span className={styles.testError}>
          {t("settings.provider.testFailed")}
          {result.error ? `：${result.error}` : ""}
        </span>
      )}
    </div>
  );
}
