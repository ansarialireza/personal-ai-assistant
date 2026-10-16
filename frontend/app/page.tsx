"use client";

import { type FormEvent, useCallback, useEffect, useState } from "react";
import { api, clearTokens, hasTokens, json, saveTokens } from "@/lib/api";

type Assistant = {
  id: string; public_id: string; name: string; description: string; instructions: string;
  language: string; tone: string; welcome_message: string; fallback_response: string;
  is_active: boolean; widget_enabled: boolean; widget_color: string;
  retrieval_top_k: number; similarity_threshold: number; created_at: string; updated_at: string;
};
type Source = { id: string; kind: string; title: string; url: string; status: string; error_message: string; created_at: string };
type CrawlJob = { id: string; start_url: string; mode: string; status: string; error_message: string; discovered_pages: { url: string; title: string; selected: boolean; status?: string; error?: string }[] };
type Conversation = { id: string; assistant_id: string; channel: string; updated_at: string };
type Message = { id: number; role: "user" | "assistant"; content: string; created_at: string };
type Screen = "home" | "assistants" | "assistant" | "conversations" | "settings";
type Tab = "settings" | "knowledge" | "playground" | "history" | "channels" | "widget";
type AuthTokens = { access: string; refresh: string; user: { email: string } };

const blankAssistant = {
  name: "", description: "", instructions: "", language: "English", tone: "Helpful",
  welcome_message: "Hi! How can I help?", fallback_response: "I don't have enough information to answer that.",
  is_active: true, widget_enabled: false, widget_color: "#CCFF00",
  retrieval_top_k: 5, similarity_threshold: 0,
};

