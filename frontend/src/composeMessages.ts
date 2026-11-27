import type { Message } from "./types";

export type LiveTurn = {
  editOf?: number;
  confirmed?: boolean;
  id: string;
  messages: Message[];
  stopping: boolean;
};

type MessageSources = {
  stored: Message[];
  live?: LiveTurn;
  streaming: boolean;
  readError?: string;
};

export function composeMessages({
  stored,
  live,
  streaming,
  readError,
}: MessageSources): Message[] {
  // Keep the current branch visible until the server accepts the edit.
  if (!live || (live.editOf && !live.confirmed)) return stored;

  const turn = stored.find(
    (m) => m.role === "user" && m.request_id === live.id,
  );
  const cut = live.editOf ? stored.findIndex((m) => m.id === live.editOf) : -1;
  const prefix = cut < 0 ? stored : stored.slice(0, cut);
  const messages = prefix.filter(
    (m) => m.request_id !== live.id && (!turn || m.parent_id !== turn.id),
  );
  for (const partial of live.messages) {
    const saved =
      turn && partial.role === "assistant"
        ? stored.find(
            (m) => m.parent_id === turn.id && m.model_id === partial.model_id,
          )
        : undefined;
    if (saved && saved.status !== "running") {
      messages.push({
        ...saved,
        reasoning_content: saved.reasoning_content ?? partial.reasoning_content,
      });
    } else if (partial.status === "running" && !streaming) {
      // Between polls, only advance a clock sampled from an active server response.
      messages.push({
        ...partial,
        elapsed_ms: readError ? null : saved?.elapsed_ms,
        elapsedSampleAt: saved?.elapsedSampleAt,
      });
    } else {
      messages.push(partial);
    }
  }
  return messages;
}
