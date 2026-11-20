import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, refreshCsrf } from "./api";
import "./style.css";

import type { User } from "./types";
import { Workspace } from "./Workspace";
import { Brand } from "./ui";
import { PortalArt } from "./Thread";
import { ThemeToggle, useTheme } from "./ThemeToggle";

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
        <div className="login-shell">
          <section className="login-intro">
            <Brand />
            <PortalArt />
            <div>
              <h2>گفتگو و مقایسهٔ مدل‌ها</h2>
              <p>
                یک پرسش را به چند مدل بدهید و پاسخ، استدلال و مصرف توکن هر مدل
                را کنار هم بخوانید.
              </p>
            </div>
          </section>
          <section className="login-card">
            <div className="login-toolbar">
              <ThemeToggle theme={theme} toggle={toggle} />
            </div>
            <h1>ورود به پورتال</h1>
            <p>برای دسترسی به فضای کار، وارد حساب خود شوید.</p>
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
        </div>
      </main>
    );
  return (
    <Workspace
      theme={theme}
      toggle={toggle}
      initialUser={user}
      onLogout={() => setUser(null)}
    />
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
