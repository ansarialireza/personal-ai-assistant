(() => {
  const elementName = "personal-ai-widget";
  if (customElements.get(elementName)) return;

  class PersonalAiWidget extends HTMLElement {
    constructor() {
      super();
      this.root = this.attachShadow({ mode: "open" });
      this.conversationId = "";
      this.ready = false;
      this.busy = false;
      this.messages = null;
      this.render();
    }

    connectedCallback() {
      const trigger = this.root.querySelector(".trigger");
      const close = this.root.querySelector(".close");
      const form = this.root.querySelector("form");
      trigger.addEventListener("click", () => this.toggle());
      close.addEventListener("click", () => this.toggle(false));
      form.addEventListener("submit", (event) => this.submit(event));
      this.root.querySelector("textarea").addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          form.requestSubmit();
        }
      });
    }

    get assistantId() {
      return this.getAttribute("assistant-id") || "";
    }

    get apiBase() {
      return (this.getAttribute("api-base") || "").replace(/\/$/, "");
    }

    get storageKey() {
      return `personal-ai-widget:${this.assistantId}`;
    }

    render() {
      this.root.innerHTML = `
        <style>
          :host { all: initial; --pai-accent: #ccff00; color: #f2f4ef; font: 14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }
          * { box-sizing: border-box; }
          .trigger { position: fixed; right: 22px; bottom: 22px; z-index: 2147483000; width: 58px; height: 58px; border: 0; border-radius: 50%; background: var(--pai-accent); color: #11150d; box-shadow: 0 7px 28px #0005; cursor: pointer; font-size: 22px; }
          .panel { position: fixed; right: 22px; bottom: 92px; z-index: 2147483000; width: min(370px,calc(100vw - 28px)); height: min(540px,calc(100vh - 120px)); display: none; flex-direction: column; overflow: hidden; background: #111411; border: 1px solid #303731; border-radius: 14px; box-shadow: 0 16px 60px #0008; }
          .panel.open { display: flex; }
          .head { flex: 0 0 auto; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 16px; border-bottom: 1px solid #293029; background: #171b17; }
          .identity { min-width: 0; display: flex; align-items: center; gap: 10px; }
          .badge { flex: 0 0 32px; width: 32px; height: 32px; display: grid; place-items: center; border-radius: 9px; background: var(--pai-accent); color: #12150e; font-weight: 800; }
          .names { display: grid; min-width: 0; }
          .names strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
          .names small { color: #9ba49b; font-size: 10px; }
          .close { border: 0; background: transparent; color: #c6cec5; padding: 4px 7px; cursor: pointer; font-size: 20px; }
          .messages { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; gap: 11px; overflow-y: auto; padding: 15px 12px; }
          .bubble { max-width: 86%; align-self: flex-start; padding: 9px 11px; border-radius: 10px; background: #222822; color: #eef1ec; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; }
          .bubble.user { align-self: flex-end; background: #27331c; }
          .bubble.error { color: #ffb8af; background: #2a1b18; }
          .loading { flex: 0 0 auto; color: #9ca69c; padding: 0 14px 8px; font-size: 11px; }
          form { flex: 0 0 auto; display: flex; align-items: flex-end; gap: 8px; padding: 10px; border-top: 1px solid #293029; }
          textarea { flex: 1; min-width: 0; resize: none; max-height: 100px; border: 1px solid #303931; outline: none; border-radius: 8px; color: #f2f4ef; background: #0d100e; padding: 9px; font: inherit; font-size: 12px; }
          textarea:focus { border-color: #78884f; }
          .send { border: 0; border-radius: 8px; padding: 10px 12px; background: var(--pai-accent); color: #15180e; cursor: pointer; font-weight: 700; }
          .send:disabled { opacity: .55; cursor: wait; }
          .foot { flex: 0 0 auto; padding: 0 10px 8px; color: #788178; font-size: 9px; text-align: center; }
          @media (max-width: 480px) { .trigger { right: 14px; bottom: 14px; } .panel { right: 8px; bottom: 82px; height: min(560px,calc(100vh - 100px)); } }
        </style>
        <button class="trigger" type="button" aria-label="Open assistant chat">✳</button>
        <section class="panel" role="dialog" aria-label="Assistant chat" aria-modal="false">
          <header class="head"><div class="identity"><span class="badge">✳</span><span class="names"><strong class="title">Assistant</strong><small>Ask a question</small></span></div><button class="close" type="button" aria-label="Close chat">×</button></header>
          <div class="messages" aria-live="polite"></div><div class="loading" aria-live="polite"></div>
          <form><textarea aria-label="Your message" placeholder="Write a message…" rows="2" maxlength="12000"></textarea><button class="send" type="submit">Send</button></form>
          <div class="foot">AI can make mistakes. Check important details.</div>
        </section>`;
    }

    async toggle(force) {
      const panel = this.root.querySelector(".panel");
      const open = typeof force === "boolean" ? force : !panel.classList.contains("open");
      panel.classList.toggle("open", open);
      this.root.querySelector(".trigger").setAttribute("aria-expanded", String(open));
      if (open && !this.ready) await this.initialize();
      if (open) this.root.querySelector("textarea").focus();
    }

    async initialize() {
      const messageList = this.root.querySelector(".messages");
      if (!this.assistantId || !this.apiBase) {
        this.addMessage("Widget setup is incomplete. Contact the website owner.", "error");
        return;
      }
      this.setLoading("Connecting…");
      try {
        this.conversationId = localStorage.getItem(this.storageKey) || "";
        const response = await fetch(`${this.apiBase}/api/v1/widget/init/`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            assistant_id: this.assistantId,
            ...(this.conversationId ? { conversation_id: this.conversationId } : {}),
          }),
        });
        if (!response.ok) throw new Error(`Unable to connect (HTTP ${response.status}).`);
        const result = await response.json();
        this.conversationId = result.conversation_id;
        localStorage.setItem(this.storageKey, this.conversationId);
        this.style.setProperty("--pai-accent", result.color || "#ccff00");
        this.root.querySelector(".title").textContent = result.assistant_name || "Assistant";
        if (Array.isArray(result.messages) && result.messages.length) {
          result.messages.forEach((message) => this.addMessage(message.content, message.role === "user" ? "user" : ""));
        } else {
          this.addMessage(result.welcome_message || "Hi! How can I help?");
        }
        this.ready = true;
      } catch (error) {
        this.addMessage(error instanceof Error ? error.message : "Could not connect to the assistant.", "error");
      } finally {
        this.setLoading("");
        messageList.scrollTop = messageList.scrollHeight;
      }
    }

    async submit(event) {
      event.preventDefault();
      const input = this.root.querySelector("textarea");
      const question = input.value.trim();
      if (!question || this.busy) return;
      if (!this.ready) await this.initialize();
      if (!this.ready) return;
      input.value = "";
      this.addMessage(question, "user");
      this.busy = true;
      this.root.querySelector(".send").disabled = true;
      this.setLoading("Thinking…");
      try {
        const response = await fetch(`${this.apiBase}/api/v1/widget/messages/`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            assistant_id: this.assistantId,
            conversation_id: this.conversationId,
            question,
          }),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || `Message failed (HTTP ${response.status}).`);
        this.addMessage(result.answer || "The assistant returned an empty response.");
      } catch (error) {
        this.addMessage(error instanceof Error ? error.message : "Message delivery failed. Please try again.", "error");
      } finally {
        this.busy = false;
        this.root.querySelector(".send").disabled = false;
        this.setLoading("");
        this.root.querySelector(".messages").scrollTop = this.root.querySelector(".messages").scrollHeight;
      }
    }

    addMessage(text, kind = "") {
      const bubble = document.createElement("div");
      bubble.className = `bubble ${kind}`.trim();
      bubble.textContent = String(text);
      this.root.querySelector(".messages").append(bubble);
    }

    setLoading(text) {
      this.root.querySelector(".loading").textContent = text;
    }
  }

  customElements.define(elementName, PersonalAiWidget);
})();
