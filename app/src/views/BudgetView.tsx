import type { CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { ProgressBar } from "../components/ProgressBar";
import { t } from "../i18n";
import { useApi } from "../lib/connection";
import styles from "./BudgetView.module.css";

function usd(value: number): string {
  return `$${value.toFixed(2)}`;
}

export function BudgetView() {
  const api = useApi();
  const { data: budget } = useQuery({ queryKey: ["budget"], queryFn: () => api.budget() });
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
          />
        </div>
      )}

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
                    <td>
                      <div>{row.name || row.task_id}</div>
                      {row.name && <div className={styles.spendId}>{row.task_id}</div>}
                    </td>
                    <td>{row.project}</td>
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
