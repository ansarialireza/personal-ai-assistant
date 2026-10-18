import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { JSDOM } from "jsdom";

const themeInitializer = readFileSync(new URL("../public/theme-init.js", import.meta.url), "utf8");

function createThemeDocument(preference, prefersDark) {
  const dom = new JSDOM("<!doctype html><html><head></head><body></body></html>", {
    url: "http://localhost/",
    runScripts: "outside-only",
  });
  dom.window.localStorage.setItem("pai_theme", preference);
  dom.window.matchMedia = () => ({ matches: prefersDark });
  dom.window.eval(themeInitializer);
  return dom;
}

test("System mode resolves the browser color scheme before rendering", () => {
  const dark = createThemeDocument("system", true);
  assert.equal(dark.window.document.documentElement.dataset.theme, "dark");
  assert.equal(dark.window.document.documentElement.dataset.themeMode, "system");
  dark.window.close();

  const light = createThemeDocument("system", false);
  assert.equal(light.window.document.documentElement.dataset.theme, "light");
  assert.equal(light.window.document.documentElement.dataset.themeMode, "system");
  light.window.close();
});

test("a saved manual theme takes precedence over the system color scheme", () => {
  for (const theme of ["light", "dark", "colorful"]) {
    const dom = createThemeDocument(theme, theme !== "dark");
    assert.equal(dom.window.document.documentElement.dataset.theme, theme);
    assert.equal(dom.window.document.documentElement.dataset.themeMode, theme);
    dom.window.close();
  }
});
