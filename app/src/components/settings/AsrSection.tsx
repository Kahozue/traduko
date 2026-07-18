import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { t } from "../../i18n";
import type { AsrTestResult } from "../../lib/api/types";
import { useApi } from "../../lib/connection";
import { Section, SettingRow } from "./Section";
import styles from "./settings.module.css";

const MODEL_SIZES = [
  { value: "tiny", label: "tiny（約 75 MB）" },
  { value: "base", label: "base（約 145 MB）" },
  { value: "small", label: "small（約 930 MB）" },
  { value: "medium", label: "medium（約 1.5 GB）" },
  { value: "large-v3", label: "large-v3（約 3.1 GB）" },
];

export function AsrSection() {
  const api = useApi();
  const [model, setModel] = useState("small");
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
    <Section title={t("settings.asr.title")} hint={t("settings.asr.hint")}>
      <SettingRow label={t("settings.asr.engine")}>
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
            setModel(event.target.value);
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
    </Section>
  );
}
