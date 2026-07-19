import { t, type MessageKey } from "../i18n";

// Engineering identifiers stay in core artifacts and profiles; the UI shows
// human wording. Unknown types (third-party profile stages) fall back to the
// raw identifier so nothing renders blank.
const STAGE_TYPE_KEYS: Record<string, MessageKey> = {
  ingest_subtitle: "stage.ingest_subtitle",
  ingest_transcript: "stage.ingest_transcript",
  extract_audio: "stage.extract_audio",
  asr: "stage.asr",
  segment: "stage.segment",
  translate: "stage.translate",
  export_subtitles: "stage.export_subtitles",
  hardburn: "stage.hardburn",
  proofread: "stage.proofread",
  noop: "stage.noop",
  ingest_document: "stage.ingest_document",
  chunk: "stage.chunk",
  translate_chunks: "stage.translate_chunks",
  qc_scan: "stage.qc_scan",
  export_document: "stage.export_document",
  diarize: "stage.diarize",
  tts_synthesize: "stage.tts_synthesize",
  align_duration: "stage.align_duration",
  mix_audio: "stage.mix_audio",
  mux: "stage.mux",
  translate_pdf: "stage.translate_pdf",
  export_transcript: "stage.export_transcript",
  export_audio: "stage.export_audio",
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

// Pipelines repeat the translate/qc pair for the flagged-retry round; a
// second occurrence gets a retry suffix so the stage list does not read
// as an accidental duplicate.
const RETRY_TYPES = new Set(["translate_chunks", "qc_scan"]);

export function stageListLabels(stages: { type: string }[]): string[] {
  const seen = new Map<string, number>();
  return stages.map((stage) => {
    const count = (seen.get(stage.type) ?? 0) + 1;
    seen.set(stage.type, count);
    const label = stageTypeLabel(stage.type);
    return count > 1 && RETRY_TYPES.has(stage.type)
      ? label + t("stage.retrySuffix")
      : label;
  });
}

export function stageStatusLabel(status: string): string {
  const key = STAGE_STATUS_KEYS[status];
  return key ? t(key) : status;
}

const EVENT_TYPE_KEYS: Record<string, MessageKey> = {
  task_started: "event.task_started",
  stage_started: "event.stage_started",
  stage_progress: "event.stage_progress",
  stage_completed: "event.stage_completed",
  task_waiting_review: "event.task_waiting_review",
  task_completed: "event.task_completed",
  task_failed: "event.task_failed",
  task_canceled: "event.task_canceled",
  task_paused: "event.task_paused",
  budget_warning: "event.budget_warning",
  budget_exceeded: "event.budget_exceeded",
  agent_round: "event.agent_round",
};

export function eventTypeLabel(type: string): string {
  const key = EVENT_TYPE_KEYS[type];
  return key ? t(key) : type;
}
