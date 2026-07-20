import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { t } from "../i18n";
import { useApi } from "../lib/connection";
import type { GlossaryEntry, GlossaryTable, TaskGlossary } from "../lib/api/types";
import styles from "./TaskGlossaryView.module.css";

type AsrMode = TaskGlossary["asr_mode"];
type ReapplyMode = "asr" | "proofread" | "translate";

const UNCATEGORIZED = "";

type Row = GlossaryEntry & { selected: boolean };

// Which glossary domain a task belongs to, from its stage makeup; mirrors
// the domain split the settings tabs and the core's profile kinds use.
const AUDIO_DOMAIN_STAGES = ["export_transcript", "export_audio"];
const DOCUMENT_STAGES = [
  "ingest_document",
  "chunk",
  "translate_chunks",
  "export_document",
  "translate_pdf",
];
const COMIC_STAGES = ["ingest_comic", "bubble_detect", "ocr", "inpaint", "typeset"];

function domainOf(task: { stages: { type: string }[] } | undefined): string {
  const types = new Set((task?.stages ?? []).map((stage) => stage.type));
  if (COMIC_STAGES.some((type) => types.has(type))) return "comic";
  if (AUDIO_DOMAIN_STAGES.some((type) => types.has(type))) return "audio";
  if (DOCUMENT_STAGES.some((type) => types.has(type))) return "document";
  return "video";
}

const DOMAIN_LABELS: Record<string, Parameters<typeof t>[0]> = {
  video: "task.glossary.domain.video",
  audio: "task.glossary.domain.audio",
  document: "task.glossary.domain.document",
  general: "task.glossary.domain.general",
  comic: "task.glossary.domain.comic",
};

