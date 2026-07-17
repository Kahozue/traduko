import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppShell, type NavKey } from "./components/AppShell";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { t } from "./i18n";
import { ConnectionProvider, useConnection } from "./lib/connection";
import { BudgetView } from "./views/BudgetView";
import { DocumentEditorView } from "./views/DocumentEditorView";
import { SettingsView, type SettingsTab } from "./views/SettingsView";
import { SkillEditorView } from "./views/SkillEditorView";
import { SubtitleEditorView } from "./views/SubtitleEditorView";
import { TaskDetailView } from "./views/TaskDetailView";
import { TasksView } from "./views/TasksView";
import styles from "./App.module.css";

export type View =
  | { name: "tasks" }
  | { name: "task"; project: string; taskId: string }
  | { name: "subtitle-editor"; project: string; taskId: string }
  | { name: "document-editor"; project: string; taskId: string }
  | { name: "skill-editor"; skill: string }
  | { name: "budget" }
  | { name: "settings"; tab?: SettingsTab };

const queryClient = new QueryClient();

function ConnectionGate() {
  const conn = useConnection();
  if (conn.status === "connecting") {
    return (
      <div className={styles.gate}>
        <span className={styles.gatePulse} />
        <p className={styles.gateTitle}>{t("conn.starting")}</p>
        <p className={styles.gateHint}>{t("conn.startingHint")}</p>
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
  // Bumped by Cmd+N or a file drop; TasksView reacts by opening the create
  // dialog (with droppedPath prefilled when set).
  const [createSignal, setCreateSignal] = useState(0);
  const [droppedPath, setDroppedPath] = useState<string | null>(null);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (!(event.metaKey || event.ctrlKey)) return;
      if (event.key === ",") {
        event.preventDefault();
        setView({ name: "settings" });
      } else if (event.key.toLowerCase() === "n") {
        event.preventDefault();
        setView({ name: "tasks" });
        setDroppedPath(null);
        setCreateSignal((n) => n + 1);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    // Native drag-and-drop only exists inside the Tauri webview; skip in
    // jsdom and plain-browser dev where the API module has no backend.
    if (!("__TAURI_INTERNALS__" in window)) return;
    let unlisten: (() => void) | null = null;
    let disposed = false;
    void import("@tauri-apps/api/webview").then(async ({ getCurrentWebview }) => {
      const stop = await getCurrentWebview().onDragDropEvent((event) => {
        if (event.payload.type !== "drop") return;
        const path = event.payload.paths[0];
        if (!path) return;
        setView({ name: "tasks" });
        setDroppedPath(path);
        setCreateSignal((n) => n + 1);
      });
      if (disposed) stop();
      else unlisten = stop;
    });
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);

  const active: NavKey =
    view.name === "task" ||
    view.name === "subtitle-editor" ||
    view.name === "document-editor"
      ? "tasks"
      : view.name === "skill-editor"
        ? "settings"
        : view.name;
  return (
    <AppShell active={active} onNavigate={(key) => setView({ name: key } as View)}>
      {conn.status !== "ready" ? (
        <ConnectionGate />
      ) : (
        <ErrorBoundary key={view.name}>
          {renderView(view, setView, createSignal, droppedPath, () => setDroppedPath(null))}
        </ErrorBoundary>
      )}
    </AppShell>
  );
}

function renderView(
  view: View,
  setView: (view: View) => void,
  createSignal: number,
  droppedPath: string | null,
  consumeDrop: () => void,
): ReactNode {
  switch (view.name) {
    case "tasks":
      return (
        <TasksView
          onOpenTask={(project, taskId) => setView({ name: "task", project, taskId })}
          onOpenSettings={() => setView({ name: "settings" })}
          createSignal={createSignal}
          droppedPath={droppedPath}
          onConsumeDrop={consumeDrop}
        />
      );
    case "task":
      return (
        <TaskDetailView
          project={view.project}
          taskId={view.taskId}
          onBack={() => setView({ name: "tasks" })}
          onOpenSettings={() => setView({ name: "settings" })}
          onOpenEditor={(kind) =>
            setView({
              name: kind === "document" ? "document-editor" : "subtitle-editor",
              project: view.project,
              taskId: view.taskId,
            })
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
    case "document-editor":
      return (
        <DocumentEditorView
          project={view.project}
          taskId={view.taskId}
          onBack={() => setView({ name: "task", project: view.project, taskId: view.taskId })}
        />
      );
    case "skill-editor":
      return (
        <SkillEditorView
          skill={view.skill}
          onBack={() => setView({ name: "settings", tab: "agent" })}
        />
      );
    case "budget":
      return <BudgetView />;
    case "settings":
      return (
        <SettingsView
          initialTab={view.tab}
          onEditSkill={(name) => setView({ name: "skill-editor", skill: name })}
        />
      );
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
