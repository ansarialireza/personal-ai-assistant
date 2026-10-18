"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";

type ThemeMode = "system" | "light" | "dark" | "colorful";

const THEME_STORAGE_KEY = "pai_theme";
const themeOptions: { value: ThemeMode; label: string; icon: string }[] = [
  { value: "system", label: "System", icon: "◐" },
  { value: "light", label: "Light", icon: "☼" },
  { value: "dark", label: "Dark", icon: "◑" },
  { value: "colorful", label: "Colorful", icon: "✦" },
];

function isThemeMode(value: string | null): value is ThemeMode {
  return value === "system" || value === "light" || value === "dark" || value === "colorful";
}

export default function ThemePicker() {
  const [mode, setMode] = useState<ThemeMode>("system");
  const [systemPrefersDark, setSystemPrefersDark] = useState(false);
  const [ready, setReady] = useState(false);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const optionRefs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    const preference = window.matchMedia("(prefers-color-scheme: dark)");
    const updateSystemPreference = () => setSystemPrefersDark(preference.matches);
    updateSystemPreference();
    preference.addEventListener("change", updateSystemPreference);

    const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (isThemeMode(saved)) setMode(saved);
    setReady(true);

    return () => preference.removeEventListener("change", updateSystemPreference);
  }, []);

  useEffect(() => {
    if (!ready) return;
    const resolved = mode === "system" ? (systemPrefersDark ? "dark" : "light") : mode;
    document.documentElement.dataset.theme = resolved;
    document.documentElement.dataset.themeMode = mode;
  }, [mode, ready, systemPrefersDark]);

  useEffect(() => {
    if (!open) return;
    const selectedIndex = themeOptions.findIndex((option) => option.value === mode);
    optionRefs.current[selectedIndex]?.focus();

    function dismiss(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function dismissOnEscape(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }

    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", dismissOnEscape);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", dismissOnEscape);
    };
  }, [mode, open]);

  function chooseTheme(value: ThemeMode) {
    window.localStorage.setItem(THEME_STORAGE_KEY, value);
    setMode(value);
    setOpen(false);
    triggerRef.current?.focus();
  }

  function moveFocus(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let nextIndex: number | undefined;
    if (event.key === "ArrowDown") nextIndex = (index + 1) % themeOptions.length;
    if (event.key === "ArrowUp") nextIndex = (index + themeOptions.length - 1) % themeOptions.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = themeOptions.length - 1;
    if (nextIndex === undefined) return;
    event.preventDefault();
    optionRefs.current[nextIndex]?.focus();
  }

  const selected = themeOptions.find((option) => option.value === mode) ?? themeOptions[0];
  const resolvedIcon = mode === "system"
    ? (systemPrefersDark ? "◑" : "☼")
    : selected.icon;

  return (
    <div className="theme-picker" ref={rootRef}>
      <button
        aria-label={`Color theme: ${selected.label}`}
        aria-haspopup="menu"
        aria-expanded={open}
        className="theme-trigger"
        onClick={() => setOpen((value) => !value)}
        ref={triggerRef}
        title={`Color theme: ${selected.label}`}
        type="button"
      >
        <span aria-hidden="true">{resolvedIcon}</span>
      </button>
      {open && (
        <div aria-label="Color theme" className="theme-menu" role="menu">
          {themeOptions.map((option, index) => (
            <button
              aria-checked={mode === option.value}
              className="theme-option"
              key={option.value}
              onClick={() => chooseTheme(option.value)}
              onKeyDown={(event) => moveFocus(event, index)}
              ref={(element) => { optionRefs.current[index] = element; }}
              role="menuitemradio"
              type="button"
            >
              <span aria-hidden="true" className="theme-option-icon">{option.icon}</span>
              <span>{option.label}</span>
              {mode === option.value && <span aria-hidden="true" className="theme-check">✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
