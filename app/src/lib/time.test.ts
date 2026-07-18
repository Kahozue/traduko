import { describe, expect, it } from "vitest";
import { formatDateTime } from "./time";

describe("formatDateTime", () => {
  it("renders zero-padded 24h local time at a fixed width", () => {
    const iso = new Date(2026, 6, 16, 21, 28, 0).toISOString();
    expect(formatDateTime(iso)).toBe("2026/07/16 21:28:00");
  });

  it("pads single-digit fields so widths never vary", () => {
    const a = formatDateTime(new Date(2026, 6, 18, 11, 50, 53).toISOString());
    const b = formatDateTime(new Date(2026, 6, 16, 9, 8, 0).toISOString());
    expect(a).toBe("2026/07/18 11:50:53");
    expect(b).toBe("2026/07/16 09:08:00");
    expect(a.length).toBe(b.length);
  });

  it("returns the raw input when unparseable", () => {
    expect(formatDateTime("not-a-date")).toBe("not-a-date");
  });
});
