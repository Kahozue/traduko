import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { t } from "../i18n";
import { useApi } from "../lib/connection";
import type { GlossaryEntry } from "../lib/api/types";
import styles from "./GlossaryEditorView.module.css";

// Full-screen glossary entry editor, drilled into from a settings glossary
// section. Follows the SkillEditorView shape: back with unsaved-changes guard,
// dirty/saved markers, explicit save. Entries are grouped by category
// (collapsible); the row order is the manifest/priority order.

type Row = GlossaryEntry & { selected: boolean };

const UNCATEGORIZED = "";

export function GlossaryEditorView({
  glossaryId,
  onBack,
}: {
  glossaryId: string;
  onBack: () => void;
}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["glossary", glossaryId],
    queryFn: () => api.getGlossary(glossaryId),
  });

  const [rows, setRows] = useState<Row[]>([]);
  const [name, setName] = useState("");
  const [loadedFrom, setLoadedFrom] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [confirmLeave, setConfirmLeave] = useState(false);
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (data && data.updated_at !== loadedFrom) {
      if (!dirty) {
        setRows(data.entries.map((entry) => ({ ...entry, selected: false })));
        setName(data.name);
      }
      setLoadedFrom(data.updated_at);
    }
  }, [data, loadedFrom, dirty]);

  function markDirty() {
    setDirty(true);
    setSaved(false);
  }

  function updateRow(index: number, patch: Partial<GlossaryEntry>) {
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
    markDirty();
  }

  function toggleSelect(index: number) {
    setRows((prev) =>
      prev.map((row, i) => (i === index ? { ...row, selected: !row.selected } : row)),
    );
  }

  function move(index: number, delta: number) {
    setRows((prev) => {
      const next = [...prev];
      const target = index + delta;
      if (target < 0 || target >= next.length) return prev;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
    markDirty();
  }

  function addRow() {
    setRows((prev) => [
      ...prev,
      { source: "", target: "", notes: "", category: "", selected: false },
    ]);
    markDirty();
  }

  function deleteSelected() {
    setRows((prev) => prev.filter((row) => !row.selected));
    markDirty();
  }

  function toggleCollapse(category: string) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });
  }

  const nameDirty = data !== undefined && name !== data.name;

  const save = useMutation({
    mutationFn: async () => {
      if (nameDirty) await api.patchGlossary(glossaryId, { name: name.trim() });
      const entries: GlossaryEntry[] = rows
        .filter((row) => row.source.trim() && row.target.trim())
        .map(({ source, target, notes, category }) => ({
          source: source.trim(),
          target: target.trim(),
          notes: notes.trim(),
          category: category.trim(),
        }));
      await api.putGlossaryEntries(glossaryId, entries);
    },
    onSuccess: () => {
      setDirty(false);
      setSaved(true);
      void queryClient.invalidateQueries({ queryKey: ["glossary", glossaryId] });
      void queryClient.invalidateQueries({ queryKey: ["glossaries"] });
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

  async function onExport() {
    const content = await api.exportGlossary(glossaryId, "csv");
    const url = URL.createObjectURL(new Blob([content], { type: "text/csv" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${glossaryId}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  function handleBack() {
    if (dirty || nameDirty) setConfirmLeave(true);
    else onBack();
  }

  const query = search.trim().toLowerCase();
  const visible = rows.map((row, index) => ({ row, index })).filter(({ row }) => {
    if (!query) return true;
    return (
      row.source.toLowerCase().includes(query) ||
      row.target.toLowerCase().includes(query) ||
      row.notes.toLowerCase().includes(query) ||
      row.category.toLowerCase().includes(query)
    );
  });
  // Group by category value while tracking each row's index in the full list;
  // grouping by object identity breaks when identical rows dedupe.
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

  return (
    <div>
      <button type="button" className={styles.back} onClick={handleBack}>
        {t("glossary.editor.back")}
      </button>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>{t("glossary.editor.title")}</h1>
          <input
            className={styles.nameInput}
            aria-label={t("settings.glossary.name")}
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              markDirty();
            }}
          />
        </div>
        <div className={styles.actions}>
          {(dirty || nameDirty) && (
            <span className={styles.dirty}>{t("glossary.editor.dirty")}</span>
          )}
          {saved && <span className={styles.saved}>{t("glossary.editor.saved")}</span>}
          <button
            type="button"
            className={styles.secondary}
            onClick={() => void onExport()}
          >
            {t("settings.glossary.export")}
          </button>
          <button
            type="button"
            className={styles.primary}
            disabled={(!dirty && !nameDirty) || save.isPending}
            onClick={() => save.mutate()}
          >
            {t("glossary.editor.save")}
          </button>
        </div>
      </header>

      <div className={styles.toolbar}>
        <input
          type="search"
          className={styles.search}
          role="searchbox"
          aria-label={t("glossary.editor.search")}
          placeholder={t("glossary.editor.searchPlaceholder")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
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

      {isLoading ? (
        <p className={styles.state}>{t("editor.loading")}</p>
      ) : isError ? (
        <p className={styles.state}>{t("glossary.editor.loadFailed")}</p>
      ) : (
        groups.map(({ category, items }) => (
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
                  <span className={styles.colCategory}>
                    {t("glossary.editor.colCategory")}
                  </span>
                  <span className={styles.colMove} />
                </div>
                {items.map(({ row, index }) => (
                    <div key={index} className={styles.row}>
                      <input
                        type="checkbox"
                        className={styles.colCheck}
                        aria-label={`${t("glossary.editor.select")} ${row.source}`}
                        checked={row.selected}
                        onChange={() => toggleSelect(index)}
                      />
                      <input
                        className={`${styles.cell} ${styles.colSource}`}
                        aria-label={t("glossary.editor.colSource")}
                        placeholder={t("glossary.editor.colSource")}
                        value={row.source}
                        onChange={(event) => updateRow(index, { source: event.target.value })}
                      />
                      <input
                        className={`${styles.cell} ${styles.colTarget}`}
                        aria-label={t("glossary.editor.colTarget")}
                        placeholder={t("glossary.editor.colTarget")}
                        value={row.target}
                        onChange={(event) => updateRow(index, { target: event.target.value })}
                      />
                      <input
                        className={`${styles.cell} ${styles.colNotes}`}
                        aria-label={t("glossary.editor.colNotes")}
                        value={row.notes}
                        onChange={(event) => updateRow(index, { notes: event.target.value })}
                      />
                      <input
                        className={`${styles.cell} ${styles.colCategory}`}
                        aria-label={t("glossary.editor.colCategory")}
                        value={row.category}
                        onChange={(event) =>
                          updateRow(index, { category: event.target.value })
                        }
                      />
                      <span className={styles.colMove}>
                        <button
                          type="button"
                          className={styles.moveButton}
                          aria-label={`${t("glossary.editor.moveUp")} ${row.source}`}
                          onClick={() => move(index, -1)}
                        >
                          ↑
                        </button>
                        <button
                          type="button"
                          className={styles.moveButton}
                          aria-label={`${t("glossary.editor.moveDown")} ${row.source}`}
                          onClick={() => move(index, 1)}
                        >
                          ↓
                        </button>
                      </span>
                    </div>
                ))}
              </div>
            )}
          </div>
        ))
      )}

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
    </div>
  );
}
