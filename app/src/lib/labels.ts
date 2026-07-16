import { t, type MessageKey } from "../i18n";

// Engineering identifiers stay in core artifacts and profiles; the UI shows
// human wording. Unknown types (third-party profile stages) fall back to the
// raw identifier so nothing renders blank.
const STAGE_TYPE_KEYS: Record<string, MessageKey> = {
  ingest_subtitle: "stage.ingest_subtitle",
  extract_audio: "stage.extract_audio",
  asr: "stage.asr",
  segment: "stage.segment",
  translate: "stage.translate",
  export_subtitles: "stage.export_subtitles",
  hardburn: "stage.hardburn",
  proofread: "stage.proofread",
  noop: "stage.noop",
};

const STAGE_STATUS_KEYS: Record<string, MessageKey> = {
  pending: "status.pending",
  running: "status.running",
  completed: "status.completed",
  failed: "status.failed",
  skipped: "status.skipped",
};

export function stageTypeLabel(type: string): string {
  const key = STAGE_TYPE_KEYS[type];
  return key ? t(key) : type;
}

export function stageStatusLabel(status: string): string {
  const key = STAGE_STATUS_KEYS[status];
  return key ? t(key) : status;
}
