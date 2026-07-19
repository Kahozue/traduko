import { expect, test } from "vitest";

import { AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, mediaKindOf } from "./media";

test("video extensions classify as video", () => {
  expect(mediaKindOf("/movies/episode.mp4")).toBe("video");
  expect(mediaKindOf("/movies/episode.mkv")).toBe("video");
  expect(mediaKindOf("/movies/episode.webm")).toBe("video");
});

test("audio extensions classify as audio", () => {
  expect(mediaKindOf("/audio/podcast.wav")).toBe("audio");
  expect(mediaKindOf("/audio/podcast.mp3")).toBe("audio");
  expect(mediaKindOf("/audio/podcast.opus")).toBe("audio");
});

test("non-media and extension-less paths classify as null", () => {
  expect(mediaKindOf("/subs/episode.srt")).toBeNull();
  expect(mediaKindOf("/docs/novel.txt")).toBeNull();
  expect(mediaKindOf("/docs/paper.pdf")).toBeNull();
  expect(mediaKindOf("/misc/README")).toBeNull();
  expect(mediaKindOf("")).toBeNull();
});

test("extension match is case-insensitive", () => {
  expect(mediaKindOf("/movies/EPISODE.MP4")).toBe("video");
  expect(mediaKindOf("/audio/VOICE.Wav")).toBe("audio");
});

test("extension lists stay disjoint", () => {
  const overlap = VIDEO_EXTENSIONS.filter((ext) => AUDIO_EXTENSIONS.includes(ext));
  expect(overlap).toEqual([]);
});
