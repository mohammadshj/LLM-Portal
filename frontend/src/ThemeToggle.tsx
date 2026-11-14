import { useEffect, useState } from "react";

type Theme = "light" | "dark";
type Preference = Theme | "system";
const storageKey = "portal-theme";
const systemQuery = "(prefers-color-scheme: dark)";
function preference(value: string | null): Preference {
  return value === "light" || value === "dark" ? value : "system";
}
function savedPreference(): Preference {
  try {
    return preference(localStorage.getItem(storageKey));
  } catch {
    return "system";
  }
}

export function useTheme() {
  const [choice, setChoice] = useState<Preference>(savedPreference);
  const [systemDark, setSystemDark] = useState(
    () => matchMedia(systemQuery).matches,
  );
  const theme: Theme =
    choice === "system" ? (systemDark ? "dark" : "light") : choice;

  useEffect(() => {
    const media = matchMedia(systemQuery);
    const onSystemChange = () => setSystemDark(media.matches);
    const onStorageChange = (event: StorageEvent) => {
      if (event.key === storageKey || event.key === null)
        setChoice(preference(event.newValue));
    };
    onSystemChange();
    media.addEventListener("change", onSystemChange);
    window.addEventListener("storage", onStorageChange);
    return () => {
      media.removeEventListener("change", onSystemChange);
      window.removeEventListener("storage", onStorageChange);
    };
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", theme === "dark" ? "#121c18" : "#f8faf9");
  }, [theme]);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setChoice(next);
    try {
      localStorage.setItem(storageKey, next);
    } catch {
      /* Current session still works. */
    }
  }

  return { theme, toggle };
}

export function ThemeToggle({
  theme,
  toggle,
}: {
  theme: Theme;
  toggle: () => void;
}) {
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      aria-label="حالت تیره"
      aria-pressed={theme === "dark"}
      title={theme === "dark" ? "فعال‌کردن حالت روشن" : "فعال‌کردن حالت تیره"}
    >
      <svg
        aria-hidden="true"
        width="18"
        height="18"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {theme === "dark" ? (
          <>
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" />
          </>
        ) : (
          <path d="M20.5 13.3A8.7 8.7 0 0 1 10.7 3.5a8.8 8.8 0 1 0 9.8 9.8Z" />
        )}
      </svg>
      <span>{theme === "dark" ? "حالت روشن" : "حالت تیره"}</span>
    </button>
  );
}