export default function Home() {
  const [authenticated, setAuthenticated] = useState(false);
  const [authReady, setAuthReady] = useState(false);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [me, setMe] = useState("");
  const [screen, setScreen] = useState<Screen>("home");
  const [tab, setTab] = useState<Tab>("settings");
  const [assistants, setAssistants] = useState<Assistant[]>([]);
  const [selected, setSelected] = useState<Assistant | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [jobs, setJobs] = useState<CrawlJob[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState("");
  const [text, setText] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [crawlUrl, setCrawlUrl] = useState("");
  const [crawlMode, setCrawlMode] = useState<"manual" | "automatic">("manual");
  const [telegramToken, setTelegramToken] = useState("");
  const [telegram, setTelegram] = useState<{ connected: boolean; bot_username: string; webhook_configured: boolean; last_error: string } | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState(blankAssistant);

  const loadAssistants = useCallback(async () => {
    const [result, chatList] = await Promise.all([
      api<Assistant[]>("/assistants/"),
      api<Conversation[]>("/conversations/"),
    ]);
    setAssistants(result);
    setConversations(chatList);
  }, []);

  const loadAssistantData = useCallback(async (assistant: Assistant) => {
    const [sourceList, crawlList, telegramState] = await Promise.all([
      api<Source[]>(`/assistants/${assistant.id}/sources/`),
      api<CrawlJob[]>(`/assistants/${assistant.id}/crawls/`),
      api<typeof telegram>(`/assistants/${assistant.id}/telegram/`),
    ]);
    setSources(sourceList);
    setJobs(crawlList);
    setTelegram(telegramState);
  }, []);

  useEffect(() => {
    if (!hasTokens()) {
      queueMicrotask(() => setAuthReady(true));
      return;
    }
    api<{ email: string }>("/auth/me/")
      .then((user) => { setMe(user.email); setAuthenticated(true); return loadAssistants(); })
      .catch(() => clearTokens())
      .finally(() => setAuthReady(true));
  }, [loadAssistants]);

  useEffect(() => {
    if (!selected) return;
    const timer = window.setTimeout(() => {
      loadAssistantData(selected).catch((reason: Error) => setError(reason.message));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [selected, loadAssistantData]);

  useEffect(() => {
    const jobsActive = jobs.some((job) => ["pending", "discovering", "processing"].includes(job.status));
    const sourcesActive = sources.some((source) => ["pending", "processing"].includes(source.status));
    if (!selected || (!jobsActive && !sourcesActive)) return;
    const timer = window.setInterval(() => {
      api<CrawlJob[]>(`/assistants/${selected.id}/crawls/`)
        .then(setJobs)
        .catch((reason: Error) => setError(reason.message));
      api<Source[]>(`/assistants/${selected.id}/sources/`).then(setSources).catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [jobs, selected, sources]);

  useEffect(() => {
    if (screen !== "conversations" && !(screen === "assistant" && tab === "history")) return;
    api<Conversation[]>("/conversations/").then(setConversations).catch((reason: Error) => setError(reason.message));
  }, [screen, tab]);

  async function authenticate(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const tokens = await api<AuthTokens>(`/auth/${authMode === "login" ? "token" : "register"}/`, {
        method: "POST", body: json(authMode === "login" ? { username: email, password } : { email, password }),
      });
      saveTokens(tokens.access, tokens.refresh);
      const user = await api<{ email: string }>("/auth/me/");
      setMe(user.email); setAuthenticated(true); await loadAssistants();
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }

  async function createAssistant(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const created = await api<Assistant>("/assistants/", { method: "POST", body: json(draft) });
      setAssistants((items) => [created, ...items]); setSelected(created); setCreating(false);
      setTab("settings"); setScreen("assistant"); setNotice("Assistant created and connected to the configured AI and RAG services.");
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }

  async function saveAssistant(event: FormEvent) {
    event.preventDefault(); if (!selected) return;
    setBusy(true); setError("");
    try {
      const updated = await api<Assistant>(`/assistants/${selected.id}/`, { method: "PATCH", body: json(selected) });
      setSelected(updated); setAssistants((items) => items.map((item) => item.id === updated.id ? updated : item));
      setNotice("Changes saved.");
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }

  async function deleteAssistant(assistant: Assistant) {
    if (!window.confirm(`Delete "${assistant.name}" and its knowledge base? This cannot be undone.`)) return;
    setBusy(true); setError("");
    try {
      await api(`/assistants/${assistant.id}/`, { method: "DELETE" });
      setAssistants((items) => items.filter((item) => item.id !== assistant.id));
      if (selected?.id === assistant.id) { setSelected(null); setScreen("assistants"); }
      setNotice("Assistant deleted.");
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }

  async function addTextSource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected) return;
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setBusy(true); setError("");
    try {
      await api(`/assistants/${selected.id}/sources/`, {
        method: "POST", body: json({ kind: "text", title: form.get("title"), content: form.get("content") }),
      });
      formElement.reset(); await loadAssistantData(selected); setNotice("Source queued for indexing.");
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }

  async function uploadFile(event: FormEvent<HTMLInputElement>) {
    if (!selected || !event.currentTarget.files?.[0]) return;
    const form = new FormData(); form.set("file", event.currentTarget.files[0]);
    setBusy(true); setError("");
    try {
      await api(`/assistants/${selected.id}/sources/`, { method: "POST", body: form });
      event.currentTarget.value = ""; await loadAssistantData(selected); setNotice("File queued for indexing.");
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }

  async function startCrawl(event: FormEvent) {
    event.preventDefault(); if (!selected) return;
    setBusy(true); setError("");
    try {
      const job = await api<CrawlJob>(`/assistants/${selected.id}/crawls/`, {
        method: "POST", body: json({ url: crawlUrl, mode: crawlMode }),
      });
      setJobs((items) => [job, ...items]); setCrawlUrl(""); setNotice("Website discovery queued.");
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }

  async function processPages(job: CrawlJob) {
    if (!selected) return;
    const urls = job.discovered_pages.filter((page) => page.selected).map((page) => page.url);
    setBusy(true); setError("");
    try {
      const updated = await api<CrawlJob>(`/assistants/${selected.id}/crawls/${job.id}/process/`, {
        method: "POST", body: json({ selected_urls: urls }),
      });
      setJobs((items) => items.map((item) => item.id === job.id ? updated : item));
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }

  async function sourceAction(source: Source, action: "retry" | "delete") {
    if (!selected) return;
    setError("");
    try {
      await api(`/assistants/${selected.id}/sources/${source.id}/${action === "retry" ? "retry/" : ""}`, {
        method: action === "retry" ? "POST" : "DELETE",
      });
      await loadAssistantData(selected);
    } catch (reason) { setError((reason as Error).message); }
  }

  async function sendMessage(event: FormEvent) {
    event.preventDefault(); if (!text.trim() || chatBusy) return;
    const question = text.trim(); setText(""); setChatBusy(true); setError("");
    setMessages((items) => [...items, { id: Date.now(), role: "user", content: question, created_at: new Date().toISOString() }]);
    try {
      let id = conversationId;
      if (!id) {
        const conversation = await api<Conversation>("/conversations/", {
          method: "POST", body: json({ assistant_id: selected?.id }),
        });
        id = conversation.id; setConversationId(id);
      }
      const response = await api<{ answer: string }>(`/conversations/${id}/messages/`, {
        method: "POST", body: json({ question }),
      });
      setMessages((items) => [...items, { id: Date.now() + 1, role: "assistant", content: response.answer, created_at: new Date().toISOString() }]);
    } catch (reason) { setError((reason as Error).message); }
    finally { setChatBusy(false); }
  }

  async function openConversation(conversation: Conversation) {
    setConversationId(conversation.id); setSelected(assistants.find((item) => item.id === conversation.assistant_id) || null);
    try {
      const history = await api<Message[]>(`/conversations/${conversation.id}/messages/`);
      setMessages(history); setScreen("assistant"); setTab("playground");
    } catch (reason) { setError((reason as Error).message); }
  }

  async function connectTelegram(event: FormEvent) {
    event.preventDefault(); if (!selected) return;
    setBusy(true); setError("");
    try {
      const result = await api<typeof telegram>(`/assistants/${selected.id}/telegram/`, {
        method: "POST", body: json({ bot_token: telegramToken }),
      });
      setTelegram(result); setTelegramToken(""); setNotice("Telegram bot token saved securely.");
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }

  function logout() {
    clearTokens(); setAuthenticated(false); setAssistants([]); setSelected(null); setScreen("home");
  }

  if (!authReady) return <div className="boot"><span className="mark">P</span><p>Loading workspace…</p></div>;
  if (!authenticated) return (
    <main className="auth-shell">
      <div className="auth-art">
        <div className="brand"><span className="mark">P</span><span>PERSONAL AI</span></div>
        <div><p className="eyebrow">YOUR KNOWLEDGE, IN CONVERSATION</p><h1>Build an assistant<br />that knows your work.</h1><p className="muted">Grounded answers. Your sources. Your channels.</p></div>
        <span className="art-dot" />
      </div>
      <form className="auth-card" onSubmit={authenticate}>
        <p className="eyebrow">{authMode === "login" ? "WELCOME BACK" : "GET STARTED"}</p>
        <h2>{authMode === "login" ? "Sign in" : "Create your account"}</h2>
        <label>Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" required /></label>
        <label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={10} autoComplete={authMode === "login" ? "current-password" : "new-password"} required /></label>
        {error && <div className="alert">{error}</div>}
        <button type="submit" className="button primary wide" disabled={busy}>{busy ? "Please wait…" : authMode === "login" ? "Sign in" : "Create account"}</button>
        <p className="auth-switch">{authMode === "login" ? "New here?" : "Already have an account?"} <button type="button" className="text-button" onClick={() => { setAuthMode(authMode === "login" ? "register" : "login"); setError(""); }}>{authMode === "login" ? "Create an account" : "Sign in"}</button></p>
      </form>
    </main>
  );

  const nav = (target: Screen, label: string, icon: string) => <button type="button" className={`nav-link ${screen === target ? "active" : ""}`} onClick={() => { setScreen(target); setCreating(false); setError(""); }}><span className="nav-icon">{icon}</span>{label}</button>;
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="mark">P</span><span>PERSONAL AI</span></div>
        <p className="nav-caption">WORKSPACE</p>
        {nav("home", "Overview", "⌂")}
        {nav("assistants", "Assistants", "✳")}
        {nav("conversations", "Conversations", "▤")}
        <div className="sidebar-bottom">
          <div className="user-card"><span className="avatar">{me.slice(0, 1).toUpperCase()}</span><span className="user-email">{me}</span><button type="button" className="more" title="Account settings" onClick={() => setScreen("settings")}>···</button></div>
          <button type="button" className="nav-link" onClick={logout}><span className="nav-icon">↗</span>Sign out</button>
        </div>
      </aside>
      <main className="main">
        <header className="topbar"><div className="breadcrumbs"><span>Workspace</span>{selected && screen === "assistant" && <><span className="crumb-sep">/</span><button type="button" onClick={() => setScreen("assistants")}>Assistants</button><span className="crumb-sep">/</span><strong>{selected.name}</strong></>}</div><span className="status-pill"><i /> Services configured by administrator</span></header>
        <div className="content">
          {error && <div className="alert inline-alert">{error}<button type="button" onClick={() => setError("")}>×</button></div>}
          {notice && <div className="notice inline-alert">{notice}<button type="button" onClick={() => setNotice("")}>×</button></div>}
          {screen === "home" && <section>
            <div className="page-heading"><div><p className="eyebrow">YOUR WORKSPACE</p><h1>Good to see you.</h1><p className="muted">Manage your assistants and the knowledge behind them.</p></div><button type="button" className="button primary" onClick={() => { setDraft(blankAssistant); setCreating(true); setScreen("assistants"); }}>＋ New assistant</button></div>
            <div className="stats-grid"><div className="stat-card"><span>Assistants</span><strong>{assistants.length}</strong><small>In your workspace</small></div><div className="stat-card"><span>Knowledge sources</span><strong>{assistants.reduce((sum, item) => sum + (item.id === selected?.id ? sources.length : 0), 0)}</strong><small>{selected ? `For ${selected.name}` : "Choose an assistant to view sources"}</small></div><div className="stat-card"><span>Conversations</span><strong>{conversations.length || "—"}</strong><small>Latest sessions</small></div></div>
            <div className="section-title"><div><h2>Your assistants</h2><p className="muted">An assistant is grounded in a private knowledge base.</p></div><button type="button" className="text-button" onClick={() => setScreen("assistants")}>View all →</button></div>
            <AssistantGrid assistants={assistants} open={(item) => { setSelected(item); setScreen("assistant"); setTab("settings"); }} />
          </section>}

          {screen === "assistants" && <section>
            <div className="page-heading"><div><p className="eyebrow">WORKSPACE</p><h1>Assistants</h1><p className="muted">Create, configure, and publish your AI assistants.</p></div><button type="button" className="button primary" onClick={() => { setDraft(blankAssistant); setCreating(true); }}>＋ New assistant</button></div>
            {creating ? <form className="panel form-panel" onSubmit={createAssistant}><div className="section-title"><div><h2>Create assistant</h2><p className="muted">A dedicated RAG knowledge base and AI assistant are provisioned for you.</p></div><button type="button" className="icon-button" onClick={() => setCreating(false)}>×</button></div>
              <div className="form-grid"><Field label="Name" value={draft.name} onChange={(value) => setDraft({ ...draft, name: value })} required /><Field label="Description" value={draft.description} onChange={(value) => setDraft({ ...draft, description: value })} /><Field label="Language" value={draft.language} onChange={(value) => setDraft({ ...draft, language: value })} /><label className="field">Tone<select value={draft.tone} onChange={(event) => setDraft({ ...draft, tone: event.target.value })}><option>Helpful</option><option>Professional</option><option>Friendly</option><option>Concise</option></select></label></div>
              <label className="field">System instructions<textarea value={draft.instructions} onChange={(event) => setDraft({ ...draft, instructions: event.target.value })} rows={4} placeholder="Describe the assistant's role and boundaries." /></label>
              <div className="form-actions"><button type="submit" className="button primary" disabled={busy}>{busy ? "Creating…" : "Create assistant"}</button></div>
            </form> : <AssistantGrid assistants={assistants} open={(item) => { setSelected(item); setScreen("assistant"); setTab("settings"); }} />}
          </section>}

          {screen === "assistant" && selected && <section>
            <div className="assistant-heading"><div className="assistant-mark">✳</div><div className="grow"><div className="title-line"><h1>{selected.name}</h1><span className={`state-chip ${selected.is_active ? "on" : "off"}`}>{selected.is_active ? "Active" : "Paused"}</span></div><p className="muted">{selected.description || "Configure knowledge, test responses, and publish this assistant."}</p></div><button type="button" className="button danger-ghost" onClick={() => deleteAssistant(selected)}>Delete</button></div>
            <div className="tabs">{(["settings", "knowledge", "playground", "history", "channels", "widget"] as Tab[]).map((item) => <button type="button" key={item} className={tab === item ? "tab active" : "tab"} onClick={() => { setTab(item); setError(""); }}>{({ settings: "Configuration", knowledge: "Knowledge", playground: "Playground", history: "History", channels: "Channels", widget: "Web widget" })[item]}</button>)}</div>
            {tab === "settings" && <form className="panel form-panel" onSubmit={saveAssistant}>
              <div className="section-title"><div><h2>Assistant configuration</h2><p className="muted">Provider and model choices are managed by the connected AI backend.</p></div></div>
              <div className="form-grid"><Field label="Name" value={selected.name} onChange={(value) => setSelected({ ...selected, name: value })} required /><Field label="Language" value={selected.language} onChange={(value) => setSelected({ ...selected, language: value })} /><Field label="Description" value={selected.description} onChange={(value) => setSelected({ ...selected, description: value })} /><label className="field">Tone<select value={selected.tone} onChange={(event) => setSelected({ ...selected, tone: event.target.value })}><option>Helpful</option><option>Professional</option><option>Friendly</option><option>Concise</option></select></label></div>
              <label className="field">System instructions<textarea value={selected.instructions} onChange={(event) => setSelected({ ...selected, instructions: event.target.value })} rows={5} /></label>
              <label className="field">Welcome message<input value={selected.welcome_message} onChange={(event) => setSelected({ ...selected, welcome_message: event.target.value })} /></label>
              <label className="field">Insufficient-evidence response<input value={selected.fallback_response} onChange={(event) => setSelected({ ...selected, fallback_response: event.target.value })} /></label>
              <label className="field">Retrieval results<input type="number" min="1" max="20" value={selected.retrieval_top_k} onChange={(event) => setSelected({ ...selected, retrieval_top_k: Number(event.target.value) })} /></label>
              <Toggle label="Assistant is active" checked={selected.is_active} onChange={(checked) => setSelected({ ...selected, is_active: checked })} />
              <div className="form-actions"><button type="submit" className="button primary" disabled={busy}>{busy ? "Saving…" : "Save changes"}</button></div>
            </form>}
            {tab === "knowledge" && <div className="stack">
              <div className="panel"><div className="section-title"><div><h2>Add knowledge</h2><p className="muted">Ingestion is processed by the RAG Core worker.</p></div></div>
                <div className="knowledge-grid"><form className="subpanel" onSubmit={addTextSource}><h3>Text</h3><label className="field">Title<input name="title" required maxLength={255} /></label><label className="field">Content<textarea name="content" rows={5} required maxLength={2000000} /></label><button type="submit" className="button secondary" disabled={busy}>Add text source</button></form>
                  <div className="subpanel"><h3>Upload a file</h3><p className="muted">PDF, DOCX, TXT, or Markdown · up to 10 MiB</p><label className="button secondary file-button">Choose file<input type="file" accept=".pdf,.docx,.txt,.md" onChange={uploadFile} /></label></div></div>
              </div>
              <div className="panel"><div className="section-title"><div><h2>Website discovery</h2><p className="muted">Discovery obeys robots.txt and limits requests to public, same-origin web pages.</p></div></div>
                <form className="crawl-form" onSubmit={startCrawl}><label className="field grow">Website URL<input type="url" placeholder="https://example.com" value={crawlUrl} onChange={(event) => setCrawlUrl(event.target.value)} required /></label><label className="field">Mode<select value={crawlMode} onChange={(event) => setCrawlMode(event.target.value as "manual" | "automatic")}><option value="manual">Select pages manually</option><option value="automatic">Automatic (within configured limit)</option></select></label><button type="submit" className="button primary" disabled={busy}>Discover pages</button></form>
                <div className="job-list">{jobs.map((job) => <div className="job" key={job.id}><div className="job-head"><div><strong>{job.start_url}</strong><span className={`state-chip ${job.status === "completed" ? "on" : ""}`}>{job.status}</span></div>{["pending", "discovering", "processing"].includes(job.status) && <button type="button" className="text-button" onClick={() => api(`/assistants/${selected.id}/crawls/${job.id}/cancel/`, { method: "POST" }).then(() => loadAssistantData(selected)).catch((reason: Error) => setError(reason.message))}>Cancel</button>}</div>
                  {job.error_message && <p className="small-error">{job.error_message}</p>}
                  {job.status === "discovered" && <><p className="muted">Select only the pages you want indexed, then confirm.</p><div className="page-picks">{job.discovered_pages.map((page) => <label key={page.url} className="page-pick"><input type="checkbox" checked={page.selected} onChange={(event) => setJobs((items) => items.map((item) => item.id === job.id ? { ...item, discovered_pages: item.discovered_pages.map((candidate) => candidate.url === page.url ? { ...candidate, selected: event.target.checked } : candidate) } : item))} /><span><strong>{page.title || page.url}</strong><small>{page.url}</small></span></label>)}</div><button type="button" className="button secondary" onClick={() => processPages(job)}>Process selected pages</button></>}
                  {job.discovered_pages.some((page) => page.status === "failed") && <p className="small-error">Some discovered pages failed processing. Review the source errors below.</p>}
                </div>)}</div>
              </div>
              <div className="panel"><div className="section-title"><div><h2>Sources</h2><p className="muted">{sources.length} source{sources.length === 1 ? "" : "s"}</p></div></div><SourceList sources={sources} action={sourceAction} /></div>
            </div>}
            {tab === "playground" && <ChatPanel name={selected.name} messages={messages} text={text} busy={chatBusy} setText={setText} send={sendMessage} />}
            {tab === "history" && <div className="panel"><div className="section-title"><div><h2>Conversations</h2><p className="muted">Conversation history belongs to this assistant.</p></div></div><ConversationList conversations={conversations.filter((item) => item.assistant_id === selected.id)} assistants={assistants} open={openConversation} refresh={() => api<Conversation[]>("/conversations/").then(setConversations)} /></div>}
            {tab === "channels" && <div className="panel"><div className="section-title"><div><h2>Telegram</h2><p className="muted">Connect an owner-managed bot token. It is encrypted and never returned.</p></div><span className={`state-chip ${telegram?.connected ? "on" : "off"}`}>{telegram?.connected ? `@${telegram.bot_username}` : "Not connected"}</span></div>
              {telegram?.last_error && <div className="setup-note">{telegram.last_error}</div>}
              <form className="connect-form" onSubmit={connectTelegram}><label className="field grow">Bot token<input type="password" autoComplete="new-password" value={telegramToken} onChange={(event) => setTelegramToken(event.target.value)} placeholder={telegram?.connected ? "Enter a new token to replace" : "Paste token from BotFather"} required /></label><button type="submit" className="button primary" disabled={busy}>{telegram?.connected ? "Replace token" : "Connect bot"}</button></form>
              {telegram?.connected && <button type="button" className="button danger-ghost" onClick={() => api(`/assistants/${selected.id}/telegram/`, { method: "DELETE" }).then(() => loadAssistantData(selected)).catch((reason: Error) => setError(reason.message))}>Disconnect bot</button>}
              <p className="small-note">The server must have a public HTTPS URL configured as <code>TELEGRAM_WEBHOOK_BASE_URL</code> for inbound updates. Without it, the bot token is saved but webhook delivery is not active.</p>
            </div>}
            {tab === "widget" && <div className="panel"><div className="section-title"><div><h2>Web chat widget</h2><p className="muted">An isolated Shadow DOM widget connects to the public product API.</p></div></div>
              <form onSubmit={saveAssistant}>
                <Toggle label="Enable public widget" checked={selected.widget_enabled} onChange={(checked) => setSelected({ ...selected, widget_enabled: checked })} />
                <label className="field color-field">Accent color<input type="color" value={selected.widget_color} onChange={(event) => setSelected({ ...selected, widget_color: event.target.value })} /></label>
                <div className="form-actions"><button type="submit" className="button primary" disabled={busy}>Save widget settings</button></div>
              </form>
              <div className="install-box"><div className="section-title"><div><h3>Installation</h3><p className="muted">Replace the API URL with your deployed backend origin.</p></div></div><pre>{`<script src="https://YOUR-DOMAIN/widget.js" defer></script>\n<personal-ai-widget assistant-id="${selected.public_id}" api-base="https://YOUR-API-DOMAIN"></personal-ai-widget>`}</pre><button type="button" className="button secondary" onClick={() => navigator.clipboard.writeText(`<script src="https://YOUR-DOMAIN/widget.js" defer></script>\n<personal-ai-widget assistant-id="${selected.public_id}" api-base="https://YOUR-API-DOMAIN"></personal-ai-widget>`).then(() => setNotice("Install snippet copied."))}>Copy snippet</button><p className="small-note">Configure CORS_ALLOWED_ORIGINS and WIDGET_ALLOWED_ORIGINS on the server for your public site. The public ID is not an authorization secret.</p></div>
            </div>}
          </section>}

          {screen === "conversations" && <section><div className="page-heading"><div><p className="eyebrow">ACTIVITY</p><h1>Conversations</h1><p className="muted">Recent playground and widget chats from your assistants.</p></div></div><div className="panel"><ConversationList conversations={conversations} assistants={assistants} open={openConversation} refresh={() => api<Conversation[]>("/conversations/").then(setConversations)} /></div></section>}
          {screen === "settings" && <section><div className="page-heading"><div><p className="eyebrow">ACCOUNT</p><h1>Settings</h1><p className="muted">Signed in as {me}.</p></div></div><div className="panel"><h2>Account</h2><p className="muted">Authentication is handled by expiring access and refresh tokens.</p><button type="button" className="button secondary" onClick={logout}>Sign out</button></div></section>}
        </div>
      </main>
    </div>
  );
}

function Field({ label, value, onChange, required = false }: { label: string; value: string; onChange: (value: string) => void; required?: boolean }) {
  return <label className="field">{label}<input value={value} onChange={(event) => onChange(event.target.value)} required={required} maxLength={255} /></label>;
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="toggle-row"><span>{label}</span><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><i /></label>;
}

function AssistantGrid({ assistants, open }: { assistants: Assistant[]; open: (assistant: Assistant) => void }) {
  if (!assistants.length) return <div className="empty-state"><span className="empty-icon">✳</span><h3>No assistants yet</h3><p>Create one and connect your first sources.</p></div>;
  return <div className="assistant-grid">{assistants.map((assistant) => <button type="button" className="assistant-card" key={assistant.id} onClick={() => open(assistant)}><div className="card-top"><span className="assistant-mark small">✳</span><span className={`state-chip ${assistant.is_active ? "on" : "off"}`}>{assistant.is_active ? "Active" : "Paused"}</span></div><h3>{assistant.name}</h3><p>{assistant.description || "Configure this assistant and add knowledge sources."}</p><div className="card-foot"><span>Updated {new Date(assistant.updated_at).toLocaleDateString()}</span><span>Open →</span></div></button>)}</div>;
}

function SourceList({ sources, action }: { sources: Source[]; action: (source: Source, action: "retry" | "delete") => void }) {
  if (!sources.length) return <div className="empty-inline"><p>No sources added. Add a text, file, or website above.</p></div>;
  return <div className="table-list">{sources.map((source) => <div className="source-row" key={source.id}><span className={`source-icon ${source.kind}`}>{source.kind === "website" ? "↗" : source.kind === "file" ? "▤" : "¶"}</span><span className="source-title"><strong>{source.title}</strong><small>{source.url || source.kind}</small>{source.error_message && <em>{source.error_message}</em>}</span><span className={`state-chip ${source.status === "indexed" ? "on" : ""}`}>{source.status}</span>{source.status === "failed" && <button type="button" className="text-button" onClick={() => action(source, "retry")}>Retry</button>}<button type="button" className="icon-button" title="Delete source" onClick={() => action(source, "delete")}>×</button></div>)}</div>;
}

function ChatPanel({ name, messages, text, busy, setText, send }: { name: string; messages: Message[]; text: string; busy: boolean; setText: (value: string) => void; send: (event: FormEvent) => void }) {
  return <div className="chat-layout"><div className="chat-head"><span className="assistant-mark small">✳</span><span><strong>{name}</strong><small>Responses use the configured knowledge base.</small></span></div><div className="chat-messages">{messages.length === 0 && <div className="chat-empty"><span className="assistant-mark">✳</span><h3>Test your assistant</h3><p>Ask a question to see how it responds with your sources.</p></div>}{messages.map((message) => <div className={`message ${message.role}`} key={message.id}><span>{message.role === "assistant" ? name : "You"}</span><p>{message.content}</p></div>)}{busy && <div className="message assistant"><span>{name}</span><p className="typing">Thinking…</p></div>}</div><form className="chat-input" onSubmit={send}><textarea value={text} onChange={(event) => setText(event.target.value)} placeholder="Ask a question…" rows={2} maxLength={12000} /><button type="submit" className="button primary" disabled={busy || !text.trim()}>Send ↑</button></form><p className="chat-footnote">AI responses may be inaccurate. Verify important information.</p></div>;
}

function ConversationList({ conversations, assistants, open, refresh }: { conversations: Conversation[]; assistants: Assistant[]; open: (conversation: Conversation) => void; refresh: () => void }) {
  if (!conversations.length) return <div className="empty-inline"><p>No conversations yet.</p><button type="button" className="text-button" onClick={refresh}>Refresh</button></div>;
  return <div className="table-list">{conversations.map((conversation) => <button type="button" className="conversation-row" key={conversation.id} onClick={() => open(conversation)}><span className="assistant-mark small">✳</span><span className="source-title"><strong>{assistants.find((item) => item.id === conversation.assistant_id)?.name || "Assistant"}</strong><small>{conversation.channel} · {new Date(conversation.updated_at).toLocaleString()}</small></span><span>Open →</span></button>)}</div>;
}
