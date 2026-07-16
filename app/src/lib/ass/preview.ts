import type { CSSProperties } from "react";
import type { SubtitleStylePreset } from "../api/types";

// ASS numpad alignment (1-9): 1-3 bottom, 4-6 middle, 7-9 top;
// column 1/4/7 left, 2/5/8 center, 3/6/9 right.
export function alignmentToFlex(alignment: number): {
  justifyContent: string;
  alignItems: string;
  textAlign: CSSProperties["textAlign"];
} {
  // In a column flex container: justifyContent is the vertical (main) axis,
  // alignItems the horizontal (cross) axis. Column of the numpad: 1/4/7 left,
  // 2/5/8 center, 3/6/9 right (alignment % 3 === 0 is the right column).
  const justifyContent =
    alignment <= 3 ? "flex-end" : alignment <= 6 ? "center" : "flex-start";
  const col = alignment % 3;
  const alignItems = col === 1 ? "flex-start" : col === 2 ? "center" : "flex-end";
  const textAlign = col === 1 ? "left" : col === 2 ? "center" : "right";
  return { justifyContent, alignItems, textAlign };
}

function outlineShadow(width: number, color: string): string {
  if (width <= 0) return "none";
  const w = width;
  const offsets = [
    [-w, -w], [0, -w], [w, -w],
    [-w, 0], [w, 0],
    [-w, w], [0, w], [w, w],
  ];
  return offsets.map(([x, y]) => `${x}px ${y}px 0 ${color}`).join(", ");
}

export function assStyleToCss(style: SubtitleStylePreset): CSSProperties {
  return {
    fontSize: `${style.font_size}px`,
    fontFamily: `"${style.font_name}", sans-serif`,
    color: style.primary_color,
    fontWeight: style.bold ? 700 : 400,
    textShadow: outlineShadow(style.outline, style.outline_color),
  };
}
