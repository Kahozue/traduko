import { useState } from "react";
import { t } from "../../i18n";
import type { BudgetConfigDoc } from "../../lib/api/types";
import { Section, SettingRow } from "./Section";
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
    <Section title={t("settings.general")}>
      <SettingRow label={t("settings.defaultProject")} htmlFor="settings-default-project">
        <input
          id="settings-default-project"
          className={styles.input}
          value={defaultProject}
          onChange={(event) => onDefaultProject(event.target.value)}
        />
        {defaultProject.trim() === "" && (
          <span className={styles.error}>{t("settings.projectRequired")}</span>
        )}
      </SettingRow>
      <SettingRow
        label={t("settings.taskLimit")}
        htmlFor="settings-task-limit"
        description={t("settings.taskLimit.desc")}
      >
        <input
          id="settings-task-limit"
          className={`${styles.input} ${styles.inputNarrow}`}
          inputMode="decimal"
          placeholder={t("settings.limitPlaceholder")}
          value={taskText}
          onChange={(event) => update("task", event.target.value)}
        />
        {!taskValid && <span className={styles.error}>{t("settings.limitInvalid")}</span>}
      </SettingRow>
      <SettingRow label={t("settings.monthlyLimit")} htmlFor="settings-monthly-limit">
        <input
          id="settings-monthly-limit"
          className={`${styles.input} ${styles.inputNarrow}`}
          inputMode="decimal"
          placeholder={t("settings.limitPlaceholder")}
          value={monthText}
          onChange={(event) => update("month", event.target.value)}
        />
        {!monthValid && <span className={styles.error}>{t("settings.limitInvalid")}</span>}
      </SettingRow>
    </Section>
  );
}
