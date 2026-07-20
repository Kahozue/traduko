export type TaskStatus =
  | "pending"
  | "running"
  | "waiting_review"
  | "paused"
  | "completed"
  | "failed"
  | "canceled";

export type StageStatus = "pending" | "running" | "completed" | "failed" | "skipped";

export interface StageRecord {
  type: string;
  status: StageStatus;
  params: Record<string, unknown>;
  pause_after: boolean;
  artifacts: string[];
  error: string | null;
}

// Pipeline switches; null means no explicit choice (the stages stand as the
// profile made them). The record field is absent on tasks from older cores.
export interface TaskSwitches {
  translate: boolean | null;
  diarize: boolean | null;
  dub: boolean | null;
}

export interface TaskRecord {
  schema_version: number;
  id: string;
  project: string;
  input_path: string;
  profile: string;
  name: string | null;
  status: TaskStatus;
  stages: StageRecord[];
  glossary: TaskGlossary;
  switches?: TaskSwitches | null;
  created_at: string;
  updated_at: string;
}

export interface TaskIndexRow {
  id: string;
  project: string;
  status: TaskStatus;
  profile: string;
  name: string;
  created_at: string;
  updated_at: string;
}

export type TaskKind = "video" | "audio" | "document" | "comic";

export interface TaskGlossary {
  global_ids: string[];
  use_task: boolean;
  asr_mode: "auto" | "force" | "off";
}

export interface ProfileInfo {
  name: string;
  kind: TaskKind;
  stages: string[];
}

export interface PreflightCheck {
  name: string;
  level: string;
  message: string;
}

export interface PreflightReport {
  ok: boolean;
  checks: PreflightCheck[];
}

export interface BudgetTaskSpend {
  task_id: string;
  project: string;
  name: string | null;
  usd: number;
}

export interface BudgetModelSpend {
  model: string;
  usd: number;
  // Number of ledger rows (LLM calls / transcriptions) behind this spend.
  // Optional: an older core may not send it.
  calls?: number;
}

export interface BudgetInfo {
  month_usd: number;
  task_usd_limit: number | null;
  monthly_usd_limit: number | null;
  tasks: BudgetTaskSpend[];
  // An older core may not send the per-model breakdown yet.
  models?: BudgetModelSpend[];
}

export interface PersistedEvent {
  ts: string;
  type: string;
  data: Record<string, unknown>;
}

export type EventType =
  | "task_started"
  | "stage_started"
  | "stage_progress"
  | "stage_completed"
  | "task_waiting_review"
  | "task_completed"
  | "task_failed"
  | "task_canceled"
  | "task_paused"
  | "budget_warning"
  | "budget_exceeded"
  | "agent_round"
  | "assistant_round"
  | "assistant_delta"
  | "assistant_text"
  | "assistant_tool_started"
  | "assistant_tool_finished"
  | "assistant_authorization_required"
  | "assistant_done";

export interface EventPayload {
  ts: string;
  type: EventType;
  task_id: string;
  project: string;
  data: Record<string, unknown>;
}

export interface TranslationSegment {
  id: number;
  start: number;
  end: number;
  source: string;
  target: string;
}

export interface TranslationArtifact {
  schema_version: number;
  source_language: string;
  target_language: string;
  segments: TranslationSegment[];
}

export interface DocBlock {
  id: string;
  kind: string;
  translate: boolean;
  text: string;
  anchor: string;
}

export interface DocChapter {
  id: string;
  title: string;
  href: string;
  blocks: DocBlock[];
}

export interface DocumentArtifact {
  schema_version: number;
  format: string;
  chapters: DocChapter[];
}

export interface DocChunk {
  id: string;
  chapter_id: string;
  block_ids: string[];
  char_count: number;
}

export interface DocChunksArtifact {
  schema_version: number;
  chunks: DocChunk[];
}

export interface DocTranslatedBlock {
  id: string;
  text: string;
}

export type DocChunkStatus = "translated" | "failed" | "pending";

export interface DocTranslatedChunk {
  id: string;
  status: DocChunkStatus;
  blocks: DocTranslatedBlock[];
}

export interface DocTranslationArtifact {
  schema_version: number;
  chunks: DocTranslatedChunk[];
}

