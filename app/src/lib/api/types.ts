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

export interface TaskRecord {
  schema_version: number;
  id: string;
  project: string;
  input_path: string;
  profile: string;
  name: string | null;
  status: TaskStatus;
  stages: StageRecord[];
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

export interface BudgetInfo {
  month_usd: number;
  task_usd_limit: number | null;
  monthly_usd_limit: number | null;
  tasks: BudgetTaskSpend[];
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
  | "agent_round";

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

export type QcFlagType = "untranslated" | "echo" | "glossary";

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
  budget: BudgetConfigDoc;
  llm_providers: Record<string, ProviderConfigDoc>;
  notifications: NotificationsConfigDoc;
  discord_bot: DiscordBotConfigDoc;
  sync: SyncConfigDoc;
  mcp_servers: Record<string, McpServerConfigDoc>;
  skills: Record<string, SkillConfigDoc>;
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
  error?: string;
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
