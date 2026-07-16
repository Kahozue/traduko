import { describe, expect, test } from "vitest";
import { alignmentToFlex, assStyleToCss } from "./preview";
import type { SubtitleStylePreset } from "../api/types";

const base: SubtitleStylePreset = {
  font_name: "Arial", font_size: 48, primary_color: "#FFEE00",
  outline_color: "#000000", outline: 2, shadow: 0, bold: true,
  alignment: 2, margin_v: 40,
};

describe("assStyleToCss", () => {
  test("maps font size, family, color and weight", () => {
    const css = assStyleToCss(base);
    expect(css.fontSize).toBe("48px");
    expect(css.fontFamily).toContain("Arial");
    expect(css.color).toBe("#FFEE00");
    expect(css.fontWeight).toBe(700);
  });

  test("outline becomes a multi-direction text-shadow in the outline color", () => {
    const css = assStyleToCss(base);
    expect(String(css.textShadow)).toContain("#000000");
    expect(String(css.textShadow).split(",").length).toBeGreaterThanOrEqual(4);
  });

  test("zero outline yields no text-shadow", () => {
    const css = assStyleToCss({ ...base, outline: 0 });
    expect(css.textShadow ?? "none").toBe("none");
  });
});

describe("alignmentToFlex", () => {
  test("2 is bottom-center", () => {
    expect(alignmentToFlex(2)).toEqual({
      justifyContent: "flex-end",
      alignItems: "center",
      textAlign: "center",
    });
  });

  test("7 is top-left", () => {
    expect(alignmentToFlex(7)).toEqual({
      justifyContent: "flex-start",
      alignItems: "flex-start",
      textAlign: "left",
    });
  });
});
