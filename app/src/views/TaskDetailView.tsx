import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Icon } from "../components/icons";
import { ProgressBar } from "../components/ProgressBar";
import { StatusBadge } from "../components/StatusBadge";
import { t } from "../i18n";
import { ApiError } from "../lib/api/client";
import type { PreflightCheck } from "../lib/api/types";
import { useApi, useConnection } from "../lib/connection";
import { openArtifact, revealArtifact } from "../lib/shell";
import { humanizeError, matchError } from "../lib/errors";
import { formatDateTime } from "../lib/time";
import { useTaskLive } from "../lib/events/store";
import { eventTypeLabel, stageListLabels, stageStatusLabel, stageTypeLabel } from "../lib/labels";
import styles from "./TaskDetailView.module.css";

const RUNNABLE = new Set(["pending", "paused", "waiting_review", "failed"]);
const CANCELABLE = new Set(["pending", "running", "waiting_review", "paused"]);
const PAUSABLE = new Set(["running"]);

// Stage types whose params carry the per-task LLM override (mirrors the
// core's tasks.LLM_STAGE_TYPES).
const LLM_STAGE_TYPES = new Set([
  "translate",
  "proofread",
  "translate_chunks",
  "translate_pdf",
]);
const REAL_PROVIDER_TYPES = new Set(["openai_compat", "anthropic", "gemini"]);
const ASR_ENGINE_LABELS: Record<string, string> = {
  faster_whisper: "faster-whisper",
  macos_native: "macOS 原生",
  openai_whisper: "whisper-1",
  openai_gpt4o_diarize: "gpt-4o-transcribe-diarize",
  openai_gpt4o: "gpt-4o-transcribe",
  openai_gpt4o_mini: "gpt-4o-mini-transcribe",
  cloud_custom: "自訂端點",
};
const ASR_ENGINE_IDS = Object.keys(ASR_ENGINE_LABELS);

// One-line human summary for an event's payload; the raw JSON stays in the
// row's tooltip instead of being dumped into the timeline.
function summarizeEventData(data: Record<string, unknown>): string {
  const parts: string[] = [];
  if (typeof data.stage === "string") parts.push(stageTypeLabel(data.stage));
  if (typeof data.current === "number" && typeof data.total === "number") {
    parts.push(`${data.current}/${data.total}`);
  }
  if (typeof data.round === "number") parts.push(String(data.round));
  if (typeof data.usd === "number") parts.push(`$${data.usd.toFixed(2)}`);
  if (typeof data.error === "string") parts.push(data.error.slice(0, 80));
  return parts.join(" · ");
}

function StageError({ raw, defaultOpen = false }: { raw: string; defaultOpen?: boolean }) {
  const human = humanizeError(raw);
  const [showRaw, setShowRaw] = useState(defaultOpen);
  return (
    <div className={styles.stageError}>
      <p className={styles.stageErrorSummary}>{human.summary}</p>
      {human.hint && <p className={styles.stageErrorHint}>{human.hint}</p>}
      <details
        className={styles.rawError}
        open={showRaw}
        onToggle={(event) => setShowRaw(event.currentTarget.open)}
      >
        <summary>{t("error.raw")}</summary>
        <pre>{raw}</pre>
      </details>
    </div>
  );
}

