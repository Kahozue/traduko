import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { t, type MessageKey } from "../i18n";
import { useApi } from "../lib/connection";
import styles from "./TranslationSettingsView.module.css";

// Static key per mode: t() takes no interpolation, so dynamic text is a
// lookup rather than a built key.
const ASR_MODE_LABELS: Record<string, MessageKey> = {
  auto: "task.glossary.asrMode.auto",
  force: "task.glossary.asrMode.force",
  off: "task.glossary.asrMode.off",
};

// Task-level translation settings. The values start as copies of the domain
// defaults taken when the task was created; editing here only ever touches
// this task. Saving is the page's single primary action -- retranslate is a
// separate, deliberate step behind a confirmation.
export function TranslationSettingsView({
  project,
  taskId,
  onBack,
  onOpenGlossary,
}: {
  project: string;
  taskId: string;
  onBack: () => void;
  onOpenGlossary: () => void;
}) {
  const api = useApi();
  const queryClient = useQueryClient();

  const { data: task } = useQuery({
    queryKey: ["task", project, taskId],
    queryFn: () => api.showTask(project, taskId),
  });

  const { data: translation } = useQuery({
    queryKey: ["task-translation", project, taskId],
    queryFn: () => api.getTaskTranslation(project, taskId),
  });

  const [targetLanguage, setTargetLanguage] = useState("");
  const [style, setStyle] = useState("");
  const [promptOverride, setPromptOverride] = useState("");
  const [dirty, setDirty] = useState(false);
  const [confirmRetranslate, setConfirmRetranslate] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!translation) return;
    setTargetLanguage(translation.target_language);
    setStyle(translation.style);
    setPromptOverride(translation.prompt_override);
    setDirty(false);
  }, [translation]);

  const save = useMutation({
    mutationFn: () =>
      api.patchTaskTranslation(project, taskId, {
        target_language: targetLanguage,
        style,
        prompt_override: promptOverride,
      }),
    onSuccess: () => {
      setError(null);
      setDirty(false);
      void queryClient.invalidateQueries({
        queryKey: ["task-translation", project, taskId],
      });
      void queryClient.invalidateQueries({ queryKey: ["task", project, taskId] });
    },
    onError: (cause: Error) => setError(cause.message),
  });

  const retranslate = useMutation({
    mutationFn: () => api.retranslate(project, taskId),
    onSuccess: () => {
      setError(null);
      setConfirmRetranslate(false);
      void queryClient.invalidateQueries({ queryKey: ["task", project, taskId] });
      onBack();
    },
    onError: (cause: Error) => {
      setConfirmRetranslate(false);
      setError(cause.message);
    },
  });

  const glossary = task?.glossary;
  const tableCount =
    (glossary?.global_ids.length ?? 0) + (glossary?.use_task ? 1 : 0);
  const canSave = dirty && targetLanguage.trim().length > 0 && !save.isPending;

  return (
    <div>
      <button type="button" className={styles.back} onClick={onBack}>
        {t("task.translation.back")}
      </button>

      <header className={styles.header}>
        <h1 className={styles.title}>{t("task.translation.title")}</h1>
        <div className={styles.actions}>
          {dirty && <span className={styles.dirty}>{t("task.translation.dirty")}</span>}
          <button
            type="button"
            className={styles.secondary}
            disabled={retranslate.isPending}
            onClick={() => setConfirmRetranslate(true)}
          >
            {t("task.translation.retranslate")}
          </button>
          <button
            type="button"
            className={styles.primary}
            disabled={!canSave}
            onClick={() => save.mutate()}
          >
            {t("task.translation.save")}
          </button>
        </div>
      </header>

      {error && <p className={styles.error}>{error}</p>}

      <section className={styles.section}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="translation-language">
            {t("task.translation.targetLanguage")}
          </label>
          <input
            id="translation-language"
            className={styles.codeInput}
            value={targetLanguage}
            onChange={(event) => {
              setTargetLanguage(event.target.value);
              setDirty(true);
            }}
          />
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="translation-style">
            {t("task.translation.style")}
          </label>
          <p className={styles.desc}>{t("task.translation.styleDesc")}</p>
          <input
            id="translation-style"
            className={styles.textInput}
            value={style}
            onChange={(event) => {
              setStyle(event.target.value);
              setDirty(true);
            }}
          />
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="translation-prompt">
            {t("task.translation.promptOverride")}
          </label>
          <p className={styles.desc}>{t("task.translation.promptOverrideDesc")}</p>
          <textarea
            id="translation-prompt"
            className={styles.promptInput}
            rows={8}
            value={promptOverride}
            onChange={(event) => {
              setPromptOverride(event.target.value);
              setDirty(true);
            }}
          />
        </div>
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("task.translation.glossaryTitle")}</h2>
        <div className={styles.glossaryRow}>
          <span className={styles.glossarySummary}>
            {tableCount} {t("task.translation.glossaryTables")}
          </span>
          <span className={styles.glossarySummary}>
            {t("task.translation.glossaryAsrMode")}
            {": "}
            {t(ASR_MODE_LABELS[glossary?.asr_mode ?? "auto"])}
          </span>
          <button type="button" className={styles.link} onClick={onOpenGlossary}>
            {t("task.translation.glossaryLink")}
          </button>
        </div>
      </section>

      {confirmRetranslate && (
        <ConfirmDialog
          title={t("task.translation.confirmTitle")}
          body={t("task.translation.confirmBody")}
          confirmLabel={t("task.translation.confirmAction")}
          cancelLabel={t("task.translation.confirmCancel")}
          danger
          busy={retranslate.isPending}
          onConfirm={() => retranslate.mutate()}
          onCancel={() => setConfirmRetranslate(false)}
        />
      )}
    </div>
  );
}
