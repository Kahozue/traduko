import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { t, type MessageKey } from "../i18n";
import { ApiError } from "../lib/api/client";
import type { ProfileInfo, TaskKind } from "../lib/api/types";
import { useApi } from "../lib/connection";
import { trapTab } from "../lib/focus";
import { AUDIO_EXTENSIONS, VIDEO_EXTENSIONS } from "../lib/media";
import { Icon, type IconName } from "./icons";
import styles from "./CreateTaskDialog.module.css";

// Task types the new-task picker offers as buttons, in display order. Each
// maps to the profiles the core classified under that kind; picking a type
// filters the profile list. A type with no profiles yet still shows, disabled.
const TASK_TYPES: { kind: TaskKind; label: MessageKey; icon: IconName }[] = [
  { kind: "video", label: "create.kind.video", icon: "film" },
  { kind: "audio", label: "create.kind.audio", icon: "audio-lines" },
  { kind: "document", label: "create.kind.document", icon: "file-text" },
  { kind: "comic", label: "create.kind.comic", icon: "book-open" },
];

// File-picker extensions per task type, matching what each kind's pipelines
// actually ingest; picking a comic/PDF file under the wrong type would only
// build a task that fails at ingest. Media buckets compose from the shared
// lists in lib/media so the picker and the task player never drift apart.
const KIND_EXTENSIONS: Record<TaskKind, string[]> = {
  video: ["srt", "vtt", "ass", "txt", ...VIDEO_EXTENSIONS, ...AUDIO_EXTENSIONS],
  audio: [...AUDIO_EXTENSIONS],
  document: ["txt", "md", "markdown", "epub", "html", "htm", "pdf"],
  comic: ["png", "jpg", "jpeg", "webp", "cbz", "zip"],
};

const KIND_FILTER_LABELS: Record<TaskKind, MessageKey> = {
  video: "create.fileFilter.video",
  audio: "create.fileFilter.audio",
  document: "create.fileFilter.document",
  comic: "create.fileFilter.comic",
};

// Engine choices for the audio kind's per-task ASR override, mirroring the
// settings menu; ids match core asr/engines.py.
const ASR_ENGINE_OPTIONS: { id: string; label: MessageKey }[] = [
  { id: "faster_whisper", label: "settings.asr.engine.fasterWhisper" },
  { id: "macos_native", label: "settings.asr.engine.macos" },
  { id: "openai_whisper", label: "settings.asr.engine.openaiWhisper" },
  { id: "openai_gpt4o_diarize", label: "settings.asr.engine.gpt4oDiarize" },
  { id: "openai_gpt4o", label: "settings.asr.engine.gpt4o" },
  { id: "openai_gpt4o_mini", label: "settings.asr.engine.gpt4oMini" },
  { id: "cloud_custom", label: "settings.asr.engine.custom" },
];