export type QcFlagType =
  | "untranslated"
  | "echo"
  | "glossary"
  | "failed"
  // Written by the document editor, never by the qc stage.
  | "manual";

export interface QcFlag {
  chunk_id: string;
  block_id: string;
  type: QcFlagType;
  evidence: string;
}

export interface QcArtifact {
  schema_version: number;
  flags: QcFlag[];
}

export interface ArtifactListItem {
  file: string;
  index: number;
  name: string;
  schema_version: number | null;
  size: number;
  mtime: number;
}

export interface ProofreadFlag {
  id: number;
  note: string;
  round: number;
}

export interface SubtitleStylePreset {
  font_name: string;
  font_size: number;
  primary_color: string;
  outline_color: string;
  outline: number;
  shadow: number;
  bold: boolean;
  alignment: number;
  margin_v: number;
}

export type ProviderConfigDoc = Record<string, unknown>;

export type ChannelConfigDoc = Record<string, unknown>;

export interface BudgetConfigDoc {
  task_usd_limit: number | null;
  monthly_usd_limit: number | null;
  [key: string]: unknown;
}

export interface NotificationsConfigDoc {
  channels: ChannelConfigDoc[];
  [key: string]: unknown;
}

export interface DiscordBotConfigDoc {
  enabled: boolean;
  bot_token: string;
  bot_token_env: string;
  guild_id: string;
  channel_id: string;
  allowed_user_ids: string[];
  [key: string]: unknown;
}

export interface SyncConfigDoc {
  enabled: boolean;
  mode: "folder" | "webdav";
  folder_path: string;
  webdav_url: string;
  webdav_username: string;
  webdav_password: string;
  auto_interval_minutes: number;
  [key: string]: unknown;
}

export interface McpServerConfigDoc {
  transport: "stdio" | "http";
  command: string;
  args: string[];
  env: Record<string, string>;
  url: string;
  auth_token: string;
  enabled: boolean;
  // Safety gate: an enabled server only enters the agent once the user has
  // confirmed its tool list. Optional because a v2-04 core omits it.
  confirmed?: boolean;
  [key: string]: unknown;
}

export interface SkillConfigDoc {
  enabled: boolean;
  confirmed: boolean;
  [key: string]: unknown;
}

// Row of GET /skills: on-disk SKILL.md folders merged with config flags.
export interface SkillInfo {
  name: string;
  description: string;
  enabled: boolean;
  confirmed: boolean;
  valid: boolean;
  errors: string[];
}

// Glossary: one named CSV table per file plus a manifest (v3_5-02). The
// settings panels manage them as files, outside the config draft.
export type GlossaryDomain = "video" | "audio" | "document" | "comic" | "general";

