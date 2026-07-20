import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { t } from "../../i18n";
import type { DubbingConfigDoc, DubbingTestResult } from "../../lib/api/types";
import { useApi } from "../../lib/connection";
import { Section, SettingRow } from "./Section";
import styles from "./settings.module.css";

function numberOrNull(raw: string): number | null {
  if (raw.trim() === "") return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

// The dubbing engine is shared by the video and audio tabs, which both
// render this section. Nothing in it is domain-specific any more: the
// per-domain pipeline defaults moved to PipelineDefaultsSection.
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
  const modelStatus = useQuery({
    queryKey: ["dubbing-model-status"],
    queryFn: () => api.getDubbingModelStatus(),
    refetchInterval: (query) => (query.state.data?.downloading ? 1500 : false),
  });

  const install = useMutation({
    mutationFn: () => api.installDubbingEngine(),
    onSuccess: () => status.refetch(),
  });
  const downloadModel = useMutation({
    mutationFn: () => api.downloadDubbingModel(),
    onSuccess: () => modelStatus.refetch(),
  });

  const test = useMutation({
    mutationFn: () => api.testDubbingEngine(),
    onSuccess: (result) => setTestResult(result),
    onError: (error) => setTestResult({ ok: false, error: String(error) }),
  });

  const s = status.data;
  const m = modelStatus.data;
  const engineText = !s
    ? "…"
    : s.installing
      ? `${t("settings.dubbing.installing")}（${s.installed_mb.toFixed(0)} MB）`
      : s.installed
        ? `${t("settings.dubbing.installed")}（${s.installed_mb.toFixed(0)} MB）`
        : t("settings.dubbing.notInstalled");
  // A configured interpreter that discovery rejected silently falls back;
  // surface the fallback so the user is not left guessing.
  const overrideIgnored =
    !!s && dubbing.python.trim() !== "" && s.python !== dubbing.python.trim();
  const modelText = !m
    ? "…"
    : m.downloading
      ? `${t("settings.dubbing.model.downloading")}（${m.downloaded_mb.toFixed(0)} / ${m.total_mb.toFixed(0)} MB）`
      : m.cached
        ? `${t("settings.dubbing.model.cached")}（${m.downloaded_mb.toFixed(0)} MB）`
        : t("settings.dubbing.model.notCached");

  return (
    <Section title={t("settings.dubbing.title")} hint={t("settings.dubbing.hint")}>
      <SettingRow
        label={t("settings.dubbing.python")}
        htmlFor="dubbing-python"
        description={t("settings.dubbing.python.desc")}
      >
        <div className={styles.asrActions}>
          <input
            id="dubbing-python"
            className={styles.asrInput}
            value={dubbing.python}
            placeholder={s?.python || "python3.11"}
            onChange={(event) => onChange({ ...dubbing, python: event.target.value })}
          />
          <span className={styles.asrStatusText}>
            {!s ? "…" : s.python || t("settings.dubbing.noPython")}
          </span>
        </div>
        {overrideIgnored && (
          <p className={styles.asrError}>
            {t("settings.dubbing.pythonOverrideInvalid")}
            {s?.python || t("settings.dubbing.noPython")}
          </p>
        )}
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
              {`（voxcpm ${testResult.voxcpm ?? "—"} · torch ${testResult.torch ?? "—"} · `}
              {testResult.mps
                ? t("settings.dubbing.deviceMps")
                : t("settings.dubbing.deviceCpu")}
              {"）"}
            </p>
          ) : (
            <p className={styles.asrError}>{testResult.error}</p>
          ))}
      </SettingRow>
      <SettingRow
        label={t("settings.dubbing.model")}
        description={t("settings.dubbing.model.desc")}
      >
        <div className={styles.asrActions}>
          <span className={styles.asrStatusText}>{modelText}</span>
          <button
            type="button"
            className={styles.asrButton}
            disabled={!m || m.cached || m.downloading || downloadModel.isPending}
            onClick={() => downloadModel.mutate()}
          >
            {t("settings.dubbing.model.download")}
          </button>
        </div>
        {m?.error && <p className={styles.asrError}>{m.error}</p>}
      </SettingRow>

      <SettingRow
        label={t("settings.dubbing.timesteps")}
        htmlFor="dubbing-timesteps"
      >
        <input
          id="dubbing-timesteps"
          className={styles.numberInput}
          inputMode="numeric"
          value={dubbing.inference_timesteps ?? ""}
          placeholder={t("settings.dubbing.engineDefault")}
          onChange={(event) =>
            onChange({
              ...dubbing,
              inference_timesteps: numberOrNull(event.target.value),
            })
          }
        />
      </SettingRow>
      <SettingRow label={t("settings.dubbing.cfg")} htmlFor="dubbing-cfg">
        <input
          id="dubbing-cfg"
          className={styles.numberInput}
          inputMode="decimal"
          value={dubbing.cfg_value ?? ""}
          placeholder={t("settings.dubbing.engineDefault")}
          onChange={(event) =>
            onChange({ ...dubbing, cfg_value: numberOrNull(event.target.value) })
          }
        />
      </SettingRow>
      <SettingRow label={t("settings.dubbing.seed")} htmlFor="dubbing-seed">
        <input
          id="dubbing-seed"
          className={styles.numberInput}
          inputMode="numeric"
          value={dubbing.seed ?? ""}
          placeholder={t("settings.dubbing.seedRandom")}
          onChange={(event) =>
            onChange({ ...dubbing, seed: numberOrNull(event.target.value) })
          }
        />
      </SettingRow>
      <SettingRow
        label={t("settings.dubbing.denoise")}
        description={t("settings.dubbing.denoise.desc")}
      >
        <input
          type="checkbox"
          aria-label={t("settings.dubbing.denoise")}
          checked={dubbing.denoise}
          onChange={(event) => onChange({ ...dubbing, denoise: event.target.checked })}
        />
      </SettingRow>

      {/* hf_token only matters for speaker diarization (voice cloning of
         multi-speaker sources); tucked away so single-voice users never
         meet it. Open by default when a token is already set. */}
      <details className={styles.disclosure} open={dubbing.hf_token !== ""}>
        <summary className={styles.disclosureSummary}>
          {t("settings.dubbing.diarizeSection")}
        </summary>
        {/* The "run diarization by default" switch used to live here, which
           put one domain's pipeline default inside a shared engine section.
           It is a pipeline default like the others, so it sits with them in
           PipelineDefaultsSection; what stays here is the engine's own
           setup (the token that unlocks the model). */}
        <SettingRow
          label={t("settings.dubbing.hfToken")}
          htmlFor="dubbing-hf-token"
          description={t("settings.dubbing.hfToken.desc")}
        >
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
      </details>
    </Section>
  );
}
