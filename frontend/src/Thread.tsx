import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import {
  ArrowDown,
  ArrowUpLeft,
  Code2,
  GitCompareArrows,
  Layers3,
  ListTree,
  PenLine,
} from "lucide-react";

export function PortalArt() {
  return (
    <div className="portal-art" aria-hidden="true">
      <div className="art-orbit" />
      <div className="art-sheet sheet-back" />
      <div className="art-sheet sheet-mid" />
      <div className="art-sheet sheet-front">
        <Layers3 />
      </div>
      <i className="art-node n1" />
      <i className="art-node n2" />
    </div>
  );
}
const starters = [
  {
    icon: ListTree,
    title: "تحلیل یک مسئله",
    hint: "مسیرهای حل را بررسی کنید",
    prompt:
      "مسئلهٔ زیر را تحلیل کن و راه‌حل‌ها را همراه با مزایا و محدودیت‌هایشان مقایسه کن:\n",
  },
  {
    icon: PenLine,
    title: "بازنویسی متن",
    hint: "لحن و ساختار را بهبود دهید",
    prompt: "متن زیر را با لحنی رسمی، روشن و روان بازنویسی کن:\n",
  },
  {
    icon: Code2,
    title: "بررسی کد",
    hint: "منطق و کیفیت کد را بسنجید",
    prompt:
      "کد زیر را بررسی کن و برای بهبود خوانایی و عملکرد آن پیشنهاد بده:\n",
  },
];
export function Welcome({ prepare }: { prepare: (v: string) => void }) {
  return (
    <div className="welcome">
      <section className="hero">
        <div className="hero-copy">
          <span className="hero-icon">
            <GitCompareArrows />
          </span>
          <h2>گفتگو و مقایسهٔ مدل‌ها</h2>
          <p>
            یک پرسش بنویسید و پاسخ یک تا سه مدل زبانی را در کنار هم بررسی کنید.
          </p>
        </div>
        <PortalArt />
      </section>
      <section className="starters">
        <h3>پیشنهادهایی برای شروع</h3>
        <div>
          {starters.map(({ icon: Icon, title, hint, prompt }) => (
            <button key={title} onClick={() => prepare(prompt)}>
              <span className="starter-icon">
                <Icon />
              </span>
              <strong>{title}</strong>
              <small>{hint}</small>
              <ArrowUpLeft className="starter-arrow" />
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

type Position = { top: number; follow: boolean };
export function Thread({
  id,
  children,
  positions,
}: {
  id: number;
  children: ReactNode;
  positions: Map<number, Position>;
}) {
  const frame = useRef<HTMLElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const [away, setAway] = useState(false);
  useLayoutEffect(() => {
    const el = frame.current!;
    const position = positions.get(id) ?? { top: 0, follow: true };
    if (position.follow) el.scrollTop = el.scrollHeight;
    else el.scrollTop = position.top;
    setAway(!position.follow);
    const observer = new ResizeObserver(() => {
      if ((positions.get(id) ?? position).follow)
        el.scrollTop = el.scrollHeight;
    });
    observer.observe(content.current!);
    observer.observe(el);
    return () => observer.disconnect();
  }, [id, positions]);
  return (
    <div className="thread-wrap">
      <section
        className="thread"
        aria-label="پیام‌های گفتگو"
        ref={frame}
        onScroll={(e) => {
          const el = e.currentTarget;
          const follow = el.scrollHeight - el.scrollTop - el.clientHeight < 75;
          positions.set(id, { top: el.scrollTop, follow });
          setAway(!follow);
        }}
      >
        <div ref={content} className="thread-content">
          {children}
        </div>
      </section>
      {away && (
        <button
          className="jump"
          onClick={() => {
            if (frame.current)
              frame.current.scrollTop = frame.current.scrollHeight;
          }}
        >
          <ArrowDown /> آخرین پیام
        </button>
      )}
    </div>
  );
}
