import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { t } from "../i18n";
import { alignmentToFlex, assStyleToCss } from "../lib/ass/preview";
import type { SubtitleStylePreset } from "../lib/api/types";
import { useApi } from "../lib/connection";
import styles from "./StyleEditorPanel.module.css";

// Controlled style form plus live previews; the owning editor holds the
// draft and the save action so the page keeps a single save button.
export function StyleEditorPanel({
  project,
  taskId,
  style,
  onChange,
}: {
  project: string;
  taskId: string;
  style: SubtitleStylePreset;
  onChange: (next: SubtitleStylePreset) => void;
}) {
  const api = useApi();
  const [sample, setSample] = useState("範例字幕 Sample");
  const [frameUrl, setFrameUrl] = useState<string | null>(null);

  const css = useMemo(() => assStyleToCss(style), [style]);
  const flex = useMemo(() => alignmentToFlex(style.alignment), [style.alignment]);

  function set<K extends keyof SubtitleStylePreset>(key: K, value: SubtitleStylePreset[K]) {
    onChange({ ...style, [key]: value });
  }

  const render = useMutation({
    mutationFn: () => api.renderFrame(project, taskId, { style, text: sample }),
    onSuccess: (blob) => setFrameUrl(URL.createObjectURL(blob)),
  });

  return (
    <div className={styles.layout}>
      <form className={styles.form}>
        <label className={styles.field}>
          <span>{t("editor.style.font")}</span>
          <input value={style.font_name} onChange={(e) => set("font_name", e.target.value)} />
        </label>
        <label className={styles.field}>
          <span>{t("editor.style.size")}</span>
          <input
            type="number"
            value={style.font_size}
            onChange={(e) => set("font_size", Number(e.target.value))}
          />
        </label>
        <label className={styles.field}>
          <span>{t("editor.style.primary")}</span>
          <input type="color" value={style.primary_color}
                 onChange={(e) => set("primary_color", e.target.value)} />
        </label>
        <label className={styles.field}>
          <span>{t("editor.style.outlineColor")}</span>
          <input type="color" value={style.outline_color}
                 onChange={(e) => set("outline_color", e.target.value)} />
        </label>
        <label className={styles.field}>
          <span>{t("editor.style.outline")}</span>
          <input type="number" step="0.5" value={style.outline}
                 onChange={(e) => set("outline", Number(e.target.value))} />
        </label>
        <label className={styles.field}>
          <span>{t("editor.style.shadow")}</span>
          <input type="number" step="0.5" value={style.shadow}
                 onChange={(e) => set("shadow", Number(e.target.value))} />
        </label>
        <label className={styles.checkField}>
          <input type="checkbox" checked={style.bold}
                 onChange={(e) => set("bold", e.target.checked)} />
          <span>{t("editor.style.bold")}</span>
        </label>
        <label className={styles.field}>
          <span>{t("editor.style.alignment")}</span>
          <input type="number" min="1" max="9" value={style.alignment}
                 onChange={(e) => set("alignment", Number(e.target.value))} />
        </label>
        <label className={styles.field}>
          <span>{t("editor.style.marginV")}</span>
          <input type="number" value={style.margin_v}
                 onChange={(e) => set("margin_v", Number(e.target.value))} />
        </label>
        <label className={styles.field}>
          <span>{t("editor.style.sampleText")}</span>
          <input value={sample} onChange={(e) => setSample(e.target.value)} />
        </label>
      </form>

      <div className={styles.previews}>
        <section className={styles.previewBlock}>
          <h2 className={styles.previewTitle}>{t("editor.style.cssPreview")}</h2>
          <div
            className={styles.stage}
            style={{ justifyContent: flex.justifyContent, alignItems: flex.alignItems }}
          >
            <span data-testid="css-preview" style={{ ...css, textAlign: flex.textAlign }}>
              {sample}
            </span>
          </div>
        </section>

        <section className={styles.previewBlock}>
          <div className={styles.exactHead}>
            <h2 className={styles.previewTitle}>{t("editor.style.exactFrame")}</h2>
            <button
              type="button"
              className={styles.secondary}
              disabled={render.isPending}
              onClick={() => render.mutate()}
            >
              {render.isPending ? t("editor.style.rendering") : t("editor.style.renderExact")}
            </button>
          </div>
          {render.isError && <p className={styles.error}>{t("editor.style.noFfmpeg")}</p>}
          {frameUrl && (
            <img data-testid="exact-frame" className={styles.frame} src={frameUrl} alt="" />
          )}
        </section>
      </div>
    </div>
  );
}
