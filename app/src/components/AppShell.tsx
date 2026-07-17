import type { ReactNode } from "react";
import { t } from "../i18n";
import { useConnection } from "../lib/connection";
import { Icon, type IconName } from "./icons";
import styles from "./AppShell.module.css";

export type NavKey = "tasks" | "budget" | "settings";

const NAV_ITEMS: { key: NavKey; icon: IconName; label: string }[] = [
  { key: "tasks", icon: "list", label: t("nav.tasks") },
  { key: "budget", icon: "wallet", label: t("nav.budget") },
  { key: "settings", icon: "sliders", label: t("nav.settings") },
];

export function AppShell({
  active,
  onNavigate,
  children,
}: {
  active: NavKey;
  onNavigate: (key: NavKey) => void;
  children: ReactNode;
}) {
  const conn = useConnection();
  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>{t("app.title")}</div>
        <nav className={styles.nav}>
          {NAV_ITEMS.map((item) => (
            <button
              key={item.key}
              type="button"
              className={item.key === active ? styles.navItemActive : styles.navItem}
              onClick={() => onNavigate(item.key)}
            >
              <span className={styles.navIcon} aria-hidden="true">
                <Icon name={item.icon} size={16} />
              </span>
              {item.label}
            </button>
          ))}
        </nav>
        <div className={styles.connBadge} data-status={conn.status}>
          <span className={styles.connDot} />
          {conn.status === "ready"
            ? t("conn.ready")
            : conn.status === "connecting"
              ? t("conn.connecting")
              : t("conn.unavailable")}
        </div>
      </aside>
      <main className={styles.content}>{children}</main>
    </div>
  );
}
