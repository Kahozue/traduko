import { useState } from "react";
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

export function TasksView({
  onOpenTask,
}: {
  onOpenTask: (project: string, taskId: string) => void;
}) {
  const api = useApi();
  const [statusFilter, setStatusFilter] = useState("");
  const [creating, setCreating] = useState(false);
  const { data: rows } = useQuery({
    queryKey: ["tasks", statusFilter],
    queryFn: () => api.listTasks(statusFilter ? { status: statusFilter } : undefined),
  });

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

      {rows && rows.length === 0 ? (
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
          onClose={() => setCreating(false)}
          onCreated={(project, taskId) => {
            setCreating(false);
            onOpenTask(project, taskId);
          }}
        />
      )}
    </div>
  );
}
