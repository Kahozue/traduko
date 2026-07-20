import { useEffect, useState } from "react";
import { t } from "../i18n";
import { readArtifactText } from "../lib/shell";
import styles from "./TextPreview.module.css";

// Inline preview for text deliverables (srt/txt/md/...). Reads through the
// asset protocol, which the core's JSON-only artifact endpoint cannot serve.
// The size control is per-preview state: subtitle files and prose want
// different comfortable sizes, and the choice is not worth persisting.

const SIZES = [12, 13, 14, 16, 18, 22];
const DEFAULT_SIZE = 14;
// Long transcripts are the common case; a preview is for looking, not for
// scrolling through a novel, so the tail is dropped rather than rendered.
const MAX_CHARS = 200_000;

export function TextPreview({ path }: { path: string }) {
  const [text, setText] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [size, setSize] = useState(DEFAULT_SIZE);

  useEffect(() => {
    let cancelled = false;
    setText(null);
    setFailed(false);
    readArtifactText(path)
      .then((body) => {
        if (!cancelled) setText(body.slice(0, MAX_CHARS));
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  const index = SIZES.indexOf(size);

  return (
    <div className={styles.preview}>
      <div className={styles.bar}>
        <span className={styles.label}>{t("task.outputs.fontSize")}</span>
        <button
          type="button"
          className={styles.sizeButton}
          aria-label={t("task.outputs.fontSmaller")}
          title={t("task.outputs.fontSmaller")}
          disabled={index <= 0}
          onClick={() => setSize(SIZES[index - 1])}
        >
          A
        </button>
        <button
          type="button"
          className={`${styles.sizeButton} ${styles.sizeLarge}`}
          aria-label={t("task.outputs.fontLarger")}
          title={t("task.outputs.fontLarger")}
          disabled={index < 0 || index >= SIZES.length - 1}
          onClick={() => setSize(SIZES[index + 1])}
        >
          A
        </button>
      </div>
      {failed ? (
        <p className={styles.state}>{t("task.outputs.previewFailed")}</p>
      ) : text === null ? (
        <p className={styles.state}>{t("task.outputs.previewLoading")}</p>
      ) : (
        <pre className={styles.body} style={{ fontSize: `${size}px` }}>
          {text}
        </pre>
      )}
    </div>
  );
}
