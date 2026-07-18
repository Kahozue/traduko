import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { t, type MessageKey } from "../../i18n";
import type { AsrConfigDoc, AsrTestResult } from "../../lib/api/types";
import { useApi } from "../../lib/connection";
import { Icon } from "../icons";
import { Section, SettingRow } from "./Section";
import styles from "./settings.module.css";

const MODEL_SIZES = [
  { value: "tiny", label: "tiny（約 75 MB）" },
  { value: "base", label: "base（約 145 MB）" },
  { value: "small", label: "small（約 930 MB）" },
  { value: "medium", label: "medium（約 1.5 GB）" },
  { value: "large-v3", label: "large-v3（約 3.1 GB）" },
];

const ENGINE_LABELS: Record<string, MessageKey> = {
  faster_whisper: "settings.asr.engine.fasterWhisper",
  macos_native: "settings.asr.engine.macos",
  openai_whisper: "settings.asr.engine.openaiWhisper",
  openai_gpt4o_diarize: "settings.asr.engine.gpt4oDiarize",
  openai_gpt4o: "settings.asr.engine.gpt4o",
  openai_gpt4o_mini: "settings.asr.engine.gpt4oMini",
  cloud_custom: "settings.asr.engine.custom",
};

const LOCAL_ENGINES = ["faster_whisper", "macos_native"];
const OPENAI_ENGINES = ["openai_whisper", "openai_gpt4o_diarize", "openai_gpt4o", "openai_gpt4o_mini"];
const NO_TIMESTAMP_ENGINES = new Set(["openai_gpt4o", "openai_gpt4o_mini"]);

// One ASR engine menu shared by the video and audio domain tabs: the
// engine assets (models, credentials, helper) are global, only the
// per-domain default engine choice differs (`engine` vs `audio_engine`).
export function AsrSection({
  asr,
  onChange,
  domain = "video",
}: {
  asr: AsrConfigDoc;
  onChange: (value: AsrConfigDoc) => void;
  domain?: "video" | "audio";
}) {
  const api = useApi();
  const engine =
    domain === "audio" ? asr.audio_engine || asr.engine : asr.engine;

  function setEngine(value: string) {
    if (domain === "audio") onChange({ ...asr, audio_engine: value });
    else onChange({ ...asr, engine: value });
  }

  function patch(partial: Partial<AsrConfigDoc>) {
    onChange({ ...asr, ...partial });
  }

  const [testResult, setTestResult] = useState<AsrTestResult | null>(null);
  const test = useMutation({
    mutationFn: () =>
      api.testAsrEngine({
        engine,
        model: asr.model,
        locale: asr.macos_locale,
      }),
    onSuccess: (result) => setTestResult(result),
    onError: (error) => setTestResult({ ok: false, error: String(error) }),
  });

  return (
    <Section title={t("settings.asr.title")} hint={t("settings.asr.hint")}>
      <SettingRow label={t("settings.asr.engine")} htmlFor="asr-engine">
        <select
          id="asr-engine"
          className={styles.asrSelect}
          value={engine}
          onChange={(event) => {
            setTestResult(null);
            setEngine(event.target.value);
          }}
        >
          <optgroup label={t("settings.asr.group.local")}>
            {LOCAL_ENGINES.map((id) => (
              <option key={id} value={id}>
                {t(ENGINE_LABELS[id])}
              </option>
            ))}
          </optgroup>
          <optgroup label={t("settings.asr.group.cloud")}>
            {OPENAI_ENGINES.map((id) => (
              <option key={id} value={id}>
                {t(ENGINE_LABELS[id])}
              </option>
            ))}
            <option value="cloud_custom">{t(ENGINE_LABELS.cloud_custom)}</option>
          </optgroup>
        </select>
      </SettingRow>

      {NO_TIMESTAMP_ENGINES.has(engine) && (
        <p className={styles.asrWarnNote}>
          <Icon name="bell" size={13} />
          {t("settings.asr.noTimestamps")}
        </p>
      )}

      {engine === "faster_whisper" && (
        <FasterWhisperRows asr={asr} onModel={(model) => patch({ model })} />
      )}
      {engine === "macos_native" && (
        <MacosRows
          locale={asr.macos_locale}
          onLocale={(macos_locale) => patch({ macos_locale })}
        />
      )}
      {OPENAI_ENGINES.includes(engine) && (
        <>
          <SecretRow
            label={t("settings.asr.cloudKey")}
            id="asr-cloud-key"
            value={asr.cloud_api_key}
            onValue={(cloud_api_key) => patch({ cloud_api_key })}
          />
          <SettingRow label={t("settings.asr.cloudKeyEnv")} htmlFor="asr-cloud-key-env">
            <input
              id="asr-cloud-key-env"
              className={styles.asrInput}
              value={asr.cloud_api_key_env}
              onChange={(event) => patch({ cloud_api_key_env: event.target.value })}
            />
          </SettingRow>
          <SettingRow
            label={t("settings.asr.zhPrompt")}
            description={t("settings.asr.zhPrompt.desc")}
          >
            <input
              type="checkbox"
              aria-label={t("settings.asr.zhPrompt")}
              checked={asr.zh_prompt}
              onChange={(event) => patch({ zh_prompt: event.target.checked })}
            />
          </SettingRow>
        </>
      )}
      {engine === "cloud_custom" && (
        <>
          <SettingRow label={t("settings.asr.customBaseUrl")} htmlFor="asr-custom-url">
            <input
              id="asr-custom-url"
              className={styles.asrInputWide}
              value={asr.custom_base_url}
              placeholder="https://api.groq.com/openai/v1"
              onChange={(event) => patch({ custom_base_url: event.target.value })}
            />
          </SettingRow>
          <SettingRow label={t("settings.asr.customModel")} htmlFor="asr-custom-model">
            <input
              id="asr-custom-model"
              className={styles.asrInput}
              value={asr.custom_model}
              placeholder="whisper-large-v3"
              onChange={(event) => patch({ custom_model: event.target.value })}
            />
          </SettingRow>
          <SecretRow
            label={t("settings.asr.cloudKey")}
            id="asr-custom-key"
            value={asr.custom_api_key}
            onValue={(custom_api_key) => patch({ custom_api_key })}
          />
          <SettingRow label={t("settings.asr.cloudKeyEnv")} htmlFor="asr-custom-key-env">
            <input
              id="asr-custom-key-env"
              className={styles.asrInput}
              value={asr.custom_api_key_env}
              onChange={(event) => patch({ custom_api_key_env: event.target.value })}
            />
          </SettingRow>
        </>
      )}

      {engine !== "faster_whisper" && (
        <SettingRow label={t("settings.asr.connection")}>
          <div className={styles.asrActions}>
            <button
              type="button"
              className={styles.asrButton}
              disabled={test.isPending}
              onClick={() => {
                setTestResult(null);
                test.mutate();
              }}
            >
              {test.isPending ? t("settings.asr.testing") : t("settings.asr.test")}
            </button>
          </div>
          {testResult &&
            (testResult.ok ? (
              <p className={styles.asrOk}>{t("settings.asr.testOk")}</p>
            ) : (
              <p className={styles.asrError}>{testResult.error}</p>
            ))}
        </SettingRow>
      )}
    </Section>
  );
}

