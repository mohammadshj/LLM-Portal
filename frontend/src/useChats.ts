import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { streamChat } from "./stream";
import type { ChatEvent } from "./stream";
import type { Conversation, Detail, Message, Model } from "./types";

type LiveTurn = { id: string; messages: Message[]; stopping: boolean };
type Chat = {
  prompt: string;
  selection?: number[];
  thinking?: Record<number, string>;
  detail?: Detail;
  live?: LiveTurn;
  error?: string;
  readError?: string;
  removing?: boolean;
  loading?: boolean;
};
const empty: Chat = { prompt: "" };
type ActiveSend = {
  id: string;
  conversation: number;
  controller: AbortController;
  started: boolean;
  stopping: boolean;
};
const errorMessage = (e: unknown) =>
  e instanceof Error ? e.message : "ارتباط با سرور ممکن نشد.";

function requestId() {
  // getRandomValues also works on an HTTP LAN development origin.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join(
    "",
  );
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20),
  ].join("-");
}

function applyEvent(live: LiveTurn, event: ChatEvent): LiveTurn {
  if (!event.model_id) return live;
  return {
    ...live,
    messages: live.messages.map((m) => {
      if (m.model_id !== event.model_id) return m;
      switch (event.type) {
        case "model_start":
          return {
            ...m,
            elapsed_ms: event.elapsed_ms ?? 0,
            elapsedSampleAt: performance.now(),
          };
        case "reasoning_delta":
          return {
            ...m,
            reasoning_content: (m.reasoning_content ?? "") + (event.text ?? ""),
          };
        case "delta":
          return { ...m, content: m.content + (event.text ?? "") };
        case "model_error":
          return {
            ...m,
            ...event.usage,
            status: event.status === "cancelled" ? "cancelled" : "failed",
            elapsed_ms: event.elapsed_ms,
            error: event.detail,
          };
        case "model_done":
          return {
            ...m,
            ...event.usage,
            elapsed_ms: event.elapsed_ms,
            status: event.status === "cancelled" ? "cancelled" : "completed",
          };
        default:
          return m;
      }
    }),
  };
}

