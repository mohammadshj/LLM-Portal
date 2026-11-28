import { useEffect, useState } from "react";
import { api } from "./api";
import { money } from "./credit";
import { number } from "./ui";
import type { Credit, User } from "./types";

type Row = Record<string, string | number | null>;
type Page = { results: Row[]; totals: Row; count: number; size: number };
type Summary = {
  allocated: number;
  used: number;
  reserved: number;
  remaining: number;
  active: number;
  empty: number;
  low: number;
  cost_1d: number;
  cost_7d: number;
  cost_30d: number;
  unknown: number;
  estimated: number;
  uncovered: number;
  unpriced: number;
  highest_prices: {
    id: number;
    name: string;
    output_price_per_million_rial: number;
  }[];
  account?: Credit;
};
const names: Record<string, string> = {
  users: "کاربران",
  models: "مدل‌ها",
  "user-model-usage": "کاربر × مدل",
  transactions: "دفتر تراکنش‌ها",
  usage: "مصرف مدل‌ها",
  trend: "روند مصرف",
  user__username: "کاربر",
  model__name: "مدل",
  model__provider: "سرویس",
  model__connection__name: "اتصال",
  requests: "درخواست",
  cost_rial: "هزینه برداشت‌شده",
  average_rial: "میانگین هر درخواست",
  last: "آخرین مصرف",
  period: "دوره",
  review: "نیازمند بررسی",
  completed: "موفق",
  failed: "ناموفق",
  cancelled: "متوقف",
  inputs: "توکن ورودی",
  outputs: "توکن خروجی",
  reasoning: "توکن استدلال",
  tokens: "کل توکن",
  unsplit: "تفکیک‌نشده",
  uncovered: "هزینه پوشش‌نداده",
  calculated_rial_sum: "هزینه محاسبه‌شده",
  share: "سهم از مصرف کاربر",
  id: "ردیف",
  kind: "نوع",
  amount_rial: "مبلغ",
  balance_after_rial: "مانده",
  created_at: "تاریخ",
  source: "منبع",
  status: "وضعیت",
  reference: "مرجع",
  description: "دلیل",
  created_by__username: "عامل",
  request_id: "شناسه درخواست",
  reply_id: "شناسه پاسخ",
  reported: "گزارش سرویس",
  estimated: "برآوردی",
  partial: "ناقص",
  estimate_in: "ورودی برآوردی",
  estimate_out: "خروجی برآوردی",
  unknown: "نامشخص",
  grant: "تخصیص",
  adjustment: "اصلاح",
  refund: "بازپرداخت",
  migration: "اعتبار اولیه",
  user: "شناسه کاربر",
  model: "شناسه مدل",
  connection: "شناسه اتصال",
  provider: "نوع سرویس",
  from: "از تاریخ",
  to: "تا تاریخ",
  q: "نام کاربری",
  refund_rial: "مجموع بازپرداخت",
  adjustment_rial: "خالص اصلاحات",
  allocated: "اعتبار تخصیص‌یافته",
  used: "مصرف خالص",
  remaining: "مانده",
  reserved: "رزرو فعال",
  active: "کاربران فعال",
  empty: "بدون اعتبار آزاد",
  low: "اعتبار کم",
  cost_1d: "مصرف امروز",
  cost_7d: "مصرف هفت روز",
  cost_30d: "مصرف سی روز",
  unpriced: "مدل با تعرفه ناقص",
  user__account__credit_limit_rial: "اعتبار کل حساب",
  user__account__credit_used_rial: "مصرف خالص حساب",
  user__account__credit_reserved_rial: "رزرو حساب",
};
function show(key: string, value: Row[string]) {
  if (value == null || value === "") return "—";
  if (key.includes("_rial") || key === "uncovered") return money(Number(value));
  if (key === "share") return number(Number(value)) + "٪";
  if (["last", "created_at", "period"].includes(key))
    return new Date(String(value)).toLocaleDateString("fa-IR");
  if (key === "kind" && value === "usage") return "مصرف";
  if (typeof value === "string") return names[value] ?? value;
  return number(value);
}
export function UsageReport({ user }: { user: User }) {
  const admin = user.is_staff;
  const initial = new URLSearchParams(location.search);
  const tabs = admin
    ? ["users", "models", "user-model-usage", "trend", "transactions"]
    : ["usage", "trend", "transactions"];
  const [view, setView] = useState(
    tabs.includes(initial.get("billing") ?? "")
      ? initial.get("billing")!
      : tabs[0],
  );
  const [filters, setFilters] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      ["user", "model"]
        .filter((k) => initial.get(k))
        .map((k) => [k, initial.get(k)!]),
    ),
  );
  const [page, setPage] = useState(1),
    [sort, setSort] = useState(""),
    [interval, setInterval] = useState("day");
  const [personal, setPersonal] = useState<{
    cost_today: number;
    cost_month: number;
  } | null>(null);
  const [loaded, setLoaded] = useState<{ path: string; data: Page } | null>(
      null,
    ),
    [summary, setSummary] = useState<Summary | null>(null),
    [error, setError] = useState(""),
    [summaryError, setSummaryError] = useState("");
  const params = new URLSearchParams({
    ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)),
    page: String(page),
    interval,
  });
  if (sort) params.set("sort", sort);
  const base = admin ? `admin/billing/${view}/` : `credits/${view}/report/`;
  const path = base + "?" + params.toString();
  const data = loaded?.path === path ? loaded.data : null;
  useEffect(() => {
    const ctl = new AbortController();
    setLoaded(null);
    setError("");
    const timer = setTimeout(
      () =>
        api<Page>(path, "GET", undefined, ctl.signal)
          .then((v) => {
            if (!ctl.signal.aborted) setLoaded({ path, data: v });
          })
          .catch((e) => {
            if (!ctl.signal.aborted) setError(e.message);
          }),
      180,
    );
    return () => {
      clearTimeout(timer);
      ctl.abort();
    };
  }, [path, user.credit_version]);
  useEffect(() => {
    const ctl = new AbortController();
    if (!admin) {
      setSummaryError("");
      api<{ cost_today: number; cost_month: number }>(
        "credits/summary/report/",
        "GET",
        undefined,
        ctl.signal,
      )
        .then((v) => {
          if (!ctl.signal.aborted) setPersonal(v);
        })
        .catch((e) => {
          if (!ctl.signal.aborted) setSummaryError(e.message);
        });
      return () => ctl.abort();
    }
    setSummary(null);
    setSummaryError("");
    api<Summary>(
      "admin/billing/summary/?user=" + encodeURIComponent(filters.user || ""),
      "GET",
      undefined,
      ctl.signal,
    )
      .then((v) => {
        if (!ctl.signal.aborted) setSummary(v);
      })
      .catch((e) => {
        if (!ctl.signal.aborted) setSummaryError(e.message);
      });
    return () => ctl.abort();
  }, [admin, filters.user, user.credit_version]);
  function change(key: string, value: string) {
    setFilters((old) => ({ ...old, [key]: value }));
    setPage(1);
  }
  function tab(v: string) {
    setView(v);
    if (v !== "transactions") setFilters((old) => ({ ...old, kind: "" }));
    setSort("");
    setPage(1);
  }
  function drill(key: string, id: Row[string]) {
    change(key, String(id));
    tab("user-model-usage");
  }
  const columns = data?.results[0]
    ? Object.keys(data.results[0]).filter(
        (k) => !["user_id", "model_id"].includes(k),
      )
    : [];
  return (
    <section className="report billing-report">
      <h2>{admin ? "گزارش مالی سامانه" : "مصرف و تراکنش‌های من"}</h2>
      {!admin && (
        <div className="billing-metrics">
          {(
            [
              ["اعتبار قابل استفاده", user.credit_available_rial],
              ["اعتبار کل", user.credit_limit_rial],
              ["رزرو فعال", user.credit_reserved_rial],
              ["مصرف خالص", user.credit_used_rial],
              ["مصرف امروز", personal?.cost_today],
              ["مصرف ماه جاری (میلادی)", personal?.cost_month],
            ] as const
          ).map(([label, value]) => (
            <div key={label}>
              <small>{label}</small>
              <strong>{value == null ? "—" : money(value)}</strong>
            </div>
          ))}
        </div>
      )}
      {summaryError && <p role="alert">{summaryError}</p>}
      {summary && (
        <>
          <div className="billing-metrics">
            {[
              "allocated",
              "used",
              "remaining",
              "reserved",
              "cost_1d",
              "cost_7d",
              "cost_30d",
              "uncovered",
              "active",
              "empty",
              "low",
              "unknown",
              "estimated",
              "unpriced",
            ].map((k, i) => (
              <div key={k}>
                <small>{names[k]}</small>
                <strong>
                  {i < 8
                    ? money(Number(summary[k as keyof Summary]))
                    : number(Number(summary[k as keyof Summary]))}
                </strong>
              </div>
            ))}
          </div>
          {summary.highest_prices.length > 0 && (
            <details>
              <summary>بالاترین تعرفه‌های خروجی</summary>
              {summary.highest_prices.map((m) => (
                <p key={m.id}>
                  {m.name} · {money(m.output_price_per_million_rial)} برای یک
                  میلیون توکن
                </p>
              ))}
            </details>
          )}
          {summary.account && (
            <p>
              اعتبار حساب انتخابی {money(summary.account.credit_limit_rial)} ·
              مصرف {money(summary.account.credit_used_rial)} · رزرو{" "}
              {money(summary.account.credit_reserved_rial)} · مانده{" "}
              {money(summary.account.credit_remaining_rial)}
            </p>
          )}
        </>
      )}
      <nav className="billing-tabs" aria-label="نماهای گزارش">
        {tabs.map((v) => (
          <button key={v} aria-pressed={view === v} onClick={() => tab(v)}>
            {names[v]}
          </button>
        ))}
      </nav>
      <div className="billing-filters">
        {(admin
          ? ["q", "user", "model", "connection", "provider", "from", "to"]
          : ["model", "from", "to"]
        ).map((k) => (
          <label key={k}>
            {names[k]}
            <input
              type={
                ["from", "to"].includes(k)
                  ? "date"
                  : ["user", "model", "connection"].includes(k)
                    ? "number"
                    : "search"
              }
              min="1"
              value={filters[k] ?? ""}
              onChange={(e) => change(k, e.target.value)}
            />
          </label>
        ))}
        {admin &&
          Object.entries({
            status: ["completed", "cancelled", "failed"],
            source: [
              "reported",
              "partial",
              "estimated",
              "estimate_in",
              "estimate_out",
              "unknown",
            ],
          }).map(([k, opts]) => (
            <label key={k}>
              {names[k]}
              <select
                value={filters[k] ?? ""}
                onChange={(e) => change(k, e.target.value)}
              >
                <option value="">همه</option>
                {opts.map((o) => (
                  <option key={o} value={o}>
                    {names[o]}
                  </option>
                ))}
              </select>
            </label>
          ))}
        {view === "trend" && (
          <label>
            دوره
            <select
              value={interval}
              onChange={(e) => {
                setInterval(e.target.value);
                setPage(1);
              }}
            >
              <option value="day">روزانه</option>
              <option value="week">هفتگی</option>
              <option value="month">ماهانه</option>
            </select>
          </label>
        )}
        {view === "transactions" && (
          <label>
            نوع تراکنش
            <select
              value={filters.kind ?? ""}
              onChange={(e) => change("kind", e.target.value)}
            >
              <option value="">همه</option>
              {["usage", "grant", "adjustment", "refund", "migration"].map(
                (k) => (
                  <option key={k} value={k}>
                    {k === "usage" ? "مصرف" : names[k]}
                  </option>
                ),
              )}
            </select>
          </label>
        )}
        <label>
          ترتیب
          <select
            value={sort}
            onChange={(e) => {
              setSort(e.target.value);
              setPage(1);
            }}
          >
            <option value="">پیش‌فرض</option>
            {(view === "transactions"
              ? ["-created_at", "created_at", "amount_rial", "-amount_rial"]
              : [
                  "-cost_rial",
                  "cost_rial",
                  "-requests",
                  ...(admin ? ["-tokens"] : []),
                ]
            ).map((k) => (
              <option key={k} value={k}>
                {names[k.replace("-", "")]}{" "}
                {k.startsWith("-") ? "نزولی" : "صعودی"}
              </option>
            ))}
          </select>
        </label>
        <a href={"/api/" + path + "&export=csv"} download>
          خروجی CSV
        </a>
      </div>
      {error ? (
        <p role="alert">{error}</p>
      ) : !data ? (
        <p role="status">در حال دریافت گزارش…</p>
      ) : (
        <>
          <p>
            {Object.entries(data.totals)
              .filter(([k]) =>
                [
                  "cost_rial",
                  "requests",
                  "tokens",
                  "average_rial",
                  "amount_rial",
                  "refund_rial",
                  "adjustment_rial",
                ].includes(k),
              )
              .map(([k, v]) => names[k] + " " + show(k, v))
              .join(" · ")}
          </p>
          {data.results.length === 0 ? (
            <p>با این فیلتر رکوردی پیدا نشد.</p>
          ) : (
            <>
              {view !== "transactions" && (
                <div
                  className="billing-chart"
                  aria-label="مقایسه هزینه در صفحه جاری"
                >
                  {data.results.slice(0, 12).map((row, i) => (
                    <div key={i}>
                      <span>
                        {String(
                          row.model__name ??
                            row.user__username ??
                            show("period", row.period),
                        )}
                      </span>
                      <progress
                        aria-label="هزینه"
                        value={Number(row.cost_rial)}
                        max={Math.max(
                          1,
                          ...data.results.map((r) => Number(r.cost_rial)),
                        )}
                      />
                      <span>{money(Number(row.cost_rial))}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="billing-table">
                <table>
                  <thead>
                    <tr>
                      {columns.map((k) => (
                        <th key={k}>{names[k] ?? k}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.results.map((row, i) => (
                      <tr key={i}>
                        {columns.map((k) => (
                          <td key={k}>
                            {admin &&
                            ((k === "user__username" && row.user_id) ||
                              (k === "model__name" && row.model_id)) ? (
                              <button
                                onClick={() =>
                                  drill(
                                    k === "user__username" ? "user" : "model",
                                    k === "user__username"
                                      ? row.user_id
                                      : row.model_id,
                                  )
                                }
                              >
                                {show(k, row[k])}
                              </button>
                            ) : (
                              show(k, row[k])
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          <div className="billing-tabs">
            <button disabled={page === 1} onClick={() => setPage(page - 1)}>
              صفحه قبل
            </button>
            <span>
              {number(page)} /{" "}
              {number(Math.max(1, Math.ceil(data.count / data.size)))}
            </span>
            <button
              disabled={page * data.size >= data.count}
              onClick={() => setPage(page + 1)}
            >
              صفحه بعد
            </button>
          </div>
        </>
      )}
    </section>
  );
}
