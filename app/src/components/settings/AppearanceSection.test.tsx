import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test } from "vitest";
import { themeStore } from "../../lib/theme";
import { AppearanceSection } from "./AppearanceSection";

beforeEach(() => {
  localStorage.clear();
  themeStore.setMode("system");
});

test("renders three options with system selected by default", () => {
  render(<AppearanceSection />);
  expect(screen.getByRole("radio", { name: "淺色" })).toHaveAttribute(
    "aria-checked",
    "false",
  );
  expect(screen.getByRole("radio", { name: "深色" })).toHaveAttribute(
    "aria-checked",
    "false",
  );
  expect(screen.getByRole("radio", { name: "跟隨系統" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
});

test("selecting dark applies immediately and persists", async () => {
  render(<AppearanceSection />);
  await userEvent.click(screen.getByRole("radio", { name: "深色" }));
  expect(screen.getByRole("radio", { name: "深色" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem("traduko.theme")).toBe("dark");
});

test("arrow keys move the selection", async () => {
  render(<AppearanceSection />);
  const light = screen.getByRole("radio", { name: "淺色" });
  await userEvent.click(light);
  light.focus();
  await userEvent.keyboard("{ArrowRight}");
  expect(screen.getByRole("radio", { name: "深色" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  expect(document.documentElement.dataset.theme).toBe("dark");
});

test("language control switches the locale store", async () => {
  const { localeStore } = await import("../../lib/locale");
  render(<AppearanceSection />);
  const group = screen.getByRole("radiogroup", { name: "介面語言" });
  expect(group).toBeInTheDocument();
  await userEvent.click(screen.getByRole("radio", { name: "English" }));
  expect(localeStore.getLocale()).toBe("en");
  localeStore.setLocale("zh-TW");
});
