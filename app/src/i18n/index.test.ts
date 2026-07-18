import { afterEach, expect, test } from "vitest";
import { localeStore } from "../lib/locale";
import { t } from "./index";
import { zhTW } from "./zh-TW";
import { en } from "./en";
import { ja } from "./ja";

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
