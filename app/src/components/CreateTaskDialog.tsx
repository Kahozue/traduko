import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { t, type MessageKey } from "../i18n";
import { ApiError } from "../lib/api/client";
import type { ProfileInfo, TaskKind } from "../lib/api/types";
import { useApi } from "../lib/connection";
import { Icon, type IconName } from "./icons";
import styles from "./CreateTaskDialog.module.css";

// Task types the new-task picker offers as buttons, in display order. Each
// maps to the profiles the core classified under that kind; picking a type
// filters the profile list. A type with no profiles yet still shows, disabled.
const TASK_TYPES: { kind: TaskKind; label: MessageKey; icon: IconName }[] = [
  { kind: "video", label: "create.kind.video", icon: "list" },
  { kind: "document", label: "create.kind.document", icon: "pencil" },
  { kind: "comic", label: "create.kind.comic", icon: "monitor" },
];

// File-picker extensions per task type, matching what each kind's pipelines
// actually ingest; picking a comic/PDF file under the wrong type would only
// build a task that fails at ingest.
const KIND_EXTENSIONS: Record<TaskKind, string[]> = {
  video: [
    "srt", "vtt", "ass", "txt",
    "mp4", "mkv", "mov", "webm", "avi", "flv", "m4v",
    "mp3", "wav", "m4a", "aac", "flac", "ogg",
  ],
  document: ["txt", "md", "markdown", "epub", "html", "htm", "pdf"],
  comic: ["png", "jpg", "jpeg", "webp", "cbz", "zip"],
};

const KIND_FILTER_LABELS: Record<TaskKind, MessageKey> = {
  video: "create.fileFilter.video",
  document: "create.fileFilter.document",
  comic: "create.fileFilter.comic",
};

export function CreateTaskDialog({
  onClose,
  onCreated,
  initialPath,
}: {
  onClose: () => void;
  onCreated: (project: string, taskId: string) => void;
  initialPath?: string;
}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const dialogRef = useRef<HTMLDivElement>(null);
  const [inputPath, setInputPath] = useState(initialPath ?? "");
  const [name, setName] = useState("");
  const [project, setProject] = useState("default");
  const [kind, setKind] = useState<TaskKind | null>(null);
  const [profile, setProfile] = useState("");
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

  // Land on the first kind that has profiles once they load.
  useEffect(() => {
    if (kind !== null || !profiles || profiles.length === 0) return;
    const firstType = TASK_TYPES.find((type) => byKind.has(type.kind));
    if (firstType) setKind(firstType.kind);
  }, [profiles, byKind, kind]);

  const kindProfiles = kind ? (byKind.get(kind) ?? []) : [];
  const extension = inputPath.split(".").pop()?.toLowerCase() ?? "";

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
    if (!candidates.some((info) => info.name === profile)) {
      setProfile(candidates[0].name);
    }
  }, [kindProfiles, profile, kind, extension]);

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  function onDialogKeyDown(event: ReactKeyboardEvent) {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const nodes = dialogRef.current?.querySelectorAll<HTMLElement>(
      'button, input, select, [tabindex]:not([tabindex="-1"])',
    );
    if (!nodes || nodes.length === 0) return;
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  const create = useMutation({
    mutationFn: () =>
      api.createTask({
        input_path: inputPath,
        profile,
        project,
        name: name.trim() === "" ? undefined : name.trim(),
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
          {t("create.title")}
        </h2>

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
              onChange={(event) => setProfile(event.target.value)}
            >
              {kindProfiles.map((info) => (
                <option key={info.name} value={info.name}>
                  {info.name}
                </option>
              ))}
            </select>
          </label>
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
