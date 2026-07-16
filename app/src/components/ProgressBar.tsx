import styles from "./ProgressBar.module.css";

export function ProgressBar({ value, max, label }: { value: number; max: number; label?: string }) {
  const percent = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className={styles.wrap}>
      {label && (
        <div className={styles.labelRow}>
          <span>{label}</span>
          <span className={styles.count}>
            {value} / {max}
          </span>
        </div>
      )}
      <div className={styles.track}>
        <div className={styles.fill} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
