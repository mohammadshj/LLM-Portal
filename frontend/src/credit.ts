import type { Credit, Model } from "./types";

const currency = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 });
export function money(rial: number) {
  return currency.format(rial / 10) + " تومان";
}

export function applyCredit<T extends Credit>(current: T, snapshot: Credit): T {
  return snapshot.credit_version >= current.credit_version
    ? { ...current, ...snapshot }
    : current;
}

export function priced(model: Model) {
  return (
    model.input_price_per_million_rial != null &&
    model.output_price_per_million_rial != null
  );
}
