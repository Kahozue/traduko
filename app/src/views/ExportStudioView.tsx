import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { convertFileSrc } from "@tauri-apps/api/core";
import { t } from "../i18n";
import { ApiError } from "../lib/api/client";
import { useApi } from "../lib/connection";
import { humanizeError } from "../lib/errors";
import { alignmentToFlex, assStyleToCss } from "../lib/ass/preview";
import { exportKindOf, mediaKindOf } from "../lib/media";
import type { ExportEstimate, ExportParams, SubtitleStylePreset } from "../lib/api/types";
import styles from "./ExportStudioView.module.css";

// Full-screen export studio. One shell, two panels: the source file's media
// kind picks the panel, since a video task fed an audio file exports audio.
// The preview frame is an editing venue (--bg-canvas, zero chroma in both
// themes); the primary color appears only on "start export".

const RESOLUTIONS = {
  source: null,
  "1080p": { width: 1920, height: 1080 },
  "720p": { width: 1280, height: 720 },
} as const;

type ResolutionKey = keyof typeof RESOLUTIONS | "custom";

const STYLE_FALLBACK: SubtitleStylePreset = {
  font_name: "Noto Sans TC",
  font_size: 48,
  primary_color: "#ffffff",
  outline_color: "#000000",
  outline: 2,
  shadow: 0,
  bold: false,
  alignment: 2,
  margin_v: 40,
};

function formatSize(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  return `${Math.round(bytes / 1024 ** 2)} MB`;
}

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return minutes > 0 ? `${minutes} m ${rest} s` : `${rest} s`;
}