export function CreateTaskDialog({
  onClose,
  onCreated,
  initialPath,
  initialKind = null,
}: {
  onClose: () => void;
  onCreated: (project: string, taskId: string) => void;
  initialPath?: string;
  // When opened from a left-rail domain view, the kind is fixed: the type
  // row is hidden, the title names the domain, and the file picker uses that
  // domain's extensions. Null (opened from "all tasks") keeps the picker.
  initialKind?: TaskKind | null;
}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const dialogRef = useRef<HTMLDivElement>(null);
  const [inputPath, setInputPath] = useState(initialPath ?? "");
  const [name, setName] = useState("");
  const [project, setProject] = useState("default");
  const [kind, setKind] = useState<TaskKind | null>(initialKind);
  const [profile, setProfile] = useState("");
  // A profile the user picked by hand stays put; only auto-picked defaults
  // may be re-derived when the global audio defaults load in.
  const [profilePinned, setProfilePinned] = useState(false);
  // Per-task LLM override; empty means "follow the configured default".
  const [providerSel, setProviderSel] = useState("");
  const [model, setModel] = useState("");
  // Per-task ASR engine override for the audio kind; empty follows defaults.
  const [asrEngine, setAsrEngine] = useState("");
  // Dubbing voice mode for dub profiles; empty means the clone default.
  const [voiceMode, setVoiceMode] = useState("");
  const [voiceInstruction, setVoiceInstruction] = useState("");
  const { data: profiles } = useQuery({
    queryKey: ["profiles-detailed"],
    queryFn: () => api.profilesDetailed(),
  });
  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: () => api.getConfig(),
  });
  const noProvider =
    config !== undefined && Object.keys(config.llm_providers ?? {}).length === 0;
  const providerNames = Object.keys(config?.llm_providers ?? {});
  // Placeholder mirrors what the core would resolve: the chosen provider's
  // default model, or the global default provider's when following defaults.
  const placeholderProvider = providerSel || config?.default_provider || "";
  const providerDefaultModel = String(
    (config?.llm_providers?.[placeholderProvider] as { model?: unknown } | undefined)
      ?.model ?? "",
  );

  // Which kinds actually have profiles, and the profiles under the chosen one.
  const byKind = useMemo(() => {
    const map = new Map<TaskKind, ProfileInfo[]>();
    for (const info of profiles ?? []) {
      const bucket = map.get(info.kind);
      if (bucket) bucket.push(info);
      else map.set(info.kind, [info]);
    }
    return map;
  }, [profiles]);

  // Land on the first kind that has profiles once they load. Skipped when the
  // kind is fixed by the caller (domain view), so it stays put.
  useEffect(() => {
    if (initialKind !== null) return;
    if (kind !== null || !profiles || profiles.length === 0) return;
    const firstType = TASK_TYPES.find((type) => byKind.has(type.kind));
    if (firstType) setKind(firstType.kind);
  }, [profiles, byKind, kind, initialKind]);

  const kindProfiles = kind ? (byKind.get(kind) ?? []) : [];
  const extension = inputPath.split(".").pop()?.toLowerCase() ?? "";
  // Dub pipelines get the voice-mode picker. The optional chain also covers
  // a core older than the stages field.
  const isDubProfile =
    kindProfiles
      .find((info) => info.name === profile)
      ?.stages?.includes("tts_synthesize") ?? false;

  // The audio global default steers the default profile toward or away from
  // the dub pipelines; the user can still pick any profile by hand.
  const audioDubDefault = config?.audio?.dub_enabled === true;

  // Keep the selected profile valid for the chosen kind, and route by input
  // extension where the pipelines differ: a .pdf only runs through
  // translate-pdf, everything else in the document kind does not.
  useEffect(() => {
    if (kindProfiles.length === 0) {
      if (profile !== "") setProfile("");
      return;
    }
    const isPdfProfile = (name: string) => name.includes("pdf");
    let candidates = kindProfiles;
    if (kind === "document" && extension !== "") {
      const matching = kindProfiles.filter(
        (info) => isPdfProfile(info.name) === (extension === "pdf"),
      );
      if (matching.length > 0) candidates = matching;
    }
    const valid = candidates.some((info) => info.name === profile);
    if (valid && (profilePinned || kind !== "audio")) return;
    // Default pick: the audio kind prefers profiles matching the global dub
    // default; a hand-picked profile never reaches this branch.
    let pick = candidates;
    if (kind === "audio") {
      const preferred = candidates.filter(
        (info) =>
          (info.stages?.includes("tts_synthesize") ?? false) === audioDubDefault,
      );
      if (preferred.length > 0) pick = preferred;
    }
    if (!pick.some((info) => info.name === profile)) {
      setProfile(pick[0].name);
    }
  }, [kindProfiles, profile, kind, extension, audioDubDefault, profilePinned]);

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  function onDialogKeyDown(event: ReactKeyboardEvent) {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    trapTab(event, dialogRef.current);
  }

  const create = useMutation({
    mutationFn: () =>
      api.createTask({
        input_path: inputPath,
        profile,
        project,
        name: name.trim() === "" ? undefined : name.trim(),
        ...(providerSel !== "" ? { provider: providerSel } : {}),
        ...(model.trim() !== "" ? { model: model.trim() } : {}),
        ...(kind === "audio" && asrEngine !== "" ? { asr_engine: asrEngine } : {}),
        ...(isDubProfile && voiceMode !== "" ? { voice_mode: voiceMode } : {}),
        ...(isDubProfile && voiceMode === "design" && voiceInstruction.trim() !== ""
          ? { voice_instruction: voiceInstruction.trim() }
          : {}),
      }),
    onSuccess: (task) => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      onCreated(task.project, task.id);
    },
  });

  async function pickFile(): Promise<void> {
    const extensions = kind ? KIND_EXTENSIONS[kind] : Object.values(KIND_EXTENSIONS).flat();
    const chosen = await open({
      multiple: false,
      filters: [
        {
          name: t(kind ? KIND_FILTER_LABELS[kind] : "create.fileFilter.any"),
          extensions,
        },
      ],
    });
    if (typeof chosen === "string") setInputPath(chosen);
  }

  const errorText =
    create.error instanceof ApiError
      ? String(create.error.detail)
      : create.error
        ? String(create.error)
        : null;

  return (
    <div className={styles.overlay}>
      <div
        ref={dialogRef}
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-task-title"
        tabIndex={-1}
        onKeyDown={onDialogKeyDown}
      >
        <h2 id="create-task-title" className={styles.title}>
          {t(initialKind ? (`create.title.${initialKind}` as MessageKey) : "create.title")}
        </h2>

        {!initialKind && (
          <>
            <span className={styles.label}>{t("create.kind")}</span>
            <div className={styles.kindRow} role="group" aria-label={t("create.kind")}>
              {TASK_TYPES.map((type) => {
                const available = byKind.has(type.kind);
                return (
                  <button
                    key={type.kind}
                    type="button"
                    className={type.kind === kind ? styles.kindButtonActive : styles.kindButton}
                    aria-pressed={type.kind === kind}
                    disabled={!available}
                    onClick={() => setKind(type.kind)}
                  >
                    <Icon name={type.icon} size={20} />
                    <span>{t(type.label)}</span>
                  </button>
                );
              })}
            </div>
          </>
        )}

        <label className={styles.label}>
          {t("create.input")}
          <div className={styles.pickRow}>
            <input className={styles.input} value={inputPath} readOnly placeholder="--" />
            <button type="button" className={styles.secondary} onClick={pickFile}>
              {t("create.pick")}
            </button>
          </div>
        </label>

        {kindProfiles.length > 0 && (
          <label className={styles.label}>
            {t("create.profile")}
            <select
              className={styles.input}
              value={profile}
              onChange={(event) => {
                setProfile(event.target.value);
                setProfilePinned(true);
              }}
            >
              {kindProfiles.map((info) => (
                <option key={info.name} value={info.name}>
                  {info.name}
                </option>
              ))}
            </select>
          </label>
        )}

        {kind === "audio" && (
          <label className={styles.label}>
            {t("create.asrEngine")}
            <select
              className={styles.input}
              value={asrEngine}
              onChange={(event) => setAsrEngine(event.target.value)}
            >
              <option value="">{t("create.asrEngine.auto")}</option>
              {ASR_ENGINE_OPTIONS.map((option) => (
                <option key={option.id} value={option.id}>
                  {t(option.label)}
                </option>
              ))}
            </select>
          </label>
        )}

        {isDubProfile && (
          <>
            <label className={styles.label}>
              {t("create.voiceMode")}
              <select
                className={styles.input}
                value={voiceMode}
                onChange={(event) => setVoiceMode(event.target.value)}
              >
                <option value="">{t("create.voiceMode.clone")}</option>
                <option value="design">{t("create.voiceMode.design")}</option>
                <option value="preview">{t("create.voiceMode.preview")}</option>
              </select>
            </label>
            {voiceMode === "design" && (
              <label className={styles.label}>
                {t("create.voiceInstruction")}
                <input
                  className={styles.input}
                  value={voiceInstruction}
                  placeholder={t("create.voiceInstruction.placeholder")}
                  onChange={(event) => setVoiceInstruction(event.target.value)}
                />
              </label>
            )}
            {voiceMode === "preview" && (
              <p className={styles.hint}>{t("create.voiceMode.previewNote")}</p>
            )}
          </>
        )}

        {providerNames.length > 0 && (
          <div className={styles.pairRow}>
            <label className={styles.label}>
              {t("create.provider")}
              <select
                className={styles.input}
                value={providerSel}
                onChange={(event) => setProviderSel(event.target.value)}
              >
                <option value="">{t("create.provider.auto")}</option>
                {providerNames.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label className={styles.label}>
              {t("create.model")}
              <input
                className={styles.input}
                value={model}
                placeholder={providerDefaultModel || t("create.model.placeholder")}
                onChange={(event) => setModel(event.target.value)}
              />
            </label>
          </div>
        )}

        <label className={styles.label}>
          {t("create.name")}
          <input
            className={styles.input}
            value={name}
            placeholder={t("create.namePlaceholder")}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className={styles.label}>
          {t("create.project")}
          <input
            className={styles.input}
            value={project}
            onChange={(event) => setProject(event.target.value)}
          />
        </label>
        {noProvider && <p className={styles.warning}>{t("create.noProvider")}</p>}
        {errorText && (
          <p className={styles.error}>
            {t("create.error")}: {errorText}
          </p>
        )}
        <div className={styles.footer}>
          <button type="button" className={styles.secondary} onClick={onClose}>
            {t("create.cancel")}
          </button>
          <button
            type="button"
            className={styles.primary}
            disabled={inputPath === "" || profile === "" || create.isPending}
            onClick={() => create.mutate()}
          >
            {t("create.submit")}
          </button>
        </div>
      </div>
    </div>
  );
}
