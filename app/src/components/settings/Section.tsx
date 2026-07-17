import type { ReactNode } from "react";
import styles from "./settings.module.css";

// Section anatomy per the design language: a heading row (title, optional
// action) above the body, separated from the previous section by a hairline.
// No cards, no icon chips — hierarchy comes from type and whitespace.
// `hint` is reserved for genuinely non-obvious section-level behavior
// (e.g. "requires a core restart"); most sections must not have one.
export function Section({
  title,
  hint,
  action,
  children,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className={styles.section}>
      <header className={styles.sectionHead}>
        <div className={styles.sectionHeadText}>
          <h2 className={styles.sectionTitle}>{title}</h2>
          {hint && <p className={styles.sectionHint}>{hint}</p>}
        </div>
        {action}
      </header>
      <div className={styles.sectionBody}>{children}</div>
    </section>
  );
}

// A label/description column on the left, the control on the right.
// The description intentionally lives outside the <label> so it never
// pollutes the control's accessible name.
export function SettingRow({
  label,
  htmlFor,
  description,
  children,
}: {
  label: string;
  htmlFor?: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <div className={styles.settingRow}>
      <div className={styles.rowText}>
        {htmlFor ? (
          <label className={styles.rowLabel} htmlFor={htmlFor}>
            {label}
          </label>
        ) : (
          <span className={styles.rowLabel}>{label}</span>
        )}
        {description && <p className={styles.rowDesc}>{description}</p>}
      </div>
      <div className={styles.rowControl}>{children}</div>
    </div>
  );
}
