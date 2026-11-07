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
};
export type Conversation = { id: number; title: string };
export type Message = {
  id: number;
  role: "user" | "assistant";
  content: string;
  model_name: string | null;
  input_tokens: number;
  output_tokens: number;
};
export type Detail = Conversation & {
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
    model__name: string;
    input_tokens: number;
    output_tokens: number;
  }[];
};