function SecretRow({
  label,
  id,
  value,
  onValue,
}: {
  label: string;
  id: string;
  value: string;
  onValue: (value: string) => void;
}) {
  const [reveal, setReveal] = useState(false);
  return (
    <SettingRow label={label} htmlFor={id}>
      <div className={styles.asrActions}>
        <input
          id={id}
          type={reveal ? "text" : "password"}
          className={styles.asrInput}
          value={value}
          onChange={(event) => onValue(event.target.value)}
        />
        <button
          type="button"
          className={styles.asrButton}
          onClick={() => setReveal((open) => !open)}
        >
          {reveal ? t("settings.hide") : t("settings.reveal")}
        </button>
      </div>
    </SettingRow>
  );
}

function FasterWhisperRows({
  asr,
  onModel,
}: {
  asr: AsrConfigDoc;
  onModel: (model: string) => void;
}) {
  const api = useApi();
  const model = asr.model || "small";
  const [testResult, setTestResult] = useState<AsrTestResult | null>(null);

  const status = useQuery({
    queryKey: ["asr-status", model],
    queryFn: () => api.getAsrStatus(model),
    refetchInterval: (query) => (query.state.data?.downloading ? 1500 : false),
  });

  const download = useMutation({
    mutationFn: () => api.downloadAsrModel(model),
    onSuccess: () => status.refetch(),
  });

  const test = useMutation({
    mutationFn: () => api.testAsr(model),
    onSuccess: (result) => setTestResult(result),
    onError: (error) => setTestResult({ ok: false, error: String(error) }),
  });

  const s = status.data;
  const modelStatusText = !s
    ? "…"
    : s.downloading
      ? `${t("settings.asr.downloading")}（${s.downloaded_mb.toFixed(0)} MB）`
      : s.cached
        ? `${t("settings.asr.cached")}（${s.downloaded_mb.toFixed(0)} MB）`
        : t("settings.asr.notCached");

  return (
    <>
      <SettingRow label={t("settings.asr.engineStatus")}>
        <span className={styles.asrStatusText}>
          {!s ? "…" : s.package ? t("settings.asr.engineReady") : t("settings.asr.engineMissing")}
        </span>
      </SettingRow>
      <SettingRow label={t("settings.asr.model")} htmlFor="asr-model">
        <select
          id="asr-model"
          className={styles.asrSelect}
          value={model}
          onChange={(event) => {
            onModel(event.target.value);
            setTestResult(null);
          }}
        >
          {MODEL_SIZES.map((size) => (
            <option key={size.value} value={size.value}>
              {size.label}
            </option>
          ))}
        </select>
      </SettingRow>
      <SettingRow label={t("settings.asr.status")}>
        <div className={styles.asrActions}>
          <span className={styles.asrStatusText}>{modelStatusText}</span>
          <button
            type="button"
            className={styles.asrButton}
            disabled={!s || !s.package || s.cached || s.downloading || download.isPending}
            onClick={() => download.mutate()}
          >
            {t("settings.asr.download")}
          </button>
          <button
            type="button"
            className={styles.asrButton}
            disabled={!s || !s.cached || test.isPending}
            onClick={() => {
              setTestResult(null);
              test.mutate();
            }}
          >
            {test.isPending ? t("settings.asr.testing") : t("settings.asr.test")}
          </button>
        </div>
        {s?.error && <p className={styles.asrError}>{s.error}</p>}
        {testResult &&
          (testResult.ok ? (
            <p className={styles.asrOk}>
              {t("settings.asr.testOk")}
              {testResult.load_seconds !== undefined && `（${testResult.load_seconds}s）`}
            </p>
          ) : (
            <p className={styles.asrError}>{testResult.error}</p>
          ))}
      </SettingRow>
    </>
  );
}

