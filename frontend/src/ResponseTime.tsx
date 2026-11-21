import { useEffect, useState } from "react";
import type { Message } from "./types";

const seconds = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 });

export function ResponseTime({ message }: { message: Message }) {
  const baseline =
    message.status === "running" && message.elapsed_ms != null
      ? message.elapsedSampleAt
      : undefined;
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    if (baseline == null) return;
    const timer = window.setInterval(() => setNow(performance.now()), 250);
    return () => window.clearInterval(timer);
  }, [baseline]);

  if (message.elapsed_ms == null) return null;
  const ms =
    message.elapsed_ms + (baseline == null ? 0 : Math.max(0, now - baseline));
  const value = baseline == null ? ms / 1000 : Math.floor(ms / 1000);
  return (
    <small className="response-time">
      زمان پاسخ{" "}
      <time dateTime={`PT${value}S`}>
        {baseline == null && ms < 100 ? "کمتر از ۰٫۱" : seconds.format(value)}{" "}
        ثانیه
      </time>
    </small>
  );
}
