import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { t, type MessageKey } from "../i18n";
import { ApiError } from "../lib/api/client";
import { useApi } from "../lib/connection";
import { AUDIO_EXTENSIONS, VIDEO_EXTENSIONS } from "../lib/media";
import styles from "./ComposeDialog.module.css";

// Sibling of CreateTaskDialog rather than a branch of it: a compose task
// takes a transcript as a stage parameter and the media as the task input,
// which inverts what every other new-task flow does.

type ComposeKind = "video" | "audio";

// What ingest_transcript can parse, mirroring core subtitles._PARSERS.
const TRANSCRIPT_EXTENSIONS = ["srt", "vtt", "ass", "txt"];

const PROFILE_OF: Record<ComposeKind, string> = {
  video: "video-compose",
  audio: "audio-compose",
};

const TITLE_OF: Record<ComposeKind, MessageKey> = {
  video: "compose.title.video",
  audio: "compose.title.audio",
};

function isTranscriptArtifact(file: string): boolean {
  const ext = file.split(".").pop()?.toLowerCase() ?? "";
  return TRANSCRIPT_EXTENSIONS.includes(ext);
}

export function ComposeDialog({
  kind,
  onClose,
  onCreated,
}: {
  kind: ComposeKind;
  onClose: () => void;
  onCreated: (project: string, taskId: string) => void;
}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const dialogRef = useRef<HTMLDivElement>(null);
  const [videoPath, setVideoPath] = useState("");
  const [baseAudio, setBaseAudio] = useState("");
  const [source, setSource] = useState<"file" | "task">("file");
  const [transcriptPath, setTranscriptPath] = useState("");
  const [sourceTask, setSourceTask] = useState("");
  const [sourceArtifact, setSourceArtifact] = useState("");
  const [name, setName] = useState("");
  const [project, setProject] = useState("default");

  const { data: tasks } = useQuery({
    queryKey: ["tasks"],
    queryFn: () => api.listTasks(),
    enabled: source === "task",
  });
  const taskRows = tasks ?? [];
  const selectedTask = taskRows.find((row) => `${row.project}/${row.id}` === sourceTask);
  const { data: artifacts } = useQuery({
    queryKey: ["artifacts", selectedTask?.project, selectedTask?.id],
    queryFn: () => api.listArtifacts(selectedTask!.project, selectedTask!.id),
    enabled: selectedTask !== undefined,
  });
  const transcriptArtifacts = useMemo(
    () => (artifacts ?? []).filter((item) => isTranscriptArtifact(item.file)),
    [artifacts],
  );

  // Land on the first task once the list arrives, so the artifact select has
  // something to populate from without a second click.
  useEffect(() => {
    if (source !== "task" || sourceTask !== "" || taskRows.length === 0) return;
    setSourceTask(`${taskRows[0].project}/${taskRows[0].id}`);
  }, [source, sourceTask, taskRows]);

  useEffect(() => {
    if (transcriptArtifacts.length === 0) {
      if (sourceArtifact !== "") setSourceArtifact("");
      return;
    }
    if (!transcriptArtifacts.some((item) => item.file === sourceArtifact)) {
      setSourceArtifact(transcriptArtifacts[0].file);
    }
  }, [transcriptArtifacts, sourceArtifact]);

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  function onDialogKeyDown(event: ReactKeyboardEvent) {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
    }
  }

  async function pick(
    setter: (value: string) => void,
    extensions: string[],
    label: MessageKey,
  ): Promise<void> {
    const chosen = await open({
      multiple: false,
      filters: [{ name: t(label), extensions }],
    });
    if (typeof chosen === "string") setter(chosen);
  }

  const transcriptReady =
    source === "file" ? transcriptPath !== "" : sourceArtifact !== "" && selectedTask !== undefined;
  const ready = transcriptReady && (kind === "video" ? videoPath !== "" : true);

  const create = useMutation({
    mutationFn: () =>
      api.createTask({
        profile: PROFILE_OF[kind],
        project,
        // An audio compose task sends no input: the server resolves the
        // transcript, which the app only knows by name when it comes from
        // another task's artifacts.
        ...(kind === "video" ? { input_path: videoPath } : {}),
        ...(name.trim() !== "" ? { name: name.trim() } : {}),
        ...(kind === "video" && baseAudio !== "" ? { base_audio: baseAudio } : {}),
        transcript:
          source === "file"
            ? { kind: "file", path: transcriptPath }
            : {
                kind: "task",
                project: selectedTask!.project,
                task_id: selectedTask!.id,
                file: sourceArtifact,
              },
      }),
    onSuccess: (task) => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      onCreated(task.project, task.id);
    },
  });

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
        aria-labelledby="compose-title"
        tabIndex={-1}
        onKeyDown={onDialogKeyDown}
      >
        <h2 id="compose-title" className={styles.title}>
          {t(TITLE_OF[kind])}
        </h2>

        {kind === "video" && (
          <label className={styles.label}>
            {t("compose.video")}
            <div className={styles.pickRow}>
              <input className={styles.input} value={videoPath} readOnly placeholder="--" />
              <button
                type="button"
                className={styles.secondary}
                onClick={() => pick(setVideoPath, VIDEO_EXTENSIONS, "compose.video")}
              >
                {t("compose.pickVideo")}
              </button>
            </div>
          </label>
        )}

        <span className={styles.label}>{t("compose.source")}</span>
        <div className={styles.sourceRow} role="group" aria-label={t("compose.source")}>
          {(["file", "task"] as const).map((value) => (
            <button
              key={value}
              type="button"
              className={source === value ? styles.sourceButtonActive : styles.sourceButton}
              aria-pressed={source === value}
              onClick={() => setSource(value)}
            >
              {t(`compose.source.${value}` as MessageKey)}
            </button>
          ))}
        </div>

        {source === "file" ? (
          <label className={styles.label}>
            {t("compose.transcript")}
            <div className={styles.pickRow}>
              <input
                className={styles.input}
                value={transcriptPath}
                readOnly
                placeholder="--"
              />
              <button
                type="button"
                className={styles.secondary}
                onClick={() =>
                  pick(setTranscriptPath, TRANSCRIPT_EXTENSIONS, "compose.transcript")
                }
              >
                {t("compose.pickTranscript")}
              </button>
            </div>
          </label>
        ) : (
          <>
            <label className={styles.label}>
              {t("compose.sourceTask")}
              <select
                className={styles.input}
                value={sourceTask}
                disabled={taskRows.length === 0}
                onChange={(event) => setSourceTask(event.target.value)}
              >
                {taskRows.map((row) => (
                  <option key={`${row.project}/${row.id}`} value={`${row.project}/${row.id}`}>
                    {row.name}
                  </option>
                ))}
              </select>
            </label>
            <label className={styles.label}>
              {t("compose.sourceArtifact")}
              <select
                className={styles.input}
                value={sourceArtifact}
                disabled={transcriptArtifacts.length === 0}
                onChange={(event) => setSourceArtifact(event.target.value)}
              >
                {transcriptArtifacts.map((item) => (
                  <option key={item.file} value={item.file}>
                    {item.file}
                  </option>
                ))}
              </select>
            </label>
            {taskRows.length === 0 && (
              <p className={styles.hint}>{t("compose.sourceTask.empty")}</p>
            )}
            {selectedTask !== undefined && transcriptArtifacts.length === 0 && (
              <p className={styles.hint}>{t("compose.sourceArtifact.empty")}</p>
            )}
          </>
        )}

        {kind === "video" && (
          <label className={styles.label}>
            {t("compose.baseAudio")}
            <div className={styles.pickRow}>
              <input className={styles.input} value={baseAudio} readOnly placeholder="--" />
              <button
                type="button"
                className={styles.secondary}
                onClick={() => pick(setBaseAudio, AUDIO_EXTENSIONS, "compose.baseAudio")}
              >
                {t("compose.pickAudio")}
              </button>
            </div>
            <p className={styles.hint}>{t("compose.baseAudio.hint")}</p>
          </label>
        )}

        <label className={styles.label}>
          {t("compose.name")}
          <input
            className={styles.input}
            value={name}
            placeholder={t("compose.namePlaceholder")}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className={styles.label}>
          {t("compose.project")}
          <input
            className={styles.input}
            value={project}
            onChange={(event) => setProject(event.target.value)}
          />
        </label>

        <p className={styles.hint}>{t("compose.note.audio")}</p>
        {errorText && (
          <p className={styles.error}>
            {t("compose.error")}: {errorText}
          </p>
        )}
        <div className={styles.footer}>
          <button type="button" className={styles.secondary} onClick={onClose}>
            {t("compose.cancel")}
          </button>
          <button
            type="button"
            className={styles.primary}
            disabled={!ready || create.isPending}
            onClick={() => create.mutate()}
          >
            {t("compose.submit")}
          </button>
        </div>
      </div>
    </div>
  );
}
