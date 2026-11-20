import { useState } from "react";
import {
  Activity,
  ChevronsRight,
  CircleUserRound,
  Ellipsis,
  History,
  LogOut,
  MessageSquare,
  Plus,
  Search,
  Wallet,
} from "lucide-react";
import type { Conversation, User } from "./types";
import type { useHistory } from "./useHistory";
import { Brand, Dialog, number } from "./ui";

export function Quota({ user }: { user: User }) {
  const left = Math.max(0, user.token_limit - user.tokens_used);
  const percent = user.token_limit
    ? Math.min(100, Math.round((100 * user.tokens_used) / user.token_limit))
    : 0;
  return (
    <section
      className="quota"
      aria-label="سهمیهٔ توکن"
      data-warning={!left || percent >= 85}
    >
      <div className="line">
        <strong>
          <Wallet /> سهمیهٔ توکن
        </strong>
        <b>{number(percent)}٪</b>
      </div>
      <progress aria-label="درصد مصرف سهمیه" value={percent} max={100} />
      <div>
        {number(user.tokens_used)} از {number(user.token_limit)} توکن
      </div>
      <small>
        {!user.token_limit
          ? "سهمیه‌ای تخصیص نیافته است"
          : !left
            ? "سهمیه تمام شده است"
            : (percent >= 85 ? "نزدیک سقف سهمیه · " : "") +
              number(left) +
              " توکن باقی‌مانده"}
      </small>
    </section>
  );
}

type Props = {
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
  activeId,
  busy,
  onNew,
  onOpen,
  onManage,
  onLogout,
  loggingOut,
  onCollapse,
}: Props) {
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
      <div className="section-label">
        <History /> گفتگوهای اخیر
      </div>
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
          history.items.map((c) => (
            <div
              className={"history-row" + (c.id === activeId ? " current" : "")}
              key={c.id}
            >
              <button
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
                title="تغییر نام یا حذف"
                onClick={() => onManage(c)}
              >
                <Ellipsis />
              </button>
            </div>
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
      <div className="account">
        <CircleUserRound />
        <div>
          <strong dir="auto">{user.username}</strong>
          <small>{user.is_staff ? "مدیر سامانه" : "حساب کاربری"}</small>
        </div>
        <button
          onClick={onLogout}
          disabled={loggingOut}
          className="icon"
          title="خروج"
          aria-label="خروج"
        >
          <LogOut />
        </button>
      </div>
    </aside>
  );
}

export function ManageConversation({
  item,
  busy,
  onRename,
  onRemove,
  close,
}: {
  item: Conversation;
  busy: boolean;
  onRename: (title: string) => Promise<void>;
  onRemove: () => Promise<void>;
  close: () => void;
}) {
  const [title, setTitle] = useState(item.title);
  const [deleting, setDeleting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
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
