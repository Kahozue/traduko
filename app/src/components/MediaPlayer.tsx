import { useMemo, useState } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { t } from "../i18n";
import { revealArtifact } from "../lib/shell";
import styles from "./MediaPlayer.module.css";

// Inline task-page player. Every media-extension input renders here; formats
// WKWebView cannot decode (mkv/avi/flv/webm/ogg/flac/opus vary by OS version)
// surface through onError as a fallback row rather than an extension
// whitelist. Outside Tauri convertFileSrc throws, which lands in the same
// fallback.
export function MediaPlayer({ path, kind }: { path: string; kind: "video" | "audio" }) {
  const [failed, setFailed] = useState(false);
  const src = useMemo(() => {
    try {
      return convertFileSrc(path);
    } catch {
      return null;
    }
  }, [path]);

  if (failed || src === null) {
    return (
      <div className={`${styles.player} ${styles.fallback}`} data-kind={kind}>
        <span className={styles.fallbackText}>{t("task.player.unsupported")}</span>
        <button
          type="button"
          className={styles.reveal}
          onClick={() => void revealArtifact(path)}
        >
          {t("task.outputs.reveal")}
        </button>
      </div>
    );
  }

  return (
    <div className={styles.player} data-kind={kind}>
      {kind === "video" ? (
        <video
          className={styles.video}
          controls
          preload="metadata"
          src={src}
          onError={() => setFailed(true)}
        />
      ) : (
        <audio
          className={styles.audio}
          controls
          preload="metadata"
          src={src}
          onError={() => setFailed(true)}
        />
      )}
    </div>
  );
}
