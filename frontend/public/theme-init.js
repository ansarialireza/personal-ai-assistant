(() => {
  try {
    const saved = localStorage.getItem("pai_theme");
    const mode = ["system", "light", "dark", "colorful"].includes(saved) ? saved : "system";
    const prefersDark = matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = mode === "system"
      ? (prefersDark ? "dark" : "light")
      : mode;
    document.documentElement.dataset.themeMode = mode;
  } catch {
    document.documentElement.dataset.theme = "dark";
    document.documentElement.dataset.themeMode = "system";
  }
})();
