import { useEffect, useState } from "react";
import { MediaActionIcon } from "./packages/MediaActionIcon";

type Theme = "light" | "dark";
const systemQuery = "(prefers-color-scheme: dark)";

function storedTheme(): Theme | null {
  try {
    const value = localStorage.getItem("dojo-theme");
    return value === "light" || value === "dark" ? value : null;
  } catch { return null; }
}

export function initializeTheme() {
  document.documentElement.dataset.theme = storedTheme() ?? (window.matchMedia?.(systemQuery).matches ? "dark" : "light");
}

export function ThemeToggle() {
  const [preference, setPreference] = useState(storedTheme);
  const [systemDark, setSystemDark] = useState(() => window.matchMedia?.(systemQuery).matches ?? false);
  const theme = preference ?? (systemDark ? "dark" : "light");
  useEffect(() => {
    const query = window.matchMedia?.(systemQuery);
    const change = () => setSystemDark(query?.matches ?? false);
    query?.addEventListener("change", change);
    return () => query?.removeEventListener("change", change);
  }, []);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  return <button type="button" className="theme-toggle" onClick={() => {
    const next = theme === "dark" ? "light" : "dark";
    setPreference(next);
    try { localStorage.setItem("dojo-theme", next); } catch { /* Appearance still works without browser storage. */ }
  }}><MediaActionIcon action={theme === "dark" ? "sun" : "moon"} />{theme === "dark" ? "Açık Mod" : "Koyu Mod"}</button>;
}
