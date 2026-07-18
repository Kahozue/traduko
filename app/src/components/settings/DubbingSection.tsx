import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { t } from "../../i18n";
import type { DubbingConfigDoc, DubbingTestResult } from "../../lib/api/types";
import { useApi } from "../../lib/connection";
import { Section, SettingRow } from "./Section";
import styles from "./settings.module.css";

export function DubbingSection({
  dubbing,
  onChange,
}: {
  dubbing: DubbingConfigDoc;
  onChange: (value: DubbingConfigDoc) => void;
}) {
  const api = useApi();
  const [reveal, setReveal] = useState(false);
  const [testResult, setTestResult] = useState<DubbingTestResult | null>(null);

  const status = useQuery({
    queryKey: ["dubbing-status"],
    queryFn: () => api.getDubbingStatus(),
    refetchInterval: (query) => (query.state.data?.installing ? 1500 : false),
  });

  const install = useMutation({
    mutationFn: () => api.installDubbingEngine(),
    onSuccess: () => status.refetch(),
  });

  const test = useMutation({
    mutationFn: () => api.testDubbingEngine(),
    onSuccess: (result) => setTestResult(result),
    onError: (error) => setTestResult({ ok: false, error: String(error) }),
  });

  const s = status.data;
  const engineText = !s
    ? "…"
    : s.installing
      ? `${t("settings.dubbing.installing")}（${s.installed_mb.toFixed(0)} MB）`
      : s.installed
        ? `${t("settings.dubbing.installed")}（${s.installed_mb.toFixed(0)} MB）`
        : t("settings.dubbing.notInstalled");

  return (
    <Section title={t("settings.dubbing.title")} hint={t("settings.dubbing.hint")}>
      <SettingRow label={t("settings.dubbing.python")}>
        <span className={styles.asrStatusText}>
          {!s ? "…" : s.python || t("settings.dubbing.noPython")}
        </span>
      </SettingRow>
      <SettingRow label={t("settings.dubbing.status")}>
        <div className={styles.asrActions}>
          <span className={styles.asrStatusText}>{engineText}</span>
          <button
            type="button"
            className={styles.asrButton}
            disabled={!s || !s.python || s.installed || s.installing || install.isPending}
            onClick={() => install.mutate()}
          >
            {t("settings.dubbing.install")}
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
            {test.isPending ? t("settings.dubbing.testing") : t("settings.dubbing.test")}
          </button>
        </div>
        {s?.error && <p className={styles.asrError}>{s.error}</p>}
        {testResult &&
          (testResult.ok ? (
            <p className={styles.asrOk}>
              {t("settings.dubbing.testOk")}
              {testResult.torch ? `（torch ${testResult.torch}` : "（torch —"}
              {testResult.mps ? " · MPS" : ""}
              {"）"}
            </p>
          ) : (
            <p className={styles.asrError}>{testResult.error}</p>
          ))}
      </SettingRow>
      <SettingRow label={t("settings.dubbing.hfToken")} htmlFor="dubbing-hf-token">
        <div className={styles.asrActions}>
          <input
            id="dubbing-hf-token"
            type={reveal ? "text" : "password"}
            className={styles.input}
            value={dubbing.hf_token}
            placeholder="hf_…"
            onChange={(event) =>
              onChange({ ...dubbing, hf_token: event.target.value })
            }
          />
          <button
            type="button"
            className={styles.asrButton}
            onClick={() => setReveal((prev) => !prev)}
          >
            {reveal ? t("settings.dubbing.hide") : t("settings.dubbing.reveal")}
          </button>
        </div>
      </SettingRow>
    </Section>
  );
}
