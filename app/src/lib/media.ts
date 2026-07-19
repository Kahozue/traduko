// Shared media-extension classification. The task player and the new-task
// file picker both derive from these lists so they cannot drift apart.
// Classification is by the file itself, not the task's domain: a video task
// fed an audio file still gets an audio player.

export const VIDEO_EXTENSIONS = ["mp4", "mkv", "mov", "webm", "avi", "flv", "m4v"];

export const AUDIO_EXTENSIONS = [
  "mp3", "wav", "m4a", "aac", "flac", "ogg", "opus", "aiff", "wma",
];

export type MediaKind = "video" | "audio";

// Stages that write a media file of their own. A compose task's input is a
// transcript, so what it can export is only knowable from what it produces.
const PRODUCED_KIND: Record<string, MediaKind> = {
  mux: "video",
  export_video: "video",
  hardburn: "video",
  export_audio: "audio",
  export_audio_custom: "audio",
};

export function producedMediaKindOf(stages: { type: string }[]): MediaKind | null {
  let found: MediaKind | null = null;
  for (const stage of stages) {
    const kind = PRODUCED_KIND[stage.type];
    // Video wins over audio: a video output already carries the audio.
    if (kind === "video") return "video";
    if (kind === "audio") found = "audio";
  }
  return found;
}

// What the export studio can work on, and therefore whether its entry point
// shows at all. Both views derive from this one function: computing it twice
// is how the two of them drift apart.
export function exportKindOf(task: {
  input_path: string;
  stages: { type: string }[];
}): MediaKind | null {
  return mediaKindOf(task.input_path) ?? producedMediaKindOf(task.stages);
}

export function mediaKindOf(path: string): "video" | "audio" | null {
  const dot = path.lastIndexOf(".");
  if (dot < 0) return null;
  const ext = path.slice(dot + 1).toLowerCase();
  if (VIDEO_EXTENSIONS.includes(ext)) return "video";
  if (AUDIO_EXTENSIONS.includes(ext)) return "audio";
  return null;
}
