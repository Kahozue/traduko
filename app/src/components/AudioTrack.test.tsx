import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";

const convertFileSrcMock = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({
  convertFileSrc: (...args: unknown[]) => convertFileSrcMock(...args),
}));

import { AudioTrack } from "./AudioTrack";

beforeEach(() => {
  convertFileSrcMock.mockReset();
  convertFileSrcMock.mockImplementation((path: string) => `asset://localhost/${path}`);
});

function speedButton() {
  return screen.getByRole("button", { name: "倍速" });
}

test("speed starts at 1x and cycles up before wrapping through the slow rates", async () => {
  render(<AudioTrack path="/media/09-dub-mix.wav" />);
  expect(speedButton()).toHaveTextContent("1×");

  for (const expected of ["1.25×", "1.5×", "1.75×", "2×", "0.25×", "0.5×", "1×"]) {
    await userEvent.click(speedButton());
    expect(speedButton()).toHaveTextContent(expected);
  }
});

test("cycling the speed applies the rate to the audio element", async () => {
  const { container } = render(<AudioTrack path="/media/09-dub-mix.wav" />);
  const audio = container.querySelector("audio")!;
  expect(audio.playbackRate).toBe(1);

  await userEvent.click(speedButton());
  expect(audio.playbackRate).toBe(1.25);
});
