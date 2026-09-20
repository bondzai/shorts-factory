export interface Channel { id: string; name: string; handle: string | null; driver: string; variants: string[]; cadence: number; active: boolean; queue?: number }
export interface Job { running: boolean; name: string | null; channel_id: string | null; log: string[]; finished_at: string | null }
export interface Snap {
  channel: Channel; counts: Record<string, number>; queue: Clip[]; approved: Clip[]; planned: number;
  recent: Clip[]; spend_usd: number; spend_total_usd: number; job: Job; agents: { available: boolean };
  tasks: Record<string, number>;
}
export interface QC { verdict?: string; hook_strength?: number; policy_risk?: string; looks_templated?: boolean; reasons?: string[] }
export interface TitleChange { title: string; until: string; by: string; why?: string; views: number | null; avg_view_pct: number | null; swipe_away_pct: number | null }
export interface Clip {
  id: string; channel_id: string; generator: string; variant: string; seed: number; status: string;
  hook: string | null; why: string | null; title: string | null; description: string | null; hashtags: string[];
  render_desc: string | null; duration_s: number | null; loudness_lufs: number | null; sameness: number | null;
  cost_usd: number; qc: QC | null; reject_reason: string | null; has_video: boolean; hook_text: string | null;
  comment_prompt: string | null; title_history: TitleChange[]; published_at: string | null;
  facts?: Record<string, unknown>; created_at?: string; views?: number | null; avg_view_pct?: number | null;
  swipe_away_pct?: number | null; deleted_at?: string | null;
}
export interface ClipDetail extends Clip {
  facts: Record<string, unknown>; params: Record<string, unknown>; created_at: string; purged_at: string | null;
  likes: number | null; metrics_at: string | null; file: { path: string | null; exists: boolean; mb: number | null };
}
export interface Step { name: string; state: "done" | "current" | "pending"; by?: string | null; at?: string; note?: string }
export interface Task {
  id: number; channel_id: string; kind: string; params: Record<string, string>; status: string; priority: number;
  created_at: string; created_by: string | null; claimed_at: string | null; claimed_by: string | null;
  finished_at: string | null; result: Record<string, string> | null; error: string | null; clip_id: string | null;
  meaning: string; steps: Step[];
}
export interface TaskKind { meaning: string; params: Record<string, string | null>; builtin: boolean }
export interface Run { id: number; channel_id: string; started_at: string; ended_at: string | null; kind: string; status: string; detail: string | null; log: string | null; cost_usd: number }
export interface LogEvent { at: string; event: string; level: string; channel?: string; clip?: string; actor?: string; by?: string; [k: string]: unknown }
