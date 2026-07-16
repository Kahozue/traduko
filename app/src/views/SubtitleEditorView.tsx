import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { t } from "../i18n";
import type { ProofreadFlag, TranslationArtifact, TranslationSegment } from "../lib/api/types";
import { useApi } from "../lib/connection";
import styles from "./SubtitleEditorView.module.css";

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

  useEffect(() => {
    if (data) setSegments(data.segments);
  }, [data]);

  const flagById = useMemo(() => {
    const map = new Map<number, string>();
    for (const flag of report?.flags ?? []) map.set(flag.id, flag.note);
    return map;
  }, [report]);

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

  function editTarget(id: number, value: string) {
    setSegments((prev) => prev.map((s) => (s.id === id ? { ...s, target: value } : s)));
    setDirty(true);
    setSaved(false);
  }

  if (isLoading) return <p className={styles.state}>{t("editor.loading")}</p>;
  if (!data || segments.length === 0) return <p className={styles.state}>{t("editor.empty")}</p>;

  return (
    <div>
      <button type="button" className={styles.back} onClick={onBack}>
        {t("editor.back")}
      </button>
      <header className={styles.header}>
        <h1 className={styles.title}>{t("editor.subtitle.title")}</h1>
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

      <table className={styles.table}>
        <thead>
          <tr>
            <th>{t("editor.col.index")}</th>
            <th>{t("editor.col.time")}</th>
            <th>{t("editor.col.source")}</th>
            <th>{t("editor.col.target")}</th>
            <th>{t("editor.col.flag")}</th>
          </tr>
        </thead>
        <tbody>
          {segments.map((seg) => {
            const flag = flagById.get(seg.id);
            return (
              <tr key={seg.id} className={flag ? styles.flagged : undefined}>
                <td className={styles.num}>{seg.id}</td>
                <td className={styles.time}>{formatRange(seg.start, seg.end)}</td>
                <td className={styles.source}>{seg.source}</td>
                <td>
                  <textarea
                    className={styles.target}
                    value={seg.target}
                    onChange={(e) => editTarget(seg.id, e.target.value)}
                  />
                </td>
                <td className={styles.flag}>
                  {flag && (
                    <span className={styles.flagBadge} title={flag}>
                      {t("editor.flag.badge")}
                    </span>
                  )}
                  {flag}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
