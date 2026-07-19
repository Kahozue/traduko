import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CreateTaskDialog } from "../components/CreateTaskDialog";
import { Icon } from "../components/icons";
import { StatusBadge } from "../components/StatusBadge";
import { t } from "../i18n";
import { useApi } from "../lib/connection";
import { formatDateTime } from "../lib/time";
import type { TaskIndexRow, TaskKind, TaskStatus } from "../lib/api/types";
import styles from "./TasksView.module.css";

const STATUS_OPTIONS: TaskStatus[] = [
  "pending",
  "running",
  "waiting_review",
  "paused",
  "completed",
  "failed",
  "canceled",
];

// Computed per call so a locale switch (which remounts the tree) always
// reads the active language instead of module-load-time text.
function statusLabel(status: TaskStatus): string {
  return t(`status.${status}` as Parameters<typeof t>[0]);
}

const KIND_LABEL_KEYS: Record<TaskKind, Parameters<typeof t>[0]> = {
  video: "create.kind.video",
  audio: "create.kind.audio",
  document: "create.kind.document",
  comic: "create.kind.comic",
};

const COLLAPSE_KEY = "traduko.tasks.collapsed";

function rowKey(row: TaskIndexRow): string {
  return `${row.project}\n${row.id}`;
}

function loadCollapsed(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(COLLAPSE_KEY) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

// The empty state is the sanctioned home of the verda-stelo mark.
function EmptyGuide({ onOpenSettings }: { onOpenSettings?: () => void }) {
  return (
    <div className={styles.emptyGuide}>
      <svg
        className={styles.emptyStar}
        viewBox="0 0 24 24"
        width="40"
        height="40"
        aria-hidden="true"
      >
        <path
          fill="currentColor"
          d="M12 2.5l2.6 6.05 6.56.56-4.98 4.32 1.5 6.41L12 16.43l-5.68 3.41 1.5-6.41-4.98-4.32 6.56-.56z"
        />
      </svg>
      <p className={styles.emptyTitle}>{t("tasks.emptyTitle")}</p>
      <ol className={styles.emptySteps}>
        <li>{t("tasks.emptyStep1")}</li>
        <li>{t("tasks.emptyStep2")}</li>
      </ol>
      {onOpenSettings && (
        <button type="button" className={styles.emptyAction} onClick={onOpenSettings}>
          {t("tasks.emptyAction")}
        </button>
      )}
    </div>
  );
}

export function TasksView({
  onOpenTask,
  onOpenSettings,
  createSignal = 0,
  droppedPath = null,
  onConsumeDrop,
  taskKind = null,
}: {
  onOpenTask: (project: string, taskId: string) => void;
  onOpenSettings?: () => void;
  createSignal?: number;
  droppedPath?: string | null;
  onConsumeDrop?: () => void;
  taskKind?: TaskKind | null;
}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("");
  const [creating, setCreating] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(loadCollapsed);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [moveMenuOpen, setMoveMenuOpen] = useState(false);
  const [newCategory, setNewCategory] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [bulkNote, setBulkNote] = useState<string | null>(null);
  // Pointer-based drag: Tauri's file drag-drop interception swallows HTML5
  // drag events inside the webview, so rows are moved with pointer events.
  const [drag, setDrag] = useState<
    null | { keys: string[]; x: number; y: number; over: string | null }
  >(null);
  const dragStartRef = useRef<null | { key: string; x: number; y: number }>(null);
  const dragRef = useRef<typeof drag>(null);
  const suppressClickRef = useRef(false);
  const moveMenuRef = useRef<HTMLDivElement>(null);
  const { data: allRows } = useQuery({
    queryKey: ["tasks", statusFilter],
    queryFn: () => api.listTasks(statusFilter ? { status: statusFilter } : undefined),
  });
  // Profile -> kind, so the sidebar's unified task-domain views can filter the
  // list by kind without the task index carrying a kind of its own.
  const { data: profileInfo } = useQuery({
    queryKey: ["profiles-detailed"],
    queryFn: () => api.profilesDetailed(),
  });
  const kindByProfile = useMemo(() => {
    const map = new Map<string, TaskKind>();
    for (const info of profileInfo ?? []) map.set(info.name, info.kind);
    return map;
  }, [profileInfo]);
  const rows = useMemo(() => {
    if (!taskKind) return allRows;
    return (allRows ?? []).filter((row) => kindByProfile.get(row.profile) === taskKind);
  }, [allRows, taskKind, kindByProfile]);

  useEffect(() => {
    if (createSignal > 0) setCreating(true);
  }, [createSignal]);

  useEffect(() => {
    if (!moveMenuOpen) return;
    function onDocMouseDown(event: MouseEvent) {
      if (!moveMenuRef.current?.contains(event.target as Node)) setMoveMenuOpen(false);
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [moveMenuOpen]);

  const groups = useMemo(() => {
    const map = new Map<string, TaskIndexRow[]>();
    for (const row of rows ?? []) {
      const bucket = map.get(row.project);
      if (bucket) bucket.push(row);
      else map.set(row.project, [row]);
    }
    return [...map.entries()].sort(([a], [b]) => {
      if (a === "default") return -1;
      if (b === "default") return 1;
      return a.localeCompare(b);
    });
  }, [rows]);

  const byKey = useMemo(() => {
    const map = new Map<string, TaskIndexRow>();
    for (const row of rows ?? []) map.set(rowKey(row), row);
    return map;
  }, [rows]);

  function toggleCollapse(project: string) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(project)) next.delete(project);
      else next.add(project);
      localStorage.setItem(COLLAPSE_KEY, JSON.stringify([...next]));
      return next;
    });
  }

  function toggleSelect(key: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
    setBulkNote(null);
  }

  function selectionRows(): TaskIndexRow[] {
    return [...selected].map((key) => byKey.get(key)).filter((row): row is TaskIndexRow => !!row);
  }

  const bulkDelete = useMutation({
    mutationFn: async () => {
      const results = await Promise.allSettled(
        selectionRows().map((row) => api.deleteTask(row.project, row.id)),
      );
      return results.filter((result) => result.status === "rejected").length;
    },
    onSuccess: (failedCount) => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      setSelected(new Set());
      setConfirmingDelete(false);
      setBulkNote(failedCount > 0 ? t("tasks.bulkPartial") : null);
    },
  });

  const selectedRef = useRef(selected);
  selectedRef.current = selected;

  const bulkMove = useMutation({
    mutationFn: async ({ keys, target }: { keys: string[]; target: string }) => {
      const moves = keys
        .map((key) => byKey.get(key))
        .filter((row): row is TaskIndexRow => !!row && row.project !== target);
      const results = await Promise.allSettled(
        moves.map((row) => api.moveTask(row.project, row.id, target)),
      );
      return results.filter((result) => result.status === "rejected").length;
    },
    onSuccess: (failedCount) => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      setSelected(new Set());
      setMoveMenuOpen(false);
      setNewCategory("");
      setBulkNote(failedCount > 0 ? t("tasks.bulkPartial") : null);
    },
  });

  const bulkMoveRef = useRef(bulkMove.mutate);
  bulkMoveRef.current = bulkMove.mutate;

  function startRowDrag(event: React.PointerEvent, key: string) {
    if (event.button !== 0) return;
    if ((event.target as HTMLElement).closest("input, button, a")) return;
    dragStartRef.current = { key, x: event.clientX, y: event.clientY };
  }

  useEffect(() => {
    function onMove(event: PointerEvent) {
      const start = dragStartRef.current;
      if (!start) return;
      if (!dragRef.current) {
        const distance = Math.hypot(event.clientX - start.x, event.clientY - start.y);
        if (distance < 6) return;
        const keys = selectedRef.current.has(start.key)
          ? [...selectedRef.current]
          : [start.key];
        dragRef.current = { keys, x: event.clientX, y: event.clientY, over: null };
      }
      const el = document.elementFromPoint?.(event.clientX, event.clientY);
      const head = (el as HTMLElement | null)?.closest?.("[data-drop-project]");
      const over = head?.getAttribute("data-drop-project") ?? null;
      dragRef.current = { ...dragRef.current, x: event.clientX, y: event.clientY, over };
      setDrag(dragRef.current);
    }
    function onUp() {
      const active = dragRef.current;
      if (active) {
        suppressClickRef.current = true;
        if (active.over) {
          bulkMoveRef.current({ keys: active.keys, target: active.over });
        }
      }
      dragStartRef.current = null;
      dragRef.current = null;
      setDrag(null);
    }
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, []);

  const projectNames = groups.map(([name]) => name);
  const hasSelection = selected.size > 0;

  return (
    <div>
      <header className={styles.header}>
        <h1 className={styles.title}>{taskKind ? t(KIND_LABEL_KEYS[taskKind]) : t("tasks.title")}</h1>
        <div className={styles.actions}>
          <select
            className={styles.select}
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option value="">{t("tasks.filter.all")}</option>
            {STATUS_OPTIONS.map((status) => (
              <option key={status} value={status}>
                {statusLabel(status)}
              </option>
            ))}
          </select>
          <button type="button" className={styles.primary} onClick={() => setCreating(true)}>
            {t("tasks.create")}
          </button>
        </div>
      </header>

      {hasSelection && (
        <div className={styles.bulkBar}>
          <span className={styles.bulkCount}>
            {t("tasks.selected")} {selected.size} {t("tasks.unit")}
          </span>
          <div className={styles.moveWrap} ref={moveMenuRef}>
            <button
              type="button"
              className={styles.bulkButton}
              onClick={() => setMoveMenuOpen((open) => !open)}
            >
              {t("tasks.move")}
            </button>
            {moveMenuOpen && (
              <div className={styles.moveMenu} role="menu">
                {projectNames.map((name) => (
                  <button
                    key={name}
                    type="button"
                    role="menuitem"
                    className={styles.moveItem}
                    onClick={() => bulkMove.mutate({ keys: [...selected], target: name })}
                  >
                    {name}
                  </button>
                ))}
                <div className={styles.moveNewRow}>
                  <input
                    className={styles.moveNewInput}
                    placeholder={t("tasks.moveNew")}
                    value={newCategory}
                    onChange={(event) => setNewCategory(event.target.value)}
                  />
                  <button
                    type="button"
                    className={styles.bulkButton}
                    disabled={newCategory.trim() === "" || bulkMove.isPending}
                    onClick={() =>
                      bulkMove.mutate({ keys: [...selected], target: newCategory.trim() })
                    }
                  >
                    {t("tasks.moveApply")}
                  </button>
                </div>
              </div>
            )}
          </div>
          <button
            type="button"
            className={styles.bulkDanger}
            onClick={() => setConfirmingDelete(true)}
          >
            {t("tasks.delete")}
          </button>
          <button
            type="button"
            className={styles.bulkButton}
            onClick={() => setSelected(new Set())}
          >
            {t("tasks.clearSelection")}
          </button>
          {bulkNote && <span className={styles.bulkNote}>{bulkNote}</span>}
        </div>
      )}
      {!hasSelection && bulkNote && <p className={styles.bulkNoteLine}>{bulkNote}</p>}

      {taskKind === "comic" && rows && rows.length === 0 ? (
        // The comic pipeline is not implemented yet (its create option is
        // disabled), so its domain view gets a placeholder instead of the
        // generic drag-a-video onboarding guide.
        <div className={styles.empty}>{t("tasks.domainUnavailable")}</div>
      ) : rows && rows.length === 0 && statusFilter === "" ? (
        <EmptyGuide onOpenSettings={onOpenSettings} />
      ) : rows && rows.length === 0 ? (
        <div className={styles.empty}>{t("tasks.empty")}</div>
      ) : (
        <div className={styles.groups}>
          {groups.map(([project, groupRows]) => {
            const isCollapsed = collapsed.has(project);
            return (
              <section key={project} className={styles.group}>
                <div
                  data-testid={`group-header-${project}`}
                  data-drop-project={project}
                  className={`${styles.groupHead} ${
                    drag?.over === project ? styles.dropActive : ""
                  }`}
                >
                  <button
                    type="button"
                    className={styles.groupToggle}
                    aria-expanded={!isCollapsed}
                    onClick={() => toggleCollapse(project)}
                  >
                    <span
                      className={`${styles.chevron} ${isCollapsed ? styles.chevronClosed : ""}`}
                    >
                      <Icon name="chevron-down" size={14} />
                    </span>
                    <span className={styles.groupName}>{project}</span>
                    <span className={styles.groupCount}>{groupRows.length}</span>
                  </button>
                </div>
                {!isCollapsed &&
                  groupRows.map((row) => {
                    const key = rowKey(row);
                    return (
                      <div
                        key={row.id}
                        className={styles.row}
                        onPointerDown={(event) => startRowDrag(event, key)}
                        onClick={() => {
                          if (suppressClickRef.current) {
                            suppressClickRef.current = false;
                            return;
                          }
                          onOpenTask(row.project, row.id);
                        }}
                      >
                        <input
                          type="checkbox"
                          className={styles.check}
                          aria-label={`${t("tasks.selectRow")} ${row.name || row.id}`}
                          checked={selected.has(key)}
                          onClick={(event) => event.stopPropagation()}
                          onChange={() => toggleSelect(key)}
                        />
                        <div className={styles.rowMain}>
                          <div className={styles.rowName}>{row.name || row.id}</div>
                        </div>
                        <span className={styles.rowProfile}>{row.profile}</span>
                        <StatusBadge status={row.status} />
                        <span className={styles.rowTime}>{formatDateTime(row.updated_at)}</span>
                      </div>
                    );
                  })}
              </section>
            );
          })}
        </div>
      )}

      {drag && (
        <div className={styles.dragGhost} style={{ left: drag.x + 14, top: drag.y + 14 }}>
          {t("tasks.moveApply")} {drag.keys.length} {t("tasks.unit")}
        </div>
      )}

      {confirmingDelete && (
        <div className={styles.scrim}>
          <div
            role="dialog"
            aria-modal="true"
            aria-label={t("tasks.deleteTitle")}
            className={styles.confirm}
            onKeyDown={(event) => {
              if (event.key === "Escape") setConfirmingDelete(false);
            }}
          >
            <p className={styles.confirmMessage}>
              {t("tasks.deleteConfirm1")} {selected.size} {t("tasks.deleteConfirm2")}
            </p>
            <div className={styles.confirmActions}>
              <button
                type="button"
                autoFocus
                className={styles.bulkButton}
                onClick={() => setConfirmingDelete(false)}
              >
                {t("tasks.deleteCancel")}
              </button>
              <button
                type="button"
                className={styles.confirmDelete}
                disabled={bulkDelete.isPending}
                onClick={() => bulkDelete.mutate()}
              >
                {t("tasks.deleteApply")}
              </button>
            </div>
          </div>
        </div>
      )}

      {creating && (
        <CreateTaskDialog
          initialPath={droppedPath ?? undefined}
          onClose={() => {
            setCreating(false);
            onConsumeDrop?.();
          }}
          onCreated={(project, taskId) => {
            setCreating(false);
            onConsumeDrop?.();
            onOpenTask(project, taskId);
          }}
        />
      )}
    </div>
  );
}
