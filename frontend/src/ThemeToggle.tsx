import { Monitor, Sun, Moon } from "lucide-react";
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
      ?.setAttribute(
        "content",
        getComputedStyle(document.documentElement)
          .getPropertyValue("--page")
          .trim(),
      );
  }, [theme]);

  function select(next: Preference) {
    setChoice(next);
    try {
      localStorage.setItem(storageKey, next);
    } catch {
      /* Current session still works. */
    }
  }

  return {
    theme,
    choice,
    select,
    toggle: () => select(theme === "dark" ? "light" : "dark"),
  };
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
      {theme === "dark" ? <Sun /> : <Moon />}
      <span>{theme === "dark" ? "حالت روشن" : "حالت تیره"}</span>
    </button>
  );
}

export function ThemeSettings({
  choice,
  select,
}: {
  choice: Preference;
  select: (v: Preference) => void;
}) {
  return (
    <label className="theme-setting">
      <Monitor />
      <span>حالت نمایش</span>
      <select
        value={choice}
        onChange={(e) => select(preference(e.target.value))}
      >
        <option value="system">مطابق سیستم</option>
        <option value="light">روشن</option>
        <option value="dark">تیره</option>
      </select>
    </label>
  );
}
