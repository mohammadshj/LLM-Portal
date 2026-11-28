import {
  memo,
  useDeferredValue,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  Activity,
  Box,
  CircleCheck,
  Expand,
  RotateCcw,
  ThumbsUp,
  ThumbsDown,
  Square,
  Ellipsis,
  TriangleAlert,
} from "lucide-react";
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
  return (
    <details className="usage">
      <summary className="response-cost">{label} · جزئیات</summary>
      <dl>
        {(
          [
            ["ورودی", m.input_tokens],
            ["خروجی", m.output_tokens],
            ["استدلال", m.reasoning_tokens],
            ["کل توکن‌ها", m.total_tokens],
          ] as const
        ).map(([key, v]) => (
          <div key={key}>
            <dt>{key}</dt>
            <dd>{v == null || m.status === "running" ? "—" : number(v)}</dd>
          </div>
        ))}
        {m.cached_input_tokens != null && (
          <div>
            <dt>ورودی از کش</dt>
            <dd>{number(m.cached_input_tokens)}</dd>
          </div>
        )}
      </dl>
      <small>
        {m.usage_source === "reported"
          ? "گزارش سرویس"
          : m.usage_source === "partial"
            ? "گزارش ناقص"
            : m.usage_source?.includes("estimat")
              ? "شامل برآورد"
              : "مصرف نامشخص"}
      </small>
      {m.input_price_snapshot_rial != null &&
        m.output_price_snapshot_rial != null && (
          <p>
            تعرفهٔ هر میلیون توکن · ورودی {money(m.input_price_snapshot_rial)} ·
            خروجی {money(m.output_price_snapshot_rial)}
          </p>
        )}
    </details>
  );
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
      {m.limited_output_tokens != null && (
        <small className="limit-note">
          متناسب با اعتبار، سقف این پاسخ {number(m.limited_output_tokens)} توکن
          است.
        </small>
      )}
      {m.error && (
        <p className="error">
          <TriangleAlert /> {m.error}
        </p>
      )}
    </>
  );
}

const ResponseCard = memo(function ResponseCard({
  m,
  question,
  retry,
  actions,
}: {
  actions: VersionActions;
  m: Message;
  question?: Message;
  retry?: Retry;
}) {
  const [stopping, setStopping] = useState(false);
  const [options, setOptions] = useState(false);
  const [feedbackBusy, setFeedbackBusy] = useState(false);
  const [feedbackError, setFeedbackError] = useState("");
  async function vote(value: "up" | "down") {
    if (feedbackBusy) return;
    setFeedbackBusy(true);
    setFeedbackError("");
    try {
      await actions.feedback(m.id, m.feedback === value ? "" : value);
    } catch {
      setFeedbackError("ثبت بازخورد ممکن نشد. دوباره تلاش کنید.");
    } finally {
      setFeedbackBusy(false);
    }
  }
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
        {question?.request_id &&
          m.model_id &&
          (m.id > 0 || m.started) &&
          m.status === "running" && (
            <button
              className="icon"
              title="توقف همین مدل"
              aria-label="توقف همین مدل"
              disabled={stopping}
              onClick={async () => {
                setStopping(true);
                try {
                  await actions.stopModel(question.request_id!, m.model_id!);
                } catch {
                  setStopping(false);
                  setFeedbackError("ثبت توقف ممکن نشد. دوباره تلاش کنید.");
                }
              }}
            >
              <Square />
            </button>
          )}
        {m.content && <CopyButton text={m.content} label="کپی پاسخ" />}
        <ResponseCost m={m} />
        {m.id > 0 && m.status !== "running" && (
          <div className="response-actions">
            {(["up", "down"] as const).map((value) => (
              <button
                key={value}
                className="icon"
                disabled={feedbackBusy}
                onClick={() => vote(value)}
                title={value === "up" ? "مفید بود" : "مفید نبود"}
                aria-label={value === "up" ? "مفید بود" : "مفید نبود"}
                aria-pressed={m.feedback === value}
              >
                {value === "up" ? <ThumbsUp /> : <ThumbsDown />}
              </button>
            ))}
            {question && m.model_id && (
              <button
                className="icon"
                title="عملیات پاسخ"
                aria-label="عملیات پاسخ"
                onClick={() => setOptions(true)}
              >
                <Ellipsis />
              </button>
            )}
          </div>
        )}
        {feedbackError && <small role="alert">{feedbackError}</small>}
        {options && question && (
          <Dialog title="عملیات پاسخ" onClose={() => setOptions(false)}>
            <div className="dialog-form">
              <p>
                تولید مجدد، نسخهٔ تازه‌ای با همین مدل می‌سازد و مصرف جداگانه
                دارد.
              </p>
              <button
                disabled={actions.locked}
                onClick={() => {
                  setOptions(false);
                  actions.save({
                    question,
                    content: question.content,
                    replies: [m],
                    onlyModel: m.model_id!,
                    changeModels: false,
                  });
                }}
              >
                <RotateCcw />
                تولید مجدد پاسخ
              </button>
            </div>
          </Dialog>
        )}
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
            <ResponseCard
              m={m}
              question={question}
              retry={retry}
              actions={actions}
            />
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
