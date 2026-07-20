import { useEffect, useRef, useState } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { Icon } from "./icons";
import { t } from "../i18n";
import styles from "./AudioTrack.module.css";

// Inline audio row for the outputs list: play/pause, a scrubber and a speed
// picker, drawn from the design tokens instead of the browser's chrome, so a
// column of them reads as one list rather than a stack of native widgets.
// Formats WKWebView cannot decode surface through onError as a plain notice.

const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2];

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds)) return "--:--";
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  return `${String(minutes).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

export function AudioTrack({ path }: { path: string }) {
  const ref = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [speed, setSpeed] = useState(1);
  const [failed, setFailed] = useState(false);

  const src = (() => {
    try {
      return convertFileSrc(path);
    } catch {
      return null;
    }
  })();

  useEffect(() => {
    if (ref.current) ref.current.playbackRate = speed;
  }, [speed]);

  if (failed || src === null) {
    return <span className={styles.failed}>{t("task.player.unsupported")}</span>;
  }

  function toggle() {
    const el = ref.current;
    if (!el) return;
    if (el.paused) void el.play();
    else el.pause();
  }

  // A zero/NaN duration (still loading, or a stream without one) would make
  // the scrubber jump around, so it stays disabled at full width until the
  // metadata lands.
  const seekable = duration > 0;

  return (
    <div className={styles.track}>
      <audio
        ref={ref}
        preload="metadata"
        src={src}
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        onTimeUpdate={(e) => setCurrent(e.currentTarget.currentTime)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onError={() => setFailed(true)}
      />
      <button
        type="button"
        className={styles.toggle}
        aria-label={playing ? t("player.pause") : t("player.play")}
        title={playing ? t("player.pause") : t("player.play")}
        onClick={toggle}
      >
        <Icon name={playing ? "pause" : "play"} size={14} />
      </button>
      <input
        type="range"
        className={styles.seek}
        aria-label={t("player.seek")}
        min={0}
        max={seekable ? duration : 1}
        step={0.01}
        value={seekable ? current : 0}
        disabled={!seekable}
        onChange={(e) => {
          const next = Number(e.target.value);
          setCurrent(next);
          if (ref.current) ref.current.currentTime = next;
        }}
      />
      <span className={styles.time}>
        {formatTime(current)} / {formatTime(duration)}
      </span>
      <select
        className={styles.speed}
        aria-label={t("player.speed")}
        title={t("player.speed")}
        value={speed}
        onChange={(e) => setSpeed(Number(e.target.value))}
      >
        {SPEEDS.map((rate) => (
          <option key={rate} value={rate}>
            {rate}×
          </option>
        ))}
      </select>
    </div>
  );
}
