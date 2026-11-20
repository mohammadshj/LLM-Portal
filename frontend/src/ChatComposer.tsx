import { useLayoutEffect, useRef, useState } from "react";
import {
  ArrowUp,
  Boxes,
  Check,
  ChevronDown,
  Search,
  SlidersHorizontal,
  Square,
  X,
} from "lucide-react";
import type { Model } from "./types";
import { Dialog, number, thinkingNames, useMedia } from "./ui";

type SelectorProps = {
  models: Model[];
  selected: number[];
  thinking?: Record<number, string>;
  choose: (ids: number[]) => void;
  setThinking: (id: number, level: string) => void;
};
function ModelSelector({
  models,
  selected,
  thinking,
  choose,
  setThinking,
  close,
}: SelectorProps & { close: () => void }) {
  const [query, setQuery] = useState("");
  const matching = models.filter((m) =>
    m.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
  );
  const advanced = models.filter(
    (m) => selected.includes(m.id) && m.thinking_levels.length,
  );
  return (
    <Dialog title="انتخاب مدل‌ها" onClose={close}>
      <div className="dialog-form">
        <p className="muted">
          یک مدل برای گفتگو یا حداکثر سه مدل برای مقایسه انتخاب کنید.
        </p>
        <label className="search">
          <Search />
          <input
            autoFocus
            placeholder="نام مدل را جست‌وجو کنید…"
            aria-label="جست‌وجوی مدل"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <div className="model-list">
          {matching.map((m) => {
            const checked = selected.includes(m.id);
            return (
              <label
                key={m.id}
                className="model-option"
                data-selected={checked}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  aria-label={m.name}
                  disabled={!checked && selected.length >= 3}
                  onChange={() =>
                    choose(
                      checked
                        ? selected.filter((id) => id !== m.id)
                        : [...selected, m.id],
                    )
                  }
                />
                <bdi>{m.name}</bdi>
                {m.provider === "demo" && <small>نمایشی</small>}
              </label>
            );
          })}
          {!matching.length && <p>مدلی پیدا نشد.</p>}
        </div>
        {!!advanced.length && (
          <details className="advanced">
            <summary>
              <SlidersHorizontal /> تنظیمات استدلال
            </summary>
            <p className="muted">
              سطح بالاتر می‌تواند زمان پاسخ و مصرف توکن را افزایش دهد.
            </p>
            {advanced.map((m) => (
              <label className="setting" key={m.id}>
                شدت استدلال <bdi>{m.name}</bdi>
                <select
                  value={thinking?.[m.id] ?? m.thinking_default}
                  onChange={(e) => setThinking(m.id, e.target.value)}
                >
                  {m.thinking_levels.map((level) => (
                    <option value={level} key={level}>
                      {thinkingNames[level] ?? level}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </details>
        )}
        <div className="line">
          <small>{number(selected.length)} از ۳ مدل</small>
          <button className="primary" onClick={close}>
            <Check /> انجام شد
          </button>
        </div>
      </div>
    </Dialog>
  );
}

export function ChatComposer(
  props: SelectorProps & {
    prompt: string;
    setPrompt: (v: string) => void;
    processing: boolean;
    stopping: boolean;
    locked: boolean;
    send: () => void;
    stop: () => void;
    modelsLoading: boolean;
    exhausted: boolean;
  },
) {
  const { models, selected, processing, stopping, locked, prompt, setPrompt } =
    props;
  const [picker, setPicker] = useState(false);
  const text = useRef<HTMLTextAreaElement>(null);
  const touch = useMedia("(pointer: coarse)");
  useLayoutEffect(() => {
    if (!text.current) return;
    text.current.style.height = "auto";
    text.current.style.height = Math.min(text.current.scrollHeight, 152) + "px";
  }, [prompt]);
  const canSend =
    !processing &&
    !locked &&
    !!prompt.trim() &&
    !!selected.length &&
    !props.exhausted;
  return (
    <section className="composer-area">
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          if (canSend) props.send();
        }}
      >
        <label className="sr-only" htmlFor="prompt">
          پیام شما
        </label>
        <textarea
          ref={text}
          rows={1}
          id="prompt"
          dir="auto"
          placeholder="پیام خود را بنویسید…"
          maxLength={12000}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (
              touch ||
              e.key !== "Enter" ||
              e.shiftKey ||
              e.ctrlKey ||
              e.altKey ||
              e.metaKey ||
              e.nativeEvent.isComposing ||
              e.nativeEvent.keyCode === 229
            )
              return;
            e.preventDefault();
            if (canSend && !e.repeat) e.currentTarget.form?.requestSubmit();
          }}
        />
        <div className="composer-tools">
          <button
            className="picker-button"
            type="button"
            aria-haspopup="dialog"
            disabled={processing || props.modelsLoading}
            onClick={() => setPicker(true)}
          >
            <Boxes /> انتخاب مدل <ChevronDown />
          </button>
          <div className="chips">
            {selected.map((id) => {
              const m = models.find((m) => m.id === id);
              return (
                m && (
                  <button
                    key={id}
                    className="chip"
                    type="button"
                    disabled={processing}
                    title={"حذف از انتخاب · " + m.name}
                    aria-label={"حذف از انتخاب " + m.name}
                    onClick={() =>
                      props.choose(selected.filter((i) => i !== id))
                    }
                  >
                    <bdi>{m.name}</bdi>
                    <X />
                  </button>
                )
              );
            })}
          </div>
          {processing ? (
            <button
              className="stop"
              type="button"
              disabled={stopping}
              aria-label="توقف پاسخ‌های این گفتگو"
              onClick={props.stop}
            >
              <Square />
              {stopping ? "در حال توقف…" : "توقف"}
            </button>
          ) : (
            <button
              className="primary send"
              type="submit"
              disabled={!canSend}
              aria-label={
                selected.length > 1 ? "مقایسهٔ پاسخ‌ها" : "ارسال پیام"
              }
            >
              <ArrowUp />
              <span>ارسال</span>
            </button>
          )}
        </div>
      </form>
      <div className="composer-note">
        {props.exhausted
          ? "سهمیهٔ توکن در دسترس نیست."
          : !models.length && !props.modelsLoading
            ? "مدل فعالی در دسترس نیست. با مدیر سامانه تماس بگیرید."
            : processing
              ? "پاسخ در حال دریافت است. می‌توانید گفتگوی دیگری را باز کنید."
              : !selected.length && models.length
                ? "برای ارسال، یک مدل انتخاب کنید."
                : "تاریخچهٔ گفتگو تا ۳۰ روز نگهداری می‌شود."}
        <span>
          {prompt.length > 10000
            ? number(prompt.length) + " / ۱۲٬۰۰۰"
            : !touch && "Shift + Enter برای خط جدید"}
        </span>
      </div>
      {picker && !processing && (
        <ModelSelector {...props} close={() => setPicker(false)} />
      )}
    </section>
  );
}
