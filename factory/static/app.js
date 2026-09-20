// The console: a nav of screens named for what you do on them, one header
// with the channel and the actions that start work, and the screens
// themselves under static/screens/. Everything shared is in lib.js and ui.js.

import { createRoot } from "https://esm.sh/react-dom@18.3.1/client";
import { html, useState, useEffect, useCallback, api, send, fmt, statusWord, channelQuery, toast, act } from "./lib.js";
import { Toasts } from "./ui.js";
import { Today } from "./screens/today.js";
import { Queue, Playbooks } from "./screens/queue.js";
import { Clips, ClipDrawer } from "./screens/clips.js";
import { Results } from "./screens/results.js";
import { Activity } from "./screens/activity.js";
import { Settings, AddChannel } from "./screens/settings.js";
import { Docs } from "./screens/docs.js";

const VIEWS = [
  { id: "today", name: "Today", meaning: "decide, then upload" },
  { id: "queue", name: "Queue", meaning: "what agents will do next" },
  { id: "clips", name: "Clips", meaning: "everything ever made" },
  { id: "results", name: "Results", meaning: "how published clips did" },
  { id: "activity", name: "Activity", meaning: "what ran, and what happened" },
  { id: "bin", name: "Bin", meaning: "what you threw away" },
  { id: "settings", name: "Settings", meaning: "this channel and its rules" },
  { id: "docs", name: "Docs", meaning: "how it all works" },
];

/* ---------- app ---------- */

