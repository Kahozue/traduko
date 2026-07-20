import { afterEach, expect, test } from "vitest";
import { localeStore } from "../lib/locale";
import { t } from "./index";
import { zhTW } from "./zh-TW";
import { en } from "./en";
import { ja } from "./ja";

// The three tables were once generated from zh-TW by a script that held its
// own copy of every translation. Two sources of truth drift, and that one
// did: it was hundreds of keys stale before anyone noticed, because nothing
// ran it. The tables are now edited by hand and these tests are what keeps
// them in step.
const LOCALE_FILES = ["./zh-TW.ts", "./en.ts", "./ja.ts"] as const;

// Read as raw text rather than through the imported objects: a duplicate key
// and a reordering are both invisible once the file has been evaluated.
const LOCALE_SOURCES = import.meta.glob("./{zh-TW,en,ja}.ts", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

function sourceKeysOf(file: string): string[] {
  const source = LOCALE_SOURCES[file];
  expect(source, `could not read ${file} as text`).toBeTruthy();
  return [...source.matchAll(/^ {2}"((?:[^"\\]|\\.)+)":/gm)].map((m) => m[1]);
}

afterEach(() => {
  localeStore.setLocale("zh-TW");
});

test("t returns traditional chinese copy by default", () => {
  expect(t("conn.unavailable")).toBe("核心服務啟動失敗");
});

test("t follows the active locale", () => {
  localeStore.setLocale("en");
  expect(t("nav.tasks")).toBe("Tasks");
  localeStore.setLocale("ja");
  expect(t("nav.tasks")).toBe("タスク");
});

test("all locales carry the full key set", () => {
  const keys = Object.keys(zhTW);
  expect(Object.keys(en).sort()).toEqual([...keys].sort());
  expect(Object.keys(ja).sort()).toEqual([...keys].sort());
  for (const key of keys) {
    expect((en as Record<string, string>)[key], `en missing ${key}`).toBeTruthy();
    expect((ja as Record<string, string>)[key], `ja missing ${key}`).toBeTruthy();
  }
});

test("no locale file declares a key twice", () => {
  // A duplicate is invisible at runtime -- the later entry wins and the
  // object still has the right size -- so only the source text shows it.
  for (const file of LOCALE_FILES) {
    const keys = sourceKeysOf(file);
    const seen = new Set<string>();
    const duplicates = keys.filter((key) => seen.size === seen.add(key).size);
    expect(duplicates, `${file} declares these keys twice`).toEqual([]);
  }
});

test("the three locale files list their keys in the same order", () => {
  // Same order means a key added to zh-TW lands next to its neighbours in
  // the other two, so the files stay diffable side by side.
  const [zhKeys, ...others] = LOCALE_FILES.map(sourceKeysOf);
  for (const [index, file] of [...LOCALE_FILES].slice(1).entries()) {
    expect(others[index], `${file} key order differs from zh-TW.ts`).toEqual(zhKeys);
  }
});
