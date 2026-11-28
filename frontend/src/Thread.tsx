import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import {
  ArrowDown,
  Code2,
  FileText,
  PenLine,
  Languages,
  Sparkles,
} from "lucide-react";

const starters = [
  {
    icon: FileText,
    title: "خلاصه‌سازی متن",
    prompt: "متن زیر را خلاصه کن و نکته‌های اصلی آن را مشخص کن:\n",
  },
  {
    icon: PenLine,
    title: "بازنویسی متن",
    prompt: "متن زیر را با لحنی رسمی و روشن بازنویسی کن:\n",
  },
  {
    icon: Code2,
    title: "بررسی کد",
    prompt: "کد زیر را بررسی کن و برای بهبود خوانایی آن پیشنهاد بده:\n",
  },
  { icon: Languages, title: "ترجمه متن", prompt: "متن زیر را ترجمه کن:\n" },
];
export function Welcome() {
  return (
    <section className="hero">
      <span className="welcome-mark">
        <Sparkles aria-hidden="true" />
      </span>
      <h2>چطور می‌توانم کمک کنم؟</h2>
      <p>با یک مدل گفتگو کنید یا پاسخ چند مدل را کنار هم بسنجید.</p>
    </section>
  );
}
export function Suggestions({ prepare }: { prepare: (text: string) => void }) {
  return (
    <div className="suggestions" aria-label="پیشنهادهایی برای شروع">
      {starters.map(({ icon: Icon, title, prompt }) => (
        <button key={title} onClick={() => prepare(prompt)}>
          <Icon />
          {title}
        </button>
      ))}
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
