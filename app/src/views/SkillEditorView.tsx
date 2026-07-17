import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { t } from "../i18n";
import { ApiError } from "../lib/api/client";
import { useApi } from "../lib/connection";
import styles from "./SkillEditorView.module.css";

// Full-screen SKILL.md editor, drilled into from the settings agent tab
// (the design language keeps content editing out of the settings page).
// Follows the document editor's shape: back with unsaved-changes guard,
// dirty/saved markers, explicit save.
export function SkillEditorView({
  skill,
  onBack,
}: {
  skill: string;
  onBack: () => void;
}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["skill", skill],
    queryFn: () => api.getSkill(skill),
  });

  const [content, setContent] = useState("");
  const [loadedFrom, setLoadedFrom] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [confirmLeave, setConfirmLeave] = useState(false);

  useEffect(() => {
    if (data && data.content !== loadedFrom) {
      // A refetch only replaces the buffer while it is clean; it must not
      // clobber in-progress edits.
      if (!dirty) setContent(data.content);
      setLoadedFrom(data.content);
    }
  }, [data, loadedFrom, dirty]);

  const save = useMutation({
    mutationFn: () => api.putSkill(skill, content),
    onSuccess: (result) => {
      setDirty(false);
      setSaved(true);
      setLoadedFrom(content);
      // Keep the cached copy in step so reopening the editor or the
      // confirmation card shows what was just saved; the list may have a
      // new description or validity.
      queryClient.setQueryData(["skill", skill], { name: skill, content });
      void queryClient.invalidateQueries({ queryKey: ["skills"] });
      if (result.confirmation_reset) {
        // The core dropped this skill's confirmed flag; forget the cached
        // config so the settings view rebuilds its draft from fresh data.
        queryClient.removeQueries({ queryKey: ["config"] });
      }
    },
  });

  const saveRef = useRef({ dirty, pending: save.isPending, mutate: () => save.mutate() });
  saveRef.current = { dirty, pending: save.isPending, mutate: () => save.mutate() };

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        const { dirty: isDirty, pending, mutate } = saveRef.current;
        if (isDirty && !pending) mutate();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function edit(value: string) {
    setContent(value);
    setDirty(true);
    setSaved(false);
  }

  function handleBack() {
    if (dirty) setConfirmLeave(true);
    else onBack();
  }

  const validationErrors =
    save.error instanceof ApiError &&
    save.error.status === 422 &&
    Array.isArray(save.error.detail)
      ? (save.error.detail as string[])
      : null;

  return (
    <div>
      <button type="button" className={styles.back} onClick={handleBack}>
        {t("editor.skill.back")}
      </button>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>{t("editor.skill.title")}</h1>
          <p className={styles.name}>{skill}</p>
        </div>
        <div className={styles.actions}>
          {dirty && <span className={styles.dirty}>{t("editor.skill.dirty")}</span>}
          {saved && <span className={styles.saved}>{t("editor.skill.saved")}</span>}
          <button
            type="button"
            className={styles.primary}
            disabled={!dirty || save.isPending}
            onClick={() => save.mutate()}
          >
            {t("editor.skill.save")}
          </button>
        </div>
      </header>

      {save.isError && (
        <div className={styles.errorBox}>
          {validationErrors ? (
            <>
              <p className={styles.errorTitle}>{t("editor.skill.invalid")}</p>
              <ul className={styles.errorList}>
                {validationErrors.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </>
          ) : (
            <p className={styles.errorTitle}>{t("editor.skill.saveFailed")}</p>
          )}
        </div>
      )}

      {isLoading ? (
        <p className={styles.state}>{t("editor.loading")}</p>
      ) : isError ? (
        <p className={styles.state}>{t("editor.skill.loadFailed")}</p>
      ) : (
        <textarea
          className={styles.editor}
          aria-label={t("editor.skill.title")}
          spellCheck={false}
          value={content}
          onChange={(event) => edit(event.target.value)}
        />
      )}

      {confirmLeave && (
        <div className={styles.scrim}>
          <div
            role="dialog"
            aria-modal="true"
            aria-label={t("editor.skill.leaveTitle")}
            className={styles.confirm}
            onKeyDown={(e) => {
              if (e.key === "Escape") setConfirmLeave(false);
            }}
          >
            <p className={styles.confirmMessage}>{t("editor.skill.leaveMessage")}</p>
            <div className={styles.confirmActions}>
              <button
                type="button"
                autoFocus
                className={styles.toolButton}
                onClick={() => setConfirmLeave(false)}
              >
                {t("editor.leave.stay")}
              </button>
              <button
                type="button"
                className={styles.discard}
                onClick={() => {
                  setConfirmLeave(false);
                  onBack();
                }}
              >
                {t("editor.leave.discard")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
