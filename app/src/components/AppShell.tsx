import { useState } from "react";
import type { ReactNode } from "react";
import { t } from "../i18n";
import { useConnection } from "../lib/connection";
import { AssistantPanel } from "./AssistantPanel";
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
  // Assistant panel open/close is chrome state, not a navigable view: it
  // never touches `active`/onNavigate, so it never enters the nav's active
  // styling and survives navigating between tabs.
  const [assistantOpen, setAssistantOpen] = useState(false);
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
        <div className={styles.sidebarBottom}>
          <button
            type="button"
            aria-pressed={assistantOpen}
            className={assistantOpen ? styles.assistantButtonActive : styles.assistantButton}
            onClick={() => setAssistantOpen((open) => !open)}
          >
            <span className={styles.navIcon} aria-hidden="true">
              <Icon name="bot" size={16} />
            </span>
            {t("assistant.open")}
          </button>
          <div className={styles.connBadge} data-status={conn.status}>
            <span className={styles.connDot} />
            {conn.status === "ready"
              ? t("conn.ready")
              : conn.status === "connecting"
                ? t("conn.connecting")
                : t("conn.unavailable")}
          </div>
        </div>
      </aside>
      <main className={styles.content}>{children}</main>
      {assistantOpen && conn.status === "ready" && (
        <AssistantPanel onClose={() => setAssistantOpen(false)} />
      )}
    </div>
  );
}
