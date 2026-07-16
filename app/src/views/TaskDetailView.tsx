import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ProgressBar } from "../components/ProgressBar";
import { StatusBadge } from "../components/StatusBadge";
import { t } from "../i18n";
import { ApiError } from "../lib/api/client";
import type { PreflightCheck } from "../lib/api/types";
import { useApi } from "../lib/connection";
import { useTaskLive } from "../lib/events/store";
import { stageStatusLabel, stageTypeLabel } from "../lib/labels";
import styles from "./TaskDetailView.module.css";

const RUNNABLE = new Set(["pending", "paused", "waiting_review", "failed"]);
const CANCELABLE = new Set(["pending", "running", "waiting_review", "paused"]);

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function TaskDetailView({
  project,
  taskId,
  onBack,
  onOpenSubtitleEditor,
  onOpenStyleEditor,
}: {
  project: string;
  taskId: string;
  onBack: () => void;
  onOpenSubtitleEditor: () => void;
  onOpenStyleEditor: () => void;
}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const live = useTaskLive(project, taskId);
  const [failedChecks, setFailedChecks] = useState<PreflightCheck[] | null>(null);
  const { data: task } = useQuery({
    queryKey: ["task", project, taskId],
    queryFn: () => api.showTask(project, taskId),
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

  const [editingName, setEditingName] = useState(false);
  const [draftName, setDraftName] = useState("");

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
  const events = live?.events ?? [];

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
                className={styles.nameInput}
                value={draftName}
                onChange={(e) => setDraftName(e.target.value)}
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
                onClick={() => {
                  setDraftName(task.name ?? task.id);
                  setEditingName(true);
                }}
              >
                {t("task.rename")}
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
            className={styles.danger}
            disabled={!CANCELABLE.has(task.status) || cancel.isPending}
            onClick={() => cancel.mutate()}
          >
            {t("task.cancel")}
          </button>
          <button type="button" className={styles.secondary} onClick={onOpenStyleEditor}>
            {t("task.openStyleEditor")}
          </button>
        </div>
      </header>

      {task.status === "waiting_review" && (
        <section className={styles.checkpoint}>
          <div>
            <h2 className={styles.sectionTitle}>{t("task.checkpoint.title")}</h2>
            <p className={styles.checkpointHint}>{t("task.checkpoint.hint")}</p>
          </div>
          <button type="button" className={styles.primary} onClick={onOpenSubtitleEditor}>
            {t("task.openSubtitleEditor")}
          </button>
        </section>
      )}

      {failedChecks && (
        <section className={styles.preflight}>
          <h2 className={styles.sectionTitle}>{t("preflight.failed")}</h2>
          <ul className={styles.checkList}>
            {failedChecks.map((check) => (
              <li key={check.name}>
                <strong>{check.name}</strong> {check.message}
              </li>
            ))}
          </ul>
          <div className={styles.preflightActions}>
            <button
              type="button"
              className={styles.secondary}
              onClick={() => setFailedChecks(null)}
            >
              {t("preflight.dismiss")}
            </button>
            <button type="button" className={styles.primary} onClick={() => run.mutate(true)}>
              {t("preflight.skipRun")}
            </button>
          </div>
        </section>
      )}

      <section className={styles.card}>
        <dl className={styles.meta}>
          <div>
            <dt>ID</dt>
            <dd className={styles.mono}>{task.id}</dd>
          </div>
          <div>
            <dt>{t("task.input")}</dt>
            <dd className={styles.mono}>{task.input_path}</dd>
          </div>
          <div>
            <dt>{t("task.profile")}</dt>
            <dd>{task.profile}</dd>
          </div>
          <div>
            <dt>{t("task.created")}</dt>
            <dd>{formatTime(task.created_at)}</dd>
          </div>
          <div>
            <dt>{t("task.updated")}</dt>
            <dd>{formatTime(task.updated_at)}</dd>
          </div>
        </dl>
        <ProgressBar value={completed} max={task.stages.length} label={t("task.progress")} />
      </section>

      <section className={styles.card}>
        <h2 className={styles.sectionTitle}>{t("task.stages")}</h2>
        <ol className={styles.stages}>
          {task.stages.map((stage, index) => (
            <li key={`${stage.type}-${index}`} className={styles.stage} data-status={stage.status}>
              <span className={styles.stageDot} />
              <div className={styles.stageBody}>
                <div className={styles.stageHead}>
                  <span className={styles.stageType}>{stageTypeLabel(stage.type)}</span>
                  <span className={styles.stageStatus}>{stageStatusLabel(stage.status)}</span>
                </div>
                {index === runningIndex && live?.stageProgress && (
                  <ProgressBar value={live.stageProgress.current} max={live.stageProgress.total} />
                )}
                {stage.error && <p className={styles.stageError}>{stage.error}</p>}
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className={styles.card}>
        <h2 className={styles.sectionTitle}>{t("task.events")}</h2>
        {events.length === 0 ? (
          <p className={styles.eventsEmpty}>{t("task.eventsEmpty")}</p>
        ) : (
          <ul className={styles.events}>
            {events
              .slice(-50)
              .reverse()
              .map((event, index) => (
                <li key={`${event.ts}-${index}`} className={styles.event}>
                  <span className={styles.eventTs}>{event.ts}</span>
                  <span className={styles.eventType}>{event.type}</span>
                  <span className={styles.eventData}>{JSON.stringify(event.data)}</span>
                </li>
              ))}
          </ul>
        )}
      </section>
    </div>
  );
}