function MacosRows({
  locale,
  onLocale,
}: {
  locale: string;
  onLocale: (locale: string) => void;
}) {
  const api = useApi();
  // Probing compiles the helper on first use, so it only happens while the
  // macOS engine is actually selected.
  const engines = useQuery({
    queryKey: ["asr-engines", "macos"],
    queryFn: () => api.getAsrEngines(true),
    refetchInterval: (query) =>
      query.state.data?.macos.assets_state === "downloading" ? 1500 : false,
  });
  const download = useMutation({
    mutationFn: () => api.downloadMacosAssets(locale),
    onSuccess: () => engines.refetch(),
  });

  const macos = engines.data?.macos;
  const locales = macos
    ? [...new Set([...macos.transcriber_locales, ...macos.dictation_locales])]
    : [];
  const selectedInstalled =
    !!macos && (locale === "" || macos.installed_locales.includes(locale));

  return (
    <>
      <SettingRow label={t("settings.asr.macosStatus")}>
        <span className={styles.asrStatusText}>
          {!macos
            ? t("settings.asr.macosProbing")
            : macos.available
              ? t("settings.asr.macosAvailable")
              : (macos.error ?? t("settings.asr.macosUnavailable"))}
        </span>
      </SettingRow>
      {macos?.available && (
        <>
          <SettingRow
            label={t("settings.asr.macosLocale")}
            htmlFor="asr-macos-locale"
            description={t("settings.asr.macosLocale.desc")}
          >
            <select
              id="asr-macos-locale"
              className={styles.asrSelect}
              value={locale}
              onChange={(event) => onLocale(event.target.value)}
            >
              <option value="">{t("settings.asr.macosLocale.auto")}</option>
              {locales.map((entry) => (
                <option key={entry} value={entry}>
                  {entry}
                  {macos.installed_locales.includes(entry)
                    ? ` ${t("settings.asr.macosInstalledMark")}`
                    : ""}
                </option>
              ))}
            </select>
          </SettingRow>
          <SettingRow label={t("settings.asr.macosAssets")}>
            <div className={styles.asrActions}>
              <span className={styles.asrStatusText}>
                {macos.assets_state === "downloading"
                  ? `${t("settings.asr.downloading")}（${Math.round(macos.assets_progress * 100)}%）`
                  : selectedInstalled
                    ? t("settings.asr.macosInstalled")
                    : t("settings.asr.notCached")}
              </span>
              <button
                type="button"
                className={styles.asrButton}
                disabled={
                  locale === "" ||
                  selectedInstalled ||
                  macos.assets_state === "downloading" ||
                  download.isPending
                }
                onClick={() => download.mutate()}
              >
                {t("settings.asr.download")}
              </button>
            </div>
            {macos.assets_error && (
              <p className={styles.asrError}>{macos.assets_error}</p>
            )}
          </SettingRow>
        </>
      )}
    </>
  );
}
