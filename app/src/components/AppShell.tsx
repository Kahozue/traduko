import { useState } from "react";
import type { ReactNode } from "react";
import { t, type MessageKey } from "../i18n";
import { useConnection } from "../lib/connection";
import type { TaskKind } from "../lib/api/types";
import { AssistantPanel } from "./AssistantPanel";
import { Icon, type IconName } from "./icons";
import styles from "./AppShell.module.css";

export type NavKey = "tasks" | "budget" | "settings";

// Task-kind sub-items shown under "任務": a unified view per pipeline domain
// that filters the task list. `null` is the "all" entry at the top.
const TASK_KINDS: { kind: TaskKind; label: MessageKey; icon: IconName }[] = [
  { kind: "video", label: "create.kind.video", icon: "list" },
  { kind: "document", label: "create.kind.document", icon: "pencil" },
  { kind: "comic", label: "create.kind.comic", icon: "monitor" },
];

export function AppShell({
  active,
  onNavigate,
  taskKind = null,
  onSelectKind,
  children,
}: {
  active: NavKey;
  onNavigate: (key: NavKey) => void;
  // Currently-selected task-kind filter (only meaningful while active is
  // "tasks"); null means "all tasks".
  taskKind?: TaskKind | null;
  onSelectKind?: (kind: TaskKind | null) => void;
  children: ReactNode;
}) {
  const conn = useConnection();
  const [assistantOpen, setAssistantOpen] = useState(false);
  const connLabel =
    conn.status === "ready"
      ? t("conn.ready")
      : conn.status === "connecting"
        ? t("conn.connecting")
        : t("conn.unavailable");
  const tasksActive = active === "tasks";
  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>{t("app.title")}</div>
        <nav className={styles.nav}>
          <button
            type="button"
            className={tasksActive && taskKind === null ? styles.navItemActive : styles.navItem}
            onClick={() => {
              onSelectKind?.(null);
              onNavigate("tasks");
            }}
          >
            <span className={styles.navIcon} aria-hidden="true">
              <Icon name="list" size={16} />
            </span>
            {t("nav.tasks")}
          </button>
          {/* Unified task-domain views, directly under 任務. */}
          <div className={styles.subNav}>
            {TASK_KINDS.map((item) => (
              <button
                key={item.kind}
                type="button"
                className={
                  tasksActive && taskKind === item.kind
                    ? styles.subItemActive
                    : styles.subItem
                }
                onClick={() => {
                  onSelectKind?.(item.kind);
                  onNavigate("tasks");
                }}
              >
                <span className={styles.navIcon} aria-hidden="true">
                  <Icon name={item.icon} size={14} />
                </span>
                {t(item.label)}
              </button>
            ))}
          </div>
          <button
            type="button"
            className={active === "budget" ? styles.navItemActive : styles.navItem}
            onClick={() => onNavigate("budget")}
          >
            <span className={styles.navIcon} aria-hidden="true">
              <Icon name="wallet" size={16} />
            </span>
            {t("nav.budget")}
          </button>
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
          {/* Footer strip: settings gear on the left, connection reduced to a
             color dot whose text shows on hover (title). */}
          <div className={styles.footerRow}>
            <button
              type="button"
              className={active === "settings" ? styles.gearButtonActive : styles.gearButton}
              title={t("nav.settings")}
              aria-label={t("nav.settings")}
              onClick={() => onNavigate("settings")}
            >
              <Icon name="sliders" size={16} />
            </button>
            <span
              className={styles.connDot}
              data-status={conn.status}
              title={connLabel}
              aria-label={connLabel}
              role="status"
            />
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
