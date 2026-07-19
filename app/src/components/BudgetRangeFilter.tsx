import { t, type MessageKey } from "../i18n";
import styles from "./BudgetRangeFilter.module.css";

export type RangeMode = "all" | "today" | "month" | "custom";

const MODES: { mode: RangeMode; key: MessageKey }[] = [
  { mode: "all", key: "budget.rangeAll" },
  { mode: "today", key: "budget.rangeToday" },
  { mode: "month", key: "budget.rangeMonth" },
  { mode: "custom", key: "budget.rangeCustom" },
];

export function BudgetRangeFilter({
  mode,
  onMode,
  from,
  to,
  onFrom,
  onTo,
}: {
  mode: RangeMode;
  onMode: (mode: RangeMode) => void;
  from: string;
  to: string;
  onFrom: (value: string) => void;
  onTo: (value: string) => void;
}) {
  return (
    <div className={styles.filter}>
      <div className={styles.segmented} role="group" aria-label={t("budget.range")}>
        {MODES.map((m) => (
          <button
            key={m.mode}
            type="button"
            className={styles.segment}
            data-active={mode === m.mode}
            onClick={() => onMode(m.mode)}
          >
            {t(m.key)}
          </button>
        ))}
      </div>
      {mode === "custom" && (
        <div className={styles.dates}>
          <input
            type="date"
            className={styles.date}
            aria-label={t("budget.from")}
            value={from}
            max={to || undefined}
            onChange={(e) => onFrom(e.target.value)}
          />
          <span className={styles.dateSep}>–</span>
          <input
            type="date"
            className={styles.date}
            aria-label={t("budget.to")}
            value={to}
            min={from || undefined}
            onChange={(e) => onTo(e.target.value)}
          />
        </div>
      )}
    </div>
  );
}
