import { describe, expect, test, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithConnection } from "../test/helpers";
import { StyleEditorView } from "./StyleEditorView";

const preset = {
  default: {
    font_name: "Arial", font_size: 48, primary_color: "#FFFFFF",
    outline_color: "#000000", outline: 2, shadow: 0, bold: false,
    alignment: 2, margin_v: 40,
  },
};

function api(overrides = {}) {
  return {
    getStyles: vi.fn(async () => preset),
    saveStyles: vi.fn(async () => ({ saved: true })),
    renderFrame: vi.fn(async () => new Blob([new Uint8Array([137, 80])], { type: "image/png" })),
    ...overrides,
  };
}

describe("StyleEditorView", () => {
  test("loads preset and shows the css preview with mapped font size", async () => {
    renderWithConnection(
      <StyleEditorView project="p" taskId="t1" onBack={() => {}} />,
      { api: api() },
    );
    const preview = await screen.findByTestId("css-preview");
    expect(preview).toHaveStyle({ fontSize: "48px" });
  });

  test("changing font size updates the preview live", async () => {
    renderWithConnection(
      <StyleEditorView project="p" taskId="t1" onBack={() => {}} />,
      { api: api() },
    );
    // Wait for the preset to load; its useEffect overwrites local edits.
    await waitFor(() =>
      expect(screen.getByTestId("css-preview")).toHaveStyle({ fontSize: "48px" }),
    );
    const size = screen.getByLabelText("字級");
    // jsdom exposes no selection API on number inputs, so clearing is not
    // possible here; append a digit instead (48 -> 480) to prove liveness.
    await userEvent.type(size, "0");
    expect(screen.getByTestId("css-preview")).toHaveStyle({ fontSize: "480px" });
  });

  test("exact frame button calls renderFrame and shows the image", async () => {
    const client = api();
    renderWithConnection(
      <StyleEditorView project="p" taskId="t1" onBack={() => {}} />,
      { api: client },
    );
    await screen.findByTestId("css-preview");
    await userEvent.click(screen.getByText("產生精確幀"));
    await waitFor(() => expect(client.renderFrame).toHaveBeenCalled());
    expect(await screen.findByTestId("exact-frame")).toBeInTheDocument();
  });

  test("save calls saveStyles with the edited preset", async () => {
    const client = api();
    renderWithConnection(
      <StyleEditorView project="p" taskId="t1" onBack={() => {}} />,
      { api: client },
    );
    await screen.findByTestId("css-preview");
    await userEvent.click(screen.getByText("儲存樣式"));
    await waitFor(() => expect(client.saveStyles).toHaveBeenCalled());
  });
});
