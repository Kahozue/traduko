import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";

const convertFileSrcMock = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({
  convertFileSrc: (...args: unknown[]) => convertFileSrcMock(...args),
}));

const revealArtifactMock = vi.fn();
vi.mock("../lib/shell", () => ({
  revealArtifact: (...args: unknown[]) => revealArtifactMock(...args),
}));

import { MediaPlayer } from "./MediaPlayer";

beforeEach(() => {
  convertFileSrcMock.mockReset();
  convertFileSrcMock.mockImplementation((path: string) => `asset://localhost/${path}`);
  revealArtifactMock.mockReset();
});

test("kind=video renders a video element with native controls and converted src", () => {
  const { container } = render(<MediaPlayer path="/media/episode.mp4" kind="video" />);
  const video = container.querySelector("video");
  expect(video).not.toBeNull();
  expect(video).toHaveAttribute("controls");
  expect(video).toHaveAttribute("src", "asset://localhost//media/episode.mp4");
  expect(container.querySelector("audio")).toBeNull();
});

test("kind=audio renders an audio element", () => {
  const { container } = render(<MediaPlayer path="/media/voice.wav" kind="audio" />);
  const audio = container.querySelector("audio");
  expect(audio).not.toBeNull();
  expect(audio).toHaveAttribute("controls");
  expect(container.querySelector("video")).toBeNull();
});

test("a media error swaps to the fallback row with a Finder button", async () => {
  const { container } = render(<MediaPlayer path="/media/episode.mkv" kind="video" />);
  fireEvent.error(container.querySelector("video")!);
  expect(screen.getByText("無法在應用內播放此格式")).toBeInTheDocument();
  expect(container.querySelector("video")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "在 Finder 顯示" }));
  expect(revealArtifactMock).toHaveBeenCalledWith("/media/episode.mkv");
});

test("convertFileSrc throwing falls back without crashing", () => {
  convertFileSrcMock.mockImplementation(() => {
    throw new Error("not in tauri");
  });
  const { container } = render(<MediaPlayer path="/media/voice.wav" kind="audio" />);
  expect(container.querySelector("audio")).toBeNull();
  expect(screen.getByText("無法在應用內播放此格式")).toBeInTheDocument();
});
