import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { t } from "../i18n";
import type { SpeakersDoc, TranslationArtifact } from "../lib/api/types";
import { useApi } from "../lib/connection";
import styles from "./SpeakerReviewView.module.css";

interface DraftSpeaker {
  id: string;
  label: string;
  ref_start: number;
  ref_end: number;
  ref_text: string;
}

export function SpeakerReviewView({
  project,
  taskId,
  onBack,
}: {
  project: string;
  taskId: string;
  onBack: () => void;
}) {
  const api = useApi();
  const { data: speakersDoc, isLoading } = useQuery({
    queryKey: ["artifact", project, taskId, "speakers.json"],
    queryFn: () => api.readArtifact<SpeakersDoc>(project, taskId, "speakers.json"),
  });
  const { data: translation } = useQuery({
    queryKey: ["artifact", project, taskId, "translation.json"],
    queryFn: () =>
      api.readArtifact<TranslationArtifact>(project, taskId, "translation.json"),
  });

  const [speakers, setSpeakers] = useState<DraftSpeaker[]>([]);
  const [assignments, setAssignments] = useState<Record<number, string>>({});
  const [loadedFrom, setLoadedFrom] = useState<SpeakersDoc | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [confirmLeave, setConfirmLeave] = useState(false);

  useEffect(() => {
    if (speakersDoc && speakersDoc !== loadedFrom) {
      setSpeakers(speakersDoc.speakers.map((s) => ({ ...s })));
      setAssignments(
        Object.fromEntries(speakersDoc.segments.map((s) => [s.id, s.speaker])),
      );
      setLoadedFrom(speakersDoc);
    }
  }, [speakersDoc, loadedFrom]);

  const sourceById = useMemo(() => {
    const map = new Map<number, string>();
    for (const seg of translation?.segments ?? []) map.set(seg.id, seg.source);
    return map;
  }, [translation]);

  function renameSpeaker(id: string, label: string) {
    setSpeakers((prev) => prev.map((s) => (s.id === id ? { ...s, label } : s)));
    setDirty(true);
    setSaved(false);
  }

  // Merge speaker `from` into `into`: reassign every segment and drop the
  // now-empty speaker from the list.
  function mergeSpeaker(from: string, into: string) {
    if (from === into) return;
    setAssignments((prev) => {
      const next = { ...prev };
      for (const [segId, speaker] of Object.entries(next)) {
        if (speaker === from) next[Number(segId)] = into;
      }
      return next;
    });
    setSpeakers((prev) => prev.filter((s) => s.id !== from));
    setDirty(true);
    setSaved(false);
  }

  function assignSegment(segId: number, speaker: string) {
    setAssignments((prev) => ({ ...prev, [segId]: speaker }));
    setDirty(true);
    setSaved(false);
  }

  const save = useMutation({
    mutationFn: () =>
      api.saveArtifact(project, taskId, "speakers.json", {
        schema_version: speakersDoc?.schema_version ?? 1,
        speakers,
        segments: (speakersDoc?.segments ?? []).map((s) => ({
          id: s.id,
          speaker: assignments[s.id] ?? s.speaker,
        })),
      }),
    onSuccess: () => {
      setDirty(false);
      setSaved(true);
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

  if (isLoading) return <p className={styles.state}>{t("editor.loading")}</p>;
  if (!speakersDoc || speakers.length === 0) {
    return <p className={styles.state}>{t("speaker.empty")}</p>;
  }

  return (
    <div>
      <button type="button" className={styles.back} onClick={handleBack}>
        {t("editor.back")}
      </button>
      <header className={styles.header}>
        <h1 className={styles.title}>{t("speaker.title")}</h1>
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
      <p className={styles.hint}>{t("speaker.hint")}</p>

      <section className={styles.speakers}>
        <h2 className={styles.sectionTitle}>{t("speaker.speakersTitle")}</h2>
        {speakers.map((speaker) => (
          <div key={speaker.id} className={styles.speakerRow}>
            <span className={styles.speakerId}>{speaker.id}</span>
            <input
              className={styles.labelInput}
              aria-label={`${speaker.id} ${t("speaker.label")}`}
              value={speaker.label}
              onChange={(e) => renameSpeaker(speaker.id, e.target.value)}
            />
            <span className={styles.refText} title={speaker.ref_text}>
              {speaker.ref_text}
            </span>
            {speakers.length > 1 && (
              <label className={styles.mergeControl}>
                {t("speaker.mergeInto")}
                <select
                  aria-label={`${speaker.id} ${t("speaker.mergeInto")}`}
                  value=""
                  onChange={(e) => {
                    if (e.target.value) mergeSpeaker(speaker.id, e.target.value);
                  }}
                >
                  <option value="">—</option>
                  {speakers
                    .filter((other) => other.id !== speaker.id)
                    .map((other) => (
                      <option key={other.id} value={other.id}>
                        {other.label || other.id}
                      </option>
                    ))}
                </select>
              </label>
            )}
          </div>
        ))}
      </section>

      <section className={styles.segments}>
        <h2 className={styles.sectionTitle}>{t("speaker.segmentsTitle")}</h2>
        <div className={styles.grid} role="table" aria-label={t("speaker.segmentsTitle")}>
          <div className={`${styles.row} ${styles.headRow}`} role="row">
            <span role="columnheader" className={styles.headCell}>
              {t("editor.col.index")}
            </span>
            <span role="columnheader" className={styles.headCell}>
              {t("editor.col.source")}
            </span>
            <span role="columnheader" className={styles.headCell}>
              {t("speaker.speaker")}
            </span>
          </div>
          {speakersDoc.segments.map((seg) => (
            <div key={seg.id} className={`${styles.row} ${styles.bodyRow}`} role="row">
              <span role="cell" className={styles.num}>
                {seg.id}
              </span>
              <span role="cell" className={styles.source}>
                {sourceById.get(seg.id) ?? ""}
              </span>
              <span role="cell">
                <select
                  className={styles.speakerSelect}
                  aria-label={`${t("speaker.speaker")} ${seg.id}`}
                  value={assignments[seg.id] ?? seg.speaker}
                  onChange={(e) => assignSegment(seg.id, e.target.value)}
                >
                  {speakers.map((speaker) => (
                    <option key={speaker.id} value={speaker.id}>
                      {speaker.label || speaker.id}
                    </option>
                  ))}
                </select>
              </span>
            </div>
          ))}
        </div>
      </section>

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
