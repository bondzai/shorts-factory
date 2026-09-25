import type { Theme } from "../lib/theme";

const THEMES: { id: Theme; label: string; title: string }[] = [
  { id: "light", label: "Light", title: "Light theme" },
  { id: "dark", label: "Dark", title: "Dark theme" },
  { id: "system", label: "Auto", title: "Follow the device" },
];

export function ThemeSwitch({ theme, setTheme }: { theme: Theme; setTheme: (t: Theme) => void }) {
  return (
    <div className="theme" role="group" aria-label="Theme">
      {THEMES.map((t) => <button key={t.id} type="button" title={t.title} aria-pressed={theme === t.id} onClick={() => setTheme(t.id)}>{t.label}</button>)}
    </div>
  );
}
