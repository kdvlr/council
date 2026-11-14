export type ModeType = 'council' | 'conversation';

export interface ModelCatalogItem {
  id: string;
  provider: string;
  underlying_model?: string | null;
  input_cost_per_token?: number | null;
  output_cost_per_token?: number | null;
  max_tokens?: number | null;
}

export interface AttachmentPayload {
  filename: string;
  mime_type: string;
  extracted_text: string;
  char_count: number;
}

export interface PresetRecord {
  id: string;
  name: string;
  mode: ModeType;
  models: string[];
  chairman_model?: string | null;
  shared_constraints?: string | null;
  created_at: string;
}

export interface Mode1ResponseItem {
  id: string;
  run_id?: string;
  slot_index: number;
  model_id: string;
  status: 'streaming' | 'completed' | 'failed';
  content: string;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  latency_ms: number;
  avg_accuracy?: number | null;
  avg_insight?: number | null;
  avg_total?: number | null;
  error_message?: string | null;
}

export interface Mode1RatingItem {
  id: string;
  run_id: string;
  reviewer_model_id: string;
  target_model_id: string;
  anon_label: string;
  accuracy: number;
  insight: number;
  critique: string;
  latency_ms: number;
  cost_usd: number;
}

export interface Mode2TurnItem {
  id: string;
  run_id?: string;
  turn_number: number;
  round_number: number;
  slot_number: number;
  model_id?: string;
  is_tie_break: boolean;
  agreed: boolean;
  plan_version: number;
  revision_notes: string;
  plan_markdown: string;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  latency_ms: number;
  status: 'streaming' | 'completed' | 'failed';
  error_message?: string | null;
  endorsed_slots?: number[];
}

export interface RunMetrics {
  total_prompt_tokens?: number;
  total_completion_tokens?: number;
  total_cost_usd?: number;
  duration_ms?: number;
  chairman_latency_ms?: number;
  total_turns?: number;
  final_plan_version?: number;
}

export interface RunDetail {
  id: string;
  session_id: string;
  run_index: number;
  mode: ModeType;
  prompt: string;
  shared_constraints?: string | null;
  models: string[];
  chairman_spec?: string | null;
  resolved_chairman?: string | null;
  status: 'running' | 'completed' | 'cancelled' | 'failed';
  stage: string;
  final_markdown: string;
  consensus_status?: 'unanimous' | 'tie_break' | null;
  slot_mapping: Record<string, string>;
  attachments: AttachmentPayload[];
  metrics: RunMetrics;
  error_message?: string | null;
  created_at: string;
  completed_at?: string | null;
  responses: Mode1ResponseItem[];
  ratings: Mode1RatingItem[];
  turns: Mode2TurnItem[];
}

export interface SessionSummary {
  id: string;
  title: string;
  mode: ModeType;
  shared_constraints?: string | null;
  created_at: string;
  updated_at: string;
  run_count: number;
  latest_status?: string | null;
}

export interface SessionDetail {
  id: string;
  title: string;
  mode: ModeType;
  shared_constraints?: string | null;
  created_at: string;
  updated_at: string;
  runs: RunDetail[];
}
