import { afterEach, describe, expect, it } from "vitest";
import { LocaleStore, localeStore } from "./locale";

afterEach(() => {
  localeStore.setLocale("zh-TW");
  localStorage.removeItem("traduko.locale");
});

describe("LocaleStore", () => {
  it("defaults to zh-TW and persists changes", () => {
    const store = new LocaleStore();
    expect(store.getLocale()).toBe("zh-TW");
    store.setLocale("ja");
    expect(store.getLocale()).toBe("ja");
    expect(localStorage.getItem("traduko.locale")).toBe("ja");
  });

  it("notifies subscribers on change", () => {
    const store = new LocaleStore();
    let calls = 0;
    const unsubscribe = store.subscribe(() => {
      calls += 1;
    });
    store.setLocale("en");
    store.setLocale("en");
    expect(calls).toBe(1);
    unsubscribe();
    store.setLocale("ja");
    expect(calls).toBe(1);
  });

  it("ignores garbage in storage", () => {
    localStorage.setItem("traduko.locale", "klingon");
    expect(new LocaleStore().getLocale()).toBe("zh-TW");
  });
});
