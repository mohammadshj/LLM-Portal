import { money } from "./credit";
import { ThemeSettings } from "./ThemeToggle";
import { historyGroups } from "./preferences";
import { useState } from "react";
import {
  Activity,
  ChevronsRight,
  CircleUserRound,
  Ellipsis,
  Pin,
  Download,
  ChevronUp,
  ChartColumn,
  LogOut,
  MessageSquare,
  Plus,
  Search,
  Wallet,
} from "lucide-react";
import type { Conversation, User } from "./types";
import type { useHistory } from "./useHistory";
import { Brand, Dialog } from "./ui";

export function Quota({ user }: { user: User }) {
  return (
    <section
      className="quota"
      aria-label="اعتبار حساب"
      data-warning={user.credit_available_rial <= 0}
    >
      <div className="line">
        <strong>
          <Wallet /> اعتبار قابل استفاده
        </strong>
        <b>{money(user.credit_available_rial)}</b>
      </div>
      {user.credit_reserved_rial > 0 && (
        <small>در حال پردازش {money(user.credit_reserved_rial)}</small>
      )}
    </section>
  );
}

type Props = {
  themeChoice: "light" | "dark" | "system";
  selectTheme: (v: "light" | "dark" | "system") => void;
  onReport: () => void;
  user: User;
  history: ReturnType<typeof useHistory>;
  activeId: number;
  busy: (id: number, listed?: boolean) => boolean;
  onNew: () => void;
  onOpen: (id: number) => void;
  onManage: (c: Conversation) => void;
  onLogout: () => void;
  loggingOut: boolean;
  onCollapse?: () => void;
};
export function Sidebar({
  user,
  history,
  themeChoice,
  selectTheme,
  onReport,
  activeId,
  busy,
  onNew,
  onOpen,
  onManage,
  onLogout,
  loggingOut,
  onCollapse,
}: Props) {
  const [accountOpen, setAccountOpen] = useState(false);
  return (
    <aside className="sidebar" aria-label="نوار گفتگوها">
      <div className="brand-row">
        <Brand />
        {onCollapse && (
          <button
            className="icon"
            title="جمع کردن نوار گفتگوها"
            aria-label="جمع کردن نوار گفتگوها"
            onClick={onCollapse}
          >
            <ChevronsRight />
          </button>
        )}
      </div>
      <button className="primary new" onClick={onNew}>
        <Plus />
        گفتگوی تازه
      </button>
      <label className="search">
        <Search />
        <input
          aria-label="جست‌وجوی گفتگوها"
          type="search"
          maxLength={100}
          value={history.query}
          placeholder="جست‌وجوی گفتگوها…"
          onChange={(e) => history.setQuery(e.target.value)}
        />
      </label>
      <nav className="history" aria-label="تاریخچه گفتگو">
        {history.loading ? (
          <div
            className="skeleton"
            role="status"
            aria-label="در حال دریافت تاریخچه"
          >
            <i />
            <i />
            <i />
          </div>
        ) : (
          historyGroups(history.items).map(([group, rows]) => (
            <section key={group}>
              <h2 className="section-label">
                {group === "سنجاق‌شده" && <Pin />}
                {group}
              </h2>
              {rows.map((c) => (
                <div
                  className={
                    "history-row" + (c.id === activeId ? " current" : "")
                  }
                  key={c.id}
                >
                  <button
                    title={c.title}
                    aria-label={c.title}
                    aria-description={
                      busy(c.id, c.is_processing) ? "در حال پردازش" : undefined
                    }
                    className="history-link"
                    aria-current={c.id === activeId ? "page" : undefined}
                    onClick={() => onOpen(c.id)}
                  >
                    {busy(c.id, c.is_processing) ? (
                      <Activity className="pulse" aria-label="در حال پردازش" />
                    ) : (
                      <MessageSquare />
                    )}
                    <bdi>{c.title}</bdi>
                  </button>
                  <button
                    className="icon"
                    aria-label={"مدیریت گفتگو " + c.title}
                    title="عملیات گفتگو"
                    onClick={() => onManage(c)}
                  >
                    <Ellipsis />
                  </button>
                </div>
              ))}
            </section>
          ))
        )}
        {!history.loading && !history.error && !history.items.length && (
          <p className="muted">
            {history.query
              ? "گفتگویی با این عنوان پیدا نشد."
              : "پس از اولین ارسال، گفتگو اینجا ذخیره می‌شود."}
          </p>
        )}
        {history.error && (
          <p role="alert">
            {history.error}{" "}
            <button onClick={history.refresh}>تلاش دوباره</button>
          </p>
        )}
        {history.next && (
          <button disabled={history.paging} onClick={history.more}>
            گفتگوهای بیشتر
          </button>
        )}
      </nav>
      <Quota user={user} />
      <button
        className="account"
        aria-haspopup="dialog"
        onClick={() => setAccountOpen(true)}
      >
        <CircleUserRound />
        <span>
          <strong dir="auto">{user.username}</strong>
          <small>{user.is_staff ? "مدیر سامانه" : "حساب کاربری"}</small>
        </span>
        <ChevronUp />
      </button>
      {accountOpen && (
        <Dialog title="حساب و تنظیمات" onClose={() => setAccountOpen(false)}>
          <div className="dialog-form">
            <strong dir="auto">{user.username}</strong>
            <Quota user={user} />
            <ThemeSettings choice={themeChoice} select={selectTheme} />
            <button
              onClick={() => {
                setAccountOpen(false);
                onReport();
              }}
            >
              <ChartColumn />
              گزارش مصرف حساب
            </button>
            <button disabled={loggingOut} onClick={onLogout}>
              <LogOut />
              خروج از حساب
            </button>
          </div>
        </Dialog>
      )}
    </aside>
  );
}

