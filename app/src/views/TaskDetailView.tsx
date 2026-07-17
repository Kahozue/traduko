import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Icon } from "../components/icons";
import { ProgressBar } from "../components/ProgressBar";
import { StatusBadge } from "../components/StatusBadge";
import { t } from "../i18n";
import { ApiError } from "../lib/api/client";
import type { PreflightCheck } from "../lib/api/types";
import { useApi } from "../lib/connection";
import { humanizeError } from "../lib/errors";
import { useTaskLive } from "../lib/events/store";
import { eventTypeLabel, stageStatusLabel, stageTypeLabel } from "../lib/labels";
import styles from "./TaskDetailView.module.css";

const RUNNABLE = new Set(["pending", "paused", "waiting_review", "failed"]);
const CANCELABLE = new Set(["pending", "running", "waiting_review", "paused"]);
const PAUSABLE = new Set(["running"]);

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString();
}

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

function StageError({ raw }: { raw: string }) {
  const human = humanizeError(raw);
  return (
    <div className={styles.stageError}>
      <p className={styles.stageErrorSummary}>{human.summary}</p>
      {human.hint && <p className={styles.stageErrorHint}>{human.hint}</p>}
      <details className={styles.rawError}>
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
  onOpenSubtitleEditor,
  onOpenStyleEditor,
}: {
  project: string;
  taskId: string;
  onBack: () => void;
  onOpenSettings?: () => void;
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
  const { data: pastEvents } = useQuery({
    queryKey: ["task-events", project, taskId],
    queryFn: () => api.taskEvents(project, taskId),
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
          <button type="button" className={styles.secondary} onClick={onOpenStyleEditor}>
            {t("task.openStyleEditor")}
          </button>
        </div>
      </header>

      <p className={styles.metaLine}>
        <span>{task.profile}</span>
        <span className={styles.metaSep}>·</span>
        <span>
          {t("task.meta.created")} {formatTime(task.created_at)}
        </span>
        <span className={styles.metaSep}>·</span>
        <span>
          {t("task.meta.updated")} {formatTime(task.updated_at)}
        </span>
      </p>
      <p className={styles.metaMono}>
        <span>{task.input_path}</span>
        <span className={styles.metaSep}>·</span>
        <span>{task.id}</span>
      </p>

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
          <StageError raw={lastStageError} />
        </section>
      )}

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
                  <span className={styles.stageType}>{stageTypeLabel(stage.type)}</span>
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
                  <span className={styles.eventTs}>{formatTime(event.ts)}</span>
                  <span className={styles.eventType}>{eventTypeLabel(event.type)}</span>
                  <span className={styles.eventData}>{summarizeEventData(event.data)}</span>
                </li>
              ))}
          </ul>
        )}
      </section>
    </div>
  );
}
