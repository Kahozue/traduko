import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { t } from "../../i18n";
import type { PdfEngineConfigDoc, PdfEngineTestResult } from "../../lib/api/types";
import { useApi } from "../../lib/connection";
import { Section, SettingRow } from "./Section";
import styles from "./settings.module.css";

export function PdfEngineSection({
  pdf,
  onChange,
}: {
  pdf: PdfEngineConfigDoc;
  onChange: (value: PdfEngineConfigDoc) => void;
}) {
  const api = useApi();
  const [testResult, setTestResult] = useState<PdfEngineTestResult | null>(null);

  const status = useQuery({
    queryKey: ["pdf-status"],
    queryFn: () => api.getPdfEngineStatus(),
    refetchInterval: (query) =>
      query.state.data?.installing || query.state.data?.warming ? 1500 : false,
  });

  const install = useMutation({
    mutationFn: () => api.installPdfEngine(),
    onSuccess: () => status.refetch(),
  });

  const test = useMutation({
    mutationFn: () => api.testPdfEngine(),
    onSuccess: (result) => setTestResult(result),
    onError: (error) => setTestResult({ ok: false, error: String(error) }),
  });

  const s = status.data;
  const overrideIgnored =
    !!s && pdf.python.trim() !== "" && s.python !== pdf.python.trim();
  const engineText = !s
    ? "…"
    : s.installing
      ? `${t("settings.pdf.installing")}（${s.installed_mb.toFixed(0)} MB）`
      : s.warming
        ? `${t("settings.pdf.warming")}（${(s.cache_mb ?? 0).toFixed(0)} MB）`
        : s.installed
          ? `${t("settings.pdf.installed")}（${s.installed_mb.toFixed(0)} MB）`
          : t("settings.pdf.notInstalled");

  return (
    <Section title={t("settings.pdf.title")} hint={t("settings.pdf.hint")}>
      <SettingRow label={t("settings.pdf.engine")}>
        <span className={styles.asrStatusText}>{t("settings.pdf.engineInfo")}</span>
      </SettingRow>
      <SettingRow
        label={t("settings.pdf.python")}
        htmlFor="pdf-python"
        description={t("settings.pdf.python.desc")}
      >
        <div className={styles.asrActions}>
          <input
            id="pdf-python"
            className={styles.asrInput}
            value={pdf.python}
            placeholder={s?.python || "python3.12"}
            onChange={(event) => onChange({ ...pdf, python: event.target.value })}
          />
          <span className={styles.asrStatusText}>
            {!s ? "…" : s.python || t("settings.pdf.noPython")}
          </span>
        </div>
        {overrideIgnored && (
          <p className={styles.asrError}>
            {t("settings.pdf.pythonOverrideInvalid")}
            {s?.python || t("settings.pdf.noPython")}
          </p>
        )}
      </SettingRow>
      <SettingRow
        label={t("settings.pdf.status")}
        description={s && !s.installed && !s.installing ? t("settings.pdf.sizeEstimate") : undefined}
      >
        <div className={styles.asrActions}>
          <span className={styles.asrStatusText}>{engineText}</span>
          <button
            type="button"
            className={styles.asrButton}
            disabled={
              !s || !s.python || s.installed || s.installing || s.warming || install.isPending
            }
            onClick={() => install.mutate()}
          >
            {t("settings.pdf.install")}
          </button>
          <button
            type="button"
            className={styles.asrButton}
            disabled={!s || !s.installed || test.isPending}
            onClick={() => {
              setTestResult(null);
              test.mutate();
            }}
          >
            {test.isPending ? t("settings.pdf.testing") : t("settings.pdf.test")}
          </button>
        </div>
        {s?.error && <p className={styles.asrError}>{s.error}</p>}
        {testResult &&
          (testResult.ok ? (
            <p className={styles.asrOk}>
              {t("settings.pdf.testOk")}
              {testResult.version ? `（${testResult.version}）` : ""}
            </p>
          ) : (
            <p className={styles.asrError}>
              {testResult.error_kind === "timeout"
                ? t("settings.pdf.testTimeout")
                : testResult.error}
            </p>
          ))}
      </SettingRow>
    </Section>
  );
}
