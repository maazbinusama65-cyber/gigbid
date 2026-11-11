import { useEffect, useState } from "react";

type Theme = "system" | "light" | "dark";
const KEY = "gigbid.theme";

function read(): Theme {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

export function initTheme(): void {
  applyTheme(read());
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(read);
  useEffect(() => {
    applyTheme(theme);
    try {
      if (theme === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);
  const next: Theme = theme === "system" ? "dark" : theme === "dark" ? "light" : "system";
  return (
    <button className="btn sm" onClick={() => setTheme(next)} aria-label={`Theme: ${theme}. Switch to ${next}.`}>
      Theme: {theme}
    </button>
  );
}
