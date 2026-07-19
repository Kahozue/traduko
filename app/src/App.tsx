import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppShell, type NavKey } from "./components/AppShell";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { t } from "./i18n";
import { ConnectionProvider, useConnection } from "./lib/connection";
import { useLocale } from "./lib/locale";
import { BudgetView } from "./views/BudgetView";
import { DocumentEditorView } from "./views/DocumentEditorView";
import { DubbingStudioView } from "./views/DubbingStudioView";
import { GlossaryEditorView } from "./views/GlossaryEditorView";
import { SettingsView, type SettingsTab } from "./views/SettingsView";
import { SkillEditorView } from "./views/SkillEditorView";
import { SubtitleEditorView } from "./views/SubtitleEditorView";
import { SpeakerReviewView } from "./views/SpeakerReviewView";
import { TaskDetailView } from "./views/TaskDetailView";
import { TaskGlossaryView } from "./views/TaskGlossaryView";
import { TasksView } from "./views/TasksView";
import type { TaskKind } from "./lib/api/types";
import styles from "./App.module.css";

export type View =
  | { name: "tasks" }
  | { name: "task"; project: string; taskId: string }
  | { name: "task-glossary"; project: string; taskId: string }
  | { name: "subtitle-editor"; project: string; taskId: string }
  | { name: "document-editor"; project: string; taskId: string }
  | { name: "speaker-review"; project: string; taskId: string }
  | { name: "dubbing-studio"; project: string; taskId: string }
  | { name: "skill-editor"; skill: string }
  | { name: "glossary-editor"; glossaryId: string; returnTab: SettingsTab }
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

function Main({
  view,
  setView,
  taskKind,
  setTaskKind,
}: {
  view: View;
  setView: (view: View) => void;
  taskKind: TaskKind | null;
  setTaskKind: (kind: TaskKind | null) => void;
}) {
  const conn = useConnection();
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
    view.name === "task-glossary" ||
    view.name === "subtitle-editor" ||
    view.name === "document-editor" ||
    view.name === "speaker-review" ||
    view.name === "dubbing-studio"
      ? "tasks"
      : view.name === "skill-editor" || view.name === "glossary-editor"
        ? "settings"
        : view.name;
  return (
    <AppShell
      active={active}
      onNavigate={(key) => setView({ name: key } as View)}
      taskKind={taskKind}
      onSelectKind={setTaskKind}
    >
      {conn.status !== "ready" ? (
        <ConnectionGate />
      ) : (
        <ErrorBoundary key={view.name}>
          {renderView(view, setView, createSignal, droppedPath, () => setDroppedPath(null), taskKind)}
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
  taskKind: TaskKind | null,
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
          taskKind={taskKind}
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
              name:
                kind === "document"
                  ? "document-editor"
                  : kind === "speakers"
                    ? "speaker-review"
                    : "subtitle-editor",
              project: view.project,
              taskId: view.taskId,
            })
          }
          onOpenGlossary={() =>
            setView({ name: "task-glossary", project: view.project, taskId: view.taskId })
          }
          onOpenDub={() =>
            setView({ name: "dubbing-studio", project: view.project, taskId: view.taskId })
          }
        />
      );
    case "task-glossary":
      return (
        <TaskGlossaryView
          project={view.project}
          taskId={view.taskId}
          onBack={() => setView({ name: "task", project: view.project, taskId: view.taskId })}
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
    case "speaker-review":
      return (
        <SpeakerReviewView
          project={view.project}
          taskId={view.taskId}
          onBack={() => setView({ name: "task", project: view.project, taskId: view.taskId })}
        />
      );
    case "dubbing-studio":
      return (
        <DubbingStudioView
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
    case "glossary-editor":
      return (
        <GlossaryEditorView
          glossaryId={view.glossaryId}
          onBack={() => setView({ name: "settings", tab: view.returnTab })}
        />
      );
    case "budget":
      return <BudgetView />;
    case "settings":
      return (
        <SettingsView
          initialTab={view.tab}
          onTabChange={(tab) => setView({ name: "settings", tab })}
          onEditSkill={(name) => setView({ name: "skill-editor", skill: name })}
          onEditGlossary={(id) =>
            setView({
              name: "glossary-editor",
              glossaryId: id,
              returnTab: view.tab ?? "general",
            })
          }
        />
      );
  }
}

export default function App() {
  // Keying the tree by locale remounts everything on a language switch, so
  // every t() call re-evaluates without per-component subscriptions.
  const locale = useLocale();
  // Navigation state lives above the locale-keyed remount so switching the
  // interface language keeps the user on the view (and settings tab) they
  // were on instead of resetting to the task list.
  const [view, setView] = useState<View>({ name: "tasks" });
  // Task-kind filter for the sidebar's unified views; null means "all".
  const [taskKind, setTaskKind] = useState<TaskKind | null>(null);
  return (
    <QueryClientProvider client={queryClient}>
      <ConnectionProvider>
        <ErrorBoundary key={locale}>
          <Main view={view} setView={setView} taskKind={taskKind} setTaskKind={setTaskKind} />
        </ErrorBoundary>
      </ConnectionProvider>
    </QueryClientProvider>
  );
}
