import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { JSDOM } from "jsdom";

test("widget initializes, resumes a conversation, sends text, and renders answers as text", async () => {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    url: "https://customer.example/",
    runScripts: "outside-only",
  });
  const calls = [];
  dom.window.fetch = async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith("/widget/init/")) {
      return {
        ok: true,
        status: 201,
        json: async () => ({
          conversation_id: "conversation-123",
          assistant_name: "Docs helper",
          welcome_message: "Welcome",
          color: "#aabbcc",
          messages: [],
        }),
      };
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({ answer: "<img src=x onerror=alert(1)>" }),
    };
  };
  dom.window.eval(readFileSync(new URL("../../widget/widget.js", import.meta.url), "utf8"));
  const widget = dom.window.document.createElement("personal-ai-widget");
  widget.setAttribute("assistant-id", "public-id");
  widget.setAttribute("api-base", "https://api.example");
  dom.window.document.body.append(widget);

  widget.shadowRoot.querySelector(".trigger").click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(widget.shadowRoot.querySelector(".title").textContent, "Docs helper");
  assert.equal(widget.shadowRoot.querySelector(".messages").textContent, "Welcome");
  assert.equal(dom.window.localStorage.getItem("personal-ai-widget:public-id"), "conversation-123");

  const input = widget.shadowRoot.querySelector("textarea");
  input.value = "How do I begin?";
  widget.shadowRoot.querySelector("form").dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(calls.length, 2);
  assert.equal(JSON.parse(calls[1].options.body).conversation_id, "conversation-123");
  assert.equal(widget.shadowRoot.querySelector(".messages img"), null);
  assert.match(widget.shadowRoot.querySelector(".messages").textContent, /<img src=x onerror=alert\(1\)>/);
  dom.window.close();
});