export interface GlossaryTableMeta {
  id: string;
  name: string;
  domain: GlossaryDomain;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

// Row of GET /glossaries: table metadata plus the entry count.
export interface GlossaryTable extends GlossaryTableMeta {
  entry_count: number;
  // Only POST /glossaries/import fills this: one message per row the core
  // dropped for a missing source or target.
  skipped?: string[];
}

export interface GlossaryEntry {
  source: string;
  target: string;
  notes: string;
  category: string;
}

// GET /glossaries/{id}: metadata plus the full entry list.
export interface GlossaryDetail extends GlossaryTableMeta {
  entries: GlossaryEntry[];
}

export interface McpCandidate {
  name: string;
  available: boolean;
  install_hint: string;
  heavy: boolean;
  config: McpServerConfigDoc;
}

export type McpServerState = "connected" | "connecting" | "error" | "disabled";

export interface McpToolInfo {
  name: string;
  description: string;
}

export interface McpServerStatus {
  name: string;
  transport: "stdio" | "http";
  enabled: boolean;
  confirmed: boolean;
  state: McpServerState;
  error: string;
  tools: McpToolInfo[];
}

export interface ProposalDoc {
  id: string;
  kind: "config";
  reason: string;
  patch: Record<string, unknown>;
  diff: string;
  status: "pending" | "applied" | "rejected";
  created_at: string;
}

export interface CoreConfigDoc {
  schema_version: number;
  default_project: string;
  default_provider?: string;
  budget: BudgetConfigDoc;
  llm_providers: Record<string, ProviderConfigDoc>;
  notifications: NotificationsConfigDoc;
  discord_bot: DiscordBotConfigDoc;
  sync: SyncConfigDoc;
  mcp_servers: Record<string, McpServerConfigDoc>;
  skills: Record<string, SkillConfigDoc>;
  dubbing: DubbingConfigDoc;
  pdf: PdfEngineConfigDoc;
  asr: AsrConfigDoc;
  audio: AudioConfigDoc;
  translation_defaults: TranslationDefaultsDoc;
  [key: string]: unknown;
}

export interface GlossaryRow {
  source: string;
  target: string;
  notes: string;
  scope: string;
}

export interface SyncConflict {
  file: string;
  source: string;
  local: GlossaryRow;
  remote: GlossaryRow;
}

export interface SyncReport {
  ok: boolean;
  pushed: string[];
  pulled: string[];
  merged: string[];
  conflicts: number;
  error: string | null;
}

export interface SyncPeerTask {
  id: string;
  project: string;
  name: string;
  status: string;
  profile: string;
  created_at: string;
  updated_at: string;
}

export interface SyncPeer {
  machine: string;
  tasks: SyncPeerTask[];
}

export interface SyncStatus {
  enabled: boolean;
  mode: "folder" | "webdav";
  syncing: boolean;
  last_sync: string | null;
  last_result: SyncReport | null;
  conflicts: SyncConflict[];
  peers: SyncPeer[];
}

export interface NotifyTestResult {
  ok: boolean;
  error?: string;
}

export interface ProviderTestResult {
  ok: boolean;
  error?: string;
}

export interface AsrStatus {
  package: boolean;
  model: string;
  cached: boolean;
  state: "idle" | "downloading" | "done" | "error";
  downloading: boolean;
  downloaded_mb: number;
  error: string | null;
}

export interface AsrTestResult {
  ok: boolean;
  load_seconds?: number;
  locales?: number;
  installed?: string[];
  error?: string;
}

export interface AsrConfigDoc {
  engine: string;
  audio_engine: string;
  model: string;
  macos_locale: string;
  cloud_base_url: string;
  cloud_api_key: string;
  cloud_api_key_env: string;
  custom_base_url: string;
  custom_api_key: string;
  custom_api_key_env: string;
  custom_model: string;
  zh_prompt: boolean;
  [key: string]: unknown;
}

export interface AsrEngineInfo {
  id: string;
  kind: "local" | "cloud";
  timestamps: boolean;
}

export interface MacosAsrStatus {
  platform_ok: boolean;
  compiled?: boolean;
  available: boolean;
  probed?: boolean;
  os_ok?: boolean;
  transcriber_locales: string[];
  dictation_locales: string[];
  installed_locales: string[];
  assets_state: "idle" | "downloading" | "done" | "error";
  assets_progress: number;
  assets_error: string | null;
  error: string | null;
}

export interface AsrEnginesInfo {
  engines: AsrEngineInfo[];
  macos: MacosAsrStatus;
  cloud_key_present: boolean;
  custom_ready: boolean;
}

export interface DubbingConfigDoc {
  hf_token: string;
  python: string;
  inference_timesteps: number | null;
  cfg_value: number | null;
  seed: number | null;
  denoise: boolean;
  // Video-domain pipeline default: whether new tasks run diarization.
  diarize_enabled: boolean;
  [key: string]: unknown;
}

// Audio-domain pipeline defaults: initial switch values for new audio tasks.
export interface TranslationDomainDefaultsDoc {
  target_language: string;
  style: string;
  prompt_override: string;
  [key: string]: unknown;
}

export interface TranslationDefaultsDoc {
  video: TranslationDomainDefaultsDoc;
  audio: TranslationDomainDefaultsDoc;
  document: TranslationDomainDefaultsDoc;
  comic: TranslationDomainDefaultsDoc;
  [key: string]: unknown;
}

// Task-level translation settings, read off the task's translate stages.
export interface TaskTranslationDoc {
  stage_type: string;
  target_language: string;
  style: string;
  prompt_override: string;
}

export interface AudioConfigDoc {
  diarize_enabled: boolean;
  dub_enabled: boolean;
  translate_enabled: boolean;
  [key: string]: unknown;
}

export interface DubbingModelStatus {
  repo: string;
  total_mb: number;
  downloaded_mb: number;
  cached: boolean;
  state: "idle" | "downloading" | "done" | "error";
  downloading: boolean;
  error: string | null;
}

export interface DubbingStatus {
  python: string;
  venv: boolean;
  installed: boolean;
  state: "idle" | "installing" | "done" | "error";
  installing: boolean;
  error: string | null;
  installed_mb: number;
}

export interface DubbingTestResult {
  ok: boolean;
  python?: string;
  torch?: string | null;
  voxcpm?: string | null;
  pyannote?: string | null;
  mps?: boolean;
  error?: string;
}

export interface PdfEngineConfigDoc {
  python: string;
  [key: string]: unknown;
}

export interface PdfEngineStatus {
  python: string;
  venv: boolean;
  installed: boolean;
  state: "idle" | "installing" | "warming" | "done" | "error";
  installing: boolean;
  warming?: boolean;
  error: string | null;
  installed_mb: number;
  cache_mb?: number;
}

export interface PdfEngineTestResult {
  ok: boolean;
  version?: string;
  // Machine-readable failure class ("timeout") so the UI can translate
  // known cases instead of dumping the raw subprocess error.
  error_kind?: string;
  error?: string;
}

export interface SpeakerDoc {
  id: string;
  label: string;
  ref_start: number;
  ref_end: number;
  ref_text: string;
}

export interface SpeakerAssignmentDoc {
  id: number;
  speaker: string;
}

export interface SpeakersDoc {
  schema_version: number;
  speakers: SpeakerDoc[];
  segments: SpeakerAssignmentDoc[];
}

export type AssistantRole = "user" | "assistant";

export interface AssistantMessageDoc {
  role: AssistantRole;
  text: string;
  ts: string;
  // Only present on assistant messages that filed a config proposal.
  proposal_ids?: string[];
  // The model that produced this assistant reply; absent on older rows and
  // on user messages.
  model?: string;
  // Absolute paths of image files attached to a user message.
  images?: string[];
}

export interface AssistantSessionRow {
  id: string;
  title: string;
  archived: boolean;
  created_at: string;
  updated_at: string;
  message_count: number;
  active: boolean;
}

export interface AssistantReply {
  reply: string;
  proposal_ids: string[];
  created_task_ids?: string[];
  converged: boolean;
  reason: string;
  history: AssistantMessageDoc[];
}

// Dubbing studio engine catalog (GET /dub/engines).
export interface TtsEngineInfo {
  id: string;
  kind: "local" | "cloud" | "placeholder";
  voice_modes: string[];
  available: boolean;
}

// Aggregated dub params for a task's dub group (GET/PATCH /tasks/.../dub/params).
export interface ExportEstimate {
  size_bytes: number;
  eta_seconds: number;
  disk_ok: boolean;
  disk_available: number;
  duration: number;
  width: number | null;
  height: number | null;
}

// Export panel snapshot. The core validates it and stores it on the
// appended stage, so the field names match the stage params exactly.
export type ExportParams = Record<string, string | number>;

// GET /dub/voices: the say engine's system voices. Empty off macOS.
export interface SayVoice {
  name: string;
  locale: string;
}

// dub-manifest.json: one entry per synthesized segment.
export interface DubManifestSegment {
  id: number;
  speaker: string;
  file: string;
  duration: number;
  status: "synthesized" | "failed";
  error: string;
}

export interface DubManifestDoc {
  schema_version: number;
  segments: DubManifestSegment[];
}

// speakers.json: the diarized speakers and their reference spans.
export interface DubSpeaker {
  id: string;
  label: string;
  ref_start: number;
  ref_end: number;
  ref_text: string;
}

export interface SpeakersDoc {
  schema_version: number;
  speakers: DubSpeaker[];
  segments: { id: number; speaker: string }[];
}

export interface DubParams {
  engine_id: string | null;
  voice_mode: string;
  instruction: string | null;
  cfg: number | null;
  timesteps: number | null;
  seed: number | null;
  denoise: number | null;
  preview_voice: string | null;
  preview_rate: number | null;
  dub_text: string;
}
