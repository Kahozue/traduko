import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppShell, type NavKey } from "./components/AppShell";
import { t } from "./i18n";
import { ConnectionProvider, useConnection } from "./lib/connection";
import { BudgetView } from "./views/BudgetView";
import { SettingsView } from "./views/SettingsView";
import { TaskDetailView } from "./views/TaskDetailView";
import { TasksView } from "./views/TasksView";
import styles from "./App.module.css";

export type View =
  | { name: "tasks" }
  | { name: "task"; project: string; taskId: string }
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
  const active: NavKey = view.name === "task" ? "tasks" : view.name;
  return (
    <AppShell active={active} onNavigate={(key) => setView({ name: key } as View)}>
      {conn.status !== "ready" ? (
        <ConnectionGate />
      ) : view.name === "tasks" ? (
        <TasksView onOpenTask={(project, taskId) => setView({ name: "task", project, taskId })} />
      ) : view.name === "task" ? (
        <TaskDetailView
          project={view.project}
          taskId={view.taskId}
          onBack={() => setView({ name: "tasks" })}
        />
      ) : view.name === "budget" ? (
        <BudgetView />
      ) : (
        <SettingsView />
      )}
    </AppShell>
  );
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
