import { expect, test } from "vitest";

import {
  AUDIO_EXTENSIONS,
  VIDEO_EXTENSIONS,
  exportKindOf,
  mediaKindOf,
  producedMediaKindOf,
} from "./media";

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

const stages = (types: string[]) => types.map((type) => ({ type }));

test("produced media kind reads the task's output stages", () => {
  expect(producedMediaKindOf(stages(["ingest_transcript", "mix_audio", "export_audio"]))).toBe(
    "audio",
  );
  expect(producedMediaKindOf(stages(["ingest_transcript", "mix_audio", "mux"]))).toBe("video");
  expect(producedMediaKindOf(stages(["export_video"]))).toBe("video");
  expect(producedMediaKindOf(stages(["export_audio_custom"]))).toBe("audio");
  expect(producedMediaKindOf(stages(["ingest_subtitle", "translate"]))).toBeNull();
});

test("a task producing both kinds counts as video", () => {
  expect(producedMediaKindOf(stages(["export_audio", "mux"]))).toBe("video");
});

test("export kind prefers the input, then what the task produces", () => {
  // A subtitle pipeline fed a video: the export studio still encodes video.
  expect(
    exportKindOf({
      input_path: "/movies/ep.mp4",
      stages: stages(["extract_audio", "asr", "export_subtitles"]),
    }),
  ).toBe("video");
  // A compose task: the input is the transcript, the output is audio.
  expect(
    exportKindOf({
      input_path: "/subs/lines.srt",
      stages: stages(["ingest_transcript", "mix_audio", "export_audio"]),
    }),
  ).toBe("audio");
  // Nothing to export either way.
  expect(
    exportKindOf({
      input_path: "/subs/lines.srt",
      stages: stages(["ingest_subtitle", "translate", "export_subtitles"]),
    }),
  ).toBeNull();
  expect(
    exportKindOf({ input_path: "/audio/talk.mp3", stages: stages(["asr"]) }),
  ).toBe("audio");
});
