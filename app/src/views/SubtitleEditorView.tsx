import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { StyleEditorPanel } from "../components/StyleEditorPanel";
import { t } from "../i18n";
import type {
  ProofreadFlag,
  SubtitleStylePreset,
  TranslationArtifact,
  TranslationSegment,
} from "../lib/api/types";
import { useApi } from "../lib/connection";
import styles from "./SubtitleEditorView.module.css";

const STYLE_FALLBACK: SubtitleStylePreset = {
  font_name: "Arial", font_size: 48, primary_color: "#FFFFFF",
  outline_color: "#000000", outline: 2, shadow: 0, bold: false,
  alignment: 2, margin_v: 40,
};

function formatRange(start: number, end: number): string {
  const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  return `${fmt(start)}–${fmt(end)}`;
}

export function SubtitleEditorView({
  project,
  taskId,
  onBack,
}: {
  project: string;
  taskId: string;
  onBack: () => void;
}) {
  const api = useApi();
  const { data, isLoading } = useQuery({
    queryKey: ["artifact", project, taskId, "translation.json"],
    queryFn: () => api.readArtifact<TranslationArtifact>(project, taskId, "translation.json"),
  });
  const { data: report } = useQuery({
    queryKey: ["artifact", project, taskId, "proofread-report.json"],
    queryFn: () =>
      api
        .readArtifact<{ flags?: ProofreadFlag[] }>(project, taskId, "proofread-report.json")
        .catch(() => ({ flags: [] as ProofreadFlag[] })),
  });

  const [segments, setSegments] = useState<TranslationSegment[]>([]);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [replaceText, setReplaceText] = useState("");
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [confirmLeave, setConfirmLeave] = useState(false);
  const [tab, setTab] = useState<"subtitle" | "style">("subtitle");
  const [styleDraft, setStyleDraft] = useState<SubtitleStylePreset | null>(null);
  const [styleDirty, setStyleDirty] = useState(false);
  const [styleSaved, setStyleSaved] = useState(false);

  const { data: stylesDoc } = useQuery({ queryKey: ["styles"], queryFn: () => api.getStyles() });

  useEffect(() => {
    if (stylesDoc && styleDraft === null) {
      setStyleDraft(stylesDoc.default ?? STYLE_FALLBACK);
    }
  }, [stylesDoc, styleDraft]);

  const saveStyle = useMutation({
    mutationFn: () =>
      api.saveStyles({ ...(stylesDoc ?? {}), default: styleDraft ?? STYLE_FALLBACK }),
    onSuccess: () => {
      setStyleDirty(false);
      setStyleSaved(true);
    },
  });

  const gridRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (data) setSegments(data.segments);
  }, [data]);

  const flagById = useMemo(() => {
    const map = new Map<number, string>();
    for (const flag of report?.flags ?? []) map.set(flag.id, flag.note);
    return map;
  }, [report]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return segments.filter((seg) => {
      if (flaggedOnly && !flagById.has(seg.id)) return false;
      if (!needle) return true;
      return (
        seg.source.toLowerCase().includes(needle) || seg.target.toLowerCase().includes(needle)
      );
    });
  }, [segments, query, flaggedOnly, flagById]);

  const save = useMutation({
    mutationFn: () =>
      api.saveArtifact(project, taskId, "translation.json", {
        ...data,
        segments,
      }),
    onSuccess: () => {
      setDirty(false);
      setSaved(true);
    },
  });

  const saveRef = useRef<{ dirty: boolean; pending: boolean; mutate: () => void }>({
    dirty,
    pending: save.isPending,
    mutate: () => save.mutate(),
  });
  saveRef.current =
    tab === "subtitle"
      ? { dirty, pending: save.isPending, mutate: () => save.mutate() }
      : { dirty: styleDirty, pending: saveStyle.isPending, mutate: () => saveStyle.mutate() };

  function editTarget(id: number, value: string) {
    setSegments((prev) => prev.map((s) => (s.id === id ? { ...s, target: value } : s)));
    setDirty(true);
    setSaved(false);
  }

  function activate(id: number) {
    setActiveId(id);
    const row = gridRef.current?.querySelector(`[data-seg-id="${id}"]`);
    row?.scrollIntoView?.({ block: "nearest" });
  }

  function moveActive(offset: number) {
    if (activeId === null) return;
    const idx = visible.findIndex((s) => s.id === activeId);
    const next = visible[idx + offset];
    if (next) activate(next.id);
    else setActiveId(null);
  }

  function jumpFlag(direction: 1 | -1) {
    const flagged = visible.filter((s) => flagById.has(s.id));
    if (flagged.length === 0) return;
    const idx = activeId === null ? -1 : flagged.findIndex((s) => s.id === activeId);
    const next =
      direction === 1
        ? flagged[idx + 1] ?? flagged[0]
        : flagged[idx - 1 < 0 ? flagged.length - 1 : idx - 1];
    activate(next.id);
  }

  const jumpFlagRef = useRef(jumpFlag);
  jumpFlagRef.current = jumpFlag;

  function replaceAll() {
    const needle = query.trim();
    if (!needle) return;
    const ids = new Set(visible.map((s) => s.id));
    let changed = false;
    const next = segments.map((s) => {
      if (!ids.has(s.id) || !s.target.includes(needle)) return s;
      changed = true;
      return { ...s, target: s.target.split(needle).join(replaceText) };
    });
    if (!changed) return;
    setSegments(next);
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
    if (dirty || styleDirty) setConfirmLeave(true);
    else onBack();
  }

  if (isLoading) return <p className={styles.state}>{t("editor.loading")}</p>;
  if (!data || segments.length === 0) return <p className={styles.state}>{t("editor.empty")}</p>;

  return (
    <div>
      <button type="button" className={styles.back} onClick={handleBack}>
        {t("editor.back")}
      </button>
      <header className={styles.header}>
        <div className={styles.headline}>
          <h1 className={styles.title}>{t("editor.subtitle.title")}</h1>
          <div className={styles.tabs} role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "subtitle"}
              className={`${styles.tabButton} ${tab === "subtitle" ? styles.tabActive : ""}`}
              onClick={() => setTab("subtitle")}
            >
              {t("editor.tab.subtitle")}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "style"}
              className={`${styles.tabButton} ${tab === "style" ? styles.tabActive : ""}`}
              onClick={() => setTab("style")}
            >
              {t("editor.tab.style")}
            </button>
          </div>
        </div>
        <div className={styles.actions}>
          {tab === "subtitle" ? (
            <>
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
            </>
          ) : (
            <>
              {styleDirty && <span className={styles.dirty}>{t("editor.dirty")}</span>}
              {styleSaved && <span className={styles.saved}>{t("editor.style.saved")}</span>}
              <button
                type="button"
                className={styles.primary}
                disabled={!styleDirty || saveStyle.isPending}
                onClick={() => saveStyle.mutate()}
              >
                {t("editor.style.save")}
              </button>
            </>
          )}
        </div>
      </header>

      {tab === "style" && styleDraft && (
        <StyleEditorPanel
          project={project}
          taskId={taskId}
          style={styleDraft}
          onChange={(next) => {
            setStyleDraft(next);
            setStyleDirty(true);
            setStyleSaved(false);
          }}
        />
      )}

      {tab === "subtitle" && (
      <>
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
          {visible.length === segments.length
            ? `${segments.length} ${t("editor.rows.unit")}`
            : `${visible.length} / ${segments.length} ${t("editor.rows.unit")}`}
        </span>
        <span className={styles.spacer} />
        <button type="button" className={styles.toolButton} onClick={() => jumpFlag(-1)}>
          {t("editor.flag.prev")}
        </button>
        <button type="button" className={styles.toolButton} onClick={() => jumpFlag(1)}>
          {t("editor.flag.next")}
        </button>
      </div>

      <div ref={gridRef} className={styles.grid} role="table" aria-label={t("editor.subtitle.title")}>
        <div className={`${styles.row} ${styles.headRow}`} role="row">
          <span role="columnheader" className={styles.headCell}>{t("editor.col.index")}</span>
          <span role="columnheader" className={styles.headCell}>{t("editor.col.time")}</span>
          <span role="columnheader" className={styles.headCell}>{t("editor.col.source")}</span>
          <span role="columnheader" className={styles.headCell}>{t("editor.col.target")}</span>
          <span role="columnheader" className={styles.headCell}>{t("editor.col.flag")}</span>
        </div>
        {visible.map((seg) => {
          const flag = flagById.get(seg.id);
          const active = activeId === seg.id;
          const rowClass = [
            styles.row,
            styles.bodyRow,
            flag ? styles.flagged : "",
            active ? styles.active : "",
          ]
            .filter(Boolean)
            .join(" ");
          return (
            <div
              key={seg.id}
              role="row"
              data-seg-id={seg.id}
              className={rowClass}
              onClick={() => activate(seg.id)}
            >
              <span role="cell" className={styles.num}>{seg.id}</span>
              <span role="cell" className={styles.time}>{formatRange(seg.start, seg.end)}</span>
              <span role="cell" className={styles.source}>{seg.source}</span>
              <span role="cell" className={styles.targetCell}>
                {active ? (
                  <textarea
                    autoFocus
                    className={styles.target}
                    aria-label={t("editor.col.target")}
                    value={seg.target}
                    onChange={(e) => editTarget(seg.id, e.target.value)}
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
                  <span className={styles.targetText}>{seg.target}</span>
                )}
              </span>
              <span role="cell" className={styles.flag}>
                {flag && (
                  <span className={styles.flagBadge} title={flag}>
                    {t("editor.flag.badge")}
                  </span>
                )}
                {flag}
              </span>
            </div>
          );
        })}
      </div>
      <p className={styles.shortcuts}>{t("editor.shortcuts")}</p>
      </>
      )}

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
