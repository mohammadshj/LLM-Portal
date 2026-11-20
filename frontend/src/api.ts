let csrfToken = "";
export async function refreshCsrf() {
  const response = await fetch("/api/auth/csrf/");
  if (!response.ok) throw new Error("ارتباط با سرور ممکن نشد.");
  csrfToken = (await response.json()).csrfToken;
}

export async function request(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
  accept = "application/json",
) {
  if (method !== "GET" && !csrfToken) await refreshCsrf();
  const response = await fetch(`/api/${path}`, {
    method,
    signal,
    headers: {
      Accept: accept,
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(
      typeof data?.detail === "string"
        ? data.detail
        : Array.isArray(data)
          ? data.join(" ")
          : "درخواست انجام نشد. ورودی و دسترسی خود را بررسی کنید.",
    );
  }
  return response;
}

export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await request(path, method, body, signal);
  return response.status === 204 ? (undefined as T) : response.json();
}
