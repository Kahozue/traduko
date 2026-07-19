import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { convertFileSrc } from "@tauri-apps/api/core";
import { t } from "../i18n";
import { useApi, useConnection } from "../lib/connection";
import type { DubParams } from "../lib/api/types";
import styles from "./DubbingStudioView.module.css";

// Full-screen dubbing studio. The engine menu, parameter area, speaker
// list, preview area, and resynthesize actions share one neutral editing
// surface: the preview frame uses --bg-canvas (zero chroma) so the user's
// audio is not color-biased; the rest follows the management-venue palette.

type EngineId = "voxcpm2" | "say_preview" | "cloud_placeholder";

const VOICE_MODES = ["clone", "design", "preview"] as const;

export function DubbingStudioView({
  project,
  taskId,
  onBack,
}: {
  project: string;
  taskId: string;
  onBack: () => void;
}) {
  const api = useApi();
  const { dataRoot } = useConnection();
  const queryClient = useQueryClient();

  const { data: task } = useQuery({
    queryKey: ["task", project, taskId],
    queryFn: () => api.showTask(project, taskId),
  });
  const { data: enginesDoc } = useQuery({
    queryKey: ["dub-engines"],
    queryFn: () => api.listDubEngines(),
  });
  const { data: params } = useQuery({
    queryKey: ["dub-params", project, taskId],
    queryFn: () => api.getDubParams(project, taskId),
  });

  const engines = enginesDoc?.engines ?? [];

  const [engineId, setEngineId] = useState<EngineId | null>(null);
  const [voiceMode, setVoiceMode] = useState<string>("clone");
  const [instruction, setInstruction] = useState("");
  const [previewVoice, setPreviewVoice] = useState("");
  const [previewRate, setPreviewRate] = useState<number | "">("");
  const [dubText, setDubText] = useState<string>("auto");

  // Hydrate local state once params arrive.
  useEffect(() => {
    if (!params) return;
    setEngineId((prev) => prev ?? (params.engine_id as EngineId) ?? "voxcpm2");
    setVoiceMode(params.voice_mode || "clone");
    setInstruction(params.instruction ?? "");
    setPreviewVoice(params.preview_voice ?? "");
    setPreviewRate(params.preview_rate ?? "");
    setDubText(params.dub_text || "auto");
  }, [params]);

  const patchParams = useMutation({
    mutationFn: (body: Partial<DubParams>) => api.patchDubParams(project, taskId, body),
    onSuccess: (next) => {
      queryClient.setQueryData(["dub-params", project, taskId], next);
    },
  });
  const redub = useMutation({
    mutationFn: (from: "synthesize" | "diarize") => api.dubRedub(project, taskId, from),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["task", project, taskId] });
    },
  });

  function artifactPath(file: string): string {
    return `${dataRoot}/projects/${project}/tasks/${taskId}/artifacts/${file}`;
  }

  const hasSpeakers = task?.stages.some(
    (s) => s.type === "diarize" && s.artifacts.includes("speakers.json"),
  ) ?? false;
  const hasManifest = task?.stages.some(
    (s) => s.type === "tts_synthesize" && s.artifacts.includes("dub-manifest.json"),
  ) ?? false;
  const hasMix = task?.stages.some(
    (s) => s.artifacts.includes("dub-mix.wav"),
  ) ?? false;

  function buildBody(): Partial<DubParams> {
    const body: Partial<DubParams> = {
      engine_id: engineId ?? "",
      voice_mode: voiceMode,
      instruction,
      dub_text: dubText,
    };
    if (previewVoice) body.preview_voice = previewVoice;
    if (previewRate !== "") body.preview_rate = Number(previewRate);
    return body;
  }

  function handleApplyResynth(): void {
    patchParams.mutate(buildBody(), {
      onSuccess: () => redub.mutate("synthesize"),
    });
  }

  const running = task?.status === "running";

  return (
    <div className={styles.wrap}>
      <button type="button" className={styles.back} onClick={onBack}>
        {t("task.back")}
      </button>
      <h1 className={styles.title}>{t("task.dub.studio.title")}</h1>

      <section className={styles.block}>
        <div className={styles.engineRow} role="group" aria-label={t("task.dub.studio.params")}>
          {engines.map((engine) => {
            const selected = engine.id === engineId;
            const disabled = !engine.available;
            return (
              <button
                key={engine.id}
                type="button"
                className={`${styles.engineChip} ${selected ? styles.engineChipActive : ""}`}
                disabled={disabled}
                title={disabled ? t("task.dub.studio.engine.cloud") : undefined}
                onClick={() => setEngineId(engine.id as EngineId)}
              >
                {engine.id === "voxcpm2"
                  ? t("task.dub.studio.engine.voxcpm2")
                  : engine.id === "say_preview"
                    ? t("task.dub.studio.engine.say")
                    : t("task.dub.studio.engine.cloud")}
              </button>
            );
          })}
        </div>
      </section>

      <section className={styles.block}>
        <h2 className={styles.sectionTitle}>{t("task.dub.studio.params")}</h2>
        {engineId === "say_preview" ? (
          <div className={styles.paramRow}>
            <label className={styles.field}>
              {t("task.dub.studio.sayVoice")}
              <input
                className={styles.input}
                value={previewVoice}
                onChange={(e) => setPreviewVoice(e.target.value)}
              />
            </label>
            <label className={styles.field}>
              {t("task.dub.studio.sayRate")}
              <input
                className={styles.input}
                type="number"
                value={previewRate}
                onChange={(e) =>
                  setPreviewRate(e.target.value === "" ? "" : Number(e.target.value))
                }
              />
            </label>
          </div>
        ) : (
          <div className={styles.paramRow}>
            <label className={styles.field}>
              {t("task.dub.studio.voiceMode")}
              <select
                className={styles.select}
                value={voiceMode}
                onChange={(e) => setVoiceMode(e.target.value)}
              >
                {VOICE_MODES.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </label>
            {voiceMode === "design" && (
              <label className={styles.fieldGrow}>
                {t("task.dub.studio.instruction")}
                <input
                  className={styles.input}
                  value={instruction}
                  onChange={(e) => setInstruction(e.target.value)}
                />
              </label>
            )}
          </div>
        )}
        <div className={styles.paramRow}>
          <label className={styles.field}>
            {t("task.dub.studio.dubText")}
            <select
              className={styles.select}
              value={dubText}
              onChange={(e) => setDubText(e.target.value)}
            >
              <option value="auto">auto</option>
              <option value="translation">{t("task.dub.studio.dubText.translation")}</option>
              <option value="original">{t("task.dub.studio.dubText.original")}</option>
            </select>
          </label>
        </div>
      </section>

      <section className={styles.block}>
        <h2 className={styles.sectionTitle}>{t("task.dub.studio.speakers")}</h2>
        {hasSpeakers ? (
          <p className={styles.hint}>{t("task.dub.studio.speakers")}</p>
        ) : (
          <p className={styles.hint}>{t("task.dub.studio.speakers.empty")}</p>
        )}
      </section>

      <section className={styles.block}>
        <h2 className={styles.sectionTitle}>{t("task.dub.studio.preview")}</h2>
        <div className={styles.canvas}>
          {hasManifest || hasMix ? (
            <div className={styles.previewList}>
              {hasMix && (
                <div className={styles.previewRow}>
                  <span className={styles.previewLabel}>{t("task.dub.studio.mix")}</span>
                  <audio
                    controls
                    className={styles.audio}
                    src={convertFileSrc(artifactPath("dub-mix.wav"))}
                  />
                </div>
              )}
              {!hasManifest && !hasMix && (
                <span className={styles.hint}>{t("task.dub.studio.preview.empty")}</span>
              )}
            </div>
          ) : (
            <span className={styles.hint}>{t("task.dub.studio.preview.empty")}</span>
          )}
        </div>
      </section>

      <div className={styles.actions}>
        <button
          type="button"
          className={styles.secondary}
          disabled={running || redub.isPending}
          onClick={() => redub.mutate("diarize")}
        >
          {t("task.dub.studio.redubFromDiarize")}
        </button>
        <button
          type="button"
          className={styles.primary}
          disabled={running || patchParams.isPending || redub.isPending}
          onClick={handleApplyResynth}
        >
          {t("task.dub.studio.apply")}
        </button>
      </div>
    </div>
  );
}
