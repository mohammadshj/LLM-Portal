import {
  memo,
  useDeferredValue,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { Activity, Box, CircleCheck, Expand, RotateCcw } from "lucide-react";
import { UserTurn, type VersionActions } from "./UserTurn";
import type { Message } from "./types";
import { CopyButton, Dialog, number } from "./ui";
import { money } from "./credit";
import { ResponseTime } from "./ResponseTime";
import { MarkdownRenderer } from "./MarkdownRenderer";

const statusText = {
  running: "در حال دریافت",
  completed: "تکمیل شد",
  partial: "بخشی از پاسخ‌ها کامل نشد",
  failed: "ناموفق",
  cancelled: "متوقف شد",
};
type Retry = (content: string, modelId?: number | null) => void;

function ResponseCost({ m }: { m: Message }) {
  const label =
    m.status === "running"
      ? "در حال محاسبه هزینه"
      : m.cost_rial == null
        ? m.billing_status === "review"
          ? "هزینه نامشخص · نیازمند بررسی"
          : "هزینه تاریخی ثبت نشده"
        : m.free_tariff
          ? "هزینه پاسخ: رایگان"
          : "هزینه " +
            money(m.cost_rial) +
            (m.billing_source === "reported"
              ? ""
              : m.billing_source === "partial"
                ? " · مصرف ناقص"
                : " · برآوردی");
  return <small className="response-cost">{label}</small>;
}
function ResponseBody({ m }: { m: Message }) {
  const [open, setOpen] = useState(m.status === "running");
  const answer = useDeferredValue(m.content);
  return (
    <>
      {m.reasoning_content && (
        <details
          className="reasoning"
          open={open}
          onToggle={(e) => setOpen(e.currentTarget.open)}
        >
          <summary>
            <Activity /> فرایند استدلال مدل{" "}
            {(m.reasoning_settings?.effort || m.thinking_level) && (
              <bdi>{m.reasoning_settings?.effort || m.thinking_level}</bdi>
            )}
            {m.reasoning_settings?.budget != null &&
              " · " + number(m.reasoning_settings.budget) + " توکن"}
          </summary>
          <p dir="auto">{m.reasoning_content}</p>
        </details>
      )}
      {m.reasoning_content && m.content && (
        <small className="section-label">پاسخ نهایی</small>
      )}
      <MarkdownRenderer text={answer} />
      {m.status === "running" && !m.content && (
        <div className="typing" aria-hidden="true">
          <i />
          <i />
          <i />
        </div>
      )}
      {m.error && <p className="error">{m.error}</p>}
    </>
  );
}

const ResponseCard = memo(function ResponseCard({
  m,
  question,
  retry,
}: {
  m: Message;
  question?: Message;
  retry?: Retry;
}) {
  const [expanded, setExpanded] = useState(false);
  const body = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  useLayoutEffect(() => {
    const el = body.current!;
    if (m.status !== "running") return;
    const observer = new ResizeObserver(() => {
      if (
        follow.current &&
        el.clientHeight &&
        el.scrollHeight > el.clientHeight
      )
        el.scrollTop = el.scrollHeight;
    });
    observer.observe(el.firstElementChild!);
    return () => observer.disconnect();
  }, [m.status]);
  return (
    <article
      className="message assistant"
      data-model-id={m.model_id}
      data-status={m.status}
    >
      <div className="card-head">
        <span className="model-mark">
          <Box />
        </span>
        <div>
          <strong className="message-label" dir="auto">
            {m.model_name || "مدل"}
          </strong>
          <div className="response-meta">
            {m.status && (
              <small className="card-status" role="status">
                {m.status === "completed" && <CircleCheck />}
                {statusText[m.status]}
              </small>
            )}
            <ResponseTime message={m} />
          </div>
        </div>
        <button
          className="icon"
          title="گسترش پاسخ"
          aria-label="گسترش پاسخ"
          onClick={() => setExpanded(true)}
        >
          <Expand />
        </button>
      </div>
      <div
        className="card-body"
        ref={body}
        onScroll={(e) => {
          const el = e.currentTarget;
          follow.current =
            el.scrollHeight - el.scrollTop - el.clientHeight < 75;
        }}
      >
        <div>
          <ResponseBody m={m} />
        </div>
      </div>
      <footer>
        {m.content && <CopyButton text={m.content} label="کپی پاسخ" />}
        <ResponseCost m={m} />
        {retry &&
          question &&
          (m.status === "failed" || m.status === "cancelled") && (
            <button
              className="retry"
              onClick={() => retry(question.content, m.model_id)}
            >
              <RotateCcw />
              آماده‌سازی ارسال مجدد
            </button>
          )}
      </footer>
      {expanded && (
        <Dialog
          title={m.model_name || "پاسخ مدل"}
          onClose={() => setExpanded(false)}
        >
          <div className="reader">
            <ResponseBody m={m} />
            <ResponseCost m={m} />
            {m.content && <CopyButton text={m.content} label="کپی پاسخ" />}
          </div>
        </Dialog>
      )}
    </article>
  );
});

function Turn({
  turn,
  retry,
  actions,
}: {
  turn: Message[];
  retry?: Retry;
  actions: VersionActions;
}) {
  const question = turn.find((m) => m.role === "user");
  const replies = turn.filter((m) => m.role === "assistant");
  const [tab, setTab] = useState(0);
  return (
    <section className="turn">
      {question && (
        <UserTurn
          question={question}
          replies={replies}
          actions={actions}
          status={
            question.status &&
            !["completed", "running"].includes(question.status)
              ? statusText[question.status]
              : undefined
          }
        />
      )}
      {replies.length > 1 && (
        <div
          className="compare-tabs"
          role="group"
          aria-label="انتخاب پاسخ برای مطالعه"
        >
          {replies.map((m, i) => (
            <button
              key={m.model_id ?? m.id}
              aria-pressed={tab === i}
              onClick={() => setTab(i)}
            >
              <bdi>{m.model_name}</bdi>
            </button>
          ))}
        </div>
      )}
      <div className="responses" data-count={replies.length}>
        {replies.map((m, i) => (
          <div
            key={m.model_id ?? m.id}
            className="compare-column"
            data-visible={i === Math.min(tab, replies.length - 1)}
          >
            <ResponseCard m={m} question={question} retry={retry} />
          </div>
        ))}
      </div>
    </section>
  );
}
export function MessageList({
  messages,
  retry,
  actions,
}: {
  messages: Message[];
  retry?: Retry;
  actions: VersionActions;
}) {
  const turns: Message[][] = [];
  for (const m of messages) {
    if (m.role === "user" || !turns.length) turns.push([]);
    turns[turns.length - 1].push(m);
  }
  return (
    <div className="messages">
      {turns.map((turn) => (
        <Turn
          key={turn[0].request_id ?? turn[0].id}
          actions={actions}
          turn={turn}
          retry={retry}
        />
      ))}
    </div>
  );
}
