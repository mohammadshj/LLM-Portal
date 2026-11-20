import { useState } from "react";
import type { Message } from "./types";

const count = (value?: number | null) =>
  value == null ? "نامعلوم" : value.toLocaleString("fa-IR");

function usageLabel(m: Message, field: "in" | "out" | "total") {
  const value =
    field === "in"
      ? m.input_tokens
      : field === "out"
        ? m.output_tokens
        : m.total_tokens;
  if (value == null) return "";
  const estimate =
    m.usage_source === "estimated" ||
    m.usage_source === "estimate_" + field ||
    (field === "total" &&
      (m.usage_source === "estimate_in" || m.usage_source === "estimate_out"));
  return estimate ? "(تخمینی)" : "(گزارش سرویس)";
}

const statusText = {
  running: "در حال دریافت…",
  completed: "",
  partial: "پاسخ بعضی مدل‌ها کامل نشد",
  failed: "ناموفق",
  cancelled: "متوقف شد",
};

function Reasoning({ message }: { message: Message }) {
  const [open, setOpen] = useState(message.status === "running");
  return (
    <details
      className="reasoning"
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary>
        فرایند استدلال مدل{" "}
        {message.status === "running" && !message.content && "· در حال دریافت"}
      </summary>
      <p dir="auto">{message.reasoning_content}</p>
    </details>
  );
}

export function MessageList({
  messages,
  retry,
}: {
  messages: Message[];
  retry?: (content: string, modelId?: number | null) => void;
}) {
  // Persisted and live replies use the same cards, ordered under their question.
  const turns: Message[][] = [];
  for (const message of messages) {
    if (message.role === "user" || !turns.length) turns.push([]);
    turns[turns.length - 1].push(message);
  }
  return (
    <>
      {turns.map((turn) => {
        const question = turn.find((m) => m.role === "user");
        return (
          <section key={turn[0].id} className="turn">
            {question && (
              <article className="message user" data-status={question.status}>
                <div className="message-label">شما</div>
                <p dir="auto">{question.content}</p>
                {question.status && (
                  <small>{statusText[question.status]}</small>
                )}
              </article>
            )}
            <div className="responses">
              {turn
                .filter((m) => m.role === "assistant")
                .map((m) => (
                  <article
                    key={m.id}
                    className="message assistant"
                    data-model-id={m.model_id}
                    data-status={m.status}
                  >
                    <div className="message-label">{m.model_name}</div>
                    {m.thinking_level && (
                      <small>Thinking · {m.thinking_level.toUpperCase()}</small>
                    )}
                    {m.reasoning_content && <Reasoning message={m} />}
                    {m.reasoning_content && m.content && (
                      <strong>پاسخ نهایی</strong>
                    )}
                    <p className="final-answer" dir="auto">
                      {m.content}
                    </p>
                    {m.status && m.status !== "completed" && (
                      <small role="status">{statusText[m.status]} </small>
                    )}
                    {m.error && (
                      <small className="reply-error">{m.error}</small>
                    )}
                    {m.usage_source === "unknown" ? (
                      <small>مصرف گزارش نشد</small>
                    ) : (
                      m.usage_source !== "none" && (
                        <small>
                          ورودی {count(m.input_tokens)} {usageLabel(m, "in")} ·
                          خروجی {count(m.output_tokens)} {usageLabel(m, "out")}{" "}
                          · مجموع {count(m.total_tokens)}{" "}
                          {usageLabel(m, "total")}
                          {m.thinking_level || m.reasoning_tokens != null
                            ? " · سهم استدلال " +
                              count(m.reasoning_tokens) +
                              (m.reasoning_tokens != null
                                ? " (گزارش سرویس)"
                                : "")
                            : ""}
                        </small>
                      )
                    )}
                    {retry &&
                      question &&
                      (m.status === "failed" || m.status === "cancelled") && (
                        <button
                          type="button"
                          className="retry"
                          onClick={() => retry(question.content, m.model_id)}
                        >
                          آماده‌سازی ارسال مجدد
                        </button>
                      )}
                  </article>
                ))}
            </div>
          </section>
        );
      })}
    </>
  );
}
