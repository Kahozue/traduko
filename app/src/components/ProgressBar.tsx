import type { ReactNode } from "react";
import styles from "./ProgressBar.module.css";

export function ProgressBar({
  value,
  max,
  label,
  count,
}: {
  value: number;
  max: number;
  label?: string;
  // Overrides the raw `value / max` readout — e.g. formatted currency.
  count?: ReactNode;
}) {
  const percent = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className={styles.wrap}>
      {label && (
        <div className={styles.labelRow}>
          <span>{label}</span>
          <span className={styles.count}>{count ?? `${value} / ${max}`}</span>
        </div>
      )}
      <div className={styles.track}>
        <div className={styles.fill} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