export function ManageConversation({
  item,
  busy,
  onRename,
  onPin,
  onExport,
  onRemove,
  close,
}: {
  item: Conversation;
  busy: boolean;
  onPin: () => Promise<void>;
  onExport: () => Promise<void>;
  onRename: (title: string) => Promise<void>;
  onRemove: () => Promise<void>;
  close: () => void;
}) {
  const [title, setTitle] = useState(item.title);
  const [deleting, setDeleting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function action(run: () => Promise<void>) {
    if (saving) return;
    setSaving(true);
    try {
      await run();
      close();
    } catch (e) {
      setError((e as Error).message);
      setSaving(false);
    }
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (saving) return;
    setSaving(true);
    setError("");
    try {
      if (deleting) await onRemove();
      else await onRename(title.trim());
      close();
    } catch (e) {
      setError((e as Error).message);
      setSaving(false);
    }
  }
  return (
    <Dialog
      title={deleting ? "حذف گفتگو" : "مدیریت گفتگو"}
      onClose={() => {
        if (!saving) close();
      }}
    >
      <form onSubmit={submit} className="dialog-form">
        {!deleting && (
          <div className="conversation-actions">
            <button
              type="button"
              disabled={saving}
              onClick={() => action(onPin)}
            >
              <Pin />
              {item.pinned ? "برداشتن سنجاق" : "سنجاق گفتگو"}
            </button>
            <button
              type="button"
              disabled={saving || busy}
              onClick={() => action(onExport)}
            >
              <Download />
              دریافت متن گفتگو
            </button>
          </div>
        )}
        {deleting ? (
          <p>
            گفتگوی «{item.title}» و پیام‌های آن حذف شوند؟ امکان بازگرداندن آن‌ها
            وجود ندارد.
          </p>
        ) : (
          <label>
            عنوان گفتگو
            <input
              maxLength={100}
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
        )}
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className="line">
          <button
            type="button"
            className={deleting ? "" : "danger-text"}
            disabled={saving || (!deleting && busy)}
            onClick={() => setDeleting(!deleting)}
          >
            {deleting ? "بازگشت" : "حذف گفتگو"}
          </button>
          <button
            className={deleting ? "danger" : "primary"}
            disabled={saving || (deleting ? busy : !title.trim())}
          >
            {deleting ? "تأیید حذف" : "ذخیرهٔ عنوان"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