function App() {
  const [channels, setChannels] = useState(null);
  const [channelId, setChannelId] = useState(null);
  const [view, setView] = useState("today");
  const [snap, setSnap] = useState(null);
  const [error, setError] = useState(null);
  const [sound, setSound] = useState(false);
  const [playbooksOpen, setPlaybooks] = useState(false);
  const [openClip, setOpenClip] = useState(null);

  const loadChannels = useCallback(async () => {
    const body = await api("/api/channels");
    setChannels(body.channels);
    setChannelId((current) => {
      if (current && body.channels.some((c) => c.id === current)) return current;
      const first = body.channels.find((c) => c.active) || body.channels[0];
      return first ? first.id : null;
    });
  }, []);

  const refresh = useCallback(async () => {
    if (!channelId) return;
    try {
      setSnap(await api(`/api/state?${channelQuery(channelId)}`));
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, [channelId]);

  useEffect(() => { loadChannels().catch((err) => setError(err.message)); }, [loadChannels]);
  useEffect(() => { refresh(); }, [refresh]);

  // The CLI, cron and an agent over MCP write the same database this page
  // reads, so changes arrive without the page having asked. Poll — quickly
  // while one of our jobs runs, slowly otherwise.
  useEffect(() => {
    const running = snap?.job?.running;
    const id = setInterval(refresh, running ? 1500 : 5000);
    return () => clearInterval(id);
  }, [refresh, snap?.job?.running]);

  const reload = useCallback(async () => { await loadChannels(); await refresh(); }, [loadChannels, refresh]);

  if (channels && !channels.length) {
    return html`<div class="wrap"><main><p class="empty">No channels yet.</p><${AddChannel} onDone=${reload} /></main></div>`;
  }

  const queueCount = snap ? snap.queue.length + snap.approved.length : 0;
  const props = { snap, channelId, refresh: reload, sound, setSound, open: setOpenClip };
  return html`
    <nav>
      <div class="brand">shorts factory</div>
      ${VIEWS.map((v) => html`
        <a key=${v.id} aria-current=${view === v.id} onClick=${() => setView(v.id)}>
          <div class="name">${v.name}${v.id === "today" && queueCount ? html`<span class="count">${queueCount}</span>` : null}${v.id === "queue" && ((snap?.tasks?.queued || 0) + (snap?.tasks?.claimed || 0)) ? html`<span class="count">${(snap.tasks.queued || 0) + (snap.tasks.claimed || 0)}</span>` : null}</div>
          <div class="meaning">${v.meaning}</div>
        </a>`)}
    </nav>
    <div class="wrap">
      <${Header} channels=${channels} channelId=${channelId} setChannelId=${setChannelId} snap=${snap} refresh=${reload} error=${error}
        playbooksOpen=${playbooksOpen} setPlaybooks=${setPlaybooks} />
      <${Toasts} />
      <main>
        ${openClip ? html`<${ClipDrawer} id=${openClip} close=${() => setOpenClip(null)} refresh=${reload} sound=${sound} />` : null}
        ${playbooksOpen ? html`<${Playbooks} channelId=${channelId} />` : null}
        ${!snap ? html`<p class="empty">${error ? `cannot reach the server: ${error}` : "loading…"}</p>`
        : view === "today" ? html`<${Today} ...${props} />`
        : view === "queue" ? html`<${Queue} ...${props} />`
        : view === "clips" ? html`<${Clips} ...${props} />`
        : view === "results" ? html`<${Results} ...${props} />`
        : view === "activity" ? html`<${Activity} ...${props} />`
        : view === "bin" ? html`<${Clips} ...${props} bin=${true} />`
        : view === "docs" ? html`<${Docs} />`
        : html`<${Settings} ...${props} channels=${channels} />`}
      </main>
    </div>`;
}

/* ---------- header: the channel, the counts, the three things you can start ---------- */

function Header({ channels, channelId, setChannelId, snap, refresh, error, playbooksOpen, setPlaybooks }) {
  const busy = snap?.job?.running;
  const job = snap?.job;
  const run = async (path, body) => {
    try { await send(path, { channel: channelId, ...(body || {}) }); }
    catch (err) { toast(err.message, "error"); }
    refresh();
  };
  const counts = snap?.counts || {};
  const order = ["planned", "awaiting_approval", "approved", "published", "qc_rejected", "failed"];
  const agents = snap?.agents?.available;
  return html`
    <header>
      <select value=${channelId || ""} onChange=${(e) => setChannelId(e.target.value)}>
        ${(channels || []).map((c) => html`<option key=${c.id} value=${c.id}>${c.name}${c.queue ? ` · ${c.queue} waiting` : ""}${c.active ? "" : " (paused)"}</option>`)}
      </select>
      ${order.filter((k) => counts[k]).map((k) => html`<span key=${k} class="pill">${statusWord(k)} <b>${counts[k]}</b></span>`)}
      <span class="grow"></span>
      ${agents ? html`
        <button disabled=${busy} onClick=${() => run("/api/plan", { count: 1 })} title="Ask the built-in Idea agent for one clip">Plan 1</button>
        <button disabled=${busy} onClick=${() => run("/api/plan", { count: 3 })} title="Ask the built-in Idea agent for three clips">Plan 3</button>
        <button disabled=${busy} onClick=${() => run("/api/build")} title="Render, title and QC everything planned">Build planned</button>
        <button disabled=${busy} onClick=${() => run("/api/digest")} title="Ask the built-in Analyst what the numbers say">Digest</button>`
      : html`<button onClick=${() => setPlaybooks((v) => !v)} aria-pressed=${playbooksOpen} class="chip" title="No API key is set, so clips are made by Codex over MCP. This hands you the instructions to paste.">Make clips with Codex</button>`}
      <button disabled=${busy} onClick=${() => run("/api/publish")} title="Publish every approved clip through the channel's driver">Publish approved</button>
      <span class="pill" title="this channel / all channels">$${fmt(snap?.spend_usd, 4)} <span class="hint">/ $${fmt(snap?.spend_total_usd, 4)}</span></span>
      ${error ? html`<span class="job bad">${error}</span>` : null}
      ${job && (job.running || job.log.length) ? html`
        <div class=${"job" + (job.running ? " running" : "")}>
          ${job.running ? `${job.name} is running on ${job.channel_id}… ` : `last job: `}${job.log[job.log.length - 1] || ""}
        </div>` : null}
    </header>`;
}

/* ---------- Queue: put the work in the system; any brain pulls it ---------- */

createRoot(document.getElementById("root")).render(html`<${App} />`);
