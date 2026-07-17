import type { ReactNode } from "react";
import { Icon, type IconName } from "../icons";
import styles from "./settings.module.css";

export type SectionTint = "accent" | "info" | "ok" | "warn" | "neutral";

// Shared card anatomy for every settings section: tinted icon chip, title
// with a one-line description, an optional action slot, then the body
// below a hairline divider.
export function Section({
  icon,
  tint = "accent",
  title,
  description,
  action,
  children,
}: {
  icon: IconName;
  tint?: SectionTint;
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className={styles.section}>
      <header className={styles.sectionHead}>
        <span className={styles.iconChip} data-tint={tint} aria-hidden="true">
          <Icon name={icon} />
        </span>
        <div className={styles.sectionHeadText}>
          <h2 className={styles.sectionTitle}>{title}</h2>
          {description && <p className={styles.sectionDesc}>{description}</p>}
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
