import { useLayoutEffect, useRef, useState } from "react";
import {
  ArrowUp,
  Cpu,
  Server,
  Clock3,
  Info,
  Check,
  ChevronDown,
  Search,
  SlidersHorizontal,
  Square,
  X,
} from "lucide-react";
import { available, type Mode } from "./preferences";
import { money, priced } from "./credit";
import { ReasoningControls } from "./ReasoningControls";
import { ready } from "./reasoning";
import type { Model, ReasoningSettings } from "./types";
import { Dialog, number, useMedia } from "./ui";

type SelectorProps = {
  mode: Mode;
  recent: number[];
  models: Model[];
  selected: number[];
  thinking?: Record<number, ReasoningSettings>;
  choose: (ids: number[]) => void;
  setThinking: (id: number, values: ReasoningSettings) => void;
};
function ModelSelector({
  models,
  mode,
  recent,
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
  const groups = new Map<string, Model[]>();
  for (const m of matching) {
    const key = recent.includes(m.id)
      ? "اخیراً استفاده‌شده"
      : m.provider_group || m.provider;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(m);
  }
  const recentGroup = "اخیراً استفاده‌شده";
  const ordered = [...groups].sort(
    ([a], [b]) => Number(b === recentGroup) - Number(a === recentGroup),
  );
  const advanced = models.filter(
    (m) =>
      selected.includes(m.id) &&
      (m.reasoning_profile.controls.length || m.reasoning_profile.mandatory),
  );
  return (
    <Dialog title="انتخاب مدل‌ها" onClose={close}>
      <div className="dialog-form">
        <p className="muted">
          {mode === "chat"
            ? "برای این گفتگو یک مدل انتخاب کنید."
            : "برای مقایسه دو یا سه مدل انتخاب کنید."}
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
          {ordered.map(([group, rows]) => (
            <section key={group}>
              <h3 className="section-label">
                {group === recentGroup ? <Clock3 /> : <Server />}
                {group}
              </h3>
              {rows.map((m) => {
                const checked = selected.includes(m.id);
                const rate = priced(m)
                  ? "تعرفهٔ یک میلیون توکن · ورودی " +
                    money(m.input_price_per_million_rial!) +
                    "، خروجی " +
                    money(m.output_price_per_million_rial!)
                  : "تعرفه تعیین نشده";
                return (
                  <div
                    className="model-option"
                    data-selected={checked}
                    key={m.id}
                  >
                    <label>
                      <input
                        type="checkbox"
                        aria-label={m.name}
                        checked={checked}
                        disabled={
                          !available(m) ||
                          (!checked &&
                            mode === "compare" &&
                            selected.length >= 3)
                        }
                        onChange={() =>
                          choose(
                            checked
                              ? selected.filter((id) => id !== m.id)
                              : mode === "chat"
                                ? [m.id]
                                : [...selected, m.id],
                          )
                        }
                      />
                      <bdi>{m.name}</bdi>
                    </label>
                    {!available(m) ? (
                      <small>غیرقابل دسترس</small>
                    ) : m.reasoning_supported === true ? (
                      <small>استدلال</small>
                    ) : null}
                    <details className="model-info">
                      <summary
                        aria-label={"مشخصات " + m.name}
                        title="مشخصات و تعرفه"
                      >
                        <Info />
                      </summary>
                      <small>
                        {m.provider_group} · {rate}
                      </small>
                    </details>
                  </div>
                );
              })}
            </section>
          ))}
          {!matching.length && <p>مدلی پیدا نشد.</p>}
        </div>
        {!!advanced.length && (
          <details className="advanced">
            <summary>
              <SlidersHorizontal /> تنظیمات استدلال
            </summary>
            <p className="muted">
              سطح بالاتر می‌تواند زمان پاسخ و هزینه را افزایش دهد.
            </p>
            {advanced.map((m) => (
              <ReasoningControls
                key={m.id}
                model={m}
                saved={thinking?.[m.id]}
                change={(v) => setThinking(m.id, v)}
              />
            ))}
          </details>
        )}
        <div className="line">
          <small>
            {mode === "compare"
              ? number(selected.length) + " از ۳ مدل"
              : "گفتگوی تک‌مدلی"}
          </small>
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
  const reasoningReady = models
    .filter((m) => selected.includes(m.id))
    .every((m) => ready(m.reasoning_profile, props.thinking?.[m.id]));
  const canSend =
    !processing &&
    !locked &&
    !!prompt.trim() &&
    selected.length >= (props.mode === "compare" ? 2 : 1) &&
    !props.exhausted &&
    reasoningReady;
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
            <Cpu /> انتخاب مدل <ChevronDown />
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
              title="ارسال پیام"
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
          ? "اعتبار آزاد برای مدل انتخابی کافی نیست."
          : !models.length && !props.modelsLoading
            ? "مدل فعالی در دسترس نیست. با مدیر سامانه تماس بگیرید."
            : processing
              ? "پاسخ در حال دریافت است. می‌توانید گفتگوی دیگری را باز کنید."
              : !reasoningReady
                ? "تنظیمات استدلال مدل انتخابی را بررسی کنید."
                : !selected.length && models.length
                  ? "برای ارسال، یک مدل انتخاب کنید."
                  : props.mode === "compare" && selected.length < 2
                    ? "برای مقایسه دست‌کم دو مدل انتخاب کنید."
                    : ""}
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
