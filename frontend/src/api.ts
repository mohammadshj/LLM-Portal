let csrfToken = "";
export async function refreshCsrf() {
  const response = await fetch("/api/auth/csrf/");
  if (!response.ok) throw new Error("ارتباط با سرور ممکن نشد.");
  csrfToken = (await response.json()).csrfToken;
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  if (method !== "GET" && !csrfToken) await refreshCsrf();
  const response = await fetch(`/api/${path}`, {
    method,
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok)
    throw new Error(
      typeof data?.detail === "string"
        ? data.detail
        : Array.isArray(data)
          ? data.join(" ")
          : "درخواست انجام نشد. ورودی و دسترسی خود را بررسی کنید.",
    );
  return data;
}
