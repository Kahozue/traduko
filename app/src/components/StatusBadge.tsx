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
      {t(KEYS[status])}
      {/* Trailing so the running dot never shifts the label: every badge's
         text keeps the same left edge down the status column. */}
      {status === "running" && <span className={styles.pulse} />}
    </span>
  );
}
