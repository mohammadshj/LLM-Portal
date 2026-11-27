export type Credit = {
  credit_limit_rial: number;
  credit_used_rial: number;
  credit_remaining_rial: number;
  credit_reserved_rial: number;
  credit_available_rial: number;
  credit_version: number;
};
export type User = Credit & {
  username: string;
  is_staff: boolean;
};
export type ReasoningSettings = {
  toggle?: boolean;
  effort?: string;
  budget?: number;
};
export type ReasoningControl = {
  type: keyof ReasoningSettings;
  default_source?: string;
  required: boolean;
  default?: boolean | string | number;
  options?: {
    value: string | boolean | number;
    label?: string;
    semantic_level?: string;
    disables_reasoning?: boolean;
  }[];
  min?: number;
  max?: number;
};
export type ReasoningProfile = {
  available: boolean;
  supported: boolean | null;
  mandatory: boolean | null;
  mode:
    | "unknown"
    | "none"
    | "fixed"
    | "toggle"
    | "effort"
    | "budget"
    | "combined";
  controls: ReasoningControl[];
  exclusive: (keyof ReasoningSettings)[];
};
export type Model = {
  input_price_per_million_rial: number | null;
  output_price_per_million_rial: number | null;
  reasoning_profile: ReasoningProfile;
  id: number;
  name: string;
  provider: string;
  context_window: number;
  reasoning_supported?: boolean | null;
  thinking_levels: string[];
  thinking_default: string;
};
export type Conversation = {
  id: number;
  title: string;
  is_processing?: boolean;
};
export type Message = {
  free_tariff?: boolean;
  cost_rial?: number | null;
  billing_source?: string;
  billing_status?: string;
  id: number;
  role: "user" | "assistant";
  content: string;
  model_name: string | null;
  status?: "running" | "completed" | "partial" | "failed" | "cancelled";
  request_id?: string | null;
  model_id?: number | null;
  parent_id?: number | null;
  error?: string;
  reasoning_content?: string | null;
  thinking_level?: string;
  reasoning_settings?: ReasoningSettings;
  elapsed_ms?: number | null;
  // Local monotonic timestamp for the latest running elapsed_ms snapshot.
  elapsedSampleAt?: number;
  reasoning_tokens?: number | null;
  total_tokens?: number | null;
  usage_source?:
    | "reported"
    | "estimated"
    | "partial"
    | "estimate_in"
    | "estimate_out"
    | "unknown"
    | "none";
  input_tokens: number | null;
  output_tokens: number | null;
};
export type Detail = Conversation & {
  active_leaf?: number | null;
  versions?: Record<number, number[]>;
  active_request_id?: string | null;
  messages: Message[];
  errors: { model: string; detail: string }[];
};
export type Page = { results: Conversation[]; next: string | null };
