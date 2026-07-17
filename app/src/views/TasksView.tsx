import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CreateTaskDialog } from "../components/CreateTaskDialog";
import { StatusBadge } from "../components/StatusBadge";
import { t } from "../i18n";
import { useApi } from "../lib/connection";
import type { TaskStatus } from "../lib/api/types";
import styles from "./TasksView.module.css";

const STATUS_OPTIONS: TaskStatus[] = [
  "pending",
  "running",
  "waiting_review",
  "paused",
  "completed",
  "failed",
  "canceled",
];

const STATUS_LABEL: Record<TaskStatus, string> = {
  pending: t("status.pending"),
  running: t("status.running"),
  waiting_review: t("status.waiting_review"),
  paused: t("status.paused"),
  completed: t("status.completed"),
  failed: t("status.failed"),
  canceled: t("status.canceled"),
};

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString();
}

// The empty state is the sanctioned home of the verda-stelo mark.
function EmptyGuide({ onOpenSettings }: { onOpenSettings?: () => void }) {
  return (
    <div className={styles.emptyGuide}>
      <svg
        className={styles.emptyStar}
        viewBox="0 0 24 24"
        width="40"
        height="40"
        aria-hidden="true"
      >
        <path
          fill="currentColor"
          d="M12 2.5l2.6 6.05 6.56.56-4.98 4.32 1.5 6.41L12 16.43l-5.68 3.41 1.5-6.41-4.98-4.32 6.56-.56z"
        />
      </svg>
      <p className={styles.emptyTitle}>{t("tasks.emptyTitle")}</p>
      <ol className={styles.emptySteps}>
        <li>{t("tasks.emptyStep1")}</li>
        <li>{t("tasks.emptyStep2")}</li>
      </ol>
      {onOpenSettings && (
        <button type="button" className={styles.emptyAction} onClick={onOpenSettings}>
          {t("tasks.emptyAction")}
        </button>
      )}
    </div>
  );
}

export function TasksView({
  onOpenTask,
  onOpenSettings,
  createSignal = 0,
  droppedPath = null,
  onConsumeDrop,
}: {
  onOpenTask: (project: string, taskId: string) => void;
  onOpenSettings?: () => void;
  createSignal?: number;
  droppedPath?: string | null;
  onConsumeDrop?: () => void;
}) {
  const api = useApi();
  const [statusFilter, setStatusFilter] = useState("");
  const [creating, setCreating] = useState(false);
  const { data: rows } = useQuery({
    queryKey: ["tasks", statusFilter],
    queryFn: () => api.listTasks(statusFilter ? { status: statusFilter } : undefined),
  });

  useEffect(() => {
    if (createSignal > 0) setCreating(true);
  }, [createSignal]);

  return (
    <div>
      <header className={styles.header}>
        <h1 className={styles.title}>{t("tasks.title")}</h1>
        <div className={styles.actions}>
          <select
            className={styles.select}
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option value="">{t("tasks.filter.all")}</option>
            {STATUS_OPTIONS.map((status) => (
              <option key={status} value={status}>
                {STATUS_LABEL[status]}
              </option>
            ))}
          </select>
          <button type="button" className={styles.primary} onClick={() => setCreating(true)}>
            {t("tasks.create")}
          </button>
        </div>
      </header>

      {rows && rows.length === 0 && statusFilter === "" ? (
        <EmptyGuide onOpenSettings={onOpenSettings} />
      ) : rows && rows.length === 0 ? (
        <div className={styles.empty}>{t("tasks.empty")}</div>
      ) : (
        <div className={styles.card}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>{t("tasks.col.task")}</th>
                <th>{t("tasks.col.profile")}</th>
                <th>{t("tasks.col.status")}</th>
                <th>{t("tasks.col.updated")}</th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((row) => (
                <tr key={row.id} onClick={() => onOpenTask(row.project, row.id)}>
                  <td>
                    <div className={styles.taskId}>{row.name || row.id}</div>
                    <div className={styles.project}>
                      {row.id} · {row.project}
                    </div>
                  </td>
                  <td>{row.profile}</td>
                  <td>
                    <StatusBadge status={row.status} />
                  </td>
                  <td className={styles.time}>{formatTime(row.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {creating && (
        <CreateTaskDialog
          initialPath={droppedPath ?? undefined}
          onClose={() => {
            setCreating(false);
            onConsumeDrop?.();
          }}
          onCreated={(project, taskId) => {
            setCreating(false);
            onConsumeDrop?.();
            onOpenTask(project, taskId);
          }}
        />
      )}
    </div>
  );
}
