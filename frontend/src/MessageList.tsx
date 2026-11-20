import type { Message } from "./types";

const statusText = {
  running: "در حال دریافت…",
  completed: "",
  partial: "پاسخ بعضی مدل‌ها کامل نشد",
  failed: "ناموفق",
  cancelled: "متوقف شد",
};

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
                    <p dir="auto">{m.content}</p>
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
                          {m.usage_source === "estimated" ? "تخمینی · " : ""}
                          {m.input_tokens?.toLocaleString("fa-IR")} ورودی ·{" "}
                          {m.output_tokens?.toLocaleString("fa-IR")} خروجی
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