export function TaskGlossaryView({
  project,
  taskId,
  onBack,
}: {
  project: string;
  taskId: string;
  onBack: () => void;
}) {
  const api = useApi();
  const queryClient = useQueryClient();

  const { data: task } = useQuery({
    queryKey: ["task", project, taskId],
    queryFn: () => api.showTask(project, taskId),
  });

  const { data: allGlossaries } = useQuery({
    queryKey: ["glossaries"],
    queryFn: () => api.listGlossaries(),
  });

  const { data: taskEntries } = useQuery({
    queryKey: ["task-glossary-entries", project, taskId],
    queryFn: () => api.getTaskGlossaryEntries(project, taskId),
    enabled: !!task?.glossary?.use_task,
  });

  const [globalIds, setGlobalIds] = useState<string[]>([]);
  const [useTask, setUseTask] = useState(false);
  const [asrMode, setAsrMode] = useState<AsrMode>("auto");
  const [dirty, setDirty] = useState(false);
  const [confirmLeave, setConfirmLeave] = useState(false);
  const [reapplyMode, setReapplyMode] = useState<ReapplyMode | null>(null);

  // Task-local entry editing state
  const [rows, setRows] = useState<Row[]>([]);
  const [loadedFrom, setLoadedFrom] = useState<string | null>(null);
  const [entrySearch, setEntrySearch] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  // Initialize from task data
  useEffect(() => {
    if (task?.glossary) {
      setGlobalIds(task.glossary.global_ids);
      setUseTask(task.glossary.use_task);
      setAsrMode(task.glossary.asr_mode);
      setDirty(false);
    }
  }, [task?.glossary]);

  // Load task entries when useTask is enabled
  useEffect(() => {
    if (taskEntries && loadedFrom !== String(taskEntries.entries.length)) {
      setRows(taskEntries.entries.map((e) => ({ ...e, selected: false })));
      setLoadedFrom(String(taskEntries.entries.length));
    }
  }, [taskEntries, loadedFrom]);

  function toggleGlobal(id: string) {
    setGlobalIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
    setDirty(true);
  }

  function handleAsrMode(mode: AsrMode) {
    setAsrMode(mode);
    setDirty(true);
  }

  function handleUseTask(value: boolean) {
    setUseTask(value);
    setDirty(true);
  }

  // Task-local entry editing helpers
  function markEntryDirty() {
    setDirty(true);
  }

  function updateRow(index: number, patch: Partial<GlossaryEntry>) {
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
    markEntryDirty();
  }

  function toggleSelect(index: number) {
    setRows((prev) =>
      prev.map((row, i) => (i === index ? { ...row, selected: !row.selected } : row)),
    );
  }

  function addRow() {
    setRows((prev) => [
      ...prev,
      { source: "", target: "", notes: "", category: "", selected: false },
    ]);
    markEntryDirty();
  }

  function deleteSelected() {
    setRows((prev) => prev.filter((row) => !row.selected));
    markEntryDirty();
  }

  function toggleCollapse(category: string) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });
  }

  const save = useMutation({
    mutationFn: async () => {
      await api.setTaskGlossary(project, taskId, {
        global_ids: globalIds,
        use_task: useTask,
        asr_mode: asrMode,
      });
      if (useTask) {
        const entries: GlossaryEntry[] = rows
          .filter((row) => row.source.trim() && row.target.trim())
          .map(({ source, target, notes, category }) => ({
            source: source.trim(),
            target: target.trim(),
            notes: notes.trim(),
            category: category.trim(),
          }));
        await api.putTaskGlossaryEntries(project, taskId, entries);
      }
    },
    onSuccess: () => {
      setDirty(false);
      void queryClient.invalidateQueries({ queryKey: ["task", project, taskId] });
      void queryClient.invalidateQueries({
        queryKey: ["task-glossary-entries", project, taskId],
      });
    },
  });

  const reapply = useMutation({
    mutationFn: (mode: ReapplyMode) => api.reapplyGlossary(project, taskId, mode),
    onSuccess: () => {
      setReapplyMode(null);
      void queryClient.invalidateQueries({ queryKey: ["task", project, taskId] });
    },
  });

  const saveRef = useRef({ dirty, pending: save.isPending, mutate: () => save.mutate() });
  saveRef.current = { dirty, pending: save.isPending, mutate: () => save.mutate() };

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        const { dirty: isDirty, pending, mutate } = saveRef.current;
        if (isDirty && !pending) mutate();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function handleBack() {
    if (dirty) setConfirmLeave(true);
    else onBack();
  }

  // Determine which reapply buttons to show based on task state
  const hasAsr = (task?.stages ?? []).some((s) => s.type === "asr");
  const hasTranslate = (task?.stages ?? []).some((s) =>
    ["translate", "translate_chunks"].includes(s.type),
  );

  // Group global glossaries by domain, listing this task's domain and the
  // general tables only (spec 3-(4)): a video task picking document tables
  // is noise, not choice.
  const taskDomain = domainOf(task);
  const glossariesByDomain = new Map<string, GlossaryTable[]>();
  for (const g of allGlossaries ?? []) {
    if (g.domain !== taskDomain && g.domain !== "general") continue;
    if (!glossariesByDomain.has(g.domain)) glossariesByDomain.set(g.domain, []);
    glossariesByDomain.get(g.domain)!.push(g);
  }
  const domainOrder = [taskDomain, "general"];

  // Task-local entry table: filter and group
  const query = entrySearch.trim().toLowerCase();
  const visible = rows.map((row, index) => ({ row, index })).filter(({ row }) => {
    if (!query) return true;
    return (
      row.source.toLowerCase().includes(query) ||
      row.target.toLowerCase().includes(query) ||
      row.notes.toLowerCase().includes(query) ||
      row.category.toLowerCase().includes(query)
    );
  });
  const groupOrder: string[] = [];
  const groupMap = new Map<string, { row: Row; index: number }[]>();
  for (const item of visible) {
    const key = item.row.category || UNCATEGORIZED;
    if (!groupMap.has(key)) {
      groupMap.set(key, []);
      groupOrder.push(key);
    }
    groupMap.get(key)!.push(item);
  }
  const groups = groupOrder.map((key) => ({ category: key, items: groupMap.get(key)! }));
  const selectedCount = rows.filter((row) => row.selected).length;

  const reapplyModes: ReapplyMode[] = [];
  if (hasAsr) reapplyModes.push("asr", "proofread");
  if (hasTranslate) reapplyModes.push("translate");

  return (
    <div>
      <button type="button" className={styles.back} onClick={handleBack}>
        {t("glossary.editor.back")}
      </button>

      <header className={styles.header}>
        <h1 className={styles.title}>{t("task.glossary.title")}</h1>
        <div className={styles.actions}>
          {dirty && <span className={styles.dirty}>{t("task.glossary.dirty")}</span>}
          <button
            type="button"
            className={styles.primary}
            disabled={!dirty || save.isPending}
            onClick={() => save.mutate()}
          >
            {t("glossary.editor.save")}
          </button>
        </div>
      </header>

      {/* Global glossary checkboxes */}
      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("task.glossary.globalTables")}</h2>
        <input
          type="search"
          className={styles.search}
          role="searchbox"
          aria-label={t("task.glossary.search")}
          placeholder={t("task.glossary.search")}
          value={entrySearch}
          onChange={(e) => setEntrySearch(e.target.value)}
        />
        {domainOrder.map((domain) => {
          const tables = glossariesByDomain.get(domain);
          if (!tables?.length) return null;
          return (
            <div key={domain} className={styles.domainGroup}>
              <h3 className={styles.domainTitle}>
                {DOMAIN_LABELS[domain] ? t(DOMAIN_LABELS[domain]) : domain}
              </h3>
              {tables.map((table) => (
                <label key={table.id} className={styles.checkRow}>
                  <input
                    type="checkbox"
                    checked={globalIds.includes(table.id)}
                    onChange={() => toggleGlobal(table.id)}
                  />
                  <span className={styles.checkName}>{table.name}</span>
                  <span className={styles.checkCount}>
                    {table.entry_count} {t("settings.glossary.entriesUnit")}
                  </span>
                  <span className={styles.checkDomain}>{table.domain}</span>
                </label>
              ))}
            </div>
          );
        })}
      </section>

      {/* ASR mode */}
      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("task.glossary.asrMode")}</h2>
        <div className={styles.radioGroup}>
          {(["auto", "force", "off"] as AsrMode[]).map((mode) => (
            <label key={mode} className={styles.radioLabel}>
              <input
                type="radio"
                name="asr-mode"
                checked={asrMode === mode}
                onChange={() => handleAsrMode(mode)}
              />
              {t(`task.glossary.asrMode.${mode}`)}
            </label>
          ))}
        </div>
      </section>

      {/* Task-local table */}
      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t("task.glossary.taskTable")}</h2>
        <label className={styles.switchRow}>
          <input
            type="checkbox"
            checked={useTask}
            onChange={(e) => handleUseTask(e.target.checked)}
          />
          {t("task.glossary.enableTaskTable")}
        </label>
        {useTask && (
          <>
            <div className={styles.toolbar}>
              <input
                type="search"
                className={styles.search}
                role="searchbox"
                aria-label={t("glossary.editor.search")}
                placeholder={t("glossary.editor.searchPlaceholder")}
                value={entrySearch}
                onChange={(e) => setEntrySearch(e.target.value)}
              />
              <button type="button" className={styles.secondary} onClick={addRow}>
                {t("glossary.editor.addRow")}
              </button>
              <button
                type="button"
                className={styles.secondary}
                disabled={selectedCount === 0}
                onClick={deleteSelected}
              >
                {t("glossary.editor.deleteSelected")}
                {selectedCount > 0 ? ` (${selectedCount})` : ""}
              </button>
            </div>
            {groups.map(({ category, items }) => (
              <div key={category || "__none__"} className={styles.group}>
                <button
                  type="button"
                  className={styles.groupHead}
                  aria-expanded={!collapsed.has(category)}
                  onClick={() => toggleCollapse(category)}
                >
                  <span className={styles.groupChevron}>
                    {collapsed.has(category) ? "▸" : "▾"}
                  </span>
                  <span className={styles.groupName}>
                    {category || t("glossary.editor.uncategorized")}
                  </span>
                  <span className={styles.groupCount}>
                    {items.length} {t("settings.glossary.entriesUnit")}
                  </span>
                </button>
                {!collapsed.has(category) && (
                  <div className={styles.table}>
                    <div className={styles.rowHead}>
                      <span className={styles.colCheck} />
                      <span className={styles.colSource}>{t("glossary.editor.colSource")}</span>
                      <span className={styles.colTarget}>{t("glossary.editor.colTarget")}</span>
                      <span className={styles.colNotes}>{t("glossary.editor.colNotes")}</span>
                      <span className={styles.colCategory}>{t("glossary.editor.colCategory")}</span>
                    </div>
                    {items.map(({ row, index }) => (
                      <div key={index} className={styles.row}>
                        <input
                          type="checkbox"
                          className={styles.colCheck}
                          checked={row.selected}
                          onChange={() => toggleSelect(index)}
                        />
                        <input
                          className={`${styles.cell} ${styles.colSource}`}
                          value={row.source}
                          onChange={(e) => updateRow(index, { source: e.target.value })}
                        />
                        <input
                          className={`${styles.cell} ${styles.colTarget}`}
                          value={row.target}
                          onChange={(e) => updateRow(index, { target: e.target.value })}
                        />
                        <input
                          className={`${styles.cell} ${styles.colNotes}`}
                          value={row.notes}
                          onChange={(e) => updateRow(index, { notes: e.target.value })}
                        />
                        <input
                          className={`${styles.cell} ${styles.colCategory}`}
                          value={row.category}
                          onChange={(e) => updateRow(index, { category: e.target.value })}
                        />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </>
        )}
      </section>

      {/* Reapply section: hidden when the task supports none of the modes,
          which would otherwise render a framed box around one hint line. */}
      {dirty && reapplyModes.length > 0 && (
        <section
          className={styles.reapplySection}
          role="group"
          aria-label={t("task.glossary.reapply.title")}
        >
          <h2 className={styles.sectionTitle}>{t("task.glossary.reapply.title")}</h2>
          <p className={styles.reapplyHint}>{t("task.glossary.reapply.hint")}</p>
          <div className={styles.reapplyButtons}>
            {reapplyModes.map((mode) => (
              <button
                key={mode}
                type="button"
                className={styles.secondary}
                onClick={() => setReapplyMode(mode)}
              >
                {t(`task.glossary.reapply.${mode}`)}
              </button>
            ))}
          </div>
        </section>
      )}

      {/* Confirm dialogs */}
      {confirmLeave && (
        <div className={styles.scrim}>
          <div
            role="dialog"
            aria-modal="true"
            aria-label={t("glossary.editor.leaveTitle")}
            className={styles.confirm}
            onKeyDown={(e) => {
              if (e.key === "Escape") setConfirmLeave(false);
            }}
          >
            <p className={styles.confirmMessage}>{t("glossary.editor.leaveMessage")}</p>
            <div className={styles.confirmActions}>
              <button
                type="button"
                autoFocus
                className={styles.toolButton}
                onClick={() => setConfirmLeave(false)}
              >
                {t("editor.leave.stay")}
              </button>
              <button
                type="button"
                className={styles.discard}
                onClick={() => {
                  setConfirmLeave(false);
                  onBack();
                }}
              >
                {t("editor.leave.discard")}
              </button>
            </div>
          </div>
        </div>
      )}

      {reapplyMode && (
        <ConfirmDialog
          title={t(`task.glossary.reapply.confirm.title.${reapplyMode}`)}
          body={t(`task.glossary.reapply.confirm.body.${reapplyMode}`)}
          confirmLabel={t("task.glossary.reapply.confirm.confirm")}
          cancelLabel={t("task.glossary.reapply.confirm.cancel")}
          danger
          busy={reapply.isPending}
          onConfirm={() => reapply.mutate(reapplyMode)}
          onCancel={() => setReapplyMode(null)}
        />
      )}
    </div>
  );
}
