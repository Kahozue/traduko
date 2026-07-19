import { useRef, useState } from "react";
import { t } from "../i18n";
import type { BudgetModelSpend } from "../lib/api/types";
import styles from "./ModelSpendCharts.module.css";

// Categorical slots assigned in fixed order, never cycled; everything past the
// cap folds into a neutral "Other" bucket so the chart never grows beyond a
// fixed number of rows regardless of how many models spent (see tokens.css and
// internal/design-language.md).
const MAX_SLICES = 6;
const SLICE_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
  "var(--chart-6)",
];
const OTHER_COLOR = "var(--chart-other)";

interface Slice {
  key: string;
  label: string;
  usd: number;
  calls: number;
  color: string;
  otherCount: number;
}

function usd(value: number): string {
  return `$${value.toFixed(2)}`;
}

// Sub-cent spend is common here; show enough digits that a real amount never
// collapses to "$0.00" in a value column.
function usdPrecise(value: number): string {
  return value > 0 && value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`;
}

function buildSlices(models: BudgetModelSpend[]): Slice[] {
  const ranked = models.filter((m) => m.usd > 0).sort((a, b) => b.usd - a.usd);
  const slices: Slice[] = ranked.slice(0, MAX_SLICES).map((m, i) => ({
    key: m.model,
    label: m.model,
    usd: m.usd,
    calls: m.calls ?? 0,
    color: SLICE_COLORS[i],
    otherCount: 0,
  }));
  const rest = ranked.slice(MAX_SLICES);
  if (rest.length > 0) {
    slices.push({
      key: "__other__",
      label: t("budget.other"),
      usd: rest.reduce((sum, m) => sum + m.usd, 0),
      calls: rest.reduce((sum, m) => sum + (m.calls ?? 0), 0),
      color: OTHER_COLOR,
      otherCount: rest.length,
    });
  }
  return slices;
}

export function ModelSpendCharts({ models }: { models: BudgetModelSpend[] }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [tip, setTip] = useState<{ key: string; mx: number; my: number } | null>(null);

  const slices = buildSlices(models);
  if (slices.length === 0) {
    return <p className={styles.empty}>{t("budget.rangeEmpty")}</p>;
  }

  const total = slices.reduce((sum, s) => sum + s.usd, 0);
  const max = slices.reduce((m, s) => Math.max(m, s.usd), 0);

  // pathLength=100 lets each arc's dash length be its own percentage; a small
  // gap carves a surface notch between adjacent arcs.
  const gap = slices.length > 1 ? 1.2 : 0;
  let offset = 0;
  const arcs = slices.map((s) => {
    const pct = (s.usd / total) * 100;
    const dash = Math.max(0, pct - gap);
    const active = hovered === s.key;
    const dim = hovered !== null && !active;
    const arc = (
      <circle
        key={s.key}
        className={styles.arc}
        cx="22"
        cy="22"
        r="15.915"
        style={{ stroke: s.color, strokeWidth: active ? 11 : 9, opacity: dim ? 0.35 : 1 }}
        pathLength={100}
        strokeDasharray={`${dash} ${100 - dash}`}
        strokeDashoffset={-offset}
        onMouseEnter={(e) => enter(s.key, e)}
        onMouseMove={(e) => move(s.key, e)}
        onMouseLeave={leave}
      />
    );
    offset += pct;
    return arc;
  });

  function enter(key: string, e: React.MouseEvent) {
    setHovered(key);
    move(key, e);
  }
  function move(key: string, e: React.MouseEvent) {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    setTip({ key, mx: e.clientX - rect.left, my: e.clientY - rect.top });
  }
  function leave() {
    setHovered(null);
    setTip(null);
  }

  const focused = hovered ? slices.find((s) => s.key === hovered) : null;
  const tipSlice = tip ? slices.find((s) => s.key === tip.key) : null;

  let tipStyle: { left: number; top: number } | undefined;
  if (tip) {
    const wrapW = wrapRef.current?.clientWidth ?? 0;
    const wrapH = wrapRef.current?.clientHeight ?? 0;
    const tw = tipRef.current?.offsetWidth ?? 200;
    const th = tipRef.current?.offsetHeight ?? 96;
    let left = tip.mx + 16;
    if (left + tw > wrapW - 8) left = tip.mx - tw - 16;
    left = Math.max(8, left);
    let top = tip.my + 16;
    if (top + th > wrapH - 8) top = wrapH - th - 8;
    top = Math.max(8, top);
    tipStyle = { left, top };
  }

  return (
    <div className={styles.wrap} ref={wrapRef}>
      <div className={styles.grid}>
        <div className={styles.card}>
          <h3 className={styles.cardTitle}>{t("budget.spendByModel")}</h3>
          <div className={styles.donutWrap}>
            <svg
              viewBox="0 0 44 44"
              className={styles.donut}
              role="img"
              aria-label={slices.map((s) => `${s.label} ${usd(s.usd)}`).join("; ")}
            >
              <g transform="rotate(-90 22 22)">{arcs}</g>
            </svg>
            <div className={styles.donutCenter}>
              {focused ? (
                <>
                  <span className={styles.centerLabel} title={focused.label}>
                    {focused.label}
                  </span>
                  <span className={styles.centerValue}>{usdPrecise(focused.usd)}</span>
                  <span className={styles.centerSub}>
                    {Math.round((focused.usd / total) * 100)}%
                  </span>
                </>
              ) : (
                <>
                  <span className={styles.centerLabel}>{t("budget.total")}</span>
                  <span className={styles.centerValue}>{usdPrecise(total)}</span>
                </>
              )}
            </div>
          </div>
        </div>

        <div className={styles.card}>
          <h3 className={styles.cardTitle}>{t("budget.modelRanking")}</h3>
          <ul className={styles.bars}>
            {slices.map((s) => {
              const active = hovered === s.key;
              const dim = hovered !== null && !active;
              return (
                <li
                  key={s.key}
                  className={styles.barRow}
                  data-active={active}
                  data-dim={dim}
                  onMouseEnter={(e) => enter(s.key, e)}
                  onMouseMove={(e) => move(s.key, e)}
                  onMouseLeave={leave}
                >
                  <span className={styles.swatch} style={{ background: s.color }} aria-hidden />
                  <span className={styles.barName} title={s.label}>
                    {s.label}
                  </span>
                  <div className={styles.barTrack}>
                    <div
                      className={styles.barFill}
                      style={{ width: `${max > 0 ? (s.usd / max) * 100 : 0}%`, background: s.color }}
                    />
                  </div>
                  <span className={styles.barValue}>{usdPrecise(s.usd)}</span>
                  <span className={styles.barPct}>{Math.round((s.usd / total) * 100)}%</span>
                </li>
              );
            })}
          </ul>
        </div>
      </div>

      {tip && tipSlice && (
        <div className={styles.tooltip} ref={tipRef} style={tipStyle} role="status">
          <div className={styles.tipHead}>
            <span className={styles.tipDot} style={{ background: tipSlice.color }} aria-hidden />
            <span className={styles.tipName}>{tipSlice.label}</span>
          </div>
          <dl className={styles.tipRows}>
            <div className={styles.tipRow}>
              <dt>{t("budget.tipSpend")}</dt>
              <dd>{usdPrecise(tipSlice.usd)}</dd>
            </div>
            <div className={styles.tipRow}>
              <dt>{t("budget.tipShare")}</dt>
              <dd>{((tipSlice.usd / total) * 100).toFixed(1)}%</dd>
            </div>
            <div className={styles.tipRow}>
              <dt>{tipSlice.otherCount > 0 ? t("budget.other") : t("budget.tipCalls")}</dt>
              <dd>
                {tipSlice.otherCount > 0
                  ? `${tipSlice.otherCount} ${t("budget.otherModels")}`
                  : tipSlice.calls}
              </dd>
            </div>
          </dl>
        </div>
      )}
    </div>
  );
}
