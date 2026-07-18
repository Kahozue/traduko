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

const OPTIONAL_FIELDS = ["api_key", "api_key_env", "model"] as const;

// Named presets: every one still speaks the OpenAI-compatible protocol
// (the only backend provider type), so a preset only pre-fills base_url and
// a starting model. Both stay editable — selecting a preset is a shortcut,
// not a lock. "custom" fills nothing.
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
    model: "gpt-4o-mini",
    type: "openai_compat",
  },
  {
    id: "claude",
    label: "Claude",
    baseUrl: "https://api.anthropic.com/v1",
    model: "claude-sonnet-4-5",
    type: "anthropic",
  },
  {
    id: "gemini",
    label: "Gemini",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta",
    model: "gemini-2.5-flash",
    type: "gemini",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    baseUrl: "https://api.deepseek.com/v1",
    model: "deepseek-chat",
    type: "openai_compat",
  },
  {
    id: "glm",
    label: "GLM",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    model: "glm-4.5",
    type: "openai_compat",
  },
  {
    id: "kimi",
    label: "Kimi",
    baseUrl: "https://api.moonshot.cn/v1",
    model: "kimi-k2-0905-preview",
    type: "openai_compat",
  },
  { id: "custom", label: t("settings.provider.custom"), baseUrl: "", model: "", type: "openai_compat" },
];

// Model suggestions per preset, offered through a datalist so the field
// stays free-text (any model the endpoint supports) while giving one-click
// common choices.
const MODEL_SUGGESTIONS: Record<string, string[]> = {
  openai: ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o4-mini"],
  claude: ["claude-opus-4-1", "claude-sonnet-4-5", "claude-3-5-haiku-latest"],
  gemini: ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"],
  deepseek: ["deepseek-chat", "deepseek-reasoner"],
  glm: ["glm-4.5", "glm-4.5-air", "glm-4-plus"],
  kimi: ["kimi-k2-0905-preview", "moonshot-v1-32k", "moonshot-v1-128k"],
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

function needsBaseUrl(config: ProviderConfigDoc): boolean {
  return String(config.type ?? "openai_compat") === "openai_compat";
}

function normalize(rows: Row[]): Record<string, ProviderConfigDoc> | null {
  const out: Record<string, ProviderConfigDoc> = {};
  for (const row of rows) {
    const name = row.name.trim();
    if (!name || name in out) return null;
    if (needsBaseUrl(row.config) && String(row.config.base_url ?? "").trim() === "") {
      return null;
    }
    out[name] = row.config;
  }
  return out;
}

export function ProvidersSection({
  providers,
  onChange,
  onTest,
}: {
  providers: Record<string, ProviderConfigDoc>;
  onChange: (providers: Record<string, ProviderConfigDoc> | null) => void;
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
      if (preset.model) config.model = preset.model;
    }
    setRow(uid, { config });
  }

  function add() {
    const uid = nextUid.current;
    nextUid.current += 1;
    setPresetByUid((prev) => ({ ...prev, [uid]: "openai" }));
    const preset = PRESETS[0];
    apply([
      ...rows,
      {
        uid,
        name: "",
        config: { type: "openai_compat", base_url: preset.baseUrl, model: preset.model },
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
      {rows.map((row) => {
        const name = row.name.trim();
        const nameInvalid =
          !name || trimmedNames.filter((candidate) => candidate === name).length > 1;
        const baseUrl = String(row.config.base_url ?? "");
        const showBaseUrl = needsBaseUrl(row.config);
        const presetId = presetByUid[row.uid] ?? presetForConfig(row.config);
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
                  {PRESETS.map((preset) => (
                    <option key={preset.id} value={preset.id}>
                      {preset.label}
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
            {showBaseUrl && (
              <label className={styles.field}>
                <span className={styles.label}>{t("settings.baseUrl")}</span>
                <input
                  className={styles.input}
                  aria-label={t("settings.baseUrl")}
                  value={baseUrl}
                  onChange={(event) => setField(row.uid, "base_url", event.target.value)}
                />
                {baseUrl.trim() === "" && (
                  <span className={styles.error}>{t("settings.baseUrlRequired")}</span>
                )}
              </label>
            )}
            {showBaseUrl && (
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
              </div>
            )}
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
