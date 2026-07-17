import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ThemeStore } from "./theme";

type MediaListener = (event: { matches: boolean }) => void;

function stubMatchMedia(initialMatches: boolean) {
  const listeners = new Set<MediaListener>();
  const mql = {
    matches: initialMatches,
    addEventListener: (_type: string, listener: MediaListener) => {
      listeners.add(listener);
    },
    removeEventListener: (_type: string, listener: MediaListener) => {
      listeners.delete(listener);
    },
  };
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue(mql));
  return {
    listeners,
    flip(matches: boolean) {
      mql.matches = matches;
      for (const listener of [...listeners]) listener({ matches });
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("defaults to system and resolves through matchMedia", () => {
  stubMatchMedia(true);
  const store = new ThemeStore();
  store.init();
  expect(store.getMode()).toBe("system");
  expect(document.documentElement.dataset.theme).toBe("dark");
});

test("without matchMedia the system mode falls back to light", () => {
  const store = new ThemeStore();
  store.init();
  expect(document.documentElement.dataset.theme).toBe("light");
});

test("setMode applies immediately and persists", () => {
  stubMatchMedia(false);
  const store = new ThemeStore();
  store.init();
  store.setMode("dark");
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem("traduko.theme")).toBe("dark");
});

test("a persisted mode wins over the system preference", () => {
  stubMatchMedia(true);
  localStorage.setItem("traduko.theme", "light");
  const store = new ThemeStore();
  store.init();
  expect(store.getMode()).toBe("light");
  expect(document.documentElement.dataset.theme).toBe("light");
});

test("system mode follows live preference changes", () => {
  const media = stubMatchMedia(false);
  const store = new ThemeStore();
  store.init();
  expect(document.documentElement.dataset.theme).toBe("light");
  media.flip(true);
  expect(document.documentElement.dataset.theme).toBe("dark");
});

test("leaving system mode stops following the media query", () => {
  const media = stubMatchMedia(false);
  const store = new ThemeStore();
  store.init();
  store.setMode("light");
  expect(media.listeners.size).toBe(0);
  media.flip(true);
  expect(document.documentElement.dataset.theme).toBe("light");
});

test("subscribers are notified on mode changes", () => {
  stubMatchMedia(false);
  const store = new ThemeStore();
  const seen: string[] = [];
  store.subscribe(() => seen.push(store.getMode()));
  store.setMode("dark");
  expect(seen).toEqual(["dark"]);
});