export function ExportStudioView({
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
  const { data: artifacts } = useQuery({
    queryKey: ["artifacts", project, taskId, task?.updated_at],
    queryFn: () => api.listArtifacts(project, taskId),
    enabled: !!task,
  });
  const { data: stylesDoc } = useQuery({
    queryKey: ["styles"],
    queryFn: () => api.getStyles(),
  });

  const kind = task ? exportKindOf(task) : null;
  // A compose task has no source recording, so neither the original-audio
  // source nor the source preview has anything behind it.
  const hasSourceMedia = task ? mediaKindOf(task.input_path) !== null : false;
  // Detection goes through the artifacts listing: on disk the mix is
  // 05-dub-mix.wav, and the listing's `name` field strips the prefix.
  const hasDubMix = (artifacts ?? []).some((item) => item.name === "dub-mix.wav");

  // Video panel.
  const [container, setContainer] = useState("mp4");
  const [resolution, setResolution] = useState<ResolutionKey>("source");
  const [customWidth, setCustomWidth] = useState<number | "">("");
  const [customHeight, setCustomHeight] = useState<number | "">("");
  const [crf, setCrf] = useState(20);
  const [audioTrack, setAudioTrack] = useState("original");
  const [subtitles, setSubtitles] = useState("none");
  const [stylePreset, setStylePreset] = useState("");
  const [videoCodec, setVideoCodec] = useState("libx264");
  const [videoBitrate, setVideoBitrate] = useState<number | "">("");
  const [fps, setFps] = useState<number | "">("");
  const [audioCodec, setAudioCodec] = useState("aac");
  const [audioBitrate, setAudioBitrate] = useState(192);
  // Audio panel.
  const [format, setFormat] = useState("m4a");
  const [source, setSource] = useState("dub");
  const [bitrate, setBitrate] = useState(192);
  const [sampleRate, setSampleRate] = useState<number | "">("");
  const [channels, setChannels] = useState<number | "">("");

  // The dubbed track is only offered once a dub mix exists. Wait for the
  // artifacts listing so a slow query does not flip the selection away from
  // a mix that actually exists.
  useEffect(() => {
    if (artifacts === undefined) return;
    if (!hasDubMix && audioTrack === "dub") setAudioTrack("original");
    if (!hasDubMix && source === "dub" && hasSourceMedia) setSource("original");
    if (!hasSourceMedia && source === "original") setSource("dub");
  }, [artifacts, hasDubMix, audioTrack, source, hasSourceMedia]);

  const params = useMemo<ExportParams>(() => {
    if (kind === "audio") {
      const body: ExportParams = { format, source, bitrate_kbps: bitrate };
      if (sampleRate !== "") body.sample_rate = sampleRate;
      if (channels !== "") body.channels = channels;
      return body;
    }
    const size =
      resolution === "custom"
        ? customWidth !== "" && customHeight !== ""
          ? { width: customWidth, height: customHeight }
          : null
        : RESOLUTIONS[resolution];
    const body: ExportParams = {
      container,
      crf,
      audio_track: audioTrack,
      subtitles,
      video_codec: videoCodec,
      audio_codec: audioCodec,
      audio_bitrate_kbps: audioBitrate,
    };
    if (size) {
      body.width = size.width;
      body.height = size.height;
    }
    if (videoBitrate !== "") body.video_bitrate_kbps = videoBitrate;
    if (fps !== "") body.fps = fps;
    if (sampleRate !== "") body.sample_rate = sampleRate;
    if (channels !== "") body.channels = channels;
    if (subtitles !== "none" && stylePreset) body.style_preset = stylePreset;
    return body;
  }, [
    kind, format, source, bitrate, sampleRate, channels, container, resolution,
    customWidth, customHeight, crf, audioTrack, subtitles, videoCodec,
    audioCodec, audioBitrate, videoBitrate, fps, stylePreset,
  ]);

  const [estimate, setEstimate] = useState<ExportEstimate | null>(null);
  // The estimate call runs the same validation the export POST does, so a
  // rejection here is the export's own reason, not just a missing number.
  const [estimateError, setEstimateError] = useState<string | null>(null);
  const paramKey = JSON.stringify(params);

  // Debounced so dragging the quality slider does not hammer ffprobe.
  useEffect(() => {
    if (kind === null) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      api
        .estimateExport(project, taskId, { ...params, kind })
        .then((next) => {
          if (cancelled) return;
          setEstimate(next);
          setEstimateError(null);
        })
        .catch((cause: unknown) => {
          if (cancelled) return;
          const raw =
            cause instanceof ApiError && typeof cause.detail === "string"
              ? cause.detail
              : String(cause);
          setEstimate(null);
          setEstimateError(humanizeError(raw).summary);
        });
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramKey, kind, project, taskId]);

  const start = useMutation({
    mutationFn: () => {
      // Unreachable: the panels below refuse to render without a kind, and
      // the task page never opens the studio for such a task.
      if (kind === null) throw new Error("this task has nothing to export");
      return api.createExport(project, taskId, kind, params);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["task", project, taskId] });
      onBack();
    },
  });

  const presets = stylesDoc ?? {};
  const activeStyle = presets[stylePreset] ?? Object.values(presets)[0] ?? STYLE_FALLBACK;
  const overlayCss = useMemo(() => assStyleToCss(activeStyle), [activeStyle]);
  const overlayFlex = useMemo(
    () => alignmentToFlex(activeStyle.alignment),
    [activeStyle.alignment],
  );

  const running = task?.status === "running";
  // No estimate means the core already refused this request; starting the
  // export would only reproduce the same rejection.
  const blocked = estimateError !== null || (estimate !== null && !estimate.disk_ok);

  if (!task || kind === null) {
    return (
      <div className={styles.wrap}>
        <button type="button" className={styles.back} onClick={onBack}>
          {t("task.back")}
        </button>
        {task && <p className={styles.hint}>{t("task.export.studio.noMedia")}</p>}
      </div>
    );
  }

  const sourceUrl = convertFileSrc(task.input_path);

  return (
    <div className={styles.wrap}>
      <button type="button" className={styles.back} onClick={onBack}>
        {t("task.back")}
      </button>
      <h1 className={styles.title}>{t("task.export.studio.title")}</h1>

      {kind === "video" ? (
        <>
          <section className={styles.block}>
            <h2 className={styles.sectionTitle}>{t("task.export.studio.basic")}</h2>
            <div className={styles.row}>
              <label className={styles.field}>
                <span>{t("task.export.studio.container")}</span>
                <select
                  className={styles.select}
                  value={container}
                  onChange={(e) => setContainer(e.target.value)}
                >
                  <option value="mp4">mp4</option>
                  <option value="mkv">mkv</option>
                  <option value="webm">webm</option>
                </select>
              </label>
              <label className={styles.field}>
                <span>{t("task.export.studio.resolution")}</span>
                <select
                  className={styles.select}
                  value={resolution}
                  onChange={(e) => setResolution(e.target.value as ResolutionKey)}
                >
                  <option value="source">{t("task.export.studio.resolution.source")}</option>
                  <option value="1080p">1080p</option>
                  <option value="720p">720p</option>
                  <option value="custom">{t("task.export.studio.resolution.custom")}</option>
                </select>
              </label>
              {resolution === "custom" && (
                <>
                  <label className={styles.fieldNarrow}>
                    <span>{t("task.export.studio.width")}</span>
                    <input
                      className={styles.input}
                      type="number"
                      value={customWidth}
                      onChange={(e) =>
                        setCustomWidth(e.target.value === "" ? "" : Number(e.target.value))
                      }
                    />
                  </label>
                  <label className={styles.fieldNarrow}>
                    <span>{t("task.export.studio.height")}</span>
                    <input
                      className={styles.input}
                      type="number"
                      value={customHeight}
                      onChange={(e) =>
                        setCustomHeight(e.target.value === "" ? "" : Number(e.target.value))
                      }
                    />
                  </label>
                </>
              )}
              <label className={styles.field} title={t("task.export.studio.crf.hint")}>
                <span>{t("task.export.studio.crf")}</span>
                <input
                  className={styles.range}
                  type="range"
                  min={18}
                  max={28}
                  value={crf}
                  onChange={(e) => setCrf(Number(e.target.value))}
                />
              </label>
              <span className={styles.rangeValue}>{crf}</span>
            </div>
          </section>

          <section className={styles.block}>
            <h2 className={styles.sectionTitle}>{t("task.export.studio.tracks")}</h2>
            <div className={styles.row}>
              <label className={styles.field}>
                <span>{t("task.export.studio.audioTrack")}</span>
                <select
                  className={styles.select}
                  value={audioTrack}
                  onChange={(e) => setAudioTrack(e.target.value)}
                >
                  <option value="original">{t("task.export.studio.audioTrack.original")}</option>
                  <option value="dub" disabled={!hasDubMix}>
                    {t("task.export.studio.audioTrack.dub")}
                  </option>
                  <option value="none">{t("task.export.studio.audioTrack.none")}</option>
                </select>
              </label>
              <label className={styles.field}>
                <span>{t("task.export.studio.audioBitrate")}</span>
                <input
                  className={styles.input}
                  type="number"
                  value={audioBitrate}
                  disabled={audioTrack === "none"}
                  onChange={(e) => setAudioBitrate(Number(e.target.value))}
                />
              </label>
            </div>
          </section>

          <section className={styles.block}>
            <h2 className={styles.sectionTitle}>{t("task.export.studio.subtitles")}</h2>
            <div className={styles.row}>
              <label className={styles.field}>
                <span>{t("task.export.studio.subtitleMode")}</span>
                <select
                  className={styles.select}
                  value={subtitles}
                  onChange={(e) => setSubtitles(e.target.value)}
                >
                  <option value="none">{t("task.export.studio.subtitleMode.none")}</option>
                  <option value="target">{t("task.export.studio.subtitleMode.target")}</option>
                  <option value="source">{t("task.export.studio.subtitleMode.source")}</option>
                  <option value="bilingual">
                    {t("task.export.studio.subtitleMode.bilingual")}
                  </option>
                </select>
              </label>
              {subtitles !== "none" && (
                <label className={styles.field}>
                  <span>{t("task.export.studio.stylePreset")}</span>
                  <select
                    className={styles.select}
                    value={stylePreset}
                    onChange={(e) => setStylePreset(e.target.value)}
                  >
                    <option value="">{t("task.export.studio.stylePreset.default")}</option>
                    {Object.keys(presets).map((name) => (
                      <option key={name} value={name}>{name}</option>
                    ))}
                  </select>
                </label>
              )}
            </div>
          </section>

          <details className={styles.advanced}>
            <summary className={styles.summary}>{t("task.export.studio.advanced")}</summary>
            <div className={styles.row}>
              <label className={styles.field}>
                <span>{t("task.export.studio.videoCodec")}</span>
                <select
                  className={styles.select}
                  value={videoCodec}
                  onChange={(e) => setVideoCodec(e.target.value)}
                >
                  <option value="libx264">H.264</option>
                  <option value="libx265">H.265</option>
                </select>
              </label>
              <label className={styles.field}>
                <span>{t("task.export.studio.videoBitrate")}</span>
                <input
                  className={styles.input}
                  type="number"
                  value={videoBitrate}
                  onChange={(e) =>
                    setVideoBitrate(e.target.value === "" ? "" : Number(e.target.value))
                  }
                />
              </label>
              <label className={styles.field}>
                <span>{t("task.export.studio.fps")}</span>
                <select
                  className={styles.select}
                  value={fps}
                  onChange={(e) => setFps(e.target.value === "" ? "" : Number(e.target.value))}
                >
                  <option value="">{t("task.export.studio.fps.source")}</option>
                  <option value="24">24</option>
                  <option value="30">30</option>
                  <option value="60">60</option>
                </select>
              </label>
              <label className={styles.field}>
                <span>{t("task.export.studio.audioCodec")}</span>
                <select
                  className={styles.select}
                  value={audioCodec}
                  onChange={(e) => setAudioCodec(e.target.value)}
                >
                  <option value="aac">aac</option>
                  <option value="libopus">opus</option>
                </select>
              </label>
              <label className={styles.field}>
                <span>{t("task.export.studio.sampleRate")}</span>
                <select
                  className={styles.select}
                  value={sampleRate}
                  onChange={(e) =>
                    setSampleRate(e.target.value === "" ? "" : Number(e.target.value))
                  }
                >
                  <option value="">{t("task.export.studio.sampleRate.source")}</option>
                  <option value="44100">44100</option>
                  <option value="48000">48000</option>
                </select>
              </label>
              <label className={styles.field}>
                <span>{t("task.export.studio.channels")}</span>
                <select
                  className={styles.select}
                  value={channels}
                  onChange={(e) =>
                    setChannels(e.target.value === "" ? "" : Number(e.target.value))
                  }
                >
                  <option value="">{t("task.export.studio.channels.source")}</option>
                  <option value="1">1</option>
                  <option value="2">2</option>
                </select>
              </label>
            </div>
          </details>
        </>
      ) : (
        <section className={styles.block}>
          <h2 className={styles.sectionTitle}>{t("task.export.studio.basic")}</h2>
          <div className={styles.row}>
            <label className={styles.field}>
              <span>{t("task.export.studio.source")}</span>
              <select
                className={styles.select}
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                <option value="dub" disabled={!hasDubMix}>
                  {t("task.export.studio.source.dub")}
                </option>
                <option value="original" disabled={!hasSourceMedia}>
                  {t("task.export.studio.source.original")}
                </option>
              </select>
            </label>
            <label className={styles.field}>
              <span>{t("task.export.studio.format")}</span>
              <select
                className={styles.select}
                value={format}
                onChange={(e) => setFormat(e.target.value)}
              >
                <option value="m4a">m4a</option>
                <option value="mp3">mp3</option>
                <option value="wav">wav</option>
                <option value="opus">opus</option>
              </select>
            </label>
            <label className={styles.field}>
              <span>{t("task.export.studio.bitrate")}</span>
              <input
                className={styles.input}
                type="number"
                value={bitrate}
                disabled={format === "wav"}
                onChange={(e) => setBitrate(Number(e.target.value))}
              />
            </label>
            <label className={styles.field}>
              <span>{t("task.export.studio.sampleRate")}</span>
              <select
                className={styles.select}
                value={sampleRate}
                onChange={(e) =>
                  setSampleRate(e.target.value === "" ? "" : Number(e.target.value))
                }
              >
                <option value="">{t("task.export.studio.sampleRate.source")}</option>
                <option value="44100">44100</option>
                <option value="48000">48000</option>
              </select>
            </label>
            <label className={styles.field}>
              <span>{t("task.export.studio.channels")}</span>
              <select
                className={styles.select}
                value={channels}
                onChange={(e) =>
                  setChannels(e.target.value === "" ? "" : Number(e.target.value))
                }
              >
                <option value="">{t("task.export.studio.channels.source")}</option>
                <option value="1">1</option>
                <option value="2">2</option>
              </select>
            </label>
          </div>
        </section>
      )}

      {hasSourceMedia && (
        <section className={styles.block}>
          <h2 className={styles.sectionTitle}>{t("task.export.studio.preview")}</h2>
          <div className={styles.canvas}>
            {kind === "video" ? (
              <div className={styles.stage}>
                <video className={styles.video} controls src={sourceUrl} />
                {subtitles !== "none" && (
                  <div
                    className={styles.overlay}
                    style={{
                      justifyContent: overlayFlex.justifyContent,
                      alignItems: overlayFlex.alignItems,
                    }}
                  >
                    <span
                      data-testid="subtitle-overlay"
                      style={{ ...overlayCss, textAlign: overlayFlex.textAlign }}
                    >
                      {t("task.export.studio.sampleText")}
                    </span>
                  </div>
                )}
              </div>
            ) : (
              <audio className={styles.audio} controls src={sourceUrl} />
            )}
          </div>
          {kind === "video" && (
            <p className={styles.hint}>{t("task.export.studio.previewNote")}</p>
          )}
        </section>
      )}

      <section className={styles.block}>
        <h2 className={styles.sectionTitle}>{t("task.export.studio.estimate")}</h2>
        {estimateError ? (
          <p className={styles.error}>
            <span aria-hidden="true">!</span> {estimateError}
          </p>
        ) : estimate ? (
          <>
            <dl className={styles.estimate} data-testid="export-estimate">
              <div className={styles.estimateItem}>
                <dt>{t("task.export.studio.size")}</dt>
                <dd className={styles.number}>{formatSize(estimate.size_bytes)}</dd>
              </div>
              <div className={styles.estimateItem}>
                <dt>{t("task.export.studio.eta")}</dt>
                <dd className={styles.number}>{formatDuration(estimate.eta_seconds)}</dd>
              </div>
              <div className={styles.estimateItem}>
                <dt>{t("task.export.studio.diskFree")}</dt>
                <dd className={styles.number}>{formatSize(estimate.disk_available)}</dd>
              </div>
            </dl>
            {blocked && (
              <p className={styles.error}>
                <span aria-hidden="true">!</span> {t("task.export.studio.diskShort")}
              </p>
            )}
          </>
        ) : (
          <p className={styles.hint}>{t("task.export.studio.estimating")}</p>
        )}
      </section>

      <div className={styles.actions}>
        <button
          type="button"
          className={styles.primary}
          disabled={blocked || running || start.isPending}
          onClick={() => start.mutate()}
        >
          {t("task.export.studio.start")}
        </button>
      </div>
    </div>
  );
}
