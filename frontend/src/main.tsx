import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, refreshCsrf } from "./api";
import "./style.css";

import type { User, Model, Conversation, Page, Usage } from "./types";
import { MessageList } from "./MessageList";
import { ThemeToggle, useTheme } from "./ThemeToggle";
import { useChats } from "./useChats";
const number = (value: number) => value.toLocaleString("fa-IR");

function App() {
  const { theme, toggle } = useTheme();
  const [user, setUser] = useState<User | null>(null),
    [loading, setLoading] = useState(true);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [username, setUsername] = useState(""),
    [password, setPassword] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    api<User>("auth/me/", "GET", undefined, controller.signal)
      .then(setUser)
      .catch(() => {})
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);
  async function login(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("auth/login/", "POST", { username, password });
      setPassword("");
      await refreshCsrf();
      setUser(await api<User>("auth/me/"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
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
  return <Workspace initialUser={user} onLogout={() => setUser(null)} />;
}

function Workspace({
  initialUser,
  onLogout,
}: {
  initialUser: User;
  onLogout: () => void;
}) {
  const { theme, toggle } = useTheme();
  const [user, setUser] = useState(initialUser);
  const [error, setError] = useState("");
  const [models, setModels] = useState<Model[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [report, setReport] = useState<Usage | null>(null);
  const [paging, setPaging] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const reportVersion = useRef(0);
  const end = useRef<HTMLDivElement>(null);
  const meRead = useRef(0);
  const initialLoad = useRef<AbortController | null>(null);
  const listChanges = useRef(new Set<number>());
  useEffect(() => {
    const controller = new AbortController();
    initialLoad.current = controller;
    api<Model[]>("models/", "GET", undefined, controller.signal)
      .then(setModels)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    api<Page>("conversations/", "GET", undefined, controller.signal)
      .then((page) => {
        setConversations((old) => [
          ...old,
          ...page.results.filter((c) => !listChanges.current.has(c.id)),
        ]);
        setNext(page.next);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, []);
  async function loadMore() {
    if (!next || paging) return;
    setPaging(true);
    try {
      const page = await api<Page>(
        `conversations/${new URL(next, window.location.href).search}`,
      );
      setConversations((old) => [
        ...old,
        ...page.results.filter(
          (c) =>
            !listChanges.current.has(c.id) &&
            !old.some((item) => item.id === c.id),
        ),
      ]);
      setNext(page.next);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPaging(false);
    }
  }
  async function refreshUsage() {
    const version = ++meRead.current;
    try {
      const me = await api<User>(
        "auth/me/",
        "GET",
        undefined,
        initialLoad.current?.signal,
      );
      if (version === meRead.current) setUser(me);
    } catch {
      /* Keep the last confirmed quota if the server is unreachable. */
    }
  }
  const chats = useChats((c) => {
    listChanges.current.add(c.id);
    setConversations((old) => [c, ...old.filter((item) => item.id !== c.id)]);
  }, refreshUsage);
  const { activeId, chat, messages } = chats;
  const active = chat.detail ?? conversations.find((c) => c.id === activeId);
  const processing = chats.busy(activeId);
  const selected = chat.selection ?? (models.length ? [models[0].id] : []);
  const prompt = chat.prompt;
  const last = messages.at(-1);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [
    activeId,
    last?.id,
    last?.content,
    chat.live?.messages.map((m) => m.content.length).join(","),
  ]);
  function switchView(action: () => void) {
    ++reportVersion.current;
    setReport(null);
    setError("");
    action();
  }
  async function openReport() {
    const version = ++reportVersion.current;
    try {
      const data = await api<Usage>("usage/");
      if (version === reportVersion.current) setReport(data);
    } catch (e) {
      if (version === reportVersion.current) setError((e as Error).message);
    }
  }
  async function remove() {
    const id = await chats.remove();
    if (id !== undefined) {
      listChanges.current.add(id);
      setConversations((old) => old.filter((c) => c.id !== id));
    }
  }
  async function logout() {
    setLoggingOut(true);
    try {
      await api("auth/logout/", "POST");
      onLogout();
      await refreshCsrf();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoggingOut(false);
    }
  }
  function send(event: React.FormEvent) {
    event.preventDefault();
    void chats.send(
      selected
        .map((id) => models.find((m) => m.id === id))
        .filter((m): m is Model => m !== undefined),
    );
  }
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
        <button className="new" onClick={() => switchView(chats.newChat)}>
          ＋ گفتگوی تازه
        </button>
        <details className="history" open>
          <summary>گفتگوهای شما</summary>
          <nav aria-label="تاریخچه گفتگو">
            {conversations.map((c) => (
              <button
                key={c.id}
                className={active?.id === c.id ? "current" : ""}
                onClick={() => switchView(() => chats.open(c.id))}
              >
                {c.title}
                {chats.busy(c.id) && <small> · در حال پاسخ</small>}
              </button>
            ))}
            {!conversations.length && <small>هنوز گفتگویی ندارید.</small>}
            {next && (
              <button disabled={paging} onClick={loadMore}>
                گفتگوهای بیشتر
              </button>
            )}
          </nav>
        </details>
        <div className="quota">
          <div>
            <span>توکن کسرشده از سهمیه</span>
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
          <button onClick={logout} disabled={loggingOut}>
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
              <button disabled={processing || chat.removing} onClick={remove}>
                حذف گفتگو
              </button>
            )}
            {user.is_staff && (
              <>
                <button onClick={openReport}>گزارش مصرف</button>
                <a href="/admin/">مدیریت ↗</a>
              </>
            )}
          </div>
        </header>
        {(error || (!report && chat.error)) && (
          <div className="error banner" role="alert">
            {error || chat.error}
            {activeId > 0 && !report && (
              <button onClick={() => chats.open(activeId)}>
                بازخوانی گفتگو
              </button>
            )}
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
                  <th>جمع توکن‌ها</th>
                </tr>
              </thead>
              <tbody>
                {report.models.map((m) => (
                  <tr key={m.model_id}>
                    <td>{m.model__name}</td>
                    <td>{number(m.input_tokens)}</td>
                    <td>{number(m.output_tokens)}</td>
                    <td>
                      {number(
                        m.input_tokens + m.output_tokens + m.unsplit_tokens,
                      )}
                    </td>
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
              {chat.loading && !messages.length ? (
                <p role="status">در حال دریافت گفتگو…</p>
              ) : !messages.length ? (
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
                      <button key={s} onClick={() => chats.setPrompt(s)}>
                        {s}
                        <span>↖</span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="messages">
                  <MessageList
                    messages={messages}
                    retry={
                      !processing
                        ? (content, modelId) => {
                            chats.setPrompt(content);
                            if (modelId && models.some((m) => m.id === modelId))
                              chats.setSelection([modelId]);
                            document
                              .querySelector<HTMLTextAreaElement>("#prompt")
                              ?.focus();
                          }
                        : undefined
                    }
                  />
                  <div ref={end} />
                </div>
              )}
              {processing && (
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
                          processing ||
                          (!selected.includes(m.id) && selected.length >= 3)
                        }
                        onChange={() =>
                          chats.setSelection(
                            selected.includes(m.id)
                              ? selected.filter((id) => id !== m.id)
                              : [...selected, m.id],
                          )
                        }
                      />
                      {m.name}
                      {m.provider === "demo" && <small>نمایشی</small>}
                    </label>
                  ))}
                </div>
                {models
                  .filter(
                    (m) => selected.includes(m.id) && m.thinking_levels?.length,
                  )
                  .map((m) => (
                    <label className="thinking-control" key={m.id}>
                      شدت استدلال {m.name}
                      <select
                        value={chat.thinking?.[m.id] ?? m.thinking_default}
                        disabled={processing}
                        onChange={(e) =>
                          chats.setThinking(m.id, e.target.value)
                        }
                      >
                        {m.thinking_levels.map((level) => (
                          <option key={level} value={level}>
                            {level.toUpperCase()}
                          </option>
                        ))}
                      </select>
                    </label>
                  ))}
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
                  disabled={processing || chat.removing}
                  onChange={(e) => chats.setPrompt(e.target.value)}
                />
                <div>
                  <small>{number(prompt.length)} / ۱۲٬۰۰۰</small>
                  {processing ? (
                    <button
                      type="button"
                      className="stop"
                      onClick={chats.stop}
                      disabled={chat.live?.stopping}
                      aria-label="توقف پاسخ‌های این گفتگو"
                    >
                      {chat.live?.stopping ? "در حال توقف…" : "توقف پاسخ"}
                    </button>
                  ) : (
                    <button
                      type="submit"
                      className="primary"
                      disabled={
                        chat.loading ||
                        chat.removing ||
                        !prompt.trim() ||
                        !selected.length
                      }
                    >
                      {selected.length > 1
                        ? "مقایسهٔ پاسخ‌ها ↑"
                        : "ارسال پیام ↑"}
                    </button>
                  )}
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
