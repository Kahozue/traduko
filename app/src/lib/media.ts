// Shared media-extension classification. The task player and the new-task
// file picker both derive from these lists so they cannot drift apart.
// Classification is by the file itself, not the task's domain: a video task
// fed an audio file still gets an audio player.

export const VIDEO_EXTENSIONS = ["mp4", "mkv", "mov", "webm", "avi", "flv", "m4v"];

export const AUDIO_EXTENSIONS = [
  "mp3", "wav", "m4a", "aac", "flac", "ogg", "opus", "aiff", "wma",
];

export function mediaKindOf(path: string): "video" | "audio" | null {
  const dot = path.lastIndexOf(".");
  if (dot < 0) return null;
  const ext = path.slice(dot + 1).toLowerCase();
  if (VIDEO_EXTENSIONS.includes(ext)) return "video";
  if (AUDIO_EXTENSIONS.includes(ext)) return "audio";
  return null;
}
