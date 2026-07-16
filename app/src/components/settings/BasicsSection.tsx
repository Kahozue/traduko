import { useState } from "react";
import { t } from "../../i18n";
import type { BudgetConfigDoc } from "../../lib/api/types";
import styles from "./settings.module.css";

function parseLimit(raw: string): { value: number | null; valid: boolean } {
  const text = raw.trim();
  if (text === "") return { value: null, valid: true };
  const value = Number(text);
  if (Number.isNaN(value) || value < 0) return { value: null, valid: false };
  return { value, valid: true };
}

function limitText(value: number | null): string {
  return value === null ? "" : String(value);
}

export function BasicsSection({
  defaultProject,
  budget,
  onDefaultProject,
  onBudget,
  onValidity,
}: {
  defaultProject: string;
  budget: BudgetConfigDoc;
  onDefaultProject: (value: string) => void;
  onBudget: (value: BudgetConfigDoc) => void;
  onValidity: (valid: boolean) => void;
}) {
  const [taskText, setTaskText] = useState(() => limitText(budget.task_usd_limit));
  const [monthText, setMonthText] = useState(() => limitText(budget.monthly_usd_limit));

  function update(field: "task" | "month", raw: string) {
    const taskRaw = field === "task" ? raw : taskText;
    const monthRaw = field === "month" ? raw : monthText;
    if (field === "task") setTaskText(raw);
    else setMonthText(raw);
    const task = parseLimit(taskRaw);
    const month = parseLimit(monthRaw);
    onValidity(task.valid && month.valid);
    if (task.valid && month.valid) {
      onBudget({ ...budget, task_usd_limit: task.value, monthly_usd_limit: month.value });
    }
  }

  const taskValid = parseLimit(taskText).valid;
  const monthValid = parseLimit(monthText).valid;

  return (
    <>
      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("settings.general")}</h2>
        <label className={styles.field}>
          <span className={styles.label}>{t("settings.defaultProject")}</span>
          <input
            className={styles.input}
            value={defaultProject}
            onChange={(event) => onDefaultProject(event.target.value)}
          />
          {defaultProject.trim() === "" && (
            <span className={styles.error}>{t("settings.projectRequired")}</span>
          )}
        </label>
      </section>
      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("settings.budget")}</h2>
        <div className={styles.fieldRow}>
          <label className={styles.field}>
            <span className={styles.label}>{t("settings.taskLimit")}</span>
            <input
              className={styles.input}
              inputMode="decimal"
              placeholder={t("settings.limitPlaceholder")}
              value={taskText}
              onChange={(event) => update("task", event.target.value)}
            />
            {!taskValid && <span className={styles.error}>{t("settings.limitInvalid")}</span>}
          </label>
          <label className={styles.field}>
            <span className={styles.label}>{t("settings.monthlyLimit")}</span>
            <input
              className={styles.input}
              inputMode="decimal"
              placeholder={t("settings.limitPlaceholder")}
              value={monthText}
              onChange={(event) => update("month", event.target.value)}
            />
            {!monthValid && <span className={styles.error}>{t("settings.limitInvalid")}</span>}
          </label>
        </div>
      </section>
    </>
  );
}
