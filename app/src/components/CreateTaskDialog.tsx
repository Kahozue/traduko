import { useEffect, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { t } from "../i18n";
import { ApiError } from "../lib/api/client";
import { useApi } from "../lib/connection";
import styles from "./CreateTaskDialog.module.css";

export function CreateTaskDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (project: string, taskId: string) => void;
}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [inputPath, setInputPath] = useState("");
  const [name, setName] = useState("");
  const [profile, setProfile] = useState("");
  const [project, setProject] = useState("default");
  const { data: profiles } = useQuery({ queryKey: ["profiles"], queryFn: () => api.profiles() });

  useEffect(() => {
    if (profiles && profiles.length > 0 && profile === "") setProfile(profiles[0]);
  }, [profiles, profile]);

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
      <div className={styles.dialog}>
        <h2 className={styles.title}>{t("create.title")}</h2>
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