export function useChats(
  onCreated: (c: Conversation) => void,
  onSettled: () => void,
) {
  // Draft IDs are negative until POST /conversations/ allocates a database ID.
  const [activeId, setActiveId] = useState(-1);
  const nextDraft = useRef(-2);
  const [chats, setChats] = useState<Record<number, Chat>>({});
  const current = useRef(chats);
  const sends = useRef(new Map<number, ActiveSend>());
  const reads = useRef(new Map<number, AbortController>());
  const polls = useRef(new Map<number, ReturnType<typeof setTimeout>>());
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      for (const run of sends.current.values()) run.controller.abort();
      for (const read of reads.current.values()) read.abort();
      for (const timer of polls.current.values()) clearTimeout(timer);
    };
  }, []);

  function replace(all: Record<number, Chat>) {
    if (!mounted.current) return;
    current.current = all;
    setChats(all);
  }
  // Synchronous ref also guards two clicks before React's next render.
  function edit(id: number, change: (chat: Chat) => Chat) {
    replace({ ...current.current, [id]: change(current.current[id] ?? empty) });
  }
  function invalidateRead(id: number) {
    reads.current.get(id)?.abort();
    clearTimeout(polls.current.get(id));
    polls.current.delete(id);
  }
  async function load(id: number) {
    if (
      !mounted.current ||
      id < 0 ||
      sends.current.has(id) ||
      current.current[id]?.removing
    )
      return;
    invalidateRead(id);
    const controller = new AbortController();
    reads.current.set(id, controller);
    if (!current.current[id]?.detail)
      edit(id, (c) => ({ ...c, loading: true }));
    try {
      const detail = await api<Detail>(
        `conversations/${id}/`,
        "GET",
        undefined,
        controller.signal,
      );
      if (controller.signal.aborted || !mounted.current) return;
      const sampledAt = performance.now();
      for (const message of detail.messages) {
        if (message.status === "running" && message.elapsed_ms != null)
          message.elapsedSampleAt = sampledAt;
      }
      edit(id, (c) => ({
        ...c,
        detail,
        readError: undefined,
        loading: false,
        live: detail.active_request_id === c.live?.id ? c.live : undefined,
      }));
      if (detail.active_request_id) {
        polls.current.set(
          id,
          setTimeout(() => void load(id), 750),
        );
      } else {
        onSettled();
      }
    } catch (e) {
      if (!controller.signal.aborted)
        edit(id, (c) => ({ ...c, loading: false, readError: errorMessage(e) }));
    } finally {
      if (reads.current.get(id) === controller) reads.current.delete(id);
    }
  }

  function newChat() {
    const id = nextDraft.current--;
    setActiveId(id);
  }
  function open(id: number) {
    setActiveId(id);
    void load(id);
  }
  async function send(selected: Model[]) {
    const source = activeId;
    const state = current.current[source] ?? empty;
    const content = state.prompt.trim();
    if (
      !content ||
      !selected.length ||
      state.removing ||
      state.loading ||
      state.detail?.active_request_id ||
      sends.current.has(source)
    )
      return;
    const run: ActiveSend = {
      id: requestId(),
      conversation: source,
      controller: new AbortController(),
      started: false,
      stopping: false,
    };
    sends.current.set(source, run);
    invalidateRead(source);
    const common = {
      request_id: run.id,
      input_tokens: 0,
      output_tokens: 0,
      usage_source: "none" as const,
    };
    const thinking: Record<number, string> = {};
    for (const model of selected) {
      const effort = state.thinking?.[model.id] ?? model.thinking_default;
      if (effort && model.thinking_levels?.includes(effort))
        thinking[model.id] = effort;
    }
    const sentAt = performance.now();
    const messages: Message[] = [
      { ...common, id: -1, role: "user", content, model_name: null },
      ...selected.map((m) => ({
        ...common,
        id: -1 - m.id,
        role: "assistant" as const,
        content: "",
        model_name: m.name,
        thinking_level: thinking[m.id],
        model_id: m.id,
        status: "running" as const,
        elapsed_ms: 0,
        elapsedSampleAt: sentAt,
      })),
    ];
    edit(source, (c) => ({
      ...c,
      prompt: "",
      error: undefined,
      live: { id: run.id, messages, stopping: false },
    }));
    try {
      if (source < 0) {
        const conversation = await api<Conversation>(
          "conversations/",
          "POST",
          { title: content.slice(0, 80) },
          run.controller.signal,
        );
        if (!mounted.current) return;
        run.conversation = conversation.id;
        sends.current.delete(source);
        sends.current.set(conversation.id, run);
        const all = { ...current.current };
        all[conversation.id] = {
          ...all[source],
          detail: { ...conversation, messages: [], errors: [] },
        };
        delete all[source];
        replace(all);
        setActiveId((id) => (id === source ? conversation.id : id));
        onCreated(conversation);
      }
      if (run.stopping) return;
      await streamChat(
        run.conversation,
        {
          content,
          model_ids: selected.map((m) => m.id),
          thinking,
          request_id: run.id,
        },
        run.controller.signal,
        (event) => {
          if (event.type === "start") {
            run.started = true;
          }
          if (event.model_id && sends.current.get(run.conversation) === run) {
            edit(run.conversation, (c) =>
              c.live?.id === run.id
                ? { ...c, live: applyEvent(c.live, event) }
                : c,
            );
          }
        },
      );
    } catch (e) {
      if (!run.stopping)
        edit(run.conversation, (c) => ({ ...c, error: errorMessage(e) }));
    } finally {
      const id = run.conversation;
      if (sends.current.get(id) === run) sends.current.delete(id);
      if (mounted.current) {
        if (!run.started)
          edit(id, (c) => ({
            ...c,
            live: undefined,
            prompt: c.prompt || content,
          }));
        await load(id);
      }
    }
  }

  async function cancelRun(run: ActiveSend) {
    // Abort immediately even if the Stop POST stalls. The ASGI disconnect
    // handler also closes the upstream connection when the SSE stream exists.
    run.controller.abort();
    if (!run.started) return;
    try {
      await api(
        `conversations/${run.conversation}/requests/${run.id}/cancel/`,
        "POST",
        {},
      );
    } catch (e) {
      edit(run.conversation, (c) => ({ ...c, error: errorMessage(e) }));
    }
  }
  async function stop() {
    const id = activeId;
    const run = sends.current.get(id);
    if (run) {
      if (run.stopping) return;
      run.stopping = true;
      edit(id, (c) =>
        c.live ? { ...c, live: { ...c.live, stopping: true } } : c,
      );
      await cancelRun(run);
    } else {
      const request = current.current[id]?.detail?.active_request_id;
      if (!request) return;
      try {
        await api(
          `conversations/${id}/requests/${request}/cancel/`,
          "POST",
          {},
        );
      } catch (e) {
        edit(id, (c) => ({ ...c, error: errorMessage(e) }));
      }
      await load(id);
    }
  }

  async function remove(id: number) {
    const chat = current.current[id];
    if (
      id < 0 ||
      sends.current.has(id) ||
      chat?.detail?.active_request_id ||
      chat?.removing
    )
      throw new Error("پس از پایان پردازش گفتگو دوباره تلاش کنید.");
    invalidateRead(id);
    edit(id, (c) => ({ ...c, removing: true }));
    try {
      await api(`conversations/${id}/`, "DELETE");
      const all = { ...current.current };
      delete all[id];
      replace(all);
      const fresh = nextDraft.current--;
      setActiveId((old) => (old === id ? fresh : old));
      return id;
    } catch (e) {
      edit(id, (c) => ({ ...c, removing: false }));
      throw e;
    }
  }

  const chat = chats[activeId] ?? empty;
  const busy = (id: number, listed = false) =>
    sends.current.has(id) ||
    (chats[id]?.detail ? !!chats[id]?.detail?.active_request_id : listed);
  // A reload can observe a turn still being settled. Poll that turn until the
  // server has persisted final messages, retaining any local partials meanwhile.
  const live = chat.live;
  const stored = chat.detail?.messages ?? [];
  const turn =
    live && stored.find((m) => m.role === "user" && m.request_id === live.id);
  const messages = stored.filter(
    (m) =>
      !live || (m.request_id !== live.id && (!turn || m.parent_id !== turn.id)),
  );
  if (live) {
    for (const m of live.messages) {
      // A reconnect may find one model settled while its siblings are still running.
      const row =
        turn && m.role === "assistant"
          ? stored.find(
              (row) => row.parent_id === turn.id && row.model_id === m.model_id,
            )
          : undefined;
      if (row && row.status !== "running") {
        messages.push({
          ...row,
          reasoning_content: row.reasoning_content ?? m.reasoning_content,
        });
      } else if (m.status === "running" && !sends.current.has(activeId)) {
        // Only advance a disconnected stream's clock while polling confirms it is active.
        messages.push({
          ...m,
          elapsed_ms: chat.readError ? null : row?.elapsed_ms,
          elapsedSampleAt: row?.elapsedSampleAt,
        });
      } else {
        messages.push(m);
      }
    }
  }
  return {
    activeId,
    chat,
    messages,
    busy,
    newChat,
    open,
    send,
    stop,
    remove,
    renamed: (id: number, title: string) => {
      if (!current.current[id]) return;
      invalidateRead(id);
      edit(id, (c) => ({
        ...c,
        detail: c.detail ? { ...c.detail, title } : undefined,
      }));
      void load(id);
    },
    setPrompt: (prompt: string) => edit(activeId, (c) => ({ ...c, prompt })),
    setThinking: (id: number, level: string) =>
      edit(activeId, (c) => ({
        ...c,
        thinking: { ...c.thinking, [id]: level },
      })),
    setSelection: (selection: number[]) =>
      edit(activeId, (c) => ({ ...c, selection })),
  };
}
