async function fetchPortal(path: string, init?: RequestInit) {
  try {
    return await fetch(path, init);
  } catch (error) {
    if (init?.signal?.aborted) throw error;
    throw new Error(
      "ارتباط با سامانه برقرار نشد. اتصال شبکه را بررسی کنید و دوباره تلاش کنید.",
    );
  }
}

let csrfToken = "";
export async function refreshCsrf() {
  const response = await fetchPortal("/api/auth/csrf/");
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
  const response = await fetchPortal(`/api/${path}`, {
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
    if (response.status === 401 || response.status === 403)
      throw new Error(
        "دسترسی به این بخش ممکن نیست. وضعیت ورود و دسترسی حساب را بررسی کنید.",
      );
    if (response.status === 504)
      throw new Error("زمان انتظار برای پاسخ سامانه به پایان رسید.");
    if (response.status === 429)
      throw new Error("تعداد درخواست‌ها زیاد است. کمی بعد دوباره تلاش کنید.");
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
