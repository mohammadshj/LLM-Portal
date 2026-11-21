export type User = {
  username: string;
  is_staff: boolean;
  token_limit: number;
  tokens_used: number;
};
export type Model = {
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
  active_request_id?: string | null;
  messages: Message[];
  errors: { model: string; detail: string }[];
};
export type Page = { results: Conversation[]; next: string | null };
export type Usage = {
  accounts: {
    user__username: string;
    token_limit: number;
    tokens_used: number;
  }[];
  models: {
    model_id: number;
    model__name: string;
    input_tokens: number;
    output_tokens: number;
    unsplit_tokens: number;
  }[];
};
