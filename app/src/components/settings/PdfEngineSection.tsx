import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { t } from "../../i18n";
import type { PdfEngineTestResult } from "../../lib/api/types";
import { useApi } from "../../lib/connection";
import { Section, SettingRow } from "./Section";
import styles from "./settings.module.css";

export function PdfEngineSection() {
  const api = useApi();
  const [testResult, setTestResult] = useState<PdfEngineTestResult | null>(null);

  const status = useQuery({
    queryKey: ["pdf-status"],
    queryFn: () => api.getPdfEngineStatus(),
    refetchInterval: (query) => (query.state.data?.installing ? 1500 : false),
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
  const engineText = !s
    ? "…"
    : s.installing
      ? `${t("settings.pdf.installing")}（${s.installed_mb.toFixed(0)} MB）`
      : s.installed
        ? `${t("settings.pdf.installed")}（${s.installed_mb.toFixed(0)} MB）`
        : t("settings.pdf.notInstalled");

  return (
    <Section title={t("settings.pdf.title")} hint={t("settings.pdf.hint")}>
      <SettingRow label={t("settings.pdf.python")}>
        <span className={styles.asrStatusText}>
          {!s ? "…" : s.python || t("settings.pdf.noPython")}
        </span>
      </SettingRow>
      <SettingRow label={t("settings.pdf.status")}>
        <div className={styles.asrActions}>
          <span className={styles.asrStatusText}>{engineText}</span>
          <button
            type="button"
            className={styles.asrButton}
            disabled={!s || !s.python || s.installed || s.installing || install.isPending}
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
            <p className={styles.asrError}>{testResult.error}</p>
          ))}
      </SettingRow>
    </Section>
  );
}
