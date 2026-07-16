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
