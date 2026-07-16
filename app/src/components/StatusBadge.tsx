import { t, type MessageKey } from "../i18n";
import type { TaskStatus } from "../lib/api/types";
import styles from "./StatusBadge.module.css";

const KEYS: Record<TaskStatus, MessageKey> = {
  pending: "status.pending",
  running: "status.running",
  waiting_review: "status.waiting_review",
  paused: "status.paused",
  completed: "status.completed",
  failed: "status.failed",
  canceled: "status.canceled",
};

export function StatusBadge({ status }: { status: TaskStatus }) {
  return (
    <span className={styles.badge} data-status={status}>
      {status === "running" && <span className={styles.pulse} />}
      {t(KEYS[status])}
    </span>
  );
}
