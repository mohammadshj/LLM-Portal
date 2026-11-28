import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Activity,
  ChartColumn,
  ChevronLeft,
  MessagesSquare,
  Columns2,
  CircleAlert,
  Menu,
  PanelRightOpen,
  Plus,
  Settings2,
} from "lucide-react";
import { api, refreshCsrf } from "./api";
import { ChatComposer } from "./ChatComposer";
import { MessageList } from "./MessageList";
import { ManageConversation, Sidebar } from "./Sidebar";
import { ThemeToggle } from "./ThemeToggle";
import { Thread, Welcome, Suggestions } from "./Thread";
import { applyCredit } from "./credit";
import { available, readPreferences, remember, type Mode } from "./preferences";
import { Brand } from "./Brand";
import { downloadChat } from "./exportChat";
import type { User, Model, Conversation, Detail } from "./types";
import { Dialog, useMedia } from "./ui";
import { ready } from "./reasoning";
import { useChats } from "./useChats";
import { useHistory } from "./useHistory";

const UsageReport = lazy(() =>
  import("./UsageReport").then((module) => ({ default: module.UsageReport })),
);

export function Workspace({
  theme,
  themeChoice,
  selectTheme,
  toggle,
  initialUser,
  onLogout,
}: {
  theme: "light" | "dark";
  themeChoice: "light" | "dark" | "system";
  selectTheme: (v: "light" | "dark" | "system") => void;
  toggle: () => void;
  initialUser: User;
  onLogout: () => void;
}) {
  const [user, setUser] = useState(initialUser);
  const [models, setModels] = useState<Model[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelError, setModelError] = useState("");
  const [retryModels, setRetryModels] = useState(0);
  const [error, setError] = useState("");
  const [quotaStale, setQuotaStale] = useState(false);
  const [report, setReport] = useState(
    new URLSearchParams(location.search).has("billing"),
  );
  const [loggingOut, setLoggingOut] = useState(false);
  const [prefs, setPrefs] = useState(() =>
    readPreferences(initialUser.username),
  );
  const collapsed = prefs.collapsed;
  function setCollapsed(value: boolean) {
    setPrefs((p) => ({ ...p, collapsed: value }));
  }
  useEffect(
    () => remember(initialUser.username, prefs),
    [initialUser.username, prefs],
  );
  const [drawer, setDrawer] = useState(false);
  const [manage, setManage] = useState<Conversation | null>(null);
  const [notice, setNotice] = useState("");
  const mobile = useMedia("(max-width: 900px)");
  const history = useHistory();
  const positions = useRef(new Map<number, { top: number; follow: boolean }>());
  const usageVersion = useRef(0);

  const life = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    life.current = controller;
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setModelsLoading(true);
    setModelError("");
    api<Model[]>("models/?catalog=1", "GET", undefined, controller.signal)
      .then(setModels)
      .catch((e) => {
        if (!controller.signal.aborted) setModelError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setModelsLoading(false);
      });
    return () => controller.abort();
  }, [retryModels]);
  useEffect(() => {
    if (!mobile) setDrawer(false);
  }, [mobile]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 3000);
    return () => clearTimeout(timer);
  }, [notice]);
  const refreshUsage = useCallback(async () => {
    const version = ++usageVersion.current;
    try {
      const data = await api<User>(
        "auth/me/",
        "GET",
        undefined,
        life.current?.signal,
      );
      if (version === usageVersion.current) {
        setUser((old) => applyCredit(old, data));
        setQuotaStale(false);
      }
    } catch {
      if (version === usageVersion.current && !life.current?.signal.aborted)
        setQuotaStale(true);
    }
  }, []);
  useEffect(() => {
    const refresh = () => {
      if (!document.hidden) void refreshUsage();
    };
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [refreshUsage]);
  const chats = useChats(
    history.refresh,
    refreshUsage,
    (snapshot) => setUser((old) => applyCredit(old, snapshot)),
    (ids) =>
      setPrefs((p) => ({
        ...p,
        recent: [...new Set([...ids, ...p.recent])].slice(0, 6),
      })),
  );
  const { activeId, chat, messages } = chats;
  const chatError = chat.readError || chat.error;
  const active = chat.detail ?? history.items.find((c) => c.id === activeId);
  const processing = chats.busy(activeId);
  const previousModels = useMemo(() => {
    const rows = chat.detail?.messages ?? [];
    const ids: number[] = [];
    for (let i = rows.length - 1; i >= 0 && rows[i].role === "assistant"; i--) {
      if (rows[i].model_id != null) ids.unshift(rows[i].model_id!);
    }
    return ids;
  }, [chat.detail?.messages]);
  const mode = chat.mode ?? (previousModels.length > 1 ? "compare" : "chat");
  const usable = models.filter(available);
  function choices(target: Mode) {
    const local = target === "chat" ? chat.single : chat.selection;
    if (local) return local.filter((id) => usable.some((m) => m.id === id));
    const prior = previousModels.filter((id) =>
      usable.some((m) => m.id === id),
    );
    if (
      (target === "chat" && prior.length === 1) ||
      (target === "compare" && prior.length >= 2)
    )
      return prior;
    const saved = prefs[target].filter((id) => usable.some((m) => m.id === id));
    return saved.length
      ? saved
      : usable.slice(0, target === "chat" ? 1 : 2).map((m) => m.id);
  }
  const selected = choices(mode);
  function choose(ids: number[], target = mode) {
    chats.setMode(target, ids);
    setPrefs((p) => ({ ...p, [target]: ids }));
  }
  const emptyStage = !chat.loading && !messages.length;
  const selectedModels = selected
    .map((id) => models.find((m) => m.id === id))
    .filter((m): m is Model => !!m);
  function keepScroll() {
    const current = positions.current.get(activeId);
    positions.current.set(activeId, { top: current?.top ?? 0, follow: false });
  }
  function change(action: () => void) {
    setDrawer(false);
    setReport(false);
    setError("");
    action();
  }
  function openReport() {
    setReport(true);
    setDrawer(false);
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
  function prepare(text: string, modelId?: number | null) {
    chats.setPrompt(text);
    if (modelId && models.some((m) => m.id === modelId))
      choose([modelId], "chat");
    document.getElementById("prompt")?.focus();
  }
  const side = (
    <Sidebar
      user={user}
      themeChoice={themeChoice}
      selectTheme={selectTheme}
      onReport={openReport}
      history={history}
      activeId={activeId}
      busy={chats.busy}
      onNew={() => change(chats.newChat)}
      onOpen={(id) => change(() => chats.open(id))}
      onManage={setManage}
      onLogout={logout}
      loggingOut={loggingOut}
      onCollapse={!mobile ? () => setCollapsed(true) : undefined}
    />
  );
  return (
    <div className="app" data-collapsed={collapsed}>
      {mobile ? (
        drawer && (
          <Dialog title="گفتگوهای من" drawer onClose={() => setDrawer(false)}>
            {side}
          </Dialog>
        )
      ) : collapsed ? (
        <aside className="rail">
          <Brand variant="icon" />
          <button
            className="icon"
            title="باز کردن نوار گفتگوها"
            aria-label="باز کردن نوار گفتگوها"
            onClick={() => setCollapsed(false)}
          >
            <PanelRightOpen />
          </button>
          <button
            className="icon"
            title="گفتگوی تازه"
            aria-label="گفتگوی تازه"
            onClick={() => change(chats.newChat)}
          >
            <Plus />
          </button>
        </aside>
      ) : (
        side
      )}
      <main className="workspace" data-empty={emptyStage && !report}>
        <header className="workspace-head">
          {mobile && (
            <button
              className="icon"
              aria-label="باز کردن گفتگوها"
              onClick={() => setDrawer(true)}
            >
              <Menu />
            </button>
          )}
          <div className="crumb">
            {mobile ? <Brand variant="icon" /> : <MessagesSquare />}
            <span>فضای کار</span>
            <ChevronLeft />
            <h1 dir="auto">
              {report ? "گزارش مصرف" : active?.title || "گفتگوی تازه"}
            </h1>
          </div>
          <div className="header-actions">
            {processing && !report && (
              <span className="live-state">
                <Activity /> در حال پاسخ
              </span>
            )}
            <>
              <button
                className="icon"
                onClick={openReport}
                aria-label="گزارش مصرف"
                title="گزارش مصرف"
              >
                <ChartColumn />
              </button>
              {user.is_staff && (
                <a
                  className="icon"
                  href="/admin/"
                  aria-label="مدیریت سامانه"
                  title="مدیریت سامانه"
                >
                  <Settings2 />
                </a>
              )}
            </>
            <ThemeToggle theme={theme} toggle={toggle} />
          </div>
        </header>
        {(modelError || error || (!report && chatError)) && (
          <div className="error banner" role="alert">
            <CircleAlert />
            {modelError || error || chatError}
            {modelError ? (
              <button onClick={() => setRetryModels((v) => v + 1)}>
                دریافت مدل‌ها
              </button>
            ) : (
              activeId > 0 &&
              !report && (
                <button onClick={() => chats.open(activeId)}>
                  بازخوانی گفتگو
                </button>
              )
            )}
          </div>
        )}
        {quotaStale && (
          <div className="banner">
            آخرین اعتبارٔ تأییدشده نمایش داده می‌شود.{" "}
            <button onClick={refreshUsage}>به‌روزرسانی</button>
          </div>
        )}
        {report ? (
          <div className="report-wrap">
            <button onClick={() => change(() => {})}>بازگشت به گفتگو</button>
            <Suspense fallback={<p role="status">در حال دریافت گزارش…</p>}>
              <UsageReport user={user} />
            </Suspense>
          </div>
        ) : (
          <>
            <div className="chat-stage">
              {emptyStage && <Welcome />}
              <div className="mode-switch" role="group" aria-label="حالت گفتگو">
                {(["chat", "compare"] as const).map((v) => (
                  <button
                    key={v}
                    disabled={processing}
                    aria-pressed={mode === v}
                    onClick={() => choose(choices(v), v)}
                  >
                    {v === "chat" ? <MessagesSquare /> : <Columns2 />}
                    {v === "chat" ? "گفتگو" : "مقایسه مدل‌ها"}
                  </button>
                ))}
              </div>
              {!emptyStage && (
                <Thread
                  key={"thread-" + activeId}
                  id={activeId}
                  positions={positions.current}
                >
                  {chat.loading && !messages.length ? (
                    <div
                      className="skeleton"
                      role="status"
                      aria-label="در حال دریافت گفتگو"
                    >
                      <i />
                      <i />
                      <i />
                    </div>
                  ) : (
                    <MessageList
                      actions={{
                        stopModel: async (request, model) => {
                          await api(
                            `conversations/${activeId}/requests/${request}/models/${model}/cancel/`,
                            "POST",
                            {},
                          );
                        },
                        feedback: async (id, value) => {
                          await api(
                            `conversations/${activeId}/messages/${id}/feedback/`,
                            "PUT",
                            { feedback: value },
                          );
                          chats.setFeedback(activeId, id, value);
                        },
                        versions: chat.detail?.versions ?? {},
                        locked: !!(
                          processing ||
                          chat.switching ||
                          chat.loading ||
                          chat.removing ||
                          chat.live
                        ),
                        canUseSelection:
                          selectedModels.length > 0 &&
                          selectedModels.every((m) =>
                            ready(m.reasoning_profile, chat.thinking?.[m.id]),
                          ),
                        selectedNames: selectedModels
                          .map((m) => m.name)
                          .join("، "),
                        save: (revision) => {
                          keepScroll();
                          void chats.send(selectedModels, revision);
                        },
                        select: (anchor, target) => {
                          keepScroll();
                          void chats.switchVersion(anchor, target);
                        },
                      }}
                      messages={messages}
                      retry={processing ? undefined : prepare}
                    />
                  )}
                </Thread>
              )}
              <ChatComposer
                key={"composer-" + activeId}
                models={models}
                selected={selected}
                thinking={chat.thinking}
                mode={mode}
                recent={prefs.recent}
                choose={choose}
                setThinking={chats.setThinking}
                prompt={chat.prompt}
                setPrompt={chats.setPrompt}
                processing={processing}
                stopping={!!chat.live?.stopping}
                locked={
                  !!(
                    chat.loading ||
                    chat.removing ||
                    chat.switching ||
                    (chat.live && !processing)
                  )
                }
                modelsLoading={modelsLoading}
                exhausted={
                  !quotaStale &&
                  user.credit_available_rial === 0 &&
                  selectedModels.some(
                    (m) =>
                      m.input_price_per_million_rial ||
                      m.output_price_per_million_rial,
                  )
                }
                send={() => {
                  chats.setMode(mode, selected);
                  void chats.send(selectedModels);
                }}
                stop={chats.stop}
              />
              {emptyStage && <Suggestions prepare={prepare} />}
            </div>
          </>
        )}
      </main>
      {manage && (
        <ManageConversation
          key={manage.id}
          item={manage}
          busy={chats.busy(manage.id, manage.is_processing)}
          close={() => setManage(null)}
          onPin={async () => {
            await api(`conversations/${manage.id}/`, "PATCH", {
              pinned: !manage.pinned,
            });
            history.refresh();
            setNotice(manage.pinned ? "سنجاق برداشته شد." : "گفتگو سنجاق شد.");
          }}
          onExport={async () =>
            downloadChat(await api<Detail>(`conversations/${manage.id}/`))
          }
          onRename={async (title) => {
            const saved = await api<Conversation>(
              `conversations/${manage.id}/`,
              "PATCH",
              { title },
            );
            chats.renamed(saved.id, saved.title);
            history.refresh();
            setNotice("عنوان گفتگو ذخیره شد.");
          }}
          onRemove={async () => {
            await chats.remove(manage.id);
            positions.current.delete(manage.id);
            history.refresh();
            setNotice("گفتگو حذف شد.");
          }}
        />
      )}
      {notice && (
        <div role="status" className="toast">
          {notice}
        </div>
      )}
    </div>
  );
}
