import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { t } from "../i18n";
import { ApiError } from "../lib/api/client";
import { useApi } from "../lib/connection";
import styles from "./CreateTaskDialog.module.css";

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
  const [profile, setProfile] = useState("");
  const [project, setProject] = useState("default");
  const { data: profiles } = useQuery({ queryKey: ["profiles"], queryFn: () => api.profiles() });

  useEffect(() => {
    if (profiles && profiles.length > 0 && profile === "") setProfile(profiles[0]);
  }, [profiles, profile]);

  useEffect(() => {
    // Move focus into the dialog so Esc and Tab land here immediately.
    dialogRef.current?.focus();
  }, []);

  function onDialogKeyDown(event: ReactKeyboardEvent) {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    // Minimal focus trap: wrap Tab / Shift+Tab at the dialog's edges.
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
    const chosen = await open({
      multiple: false,
      filters: [
        {
          name: t("create.fileFilter"),
          // Subtitle inputs plus the common video/audio containers the AV
          // pipeline can extract audio from. Keeps users from picking a .png
          // and hitting an opaque ingest failure downstream.
          extensions: [
            "srt",
            "vtt",
            "ass",
            "txt",
            "mp4",
            "mkv",
            "mov",
            "webm",
            "avi",
            "flv",
            "m4v",
            "mp3",
            "wav",
            "m4a",
            "aac",
            "flac",
            "ogg",
          ],
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
        <label className={styles.label}>
          {t("create.input")}
          <div className={styles.pickRow}>
            <input className={styles.input} value={inputPath} readOnly placeholder="--" />
            <button type="button" className={styles.secondary} onClick={pickFile}>
              {t("create.pick")}
            </button>
          </div>
        </label>
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
          {t("create.profile")}
          <select
            className={styles.input}
            value={profile}
            onChange={(event) => setProfile(event.target.value)}
          >
            {(profiles ?? []).map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.label}>
          {t("create.project")}
          <input
            className={styles.input}
            value={project}
            onChange={(event) => setProject(event.target.value)}
          />
        </label>
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
