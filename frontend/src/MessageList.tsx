import type { Message } from "./types";

function MessageCard({ message }: { message: Message }) {
  const m = message;
  return (
    <article className={`message ${m.role}`}>
      <div className="message-label">
        {m.role === "user" ? "شما" : m.model_name}
      </div>
      <p dir="auto">{m.content}</p>
      {m.role === "assistant" && (
        <small>
          {m.input_tokens.toLocaleString("fa-IR")} ورودی ·{" "}
          {m.output_tokens.toLocaleString("fa-IR")} خروجی
        </small>
      )}
    </article>
  );
}

export function MessageList({ messages }: { messages: Message[] }) {
  // Group replies to the same question so comparison stays readable on desktop.
  const turns: Message[][] = [];
  for (const message of messages) {
    if (message.role === "user" || turns.length === 0) turns.push([]);
    turns[turns.length - 1].push(message);
  }
  return (
    <>
      {turns.map((turn) => (
        <section key={turn[0].id} className="turn">
          {turn
            .filter((m) => m.role === "user")
            .map((m) => (
              <MessageCard key={m.id} message={m} />
            ))}
          <div className="responses">
            {turn
              .filter((m) => m.role === "assistant")
              .map((m) => (
                <MessageCard key={m.id} message={m} />
              ))}
          </div>
        </section>
      ))}
    </>
  );
}
