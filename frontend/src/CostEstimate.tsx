import { useEffect, useState } from "react";
import type { Model, ReasoningSettings } from "./types";
import { selectionFor, ready } from "./reasoning";
import { api } from "./api";
import { money } from "./credit";

export function CostEstimate({
  chatId,
  prompt,
  models,
  thinking,
  leaf,
  busy,
}: {
  chatId: number;
  prompt: string;
  models: Model[];
  thinking?: Record<number, ReasoningSettings>;
  leaf?: number | null;
  busy: boolean;
}) {
  const payload =
    !busy &&
    prompt.trim() &&
    models.length &&
    models.every((m) => ready(m.reasoning_profile, thinking?.[m.id]))
      ? JSON.stringify({
          content: prompt,
          model_ids: models.map((m) => m.id),
          expected_leaf: leaf ?? null,
          reasoning: Object.fromEntries(
            models.map((m) => [
              m.id,
              selectionFor(m.reasoning_profile, thinking?.[m.id]),
            ]),
          ),
        })
      : "";
  const [quote, setQuote] = useState<{ key: string; amount: number } | null>(
    null,
  );
  const key = chatId + "/" + payload;
  useEffect(() => {
    if (!payload) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      api<{ required_rial: number }>(
        chatId < 0 ? "credits/estimate/" : `conversations/${chatId}/estimate/`,
        "POST",
        JSON.parse(payload),
        controller.signal,
      )
        .then((q) => {
          if (!controller.signal.aborted)
            setQuote({ key, amount: q.required_rial });
        })
        .catch(() => {});
    }, 650);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [key, payload, chatId]);
  return quote?.key === key ? (
    <small className="cost-estimate">
      حداکثر رزرو برآوردی {money(quote.amount)}
    </small>
  ) : null;
}
