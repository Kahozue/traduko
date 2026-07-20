import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { convertFileSrc } from "@tauri-apps/api/core";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { t } from "../i18n";
import { useApi, useConnection } from "../lib/connection";
import type {
  DubManifestDoc,
  DubParams,
  SpeakersDoc,
} from "../lib/api/types";
import styles from "./DubbingStudioView.module.css";

// Full-screen dubbing studio. The engine menu, parameter area, speaker
// list, preview area, and resynthesize actions share one neutral editing
// surface: the preview frame uses --bg-canvas (zero chroma) so the user's
// audio is not color-biased; the rest follows the management-venue palette.

type EngineId = "voxcpm2" | "say_preview" | "cloud_placeholder";

const VOICE_MODES = ["clone", "design", "preview"] as const;

// The say engine is the preview voice mode: the executor picks the engine
// from voice_mode, so letting the two disagree makes the engine chip a lie.
const PREVIEW_ENGINE: EngineId = "say_preview";

// A timeline document (align_duration) carries each segment's placement.
interface TimelineSegment {
  id: number;
  start: number;
}

// Whatever transcript the dub read: the fallback chain mirrors the core's
// _read_dub_text, so segment text here is the text that was voiced.
interface TextSegment {
  id: number;
  start?: number;
  source?: string;
  target?: string;
}

const TEXT_ARTIFACTS = ["segments.diarized.json", "translation.json", "asr.json"];

