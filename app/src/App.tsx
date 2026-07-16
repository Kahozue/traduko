import { useState } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppShell, type NavKey } from "./components/AppShell";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { t } from "./i18n";
import { ConnectionProvider, useConnection } from "./lib/connection";
import { BudgetView } from "./views/BudgetView";
import { SettingsView } from "./views/SettingsView";
import { StyleEditorView } from "./views/StyleEditorView";
import { SubtitleEditorView } from "./views/SubtitleEditorView";
import { TaskDetailView } from "./views/TaskDetailView";
import { TasksView } from "./views/TasksView";
import styles from "./App.module.css";

export type View =
  | { name: "tasks" }
  | { name: "task"; project: string; taskId: string }
  | { name: "subtitle-editor"; project: string; taskId: string }
  | { name: "style-editor"; project: string; taskId: string }
  | { name: "budget" }
  | { name: "settings" };

const queryClient = new QueryClient();

function ConnectionGate() {
  const conn = useConnection();
  if (conn.status === "connecting") {
    return (
      <div className={styles.gate}>
        <span className={styles.gatePulse} />
        <p className={styles.gateTitle}>{t("conn.connecting")}</p>
      </div>
    );
  }
  return (
    <div className={styles.gate}>
      <p className={styles.gateTitle}>{t("conn.unavailable")}</p>
      <p className={styles.gateHint}>{t("conn.hint")}</p>
      <button type="button" className={styles.gateRetry} onClick={conn.retry}>
        {t("conn.retry")}
      </button>
    </div>
  );
}

function Main() {
  const conn = useConnection();
  const [view, setView] = useState<View>({ name: "tasks" });
  const active: NavKey =
    view.name === "task" || view.name === "subtitle-editor" || view.name === "style-editor"
      ? "tasks"
      : view.name;
  return (
    <AppShell active={active} onNavigate={(key) => setView({ name: key } as View)}>
      {conn.status !== "ready" ? (
        <ConnectionGate />
      ) : (
        <ErrorBoundary key={view.name}>{renderView(conn, view, setView)}</ErrorBoundary>
      )}
    </AppShell>
  );
}

function renderView(
  conn: Extract<ReturnType<typeof useConnection>, { status: "ready" }>,
  view: View,
  setView: (view: View) => void,
): ReactNode {
  void conn;
  switch (view.name) {
    case "tasks":
      return (
        <TasksView
          onOpenTask={(project, taskId) => setView({ name: "task", project, taskId })}
        />
      );
    case "task":
      return (
        <TaskDetailView
          project={view.project}
          taskId={view.taskId}
          onBack={() => setView({ name: "tasks" })}
          onOpenSubtitleEditor={() =>
            setView({ name: "subtitle-editor", project: view.project, taskId: view.taskId })
          }
          onOpenStyleEditor={() =>
            setView({ name: "style-editor", project: view.project, taskId: view.taskId })
          }
        />
      );
    case "subtitle-editor":
      return (
        <SubtitleEditorView
          project={view.project}
          taskId={view.taskId}
          onBack={() => setView({ name: "task", project: view.project, taskId: view.taskId })}
        />
      );
    case "style-editor":
      return (
        <StyleEditorView
          project={view.project}
          taskId={view.taskId}
          onBack={() => setView({ name: "task", project: view.project, taskId: view.taskId })}
        />
      );
    case "budget":
      return <BudgetView />;
    case "settings":
      return <SettingsView />;
  }
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ConnectionProvider>
        <Main />
      </ConnectionProvider>
    </QueryClientProvider>
  );
}
