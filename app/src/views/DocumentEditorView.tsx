import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { t, type MessageKey } from "../i18n";
import type {
  DocChunksArtifact,
  DocTranslationArtifact,
  DocTranslatedChunk,
  DocumentArtifact,
  QcArtifact,
  QcFlagType,
} from "../lib/api/types";
import { useApi } from "../lib/connection";
import styles from "./DocumentEditorView.module.css";

interface DocRow {
  blockId: string;
  chunkId: string;
  chapterId: string;
  source: string;
}

const QC_LABEL: Record<QcFlagType, MessageKey> = {
  untranslated: "editor.qc.untranslated",
  echo: "editor.qc.echo",
  glossary: "editor.qc.glossary",
  failed: "editor.qc.failed",
  manual: "editor.qc.manual",
};

// A note typed on a block the checker never flagged.
const MANUAL: QcFlagType = "manual";

export function DocumentEditorView({
  project,
  taskId,
  onBack,
}: {
  project: string;
  taskId: string;
  onBack: () => void;
}) {
  const api = useApi();
  const { data: document } = useQuery({
    queryKey: ["artifact", project, taskId, "document.json"],
    queryFn: () => api.readArtifact<DocumentArtifact>(project, taskId, "document.json"),
  });
  const { data: chunks } = useQuery({
    queryKey: ["artifact", project, taskId, "chunks.json"],
    queryFn: () => api.readArtifact<DocChunksArtifact>(project, taskId, "chunks.json"),
  });
  const { data: translation, isLoading } = useQuery({
    queryKey: ["artifact", project, taskId, "doc-translation.json"],
    queryFn: () =>
      api.readArtifact<DocTranslationArtifact>(project, taskId, "translation.json"),
  });
  const { data: qc } = useQuery({
    queryKey: ["artifact", project, taskId, "qc.json"],
    queryFn: () =>
      api
        .readArtifact<QcArtifact>(project, taskId, "qc.json")
        .catch(() => ({ schema_version: 1, flags: [] }) as QcArtifact),
  });

  const [targets, setTargets] = useState<Record<string, string>>({});
  // Notes are editable like the translation: the qc pass seeds them, and a
  // human can correct one or write one where the checker flagged nothing.
  const [notes, setNotes] = useState<Record<string, { type: QcFlagType; evidence: string }>>(
    {},
  );
  const [notesDirty, setNotesDirty] = useState(false);
  const [loadedFrom, setLoadedFrom] = useState<DocTranslationArtifact | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [replaceText, setReplaceText] = useState("");
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [confirmLeave, setConfirmLeave] = useState(false);

  const gridRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (translation && translation !== loadedFrom) {
      const next: Record<string, string> = {};
      for (const chunk of translation.chunks) {
        for (const block of chunk.blocks) next[block.id] = block.text;
      }
      setTargets(next);
      setLoadedFrom(translation);
    }
  }, [translation, loadedFrom]);

  const rows = useMemo<DocRow[]>(() => {
    if (!document || !chunks) return [];
    const sources = new Map<string, string>();
    for (const chapter of document.chapters) {
      for (const block of chapter.blocks) sources.set(block.id, block.text);
    }
    const list: DocRow[] = [];
    for (const chunk of chunks.chunks) {
      for (const blockId of chunk.block_ids) {
        list.push({
          blockId,
          chunkId: chunk.id,
          chapterId: chunk.chapter_id,
          source: sources.get(blockId) ?? "",
        });
      }
    }
    return list;
  }, [document, chunks]);

  const chapterTitles = useMemo(() => {
    const map = new Map<string, string>();
    for (const chapter of document?.chapters ?? []) {
      map.set(chapter.id, chapter.title || chapter.href || chapter.id);
    }
    return map;
  }, [document]);

  const multiChapter = useMemo(
    () => new Set(rows.map((row) => row.chapterId)).size > 1,
    [rows],
  );

  // A chunk-level flag has no block of its own, so it lands on the chunk's
  // first block; that is also the block it is written back from.
  useEffect(() => {
    if (!qc || rows.length === 0) return;
    const firstBlockOfChunk = new Map<string, string>();
    for (const row of rows) {
      if (!firstBlockOfChunk.has(row.chunkId)) {
        firstBlockOfChunk.set(row.chunkId, row.blockId);
      }
    }
    const next: Record<string, { type: QcFlagType; evidence: string }> = {};
    for (const flag of qc.flags ?? []) {
      const blockId = flag.block_id || firstBlockOfChunk.get(flag.chunk_id);
      if (!blockId || blockId in next) continue;
      next[blockId] = { type: flag.type, evidence: flag.evidence };
    }
    setNotes(next);
    setNotesDirty(false);
  }, [qc, rows]);

  // Derived from the edited notes, not the fetched report, so the flagged-only
  // filter and the flag jumps follow what is on screen.
  const flagById = useMemo(() => {
    const map = new Map<string, { badge: string; text: string }>();
    for (const [blockId, entry] of Object.entries(notes)) {
      if (entry.evidence.trim() === "") continue;
      map.set(blockId, { badge: t(QC_LABEL[entry.type]), text: entry.evidence });
    }
    return map;
  }, [notes]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return rows.filter((row) => {
      if (flaggedOnly && !flagById.has(row.blockId)) return false;
      if (!needle) return true;
      const target = targets[row.blockId] ?? "";
      return (
        row.source.toLowerCase().includes(needle) ||
        target.toLowerCase().includes(needle)
      );
    });
  }, [rows, query, flaggedOnly, flagById, targets]);

  const save = useMutation({
    mutationFn: async () => {
      const prior = new Map<string, DocTranslatedChunk>();
      for (const chunk of translation?.chunks ?? []) prior.set(chunk.id, chunk);
      const rebuilt = (chunks?.chunks ?? []).map((chunk) => {
        const blocks = chunk.block_ids.map((id) => ({ id, text: targets[id] ?? "" }));
        const complete = blocks.every((block) => block.text !== "");
        const status = complete
          ? "translated"
          : (prior.get(chunk.id)?.status ?? "pending");
        return { id: chunk.id, status, blocks };
      });
      await api.saveArtifact(project, taskId, "translation.json", {
        schema_version: translation?.schema_version ?? 1,
        chunks: rebuilt,
      });
      if (!notesDirty) return;
      const chunkOfBlock = new Map(rows.map((row) => [row.blockId, row.chunkId]));
      const flags = Object.entries(notes)
        .filter(([, entry]) => entry.evidence.trim() !== "")
        .map(([blockId, entry]) => ({
          chunk_id: chunkOfBlock.get(blockId) ?? "",
          block_id: blockId,
          type: entry.type,
          evidence: entry.evidence.trim(),
        }));
      await api.saveArtifact(project, taskId, "qc.json", {
        schema_version: qc?.schema_version ?? 1,
        flags,
      });
    },
    onSuccess: () => {
      setDirty(false);
      setNotesDirty(false);
      setSaved(true);
    },
  });

  const saveRef = useRef({ dirty, pending: save.isPending, mutate: () => save.mutate() });
  saveRef.current = { dirty, pending: save.isPending, mutate: () => save.mutate() };

  function editTarget(blockId: string, value: string) {
    setTargets((prev) => ({ ...prev, [blockId]: value }));
    setDirty(true);
    setSaved(false);
  }

  function editNote(blockId: string, value: string) {
    setNotes((prev) => ({
      ...prev,
      [blockId]: { type: prev[blockId]?.type ?? MANUAL, evidence: value },
    }));
    setNotesDirty(true);
    setDirty(true);
    setSaved(false);
  }

  function activate(blockId: string) {
    setActiveId(blockId);
    const row = gridRef.current?.querySelector(`[data-block-id="${blockId}"]`);
    row?.scrollIntoView?.({ block: "nearest" });
  }

  function moveActive(offset: number) {
    if (activeId === null) return;
    const idx = visible.findIndex((row) => row.blockId === activeId);
    const next = visible[idx + offset];
    if (next) activate(next.blockId);
    else setActiveId(null);
  }

  function jumpFlag(direction: 1 | -1) {
    const flagged = visible.filter((row) => flagById.has(row.blockId));
    if (flagged.length === 0) return;
    const idx =
      activeId === null ? -1 : flagged.findIndex((row) => row.blockId === activeId);
    const next =
      direction === 1
        ? flagged[idx + 1] ?? flagged[0]
        : flagged[idx - 1 < 0 ? flagged.length - 1 : idx - 1];
    activate(next.blockId);
  }

  const jumpFlagRef = useRef(jumpFlag);
  jumpFlagRef.current = jumpFlag;

  function replaceAll() {
    const needle = query.trim();
    if (!needle) return;
    let changed = false;
    const next = { ...targets };
    for (const row of visible) {
      const current = next[row.blockId] ?? "";
      if (!current.includes(needle)) continue;
      changed = true;
      next[row.blockId] = current.split(needle).join(replaceText);
    }
    if (!changed) return;
    setTargets(next);
    setDirty(true);
    setSaved(false);
  }

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        const { dirty: isDirty, pending, mutate } = saveRef.current;
        if (isDirty && !pending) mutate();
      } else if ((e.metaKey || e.ctrlKey) && e.key === "f") {
        e.preventDefault();
        searchRef.current?.focus();
      } else if (e.altKey && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
        e.preventDefault();
        jumpFlagRef.current(e.key === "ArrowDown" ? 1 : -1);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function handleBack() {
    if (dirty) setConfirmLeave(true);
    else onBack();
  }

  if (isLoading) return <p className={styles.state}>{t("editor.loading")}</p>;
  if (!document || !chunks || !translation || rows.length === 0) {
    return <p className={styles.state}>{t("editor.empty")}</p>;
  }

  let lastChapter: string | null = null;

  return (
    <div>
      <button type="button" className={styles.back} onClick={handleBack}>
        {t("editor.back")}
      </button>
      <header className={styles.header}>
        <h1 className={styles.title}>{t("editor.document.title")}</h1>
        <div className={styles.actions}>
          {dirty && <span className={styles.dirty}>{t("editor.dirty")}</span>}
          {saved && <span className={styles.saved}>{t("editor.saved")}</span>}
          <button
            type="button"
            className={styles.primary}
            disabled={!dirty || save.isPending}
            onClick={() => save.mutate()}
          >
            {t("editor.save")}
          </button>
        </div>
      </header>

      <div className={styles.toolbar}>
        <input
          ref={searchRef}
          type="search"
          className={styles.search}
          aria-label={t("editor.search.label")}
          placeholder={t("editor.search.placeholder")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <input
          type="text"
          className={styles.replace}
          aria-label={t("editor.replace.label")}
          placeholder={t("editor.replace.label")}
          value={replaceText}
          onChange={(e) => setReplaceText(e.target.value)}
        />
        <button
          type="button"
          className={styles.toolButton}
          disabled={!query.trim()}
          onClick={replaceAll}
        >
          {t("editor.replace.apply")}
        </button>
        <label className={styles.flaggedToggle}>
          <input
            type="checkbox"
            checked={flaggedOnly}
            onChange={(e) => setFlaggedOnly(e.target.checked)}
          />
          {t("editor.filter.flagged")}
        </label>
        <span className={styles.rowCount}>
          {visible.length === rows.length
            ? `${rows.length} ${t("editor.rows.unit")}`
            : `${visible.length} / ${rows.length} ${t("editor.rows.unit")}`}
        </span>
        <span className={styles.spacer} />
        <button type="button" className={styles.toolButton} onClick={() => jumpFlag(-1)}>
          {t("editor.flag.prev")}
        </button>
        <button type="button" className={styles.toolButton} onClick={() => jumpFlag(1)}>
          {t("editor.flag.next")}
        </button>
      </div>

      <div
        ref={gridRef}
        className={styles.grid}
        role="table"
        aria-label={t("editor.document.title")}
      >
        <div className={`${styles.row} ${styles.headRow}`} role="row">
          <span role="columnheader" className={styles.headCell}>{t("editor.col.index")}</span>
          <span role="columnheader" className={styles.headCell}>{t("editor.col.source")}</span>
          <span role="columnheader" className={styles.headCell}>{t("editor.col.target")}</span>
          <span role="columnheader" className={styles.headCell}>{t("editor.col.qc")}</span>
        </div>
        {visible.map((row, index) => {
          const flag = flagById.get(row.blockId);
          const target = targets[row.blockId] ?? "";
          const active = activeId === row.blockId;
          const rowClass = [
            styles.row,
            styles.bodyRow,
            flag ? styles.flagged : "",
            active ? styles.active : "",
          ]
            .filter(Boolean)
            .join(" ");
          const chapterBreak =
            multiChapter && row.chapterId !== lastChapter ? row.chapterId : null;
          lastChapter = row.chapterId;
          return (
            <Fragment key={row.blockId}>
              {chapterBreak && (
                <div className={styles.chapterRow} role="row">
                  <span role="cell" className={styles.chapterLabel}>
                    {chapterTitles.get(chapterBreak) ?? chapterBreak}
                  </span>
                </div>
              )}
              <div
                role="row"
                data-block-id={row.blockId}
                className={rowClass}
                onClick={() => activate(row.blockId)}
              >
                <span role="cell" className={styles.num}>{index + 1}</span>
                <span role="cell" className={styles.source}>{row.source}</span>
                <span role="cell" className={styles.targetCell}>
                  {active ? (
                    <textarea
                      autoFocus
                      className={styles.target}
                      aria-label={t("editor.col.target")}
                      value={target}
                      onChange={(e) => editTarget(row.blockId, e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          moveActive(1);
                        } else if (e.key === "Tab") {
                          e.preventDefault();
                          moveActive(e.shiftKey ? -1 : 1);
                        } else if (e.key === "Escape") {
                          setActiveId(null);
                        }
                      }}
                    />
                  ) : (
                    <span className={styles.targetText}>{target}</span>
                  )}
                </span>
                <span role="cell" className={styles.flag}>
                  {active ? (
                    <textarea
                      className={styles.note}
                      aria-label={t("editor.col.qc")}
                      placeholder={t("editor.qc.placeholder")}
                      value={notes[row.blockId]?.evidence ?? ""}
                      onChange={(e) => editNote(row.blockId, e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Escape") setActiveId(null);
                      }}
                    />
                  ) : (
                    <>
                      {flag && (
                        <span className={styles.flagBadge} title={flag.text}>
                          {flag.badge}
                        </span>
                      )}
                      {flag?.text}
                    </>
                  )}
                </span>
              </div>
            </Fragment>
          );
        })}
      </div>
      <p className={styles.shortcuts}>{t("editor.shortcuts")}</p>

      {confirmLeave && (
        <div className={styles.scrim}>
          <div
            role="dialog"
            aria-modal="true"
            aria-label={t("editor.leave.title")}
            className={styles.confirm}
            onKeyDown={(e) => {
              if (e.key === "Escape") setConfirmLeave(false);
            }}
          >
            <p className={styles.confirmMessage}>{t("editor.leave.message")}</p>
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
