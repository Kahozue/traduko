import { type CSSProperties, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BudgetRangeFilter, type RangeMode } from "../components/BudgetRangeFilter";
import { ModelSpendCharts } from "../components/ModelSpendCharts";
import { ProgressBar } from "../components/ProgressBar";
import { t } from "../i18n";
import { useApi } from "../lib/connection";
import styles from "./BudgetView.module.css";

function usd(value: number): string {
  return `$${value.toFixed(2)}`;
}

// Resolve the filter into a [from, to) ISO window in the user's local zone;
// an all-time selection sends no bounds. `to` for a custom range is the start
// of the day after the picked end date so that whole day is included.
function resolveRange(mode: RangeMode, from: string, to: string): { from?: string; to?: string } {
  if (mode === "today") {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    return { from: start.toISOString() };
  }
  if (mode === "month") {
    const now = new Date();
    return { from: new Date(now.getFullYear(), now.getMonth(), 1).toISOString() };
  }
  if (mode === "custom") {
    const range: { from?: string; to?: string } = {};
    if (from) range.from = new Date(`${from}T00:00:00`).toISOString();
    if (to) {
      const end = new Date(`${to}T00:00:00`);
      end.setDate(end.getDate() + 1);
      range.to = end.toISOString();
    }
    return range;
  }
  return {};
}

export function BudgetView() {
  const api = useApi();
  const [mode, setMode] = useState<RangeMode>("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const range = useMemo(() => resolveRange(mode, from, to), [mode, from, to]);
  const { data: budget } = useQuery({
    queryKey: ["budget", range.from ?? null, range.to ?? null],
    queryFn: () => api.budget(range),
  });
  if (!budget) return null;

  const nearLimit =
    budget.monthly_usd_limit !== null && budget.month_usd >= budget.monthly_usd_limit * 0.8;
  // An older core may not send the per-task breakdown yet.
  const spend = budget.tasks ?? [];

  return (
    <div>
      <h1 className={styles.title}>{t("budget.title")}</h1>
      <div className={styles.grid}>
        <div className={styles.stat}>
          <div className={styles.statLabel}>{t("budget.month")}</div>
          <div className={styles.statValue}>{usd(budget.month_usd)}</div>
        </div>
        <div className={styles.stat}>
          <div className={styles.statLabel}>{t("budget.taskLimit")}</div>
          <div className={styles.statValue}>
            {budget.task_usd_limit === null ? t("budget.unlimited") : usd(budget.task_usd_limit)}
          </div>
        </div>
        <div className={styles.stat}>
          <div className={styles.statLabel}>{t("budget.monthlyLimit")}</div>
          <div className={styles.statValue}>
            {budget.monthly_usd_limit === null
              ? t("budget.unlimited")
              : usd(budget.monthly_usd_limit)}
          </div>
        </div>
      </div>
      {budget.monthly_usd_limit !== null && (
        <div
          className={styles.barCard}
          style={
            nearLimit
              ? ({ "--accent": "var(--warn)", "--accent-strong": "var(--warn)" } as CSSProperties)
              : undefined
          }
        >
          <ProgressBar
            value={budget.month_usd}
            max={budget.monthly_usd_limit}
            label={t("budget.month")}
            count={`${usd(budget.month_usd)} / ${usd(budget.monthly_usd_limit)}`}
          />
        </div>
      )}

      <section className={styles.analysisSection}>
        <div className={styles.analysisHead}>
          <h2 className={styles.spendTitle}>{t("budget.analysis")}</h2>
          <BudgetRangeFilter
            mode={mode}
            onMode={setMode}
            from={from}
            to={to}
            onFrom={setFrom}
            onTo={setTo}
          />
        </div>
        <ModelSpendCharts models={budget.models ?? []} />
      </section>

      <section className={styles.spendSection}>
        <h2 className={styles.spendTitle}>{t("budget.taskSpend")}</h2>
        {spend.length === 0 ? (
          <p className={styles.spendEmpty}>{t("budget.taskSpendEmpty")}</p>
        ) : (
          <div className={styles.spendCard}>
            <table className={styles.spendTable}>
              <thead>
                <tr>
                  <th>{t("budget.col.task")}</th>
                  <th>{t("budget.col.project")}</th>
                  <th className={styles.spendUsd}>{t("budget.col.usd")}</th>
                </tr>
              </thead>
              <tbody>
                {spend.map((row) => (
                  <tr key={row.task_id}>
                    <td>{row.name || row.task_id}</td>
                    <td className={styles.spendProject}>{row.project}</td>
                    <td className={styles.spendUsd}>{usd(row.usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
