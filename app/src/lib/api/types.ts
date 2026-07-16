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

export interface BudgetInfo {
  month_usd: number;
  task_usd_limit: number | null;
  monthly_usd_limit: number | null;
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

export interface CoreConfigDoc {
  schema_version: number;
  default_project: string;
  budget: BudgetConfigDoc;
  llm_providers: Record<string, ProviderConfigDoc>;
  notifications: NotificationsConfigDoc;
  discord_bot: DiscordBotConfigDoc;
  [key: string]: unknown;
}

export interface NotifyTestResult {
  ok: boolean;
  error?: string;
}
