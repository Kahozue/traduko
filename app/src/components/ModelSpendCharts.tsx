import { t } from "../i18n";
import type { BudgetModelSpend } from "../lib/api/types";
import styles from "./ModelSpendCharts.module.css";

// Categorical slots assigned in fixed order, never cycled; overflow folds
// into a neutral "Other" bucket (see tokens.css and internal/design-language.md).
const MAX_SLICES = 5;
const SLICE_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];
const OTHER_COLOR = "var(--chart-other)";

interface Slice {
  label: string;
  usd: number;
  color: string;
}

function usd(value: number): string {
  return `$${value.toFixed(2)}`;
}

function buildSlices(models: BudgetModelSpend[]): Slice[] {
  const ranked = models.filter((m) => m.usd > 0).sort((a, b) => b.usd - a.usd);
  const slices: Slice[] = ranked
    .slice(0, MAX_SLICES)
    .map((m, i) => ({ label: m.model, usd: m.usd, color: SLICE_COLORS[i] }));
  const rest = ranked.slice(MAX_SLICES);
  if (rest.length > 0) {
    slices.push({
      label: t("budget.other"),
      usd: rest.reduce((sum, m) => sum + m.usd, 0),
      color: OTHER_COLOR,
    });
  }
  return slices;
}

export function ModelSpendCharts({ models }: { models: BudgetModelSpend[] }) {
  const slices = buildSlices(models);
  if (slices.length === 0) return null;

  const total = slices.reduce((sum, s) => sum + s.usd, 0);
  // pathLength=100 lets each arc's dash length be its own percentage; a small
  // gap carves a surface notch between adjacent arcs.
  const gap = slices.length > 1 ? 1.2 : 0;
  let offset = 0;
  const arcs = slices.map((s) => {
    const pct = (s.usd / total) * 100;
    const dash = Math.max(0, pct - gap);
    const arc = (
      <circle
        key={s.label}
        className={styles.arc}
        cx="21"
        cy="21"
        r="15.915"
        style={{ stroke: s.color }}
        pathLength={100}
        strokeDasharray={`${dash} ${100 - dash}`}
        strokeDashoffset={-offset}
      />
    );
    offset += pct;
    return arc;
  });

  const ranked = [...slices].sort((a, b) => b.usd - a.usd);
  const max = ranked[0].usd;

  return (
    <section className={styles.grid}>
      <div className={styles.card}>
        <h3 className={styles.cardTitle}>{t("budget.spendByModel")}</h3>
        <div className={styles.donutRow}>
          <div className={styles.donutWrap}>
            <svg
              viewBox="0 0 42 42"
              className={styles.donut}
              role="img"
              aria-label={slices.map((s) => `${s.label} ${usd(s.usd)}`).join("；")}
            >
              <g transform="rotate(-90 21 21)">{arcs}</g>
            </svg>
            <div className={styles.donutCenter}>
              <span className={styles.donutTotalLabel}>{t("budget.total")}</span>
              <span className={styles.donutTotal}>{usd(total)}</span>
            </div>
          </div>
          <ul className={styles.legend}>
            {slices.map((s) => (
              <li key={s.label} className={styles.legendRow}>
                <span className={styles.swatch} style={{ background: s.color }} aria-hidden />
                <span className={styles.legendName} title={s.label}>
                  {s.label}
                </span>
                <span className={styles.legendPct}>{Math.round((s.usd / total) * 100)}%</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className={styles.card}>
        <h3 className={styles.cardTitle}>{t("budget.modelRanking")}</h3>
        <ul className={styles.bars}>
          {ranked.map((s) => (
            <li key={s.label} className={styles.barRow}>
              <span className={styles.barName} title={s.label}>
                {s.label}
              </span>
              <div className={styles.barTrack}>
                <div
                  className={styles.barFill}
                  style={{ width: `${max > 0 ? (s.usd / max) * 100 : 0}%`, background: s.color }}
                />
              </div>
              <span className={styles.barValue}>{usd(s.usd)}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
