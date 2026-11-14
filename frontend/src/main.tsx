import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, refreshCsrf } from "./api";
import "./style.css";

import type { User, Model, Conversation, Detail, Page, Usage } from "./types";
import { MessageList } from "./MessageList";
import { ThemeToggle, useTheme } from "./ThemeToggle";
const number = (value: number) => value.toLocaleString("fa-IR");

function App() {
  const { theme, toggle } = useTheme();
  const [user, setUser] = useState<User | null>(null),
    [loading, setLoading] = useState(true);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [username, setUsername] = useState(""),
    [password, setPassword] = useState("");
  const [models, setModels] = useState<Model[]>([]),
    [selected, setSelected] = useState<number[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]),
    [next, setNext] = useState<string | null>(null);
  const [active, setActive] = useState<Detail | null>(null),
    [prompt, setPrompt] = useState("");
  const [report, setReport] = useState<Usage | null>(null);
  const end = useRef<HTMLDivElement>(null);
  async function loadHistory(path = "conversations/", append = false) {
    const page = await api<Page>(path);
    setConversations((old) =>
      append ? [...old, ...page.results] : page.results,
    );
    setNext(page.next);
  }
  async function loadWorkspace() {
    const [me, available] = await Promise.all([
      api<User>("auth/me/"),
      api<Model[]>("models/"),
    ]);
    setUser(me);
    setModels(available);
    setSelected(available.length ? [available[0].id] : []);
    await loadHistory();
  }
  useEffect(() => {
    loadWorkspace()
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [active]);
  async function login(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("auth/login/", "POST", { username, password });
      setPassword("");
      await refreshCsrf();
      await loadWorkspace();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function send(event: React.FormEvent) {
    event.preventDefault();
    if (!prompt.trim() || !selected.length) return;
    setBusy(true);
    setError("");
    setReport(null);
    try {
      const conversation =
        active ??
        (await api<Conversation>("conversations/", "POST", {
          title: prompt.trim().slice(0, 80),
        }));
      // Keep a newly created conversation even if the subsequent request fails.
      if (!active) setActive({ ...conversation, messages: [], errors: [] });
      const detail = await api<Detail>(
        `conversations/${conversation.id}/`,
        "POST",
        { content: prompt, model_ids: selected },
      );
      setActive(detail);
      setPrompt("");
      setError(detail.errors.map((e) => `${e.model}: ${e.detail}`).join(" / "));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      try {
        setUser(await api<User>("auth/me/"));
        await loadHistory();
      } catch {}
      setBusy(false);
    }
  }
  async function open(id: number) {
    setBusy(true);
    setError("");
    setReport(null);
    try {
      setActive(await api<Detail>(`conversations/${id}/`));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function remove() {
    if (!active || !window.confirm("این گفتگو حذف شود؟")) return;
    setBusy(true);
    try {
      await api(`conversations/${active.id}/`, "DELETE");
      setActive(null);
      await loadHistory();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function logout() {
    try {
      await api("auth/logout/", "POST");
      setUser(null);
      setActive(null);
      setReport(null);
      setConversations([]);
      await refreshCsrf();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  if (loading)
    return (
      <main className="login">
        <p role="status">در حال اتصال به پورتال…</p>
      </main>
    );
  if (!user)
    return (
      <main className="login">
        <section className="login-card">
          <div className="login-toolbar">
            <ThemeToggle theme={theme} toggle={toggle} />
          </div>
          <div className="mark">پ</div>
          <span className="eyebrow">فضای اختصاصی شما</span>
          <h1>پورتال مدل‌های زبانی</h1>
          <p>یک فضا برای گفتگو، مقایسه و کشف پاسخ‌های بهتر.</p>
          <form onSubmit={login}>
            <label>
              نام کاربری
              <input
                autoComplete="username"
                dir="ltr"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>
            <label>
              رمز عبور
              <input
                type="password"
                autoComplete="current-password"
                dir="ltr"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            <button className="primary" disabled={busy}>
              {busy ? "در حال ورود…" : "ورود به پورتال ←"}
            </button>
          </form>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <small>حساب کاربری توسط مدیر سامانه ایجاد می‌شود.</small>
        </section>
      </main>
    );
  return (
    <div className="app">
      <aside>
        <div className="brand">
          <div className="mark">پ</div>
          <div>
            <strong>پورتال هوش مصنوعی</strong>
            <small>فضایی برای پاسخ‌های بهتر</small>
          </div>
        </div>
        <button
          className="new"
          disabled={busy}
          onClick={() => {
            setActive(null);
            setReport(null);
            setError("");
            setPrompt("");
          }}
        >
          ＋ گفتگوی تازه
        </button>
        <details className="history" open>
          <summary>گفتگوهای شما</summary>
          <nav aria-label="تاریخچه گفتگو">
            {conversations.map((c) => (
              <button
                disabled={busy}
                key={c.id}
                className={active?.id === c.id ? "current" : ""}
                onClick={() => open(c.id)}
              >
                ◌ {c.title}
              </button>
            ))}
            {!conversations.length && <small>هنوز گفتگویی ندارید.</small>}
            {next && (
              <button
                disabled={busy}
                onClick={() =>
                  loadHistory(
                    `conversations/${new URL(next).search}`,
                    true,
                  ).catch((e) => setError(e.message))
                }
              >
                گفتگوهای بیشتر
              </button>
            )}
          </nav>
        </details>
        <div className="quota">
          <div>
            <span>مصرف توکن</span>
            <strong>{number(user.tokens_used)}</strong>
          </div>
          <progress
            value={Math.min(user.tokens_used, user.token_limit)}
            max={user.token_limit || 1}
          />
          <small>از {number(user.token_limit)} توکن تخصیص‌یافته</small>
        </div>
        <div className="account">
          <span>◉ {user.username}</span>
          <button onClick={logout} disabled={busy}>
            خروج
          </button>
        </div>
      </aside>
      <main className="workspace">
        <header>
          <div>
            <span className="eyebrow">LLM PORTAL</span>
            <h1>{report ? "گزارش مصرف" : active?.title || "گفتگوی تازه"}</h1>
          </div>
          <div className="header-actions">
            <ThemeToggle theme={theme} toggle={toggle} />
            {active && !report && (
              <button disabled={busy} onClick={remove}>
                حذف گفتگو
              </button>
            )}
            {user.is_staff && (
              <>
                <button
                  disabled={busy}
                  onClick={() =>
                    api<Usage>("usage/")
                      .then(setReport)
                      .catch((e) => setError(e.message))
                  }
                >
                  گزارش مصرف
                </button>
                <a href="/admin/">مدیریت ↗</a>
              </>
            )}
          </div>
        </header>
        {error && (
          <div className="error banner" role="alert">
            {error}
          </div>
        )}
        {report ? (
          <section className="report">
            <h2>مصرف کاربران</h2>
            <table>
              <thead>
                <tr>
                  <th>کاربر</th>
                  <th>مصرف</th>
                  <th>سهمیه</th>
                </tr>
              </thead>
              <tbody>
                {report.accounts.map((a) => (
                  <tr key={a.user__username}>
                    <td>{a.user__username}</td>
                    <td>{number(a.tokens_used)}</td>
                    <td>{number(a.token_limit)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h2>مصرف مدل‌ها</h2>
            <table>
              <thead>
                <tr>
                  <th>مدل</th>
                  <th>ورودی</th>
                  <th>خروجی</th>
                </tr>
              </thead>
              <tbody>
                {report.models.map((m) => (
                  <tr key={m.model__name}>
                    <td>{m.model__name}</td>
                    <td>{number(m.input_tokens)}</td>
                    <td>{number(m.output_tokens)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ) : (
          <>
            <section
              className="thread"
              aria-label="پیام‌های گفتگو"
              aria-live="polite"
            >
              {!active?.messages.length ? (
                <div className="welcome">
                  <span className="welcome-symbol">✳</span>
                  <span className="eyebrow">گفتگو از یک پرسش آغاز می‌شود</span>
                  <h2>امروز چه چیزی را بررسی کنیم؟</h2>
                  <p>
                    مدل دلخواهتان را انتخاب کنید یا پاسخ چند مدل را کنار هم
                    ببینید.
                  </p>
                  <div className="suggestions">
                    {[
                      "یک موضوع پیچیده را ساده توضیح بده",
                      "برای یک مسئله چند راه‌حل پیشنهاد کن",
                      "یک متن را بررسی و بازنویسی کن",
                    ].map((s) => (
                      <button key={s} onClick={() => setPrompt(s)}>
                        {s}
                        <span>↖</span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="messages">
                  <MessageList messages={active.messages} />
                  <div ref={end} />
                </div>
              )}
              {busy && (
                <p className="working" role="status">
                  در حال پردازش درخواست…
                </p>
              )}
            </section>
            <section className="composer-area">
              <div className="model-picker">
                <span>
                  انتخاب مدل <small>حداکثر ۳ مدل برای مقایسه</small>
                </span>
                <div>
                  {models.map((m) => (
                    <label
                      className={selected.includes(m.id) ? "selected" : ""}
                      key={m.id}
                    >
                      <input
                        type="checkbox"
                        checked={selected.includes(m.id)}
                        disabled={
                          busy ||
                          (!selected.includes(m.id) && selected.length >= 3)
                        }
                        onChange={() =>
                          setSelected((old) =>
                            old.includes(m.id)
                              ? old.filter((id) => id !== m.id)
                              : [...old, m.id],
                          )
                        }
                      />
                      {m.name}
                      {m.provider === "demo" && <small>نمایشی</small>}
                    </label>
                  ))}
                </div>
                {!models.length && (
                  <p>مدلی فعال نیست؛ با مدیر سامانه تماس بگیرید.</p>
                )}
              </div>
              <form className="composer" onSubmit={send}>
                <label className="sr-only" htmlFor="prompt">
                  پیام شما
                </label>
                <textarea
                  id="prompt"
                  placeholder="پیام خود را اینجا بنویسید…"
                  maxLength={12000}
                  value={prompt}
                  disabled={busy}
                  onChange={(e) => setPrompt(e.target.value)}
                />
                <div>
                  <small>{number(prompt.length)} / ۱۲٬۰۰۰</small>
                  <button
                    className="primary"
                    disabled={busy || !prompt.trim() || !selected.length}
                  >
                    {busy
                      ? "در حال دریافت…"
                      : selected.length > 1
                        ? "مقایسهٔ پاسخ‌ها ↑"
                        : "ارسال پیام ↑"}
                  </button>
                </div>
              </form>
              <p className="footnote">
                پاسخ مدل‌ها ممکن است نادرست باشد. اطلاعات حساس را وارد نکنید.
                تاریخچه تا ۳۰ روز نگهداری می‌شود.
              </p>
            </section>
          </>
        )}
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