export function TaskDetailView({
  project,
  taskId,
  onBack,
  onOpenSettings,
  onOpenEditor,
}: {
  project: string;
  taskId: string;
  onBack: () => void;
  onOpenSettings?: () => void;
  onOpenEditor: (kind: "subtitle" | "document" | "speakers") => void;
}) {
  const api = useApi();
  const { dataRoot } = useConnection();
  const queryClient = useQueryClient();
  const live = useTaskLive(project, taskId);
  const [failedChecks, setFailedChecks] = useState<PreflightCheck[] | null>(null);
  const { data: task } = useQuery({
    queryKey: ["task", project, taskId],
    queryFn: () => api.showTask(project, taskId),
  });
  const { data: artifacts } = useQuery({
    queryKey: ["artifacts", project, taskId, task?.updated_at],
    queryFn: () => api.listArtifacts(project, taskId),
    enabled: !!task,
  });
  const { data: pastEvents } = useQuery({
    queryKey: ["task-events", project, taskId],
    queryFn: () => api.taskEvents(project, taskId),
  });
  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: () => api.getConfig(),
  });

  const run = useMutation({
    mutationFn: (skipPreflight: boolean) => api.runTask(project, taskId, { skipPreflight }),
    onSuccess: () => {
      setFailedChecks(null);
      queryClient.invalidateQueries({ queryKey: ["task", project, taskId] });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        const detail = error.detail as { checks?: PreflightCheck[] } | string;
        if (typeof detail === "object" && detail?.checks) {
          setFailedChecks(detail.checks);
        }
      }
    },
  });

  const cancel = useMutation({
    mutationFn: () => api.cancelTask(project, taskId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["task", project, taskId] }),
  });

  const pause = useMutation({
    mutationFn: () => api.pauseTask(project, taskId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["task", project, taskId] }),
  });

  const [editingName, setEditingName] = useState(false);
  const [draftName, setDraftName] = useState("");
  const [showDetails, setShowDetails] = useState(false);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [draftProvider, setDraftProvider] = useState("");
  const [draftModel, setDraftModel] = useState("");
  const setModel = useMutation({
    mutationFn: ({ provider, model }: { provider: string; model: string }) =>
      api.setTaskModel(project, taskId, provider, model),
    onSuccess: () => {
      setModelMenuOpen(false);
      queryClient.invalidateQueries({ queryKey: ["task", project, taskId] });
    },
  });
  const [asrMenuOpen, setAsrMenuOpen] = useState(false);
  const [draftAsrEngine, setDraftAsrEngine] = useState("");
  const setAsrEngine = useMutation({
    mutationFn: (engine: string) => api.setTaskAsrEngine(project, taskId, engine),
    onSuccess: () => {
      setAsrMenuOpen(false);
      queryClient.invalidateQueries({ queryKey: ["task", project, taskId] });
    },
  });
  const [voiceMenuOpen, setVoiceMenuOpen] = useState(false);
  const [draftVoiceMode, setDraftVoiceMode] = useState("");
  const [draftVoiceInstruction, setDraftVoiceInstruction] = useState("");
  const setVoiceMode = useMutation({
    mutationFn: ({ mode, instruction }: { mode: string; instruction: string }) =>
      api.setTaskVoiceMode(project, taskId, mode, instruction),
    onSuccess: () => {
      setVoiceMenuOpen(false);
      queryClient.invalidateQueries({ queryKey: ["task", project, taskId] });
    },
  });
  const [modelDownload, setModelDownload] = useState<
    null | { model: string; mb: number; error?: string }
  >(null);

  // Preflight failed because the ASR model is missing: download it here,
  // then run the task, instead of sending the user to hunt for settings.
  const missingModel = (() => {
    const check = failedChecks?.find(
      (item) => item.name === "asr model" && item.message.includes("not downloaded"),
    );
    return check ? (/'([^']+)'/.exec(check.message)?.[1] ?? "small") : null;
  })();

  async function downloadModelAndRun(model: string) {
    setModelDownload({ model, mb: 0 });
    try {
      await api.downloadAsrModel(model);
      for (;;) {
        const status = await api.getAsrStatus(model);
        setModelDownload({ model, mb: status.downloaded_mb });
        if (status.state === "error") {
          setModelDownload({ model, mb: status.downloaded_mb, error: status.error ?? "" });
          return;
        }
        if (status.cached) break;
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
      setModelDownload(null);
      setFailedChecks(null);
      run.mutate(false);
    } catch (error) {
      setModelDownload({ model, mb: 0, error: String(error) });
    }
  }

  const rename = useMutation({
    mutationFn: (value: string) => api.renameTask(project, taskId, value),
    onSuccess: () => {
      setEditingName(false);
      queryClient.invalidateQueries({ queryKey: ["task", project, taskId] });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });

  if (!task) return null;

  const completed = task.stages.filter((stage) => stage.status === "completed").length;
  const runningIndex = task.stages.findIndex((stage) => stage.status === "running");

  // Persisted log first, then live WS events; dedupe the overlap window
  // between the initial fetch and the socket subscription.
  const seen = new Set<string>();
  const events = [...(pastEvents ?? []), ...(live?.events ?? [])].filter((event) => {
    const key = `${event.ts}|${event.type}|${JSON.stringify(event.data)}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  const lastStageError = [...task.stages].reverse().find((stage) => stage.error)?.error;

  const hasTranslation = (artifacts ?? []).some((item) => item.name === "translation.json");
  const isDocumentTask = (task?.stages ?? []).some(
    (stage) => stage.type === "ingest_document",
  );
  const hasSpeakers = (artifacts ?? []).some((item) => item.name === "speakers.json");
  const isDubTask = (task?.stages ?? []).some((stage) => stage.type === "diarize");
  // Only pipelines that produce a translation artifact get an editor entry;
  // translate_pdf outputs finished PDFs with nothing to edit in-app.
  const supportsEditor = task.stages.some((stage) =>
    ["ingest_subtitle", "asr", "translate", "proofread", "ingest_document", "translate_chunks"].includes(stage.type),
  );
  const editorKind = isDocumentTask ? "document" : "subtitle";
  const editorLabel = isDocumentTask ? t("task.textEditor") : t("task.subtitleEditor");
  const stageLabels = stageListLabels(task.stages);
  const outputs = (artifacts ?? []).filter((item) => !item.file.endsWith(".json"));

  // Effective LLM choice for the model chip, mirroring the core's
  // resolve_provider_name: explicit override wins, then the configured
  // default, then the sole real provider.
  const llmStage = task.stages.find((stage) => LLM_STAGE_TYPES.has(stage.type));
  const overrideProvider =
    typeof llmStage?.params.provider === "string" ? llmStage.params.provider : "";
  const overrideModel =
    typeof llmStage?.params.model === "string" ? llmStage.params.model : "";
  const providers = config?.llm_providers ?? {};
  const realNames = Object.entries(providers)
    .filter(([, value]) =>
      REAL_PROVIDER_TYPES.has(String((value as { type?: unknown }).type)),
    )
    .map(([name]) => name);
  const isExplicit = overrideProvider !== "" && overrideProvider !== "fake";
  const effectiveProvider = isExplicit
    ? overrideProvider
    : config?.default_provider && providers[config.default_provider]
      ? config.default_provider
      : realNames.length === 1
        ? realNames[0]
        : "";
  const providerDefaultModel = String(
    (providers[effectiveProvider] as { model?: unknown } | undefined)?.model ?? "",
  );
  const effectiveModel = overrideModel || providerDefaultModel;
  const modelChipLabel = effectiveProvider
    ? `${effectiveProvider} · ${effectiveModel || "--"}`
    : t("task.model.unset");
  const modelLocked = task.status === "running";

  // Read-only engine chips; the ASR chip switches in place, TTS/PDF stay
  // informational until their engines grow choices.
  const asrStage = task.stages.find((stage) => stage.type === "asr");
  const asrEngineParam =
    typeof asrStage?.params.engine === "string" ? asrStage.params.engine : "";
  const asrProviderParam =
    typeof asrStage?.params.provider === "string" ? asrStage.params.provider : "";
  const asrExplicit =
    asrEngineParam !== "" &&
    asrEngineParam !== "auto" &&
    asrEngineParam !== "auto_audio";
  const asrChipLabel = asrExplicit
    ? (ASR_ENGINE_LABELS[asrEngineParam] ?? asrEngineParam)
    : asrProviderParam && !asrEngineParam
      ? (ASR_ENGINE_LABELS[asrProviderParam] ?? asrProviderParam)
      : t("task.asrEngine.auto");
  // The dubbing chip switches the task's voice mode in place; the PDF chip
  // stays informational until its engine grows choices.
  const ttsStage = task.stages.find((stage) => stage.type === "tts_synthesize");
  const voiceModeParam =
    typeof ttsStage?.params.voice_mode === "string" ? ttsStage.params.voice_mode : "";
  const voiceInstructionParam =
    typeof ttsStage?.params.voice_instruction === "string"
      ? ttsStage.params.voice_instruction
      : "";
  const voiceChipLabel =
    voiceModeParam === "preview"
      ? t("task.voiceMode.preview")
      : voiceModeParam === "design"
        ? `VoxCPM2 · ${t("task.voiceMode.design")}`
        : `VoxCPM2 · ${t("task.voiceMode.clone")}`;
  const engineChips: string[] = [];
  if (task.stages.some((stage) => stage.type === "translate_pdf")) {
    engineChips.push("pdf2zh-next");
  }

  function artifactPath(file: string): string {
    return `${dataRoot}/projects/${project}/tasks/${taskId}/artifacts/${file}`;
  }

  function formatSize(bytes: number): string {
    if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }

  return (
    <div>
      <button type="button" className={styles.back} onClick={onBack}>
        {t("task.back")}
      </button>
      <header className={styles.header}>
        <div className={styles.headline}>
          {editingName ? (
            <>
              <input
                autoFocus
                className={styles.nameInput}
                value={draftName}
                onChange={(e) => setDraftName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && draftName.trim() !== "" && !rename.isPending) {
                    rename.mutate(draftName.trim());
                  } else if (e.key === "Escape") {
                    setEditingName(false);
                  }
                }}
              />
              <button
                type="button"
                className={styles.secondary}
                disabled={draftName.trim() === "" || rename.isPending}
                onClick={() => rename.mutate(draftName.trim())}
              >
                {t("task.renameSave")}
              </button>
              <button
                type="button"
                className={styles.secondary}
                onClick={() => setEditingName(false)}
              >
                {t("task.renameCancel")}
              </button>
            </>
          ) : (
            <>
              <h1 className={styles.title}>{task.name ?? task.id}</h1>
              <StatusBadge status={task.status} />
              <button
                type="button"
                className={styles.renameBtn}
                aria-label={t("task.rename")}
                title={t("task.rename")}
                onClick={() => {
                  setDraftName(task.name ?? task.id);
                  setEditingName(true);
                }}
              >
                <Icon name="pencil" size={15} />
              </button>
            </>
          )}
        </div>
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.primary}
            disabled={!RUNNABLE.has(task.status) || run.isPending}
            onClick={() => run.mutate(false)}
          >
            {t("task.run")}
          </button>
          <button
            type="button"
            className={styles.secondary}
            disabled={!PAUSABLE.has(task.status) || pause.isPending}
            onClick={() => pause.mutate()}
          >
            {t("task.pause")}
          </button>
          <button
            type="button"
            className={styles.danger}
            disabled={!CANCELABLE.has(task.status) || cancel.isPending}
            onClick={() => cancel.mutate()}
          >
            {t("task.cancel")}
          </button>
          {supportsEditor && (
            <button
              type="button"
              className={styles.secondary}
              disabled={!hasTranslation}
              title={hasTranslation ? undefined : t("task.editorDisabledHint")}
              onClick={() => onOpenEditor(editorKind)}
            >
              {editorLabel}
            </button>
          )}
          {isDubTask && (
            <button
              type="button"
              className={styles.secondary}
              disabled={!hasSpeakers}
              onClick={() => onOpenEditor("speakers")}
            >
              {t("task.speakerReview")}
            </button>
          )}
        </div>
      </header>

      <div className={styles.metaLine}>
        <span>{task.profile}</span>
        {llmStage && config && (
          <>
            <span className={styles.metaSep}>·</span>
            <span className={styles.modelWrap}>
              <button
                type="button"
                className={styles.modelChip}
                disabled={modelLocked}
                aria-expanded={modelMenuOpen}
                title={t("task.model.title")}
                onClick={() => {
                  setDraftProvider(isExplicit ? overrideProvider : "");
                  setDraftModel(overrideModel);
                  setModelMenuOpen((open) => !open);
                }}
              >
                {modelChipLabel}
                {!isExplicit && effectiveProvider && (
                  <span className={styles.modelAuto}>{t("task.model.auto")}</span>
                )}
              </button>
              {modelMenuOpen && (
                <div className={styles.modelMenu}>
                  <label className={styles.modelField}>
                    {t("create.provider")}
                    <select
                      className={styles.modelSelect}
                      value={draftProvider}
                      onChange={(event) => setDraftProvider(event.target.value)}
                    >
                      <option value="">{t("create.provider.auto")}</option>
                      {Object.keys(providers).map((name) => (
                        <option key={name} value={name}>
                          {name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className={styles.modelField}>
                    {t("create.model")}
                    <input
                      className={styles.modelInput}
                      value={draftModel}
                      placeholder={t("create.model.placeholder")}
                      onChange={(event) => setDraftModel(event.target.value)}
                    />
                  </label>
                  <div className={styles.modelActions}>
                    <button
                      type="button"
                      className={styles.secondary}
                      disabled={setModel.isPending}
                      onClick={() => setModel.mutate({ provider: "", model: "" })}
                    >
                      {t("task.model.reset")}
                    </button>
                    <button
                      type="button"
                      className={styles.primary}
                      disabled={setModel.isPending}
                      onClick={() =>
                        setModel.mutate({
                          provider: draftProvider,
                          model: draftModel.trim(),
                        })
                      }
                    >
                      {t("task.model.apply")}
                    </button>
                  </div>
                </div>
              )}
            </span>
          </>
        )}
        {asrStage && (
          <span className={styles.modelWrap}>
            <button
              type="button"
              className={styles.modelChip}
              disabled={modelLocked}
              aria-expanded={asrMenuOpen}
              title={t("task.asrEngine.title")}
              onClick={() => {
                setDraftAsrEngine(asrExplicit ? asrEngineParam : "");
                setAsrMenuOpen((open) => !open);
              }}
            >
              ASR · {asrChipLabel}
            </button>
            {asrMenuOpen && (
              <div className={styles.modelMenu}>
                <label className={styles.modelField}>
                  {t("create.asrEngine")}
                  <select
                    className={styles.modelSelect}
                    value={draftAsrEngine}
                    onChange={(event) => setDraftAsrEngine(event.target.value)}
                  >
                    <option value="">{t("create.asrEngine.auto")}</option>
                    {ASR_ENGINE_IDS.map((id) => (
                      <option key={id} value={id}>
                        {ASR_ENGINE_LABELS[id]}
                      </option>
                    ))}
                  </select>
                </label>
                <div className={styles.modelActions}>
                  <button
                    type="button"
                    className={styles.secondary}
                    disabled={setAsrEngine.isPending}
                    onClick={() => setAsrEngine.mutate("")}
                  >
                    {t("task.model.reset")}
                  </button>
                  <button
                    type="button"
                    className={styles.primary}
                    disabled={setAsrEngine.isPending}
                    onClick={() => setAsrEngine.mutate(draftAsrEngine)}
                  >
                    {t("task.model.apply")}
                  </button>
                </div>
              </div>
            )}
          </span>
        )}
        {ttsStage && (
          <span className={styles.modelWrap}>
            <button
              type="button"
              className={styles.modelChip}
              disabled={modelLocked}
              aria-expanded={voiceMenuOpen}
              title={t("task.voiceMode.title")}
              onClick={() => {
                setDraftVoiceMode(voiceModeParam);
                setDraftVoiceInstruction(voiceInstructionParam);
                setVoiceMenuOpen((open) => !open);
              }}
            >
              {voiceChipLabel}
            </button>
            {voiceMenuOpen && (
              <div className={styles.modelMenu}>
                <label className={styles.modelField}>
                  {t("create.voiceMode")}
                  <select
                    className={styles.modelSelect}
                    value={draftVoiceMode}
                    onChange={(event) => setDraftVoiceMode(event.target.value)}
                  >
                    <option value="">{t("create.voiceMode.clone")}</option>
                    <option value="design">{t("create.voiceMode.design")}</option>
                    <option value="preview">{t("create.voiceMode.preview")}</option>
                  </select>
                </label>
                {draftVoiceMode === "design" && (
                  <label className={styles.modelField}>
                    {t("create.voiceInstruction")}
                    <input
                      className={styles.modelInput}
                      value={draftVoiceInstruction}
                      placeholder={t("create.voiceInstruction.placeholder")}
                      onChange={(event) =>
                        setDraftVoiceInstruction(event.target.value)
                      }
                    />
                  </label>
                )}
                <div className={styles.modelActions}>
                  <button
                    type="button"
                    className={styles.secondary}
                    disabled={setVoiceMode.isPending}
                    onClick={() => setVoiceMode.mutate({ mode: "", instruction: "" })}
                  >
                    {t("task.model.reset")}
                  </button>
                  <button
                    type="button"
                    className={styles.primary}
                    disabled={setVoiceMode.isPending}
                    onClick={() =>
                      setVoiceMode.mutate({
                        mode: draftVoiceMode,
                        instruction:
                          draftVoiceMode === "design"
                            ? draftVoiceInstruction.trim()
                            : "",
                      })
                    }
                  >
                    {t("task.model.apply")}
                  </button>
                </div>
              </div>
            )}
          </span>
        )}
        {engineChips.map((chip) => (
          <span key={chip} className={styles.engineChip} title={t("task.engine.title")}>
            {chip}
          </span>
        ))}
        <span className={styles.metaSep}>·</span>
        <span>
          {t("task.meta.updated")} {formatDateTime(task.updated_at)}
        </span>
        <button
          type="button"
          className={styles.metaToggle}
          aria-expanded={showDetails}
          onClick={() => setShowDetails((open) => !open)}
        >
          {t("task.detail.more")}
          <span className={`${styles.metaChevron} ${showDetails ? styles.metaChevronOpen : ""}`}>
            <Icon name="chevron-down" size={13} />
          </span>
        </button>
      </div>
      {showDetails && (
        <dl className={styles.details}>
          <div className={styles.detailsRow}>
            <dt>{t("task.input")}</dt>
            <dd>{task.input_path}</dd>
          </div>
          <div className={styles.detailsRow}>
            <dt>ID</dt>
            <dd>{task.id}</dd>
          </div>
          <div className={styles.detailsRow}>
            <dt>{t("task.created")}</dt>
            <dd>{formatDateTime(task.created_at)}</dd>
          </div>
        </dl>
      )}

      {task.status === "paused" && (
        <section className={styles.noticePaused}>
          <div>
            <h2 className={styles.sectionTitle}>{t("task.paused.title")}</h2>
            <p className={styles.noticeHint}>{t("task.paused.hint")}</p>
          </div>
          {onOpenSettings && (
            <button type="button" className={styles.secondary} onClick={onOpenSettings}>
              {t("task.gotoSettings")}
            </button>
          )}
        </section>
      )}

      {task.status === "failed" && lastStageError && (
        <section className={styles.noticeFailed}>
          <h2 className={styles.sectionTitle}>{t("task.failed.title")}</h2>
          <StageError raw={lastStageError} defaultOpen />
        </section>
      )}

      {task.status === "waiting_review" && (
        <section className={styles.checkpoint}>
          <div>
            <h2 className={styles.sectionTitle}>{t("task.checkpoint.title")}</h2>
            <p className={styles.checkpointHint}>
              {isDubTask && hasSpeakers
                ? t("task.checkpoint.hint.speakers")
                : isDocumentTask
                  ? t("task.checkpoint.hint.document")
                  : t("task.checkpoint.hint")}
            </p>
          </div>
          <button
            type="button"
            className={styles.primary}
            onClick={() =>
              onOpenEditor(isDubTask && hasSpeakers ? "speakers" : editorKind)
            }
          >
            {isDubTask && hasSpeakers
              ? t("task.speakerReview")
              : isDocumentTask
                ? t("task.openTextEditor")
                : t("task.openSubtitleEditor")}
          </button>
        </section>
      )}

      {failedChecks && (
        <section className={styles.preflight}>
          <h2 className={styles.sectionTitle}>{t("preflight.failed")}</h2>
          <ul className={styles.checkList}>
            {failedChecks.map((check) => {
              const human = matchError(check.message);
              return (
                <li key={check.name}>
                  <strong>{check.name}</strong> {human ? human.summary : check.message}
                  {human?.hint && <p className={styles.checkHint}>{human.hint}</p>}
                </li>
              );
            })}
          </ul>
          {modelDownload && !modelDownload.error && (
            <p className={styles.modelProgress}>
              {t("preflight.downloadingModel")}（{modelDownload.mb.toFixed(0)} MB）
            </p>
          )}
          {modelDownload?.error && (
            <p className={styles.modelError}>{modelDownload.error}</p>
          )}
          <div className={styles.preflightActions}>
            <button
              type="button"
              className={styles.secondary}
              onClick={() => setFailedChecks(null)}
            >
              {t("preflight.dismiss")}
            </button>
            {missingModel && (
              <button
                type="button"
                className={styles.primary}
                disabled={!!modelDownload && !modelDownload.error}
                onClick={() => downloadModelAndRun(missingModel)}
              >
                {t("preflight.downloadModel")}
              </button>
            )}
            <button
              type="button"
              className={missingModel ? styles.secondary : styles.primary}
              onClick={() => run.mutate(true)}
            >
              {t("preflight.skipRun")}
            </button>
          </div>
        </section>
      )}

      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle}>{t("task.stages")}</h2>
          <span className={styles.stageCount}>
            {completed} / {task.stages.length}
          </span>
        </div>
        <ProgressBar value={completed} max={task.stages.length} />
        <ol className={styles.stages}>
          {task.stages.map((stage, index) => (
            <li key={`${stage.type}-${index}`} className={styles.stage} data-status={stage.status}>
              <span className={styles.stageDot} />
              <div className={styles.stageBody}>
                <div className={styles.stageHead}>
                  <span className={styles.stageType}>{stageLabels[index]}</span>
                  <span className={styles.stageStatus}>{stageStatusLabel(stage.status)}</span>
                </div>
                {index === runningIndex && live?.stageProgress && (
                  <ProgressBar value={live.stageProgress.current} max={live.stageProgress.total} />
                )}
                {stage.error && <StageError raw={stage.error} />}
              </div>
            </li>
          ))}
        </ol>
      </section>

      {outputs.length > 0 && (
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t("task.outputs")}</h2>
          <ul className={styles.outputs}>
            {outputs.map((item) => (
              <li key={item.file} className={styles.output}>
                <span className={styles.outputName}>{item.file}</span>
                <span className={styles.outputSize}>{formatSize(item.size)}</span>
                <button
                  type="button"
                  className={styles.outputButton}
                  onClick={() => void openArtifact(artifactPath(item.file))}
                >
                  {t("task.outputs.open")}
                </button>
                <button
                  type="button"
                  className={styles.outputButton}
                  onClick={() => void revealArtifact(artifactPath(item.file))}
                >
                  {t("task.outputs.reveal")}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("task.events")}</h2>
        {events.length === 0 ? (
          <p className={styles.eventsEmpty}>{t("task.eventsEmpty")}</p>
        ) : (
          <ul className={styles.events}>
            {events
              .slice(-50)
              .reverse()
              .map((event, index) => (
                <li
                  key={`${event.ts}-${index}`}
                  className={styles.event}
                  title={JSON.stringify(event.data)}
                >
                  <span className={styles.eventTs}>{formatDateTime(event.ts)}</span>
                  <span className={styles.eventData}>{summarizeEventData(event.data)}</span>
                  <span className={styles.eventType}>{eventTypeLabel(event.type)}</span>
                </li>
              ))}
          </ul>
        )}
      </section>
    </div>
  );
}
