import type { Credit, Message, ReasoningSettings } from "./types";
import { request } from "./api";

export type ChatEvent = {
  type:
    | "start"
    | "model_start"
    | "reasoning_delta"
    | "delta"
    | "model_done"
    | "model_error"
    | "ping"
    | "done";
  request_id: string;
  conversation_id: number;
  model_id?: number;
  text?: string;
  elapsed_ms?: number | null;
  detail?: string;
  usage?: Pick<
    Message,
    | "input_tokens"
    | "output_tokens"
    | "reasoning_tokens"
    | "total_tokens"
    | "usage_source"
  >;
  billing?: Pick<
    Message,
    "free_tariff" | "cost_rial" | "billing_status" | "billing_source"
  >;
  credit?: Credit;
  status?: string;
};

export async function streamChat(
  conversation: number,
  body: {
    content: string;
    model_ids?: number[];
    edit_of?: number;
    expected_leaf?: number | null;
    reasoning?: Record<number, ReasoningSettings>;
    request_id: string;
  },
  signal: AbortSignal,
  receive: (event: ChatEvent) => void,
) {
  const response = await request(
    `conversations/${conversation}/stream/`,
    "POST",
    body,
    signal,
    "text/event-stream",
  );
  if (
    !response.headers.get("content-type")?.startsWith("text/event-stream") ||
    !response.body
  )
    throw new Error("جریان پاسخ معتبر دریافت نشد.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let lines: string[] = [];
  let finished = false;
  function dispatch(line: string) {
    if (line.startsWith("data:")) {
      lines.push(line.slice(5).replace(/^ /, ""));
    } else if (line === "" && lines.length) {
      const event: ChatEvent = JSON.parse(lines.join("\n"));
      lines = [];
      if (
        event.request_id !== body.request_id ||
        event.conversation_id !== conversation
      )
        throw new Error("شناسهٔ جریان با گفتگو مطابقت ندارد.");
      receive(event);
      finished = event.type === "done";
    }
  }
  try {
    while (!finished) {
      const { value, done } = await reader.read();
      if (done) throw new Error("ارتباط پیش از پایان پاسخ قطع شد.");
      buffer += decoder.decode(value, { stream: true });
      let boundary: number;
      while (!finished && (boundary = buffer.indexOf("\n")) !== -1) {
        dispatch(buffer.slice(0, boundary).replace(/\r$/, ""));
        buffer = buffer.slice(boundary + 1);
      }
    }
  } catch (error) {
    if (
      !signal.aborted &&
      (error instanceof TypeError || error instanceof SyntaxError)
    )
      throw new Error(
        "ارتباط با جریان پاسخ قطع شد. وضعیت گفتگو را دوباره بررسی کنید.",
      );
    throw error;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
