import { StrictMode, lazy, Suspense, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, refreshCsrf } from "./api";
import "./style.css";

import type { User } from "./types";
import { Brand } from "./ui";
import { Eye, EyeOff } from "lucide-react";
import { ThemeSettings, useTheme } from "./ThemeToggle";

const Workspace = lazy(() =>
  import("./Workspace").then((module) => ({ default: module.Workspace })),
);

function App() {
  const { theme, toggle, choice, select } = useTheme();
  const [visible, setVisible] = useState(false);
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
          <section className="login-card">
            <div className="login-toolbar">
              <ThemeSettings choice={choice} select={select} />
            </div>
            <Brand variant="login" />
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
                <span className="password-field">
                  <input
                    aria-label="رمز عبور"
                    type={visible ? "text" : "password"}
                    autoComplete="current-password"
                    dir="ltr"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                  <button
                    type="button"
                    className="icon"
                    aria-label="نمایش رمز عبور"
                    aria-pressed={visible}
                    onClick={() => setVisible(!visible)}
                  >
                    {visible ? <EyeOff /> : <Eye />}
                  </button>
                </span>
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
    <Suspense
      fallback={
        <main className="login">
          <p role="status">در حال آماده‌سازی فضای گفتگو…</p>
        </main>
      }
    >
      <Workspace
        theme={theme}
        toggle={toggle}
        themeChoice={choice}
        selectTheme={select}
        initialUser={user}
        onLogout={() => setUser(null)}
      />
    </Suspense>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
