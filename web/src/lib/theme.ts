// Theme: "dark" | "light" | "system". Stored per browser; the html element
// carries data-theme so tokens.css can swap the palette. index.html applies the
// stored choice before React loads, so there is no flash.
import { useCallback, useEffect, useState } from "react";

export type Theme = "dark" | "light" | "system";
const KEY = "theme";

export function readTheme(): Theme {
  try { const v = localStorage.getItem(KEY); if (v === "dark" || v === "light") return v; } catch { /* private mode */ }
  return "system";
}

export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", theme);
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(readTheme);
  useEffect(() => { applyTheme(theme); }, [theme]);
  const setTheme = useCallback((t: Theme) => {
    try { if (t === "system") localStorage.removeItem(KEY); else localStorage.setItem(KEY, t); } catch { /* ignore */ }
    setThemeState(t);
  }, []);
  return [theme, setTheme];
}