function formatTimecode(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

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
  const { data: artifacts } = useQuery({
    queryKey: ["artifacts", project, taskId, task?.updated_at],
    queryFn: () => api.listArtifacts(project, taskId),
    enabled: !!task,
  });
  const { data: enginesDoc } = useQuery({
    queryKey: ["dub-engines"],
    queryFn: () => api.listDubEngines(),
  });
  const { data: voicesDoc } = useQuery({
    queryKey: ["dub-voices"],
    queryFn: () => api.listDubVoices(),
  });
  const { data: params } = useQuery({
    queryKey: ["dub-params", project, taskId],
    queryFn: () => api.getDubParams(project, taskId),
  });

  const engines = enginesDoc?.engines ?? [];
  const voices = voicesDoc?.voices ?? [];

  const [engineId, setEngineId] = useState<EngineId | null>(null);
  const [voiceMode, setVoiceMode] = useState<string>("clone");
  const [instruction, setInstruction] = useState("");
  const [previewVoice, setPreviewVoice] = useState("");
  const [previewRate, setPreviewRate] = useState<number | "">("");
  const [dubText, setDubText] = useState<string>("auto");
  const [cfg, setCfg] = useState<number | "">("");
  const [timesteps, setTimesteps] = useState<number | "">("");
  const [seed, setSeed] = useState<number | "">("");
  const [denoise, setDenoise] = useState<number | "">("");
  const [confirmingSeparate, setConfirmingSeparate] = useState(false);

  // Hydrate local state once params arrive.
  useEffect(() => {
    if (!params) return;
    setEngineId((prev) => prev ?? (params.engine_id as EngineId) ?? "voxcpm2");
    setVoiceMode(params.voice_mode || "clone");
    setInstruction(params.instruction ?? "");
    setPreviewVoice(params.preview_voice ?? "");
    setPreviewRate(params.preview_rate ?? "");
    setDubText(params.dub_text || "auto");
    setCfg(params.cfg ?? "");
    setTimesteps(params.timesteps ?? "");
    setSeed(params.seed ?? "");
    setDenoise(params.denoise ?? "");
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

  // On disk every artifact carries an index prefix (05-dub-mix.wav); the
  // listing's `name` field strips it, so detection and playback both go
  // through the listing rather than the stage records.
  function artifactFile(name: string): string | null {
    return artifacts?.find((item) => item.name === name)?.file ?? null;
  }

  const hasSpeakers = artifactFile("speakers.json") !== null;
  const hasManifest = artifactFile("dub-manifest.json") !== null;
  const mixFile = artifactFile("dub-mix.wav");
  const hasMix = mixFile !== null;

  const { data: speakersDoc } = useQuery({
    queryKey: ["dub-speakers", project, taskId, task?.updated_at],
    queryFn: () => api.readArtifact<SpeakersDoc>(project, taskId, "speakers.json"),
    enabled: hasSpeakers,
  });
  const { data: manifestDoc } = useQuery({
    queryKey: ["dub-manifest", project, taskId, task?.updated_at],
    queryFn: () =>
      api.readArtifact<DubManifestDoc>(project, taskId, "dub-manifest.json"),
    enabled: hasManifest,
  });
  const { data: timelineDoc } = useQuery({
    queryKey: ["dub-timeline", project, taskId, task?.updated_at],
    queryFn: () =>
      api.readArtifact<{ segments: TimelineSegment[] }>(
        project,
        taskId,
        "dub-timeline.json",
      ),
    enabled: artifactFile("dub-timeline.json") !== null,
  });
  // Segment text follows the core's own fallback chain; the first artifact
  // that exists is the one the dub voiced.
  const textArtifact =
    TEXT_ARTIFACTS.find((name) => artifactFile(name) !== null) ?? null;
  const { data: textDoc } = useQuery({
    queryKey: ["dub-text", project, taskId, textArtifact, task?.updated_at],
    queryFn: () =>
      api.readArtifact<{ segments: TextSegment[] }>(
        project,
        taskId,
        textArtifact as string,
      ),
    enabled: textArtifact !== null,
  });

  const startOf = new Map(
    (timelineDoc?.segments ?? []).map((seg) => [seg.id, seg.start]),
  );
  const textOf = new Map(
    (textDoc?.segments ?? []).map((seg) => [
      seg.id,
      { text: seg.target || seg.source || "", start: seg.start },
    ]),
  );
  const segments = (manifestDoc?.segments ?? []).map((entry) => {
    const text = textOf.get(entry.id);
    return {
      ...entry,
      start: startOf.get(entry.id) ?? text?.start ?? null,
      text: text?.text ?? "",
    };
  });

  function buildBody(): Partial<DubParams> {
    const body: Partial<DubParams> = {
      engine_id: engineId ?? "",
      voice_mode: voiceMode,
      instruction,
      dub_text: dubText,
    };
    if (previewVoice) body.preview_voice = previewVoice;
    if (previewRate !== "") body.preview_rate = Number(previewRate);
    // Blank advanced fields follow the global defaults instead of pinning
    // the current value onto the task.
    if (cfg !== "") body.cfg = Number(cfg);
    if (timesteps !== "") body.timesteps = Number(timesteps);
    if (seed !== "") body.seed = Number(seed);
    if (denoise !== "") body.denoise = Number(denoise);
    return body;
  }

  function handleApplyResynth(): void {
    patchParams.mutate(buildBody(), {
      onSuccess: () => redub.mutate("synthesize"),
    });
  }

  // The engine chip and the voice mode are two views of one choice: say is
  // the preview mode, and every other engine is not.
  function pickEngine(next: EngineId): void {
    setEngineId(next);
    if (next === PREVIEW_ENGINE) setVoiceMode("preview");
    else if (voiceMode === "preview") setVoiceMode("clone");
  }

  function pickVoiceMode(next: string): void {
    setVoiceMode(next);
    if (next === "preview") setEngineId(PREVIEW_ENGINE);
    else if (engineId === PREVIEW_ENGINE) setEngineId("voxcpm2");
  }

  const running = task?.status === "running";
  const busy = running || patchParams.isPending || redub.isPending;

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
                aria-pressed={selected}
                title={disabled ? t("task.dub.studio.engine.cloud") : undefined}
                onClick={() => pickEngine(engine.id as EngineId)}
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
              <select
                className={styles.select}
                value={previewVoice}
                onChange={(e) => setPreviewVoice(e.target.value)}
              >
                <option value="">{t("task.dub.studio.sayVoice.auto")}</option>
                {voices.map((voice) => (
                  <option key={voice.name} value={voice.name}>
                    {voice.name} · {voice.locale}
                  </option>
                ))}
              </select>
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
                onChange={(e) => pickVoiceMode(e.target.value)}
              >
                {VOICE_MODES.map((m) => (
                  <option key={m} value={m}>
                    {m === "clone"
                      ? t("task.voiceMode.clone")
                      : m === "design"
                        ? t("task.voiceMode.design")
                        : t("task.voiceMode.preview")}
                  </option>
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
              <option value="auto">{t("task.dub.studio.dubText.auto")}</option>
              <option value="translation">{t("task.dub.studio.dubText.translation")}</option>
              <option value="original">{t("task.dub.studio.dubText.original")}</option>
            </select>
          </label>
        </div>
        {engineId === "voxcpm2" && (
          <details className={styles.advanced}>
            <summary className={styles.summary}>{t("task.dub.studio.advanced")}</summary>
            <p className={styles.hintNote}>{t("task.dub.studio.advancedHint")}</p>
            <div className={styles.paramRow}>
              <label className={styles.fieldNarrow}>
                {t("task.dub.studio.cfg")}
                <input
                  className={styles.input}
                  type="number"
                  step="0.1"
                  value={cfg}
                  onChange={(e) =>
                    setCfg(e.target.value === "" ? "" : Number(e.target.value))
                  }
                />
              </label>
              <label className={styles.fieldNarrow}>
                {t("task.dub.studio.timesteps")}
                <input
                  className={styles.input}
                  type="number"
                  value={timesteps}
                  onChange={(e) =>
                    setTimesteps(e.target.value === "" ? "" : Number(e.target.value))
                  }
                />
              </label>
              <label className={styles.fieldNarrow}>
                {t("task.dub.studio.seed")}
                <input
                  className={styles.input}
                  type="number"
                  value={seed}
                  onChange={(e) =>
                    setSeed(e.target.value === "" ? "" : Number(e.target.value))
                  }
                />
              </label>
              <label className={styles.fieldNarrow}>
                {t("task.dub.studio.denoise")}
                <input
                  className={styles.input}
                  type="number"
                  step="0.1"
                  value={denoise}
                  onChange={(e) =>
                    setDenoise(e.target.value === "" ? "" : Number(e.target.value))
                  }
                />
              </label>
            </div>
          </details>
        )}
      </section>

      <section className={styles.block}>
        <h2 className={styles.sectionTitle}>{t("task.dub.studio.speakers")}</h2>
        <div className={styles.speakerList} role="group" aria-label={t("task.dub.studio.speakers")}>
          {hasSpeakers && speakersDoc ? (
            speakersDoc.speakers.map((speaker) => {
              const ref = artifactFile(`ref-${speaker.id}.wav`);
              return (
                <div key={speaker.id} className={styles.speakerRow}>
                  <div className={styles.speakerText}>
                    <span className={styles.speakerName}>
                      {speaker.label || speaker.id}
                    </span>
                    {speaker.ref_text && (
                      <span className={styles.speakerRef}>{speaker.ref_text}</span>
                    )}
                  </div>
                  {ref ? (
                    <audio
                      controls
                      className={styles.audio}
                      aria-label={`${t("task.dub.studio.speakers.refAudio")} ${speaker.id}`}
                      src={convertFileSrc(artifactPath(ref))}
                    />
                  ) : (
                    <span className={styles.speakerSpan}>
                      {formatTimecode(speaker.ref_start)} – {formatTimecode(speaker.ref_end)}
                    </span>
                  )}
                </div>
              );
            })
          ) : (
            <div className={styles.emptyRow}>
              <p className={styles.hint}>{t("task.dub.studio.speakers.empty")}</p>
              <button
                type="button"
                className={styles.secondary}
                disabled={busy}
                onClick={() => setConfirmingSeparate(true)}
              >
                {t("task.dub.studio.speakers.separateNow")}
              </button>
            </div>
          )}
        </div>
      </section>

      <section className={styles.block}>
        <h2 className={styles.sectionTitle}>{t("task.dub.studio.preview")}</h2>
        <div className={styles.canvas}>
          {hasMix || segments.length > 0 ? (
            <div className={styles.previewList}>
              {mixFile && (
                <div className={styles.previewRow}>
                  <span className={styles.previewLabel}>{t("task.dub.studio.mix")}</span>
                  <audio
                    controls
                    className={styles.audio}
                    src={convertFileSrc(artifactPath(mixFile))}
                  />
                </div>
              )}
              {segments.map((segment) => (
                <div
                  key={segment.id}
                  className={styles.segmentRow}
                  data-testid="dub-segment"
                >
                  <span className={styles.segmentTime}>
                    {segment.start === null ? "--:--" : formatTimecode(segment.start)}
                  </span>
                  <span className={styles.segmentText}>{segment.text}</span>
                  {segment.status === "synthesized" && segment.file ? (
                    <audio
                      controls
                      className={styles.segmentAudio}
                      src={convertFileSrc(artifactPath(segment.file))}
                    />
                  ) : (
                    <span className={styles.segmentFailed}>
                      {t("task.dub.studio.segment.failed")}
                      {segment.error ? `：${segment.error}` : ""}
                    </span>
                  )}
                </div>
              ))}
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
          disabled={busy}
          onClick={() => redub.mutate("diarize")}
        >
          {t("task.dub.studio.redubFromDiarize")}
        </button>
        <button
          type="button"
          className={styles.primary}
          disabled={busy}
          onClick={handleApplyResynth}
        >
          {t("task.dub.studio.apply")}
        </button>
      </div>

      {confirmingSeparate && (
        <ConfirmDialog
          title={t("task.dub.studio.speakers.separateConfirm.title")}
          body={t("task.dub.studio.speakers.separateConfirm.body")}
          confirmLabel={t("task.dub.studio.speakers.separateNow")}
          cancelLabel={t("task.rerunConfirm.cancel")}
          busy={redub.isPending}
          onConfirm={() => {
            setConfirmingSeparate(false);
            redub.mutate("diarize");
          }}
          onCancel={() => setConfirmingSeparate(false)}
        />
      )}
    </div>
  );
}
