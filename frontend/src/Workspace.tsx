import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ChartColumn,
  ChevronLeft,
  LayoutDashboard,
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
import { Thread, Welcome } from "./Thread";
import { applyCredit, priced } from "./credit";
import { CostEstimate } from "./CostEstimate";
import type { User, Model, Conversation } from "./types";
import { Dialog, useMedia } from "./ui";
import { UsageReport } from "./UsageReport";
import { ready } from "./reasoning";
import { useChats } from "./useChats";
import { useHistory } from "./useHistory";

export function Workspace({
  theme,
  toggle,
  initialUser,
  onLogout,
}: {
  theme: "light" | "dark";
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
  const [collapsed, setCollapsed] = useState(false);
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
    api<Model[]>("models/", "GET", undefined, controller.signal)
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
  const chats = useChats(history.refresh, refreshUsage, (snapshot) =>
    setUser((old) => applyCredit(old, snapshot)),
  );
  const { activeId, chat, messages } = chats;
  const chatError = chat.readError || chat.error;
  const active = chat.detail ?? history.items.find((c) => c.id === activeId);
  const processing = chats.busy(activeId);
  const selected =
    chat.selection ??
    models
      .filter(priced)
      .slice(0, 1)
      .map((m) => m.id);
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
      chats.setSelection([modelId]);
    document.getElementById("prompt")?.focus();
  }
  const side = (
    <Sidebar
      user={user}
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
      <main className="workspace">
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
            <LayoutDashboard />
            <span>میز کار</span>
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
            <UsageReport user={user} />
          </div>
        ) : (
          <>
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
              ) : !messages.length ? (
                <Welcome prepare={prepare} />
              ) : (
                <MessageList
                  actions={{
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
                    selectedNames: selectedModels.map((m) => m.name).join("، "),
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
            <CostEstimate
              chatId={activeId}
              prompt={chat.prompt}
              models={selectedModels}
              thinking={chat.thinking}
              leaf={chat.detail?.active_leaf}
              busy={processing || !!chat.loading}
            />
            <ChatComposer
              key={"composer-" + activeId}
              models={models}
              selected={selected}
              thinking={chat.thinking}
              choose={chats.setSelection}
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
              send={() => void chats.send(selectedModels)}
              stop={chats.stop}
            />
          </>
        )}
      </main>
      {manage && (
        <ManageConversation
          key={manage.id}
          item={manage}
          busy={chats.busy(manage.id, manage.is_processing)}
          close={() => setManage(null)}
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
