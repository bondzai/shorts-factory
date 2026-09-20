// The operator's console, as five screens named for what you do on them.
//
//   Today     decide on what is waiting, then upload what you approved
//   Clips     everything ever made, with the file a click away
//   Results   how published clips did, and the levers you still have
//   Activity  what ran and what happened inside it — one timeline, not two
//   Settings  this channel and the rules its agents read
//
// React 18 with htm from a CDN: no build step, because the rest of the project
// is one Python venv and this page should not be the thing that needs npm.
// Swapping to a Vite build later is a move, not a rewrite.

import React, { useState, useEffect, useRef, useCallback } from "https://esm.sh/react@18.3.1";
import { createRoot } from "https://esm.sh/react-dom@18.3.1/client";
import htm from "https://esm.sh/htm@3.1.1";

const html = htm.bind(React.createElement);

/* ---------- helpers ---------- */

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || res.statusText);
  }
  return res.json();
}
const send = (path, body, method = "POST") => api(path, {
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}),
});
const fmt = (n, d = 1) => (n === null || n === undefined) ? "—" : Number(n).toFixed(d);
const num = (n) => (n === null || n === undefined) ? "—" : Number(n).toLocaleString();
const pct = (n) => (n === null || n === undefined) ? "—" : `${Number(n).toFixed(0)}%`;
const when = (iso) => iso ? iso.slice(0, 16).replace("T", " ") : "—";
const clock = (iso) => iso ? iso.slice(11, 19) : "";
const statusWord = (s) => (s || "").replace(/_/g, " ");

const VIEWS = [
  { id: "today", name: "Today", meaning: "decide, then upload" },
  { id: "queue", name: "Queue", meaning: "what agents will do next" },
  { id: "clips", name: "Clips", meaning: "everything ever made" },
  { id: "results", name: "Results", meaning: "how published clips did" },
  { id: "activity", name: "Activity", meaning: "what ran, and what happened" },
  { id: "bin", name: "Bin", meaning: "what you threw away" },
  { id: "settings", name: "Settings", meaning: "this channel and its rules" },
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
      setSnap(await api(`/api/state?channel=${encodeURIComponent(channelId)}`));
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
    catch (err) { alert(err.message); }
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

function Queue({ snap, channelId, refresh, open }) {
  const [body, setBody] = useState(null);
  const [kind, setKind] = useState("make-clip");
  const [params, setParams] = useState({});
  const [count, setCount] = useState(1);
  const [standing, setStanding] = useState("");
  const [copied, setCopied] = useState(false);
  const load = useCallback(() => api(`/api/tasks?channel=${encodeURIComponent(channelId)}`).then(setBody), [channelId]);
  useEffect(() => { load().catch((err) => alert(err.message)); }, [load, snap?.tasks?.queued, snap?.tasks?.claimed, snap?.tasks?.done]);
  useEffect(() => { api(`/api/playbook/work?channel=${encodeURIComponent(channelId)}`).then((b) => setStanding(b.text)).catch(() => {}); }, [channelId]);
  if (!body) return html`<p class="empty">loading…</p>`;

  const spec = body.kinds[kind] || { params: {} };
  const variants = snap.channel.variants || [];
  const add = async (e) => {
    e.preventDefault();
    try { await send("/api/tasks", { channel: channelId, kind, params, count: Number(count) }); }
    catch (err) { alert(err.message); return; }
    setParams({}); setCount(1); await load(); refresh();
  };
  const cancel = async (id) => {
    try { await api(`/api/tasks/${id}`, { method: "DELETE" }); } catch (err) { alert(err.message); return; }
    await load(); refresh();
  };
  const runBuiltin = async () => {
    try { await send("/api/tasks/work", { channel: channelId }); } catch (err) { alert(err.message); return; }
    refresh();
  };
  const copy = async () => { try { await navigator.clipboard.writeText(standing); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { alert(standing); } };
  const tone = (s) => s === "done" ? "good" : s === "failed" ? "bad" : s === "claimed" ? "warn" : "";
  const active = body.tasks.filter((t) => t.status === "claimed");
  const strip = (t) => html`
    <div class="steps">
      ${t.steps.map((s, i) => html`
        <span key=${s.name} class=${"step " + s.state} title=${s.at ? `${s.by || ""} · ${when(s.at)}` : ""}>
          <i></i>${s.name}${s.note ? html` <em>${s.note}</em>` : null}${s.state === "current" && s.by ? html` <em>← ${s.by}</em>` : null}
        </span>${i < t.steps.length - 1 ? html`<span class="step-line"></span>` : null}`)}
    </div>`;
  const paramInput = (k) => {
    if (k === "variant") return html`<select key=${k} value=${params.variant || ""} onChange=${(e) => setParams({ ...params, variant: e.target.value, generator: e.target.value.split("/")[0] })}>
      <option value="">variant…</option>${variants.map((v) => html`<option key=${v} value=${v.split("/")[1]}>${v}</option>`)}</select>`;
    if (k === "generator") return null;
    return html`<input key=${k} placeholder=${k} value=${params[k] ?? ""} onChange=${(e) => setParams({ ...params, [k]: e.target.value })} style=${{ width: 140 }} />`;
  };

  return html`
    <h1>What agents will do next</h1>
    <p class="lead">Put the work here once. Any agent connected over MCP pulls the next task with its full instructions and reports back; with a ready provider, the built-in agents can work the same queue.</p>
    ${active.length ? html`<div class="card" style=${{ borderColor: "var(--key)" }}>
      <h3>Now</h3>
      ${active.map((t) => { const cur = t.steps.find((s) => s.state === "current"); const n = t.steps.filter((s) => s.state === "done").length;
        return html`<div key=${t.id} class="row"><b>#${t.id} ${t.kind}</b><span class="hint">${t.claimed_by} is at <b>${cur ? cur.name : "…"}</b> — step ${n + 1} of ${t.steps.length}</span></div>${strip(t)}`; })}
    </div>` : null}
    <div class="card">
      <h3>Add work</h3>
      <form class="row" onSubmit=${add} style=${{ flexWrap: "wrap" }}>
        <select value=${kind} onChange=${(e) => { setKind(e.target.value); setParams({}); }}>
          ${Object.entries(body.kinds).map(([k, v]) => html`<option key=${k} value=${k}>${k} — ${v.meaning}</option>`)}
        </select>
        ${Object.keys(spec.params).map(paramInput)}
        ${kind === "make-clip" ? html`<input type="number" min="1" max="50" value=${count} onChange=${(e) => setCount(e.target.value)} style=${{ width: 70 }} title="how many" />` : null}
        <button type="submit" class="ok">Add to queue</button>
        <span class="hint">${spec.builtin ? "built-in agents can do this" : "needs an external agent's judgement"}</span>
      </form>
    </div>
    <div class="card">
      <h3>Hand the queue to an agent</h3>
      <div class="hint" style=${{ marginBottom: 8 }}>Paste this into Codex, Claude Code or any MCP-connected agent. It is the same for every task and every model — the task carries its own playbook.</div>
      <div class="row">
        <pre class="captured" style=${{ margin: 0, flex: 1, maxHeight: 140, overflow: "auto" }}>${standing || "loading…"}</pre>
        <button class="small ok" onClick=${copy} disabled=${!standing}>${copied ? "Copied" : "Copy"}</button>
      </div>
      ${snap.agents?.available ? html`<div class="row" style=${{ marginTop: 8 }}><button onClick=${runBuiltin} disabled=${snap.job?.running}>Run with built-in agents</button><span class="hint">does every make-clip task in the queue, in a job</span></div>`
        : html`<div class="hint" style=${{ marginTop: 8 }}>No built-in provider is ready (Settings → Brains), so an external agent works this queue.</div>`}
    </div>
    <table>
      <thead><tr><th>#</th><th>task</th><th>parameters</th><th>status</th><th>who</th><th>result</th><th></th></tr></thead>
      <tbody>
        ${body.tasks.map((t) => html`
          <tr key=${t.id}>
            <td class="hint">${t.id}</td>
            <td><b>${t.kind}</b><div class="hint">${t.meaning}</div></td>
            <td class="hint">${Object.entries(t.params).map(([k, v]) => `${k}=${v}`).join(" ") || "—"}</td>
            <td><span class=${"badge " + tone(t.status)}>${t.status}</span><div class="hint">${when(t.finished_at || t.claimed_at || t.created_at)}</div></td>
            <td class="hint">${t.claimed_by || ""}</td>
            <td class="hint">${t.error ? html`<span class="bad">${t.error}</span>` : (t.result?.summary || t.result?.detail || "")}
              ${t.clip_id ? html` <button class="small" onClick=${() => open(t.clip_id)}>View clip</button>` : null}</td>
            <td>${["queued", "claimed"].includes(t.status) ? html`<button class="small" onClick=${() => cancel(t.id)}>Cancel</button>` : null}</td>
          </tr>
          ${t.status !== "queued" ? html`<tr key=${t.id + "s"}><td></td><td colSpan="6" style=${{ paddingTop: 0, borderBottom: "1px solid #1f1f29" }}>${strip(t)}</td></tr>` : null}`)}
        ${!body.tasks.length ? html`<tr><td colSpan="7" class="empty">Nothing queued. Add work above.</td></tr>` : null}
      </tbody>
    </table>`;
}

/* ---------- Playbooks: the instructions Codex gets, filled from this database ---------- */

function Playbooks({ channelId }) {
  const [names, setNames] = useState([]);
  const [name, setName] = useState("make-clip");
  const [text, setText] = useState("");
  const [copied, setCopied] = useState(false);
  useEffect(() => { api("/api/playbooks").then((b) => setNames(b.playbooks)).catch(() => {}); }, []);
  useEffect(() => {
    setText("");
    api(`/api/playbook/${name}?channel=${encodeURIComponent(channelId)}`).then((b) => setText(b.text)).catch((err) => setText(err.message));
  }, [name, channelId]);
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { alert("Select the text and copy it."); }
  };
  const meaning = { "make-clip": "render one clip, look at it, title it, QC it", "plan-week": "propose a week of clips from the numbers, no rendering", "review": "judge what is in the queue", "retitle": "propose new titles for published clips that underperform" };
  return html`
    <div class="card">
      <h3>Make clips with Codex</h3>
      <div class="hint" style=${{ marginBottom: 10 }}>No API key is set, so the agent is Codex over MCP. Pick a playbook — it is filled in from this channel right now (rules, recent clips, numbers) — copy it, and paste it into Codex opened in the project folder. Approve each tool call there; results land here.</div>
      <div class="bar">
        ${names.map((n) => html`<button key=${n} class="small chip" aria-pressed=${n === name} onClick=${() => setName(n)} title=${meaning[n] || ""}>${n}</button>`)}
        <span class="grow"></span>
        <button class="small ok" onClick=${copy} disabled=${!text}>${copied ? "Copied" : "Copy playbook"}</button>
      </div>
      <div class="hint" style=${{ marginBottom: 8 }}>${meaning[name] || ""}</div>
      <pre class="captured" style=${{ maxHeight: 320, overflow: "auto" }}>${text || "loading…"}</pre>
    </div>`;
}

/* ---------- Today: the queue, then what you approved ---------- */

function Today({ snap, refresh, sound, setSound, channelId }) {
  const items = [...snap.queue, ...snap.approved];
  const [index, setIndex] = useState(0);
  const safe = Math.min(index, Math.max(0, items.length - 1));
  const current = items[safe];

  const decide = useCallback(async (id, what) => {
    let body = {};
    if (what === "reject") {
      const reason = prompt("Why? This is what the next planner reads. Cancel keeps the clip.", "");
      if (reason === null) return;
      body = { reason: reason.trim() || "rejected in review" };
    }
    try { await send(`/api/clip/${id}/${what}`, body); } catch (err) { alert(err.message); }
    refresh();
  }, [refresh]);

  useEffect(() => {
    const onKey = (event) => {
      if (event.target?.matches?.("input, textarea, select")) return;
      if (!current) return;
      const pending = current.status !== "approved";
      if (pending && /^[aA]$/.test(event.key)) decide(current.id, "approve");
      else if (pending && /^[rR]$/.test(event.key)) decide(current.id, "reject");
      else if (/^[jJ]$/.test(event.key)) setIndex((i) => Math.min(i + 1, items.length - 1));
      else if (/^[kK]$/.test(event.key)) setIndex((i) => Math.max(i - 1, 0));
      else if (event.key === " ") {
        event.preventDefault();
        const p = document.querySelector("video");
        if (p) p.paused ? p.play() : p.pause();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [current, items.length, decide]);

  if (!items.length) {
    return html`
      <h1>Nothing waiting on ${snap.channel.name}</h1>
      <p class="lead">${snap.planned ? `${snap.planned} clip(s) are planned — press Build planned.`
        : snap.agents?.available ? "Press Plan to ask for ideas, then Build planned."
        : "To make new clips, press “Make clips with Codex” above and paste the playbook into Codex."}</p>
      <div class="note">Looking for a clip you already handled? Every clip ever made is under <b>Clips</b>, each with a Download button while its file is kept (a month for published ones).</div>`;
  }
  return html`
    <div class="bar">
      <h1 style=${{ margin: 0 }}>${snap.queue.length} to decide · ${snap.approved.length} to upload</h1>
      <span class="grow"></span>
      <button class="small" onClick=${() => setSound(!sound)}>Sound: ${sound ? "on" : "off"}</button>
    </div>
    <${ClipCard} key=${current.id} clip=${current} sound=${sound} refresh=${refresh} decide=${decide} channelId=${channelId}
      position=${`${safe + 1} of ${items.length}`} />
    <div class="strip">
      ${items.map((q, i) => html`
        <button key=${q.id} class="small" aria-current=${i === safe} onClick=${() => setIndex(i)}>
          ${q.status === "approved" ? "✓ " : ""}${i + 1}. ${(q.title || q.id).slice(0, 32)}
        </button>`)}
    </div>`;
}

function ClipCard({ clip: c, sound, refresh, decide, position, channelId }) {
  const ready = c.status === "approved";
  const [title, setTitle] = useState(c.title || "");
  const [hook, setHook] = useState(c.hook_text || "");
  const [promptText, setPromptText] = useState(c.comment_prompt || "");
  const [rendering, setRendering] = useState(false);
  const [version, setVersion] = useState(0);
  const [copied, setCopied] = useState(false);
  const qc = c.qc || {};

  const saveText = async () => {
    const body = { comment_prompt: promptText.trim() };
    if (title.trim() !== (c.title || "")) body.title = title.trim();
    try {
      const out = await send(`/api/clip/${c.id}/text`, body, "PATCH");
      if (out.needs_manual_update) alert("Saved. This clip is published on a manual channel — change the title in YouTube Studio too.");
    } catch (err) { alert(err.message); return; }
    refresh();
  };
  const rehook = async () => {
    const text = hook.trim();
    if (!text) { alert("Type a caption first."); return; }
    try { await send(`/api/clip/${c.id}/hook`, { text }); } catch (err) { alert(err.message); return; }
    setRendering(true);
    // Wait here, not on another screen. A race re-renders in about a minute.
    for (let tick = 0; tick < 240; tick++) {
      await new Promise((r) => setTimeout(r, 1500));
      let latest;
      try { latest = await api(`/api/state?channel=${encodeURIComponent(channelId)}`); } catch { continue; }
      if (!latest.job.running) break;
    }
    setRendering(false);
    setVersion((v) => v + 1);
    refresh();
  };
  const copy = async () => {
    const text = [title.trim(), "", c.description || "", "", (c.hashtags || []).join(" "), "",
      promptText.trim() ? `Pinned comment: ${promptText.trim()}` : ""].join("\n").trim();
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); }
    catch { alert(text); }
  };
  const uploaded = async () => {
    if (!confirm("Mark this clip as uploaded? It moves to published and leaves this screen.")) return;
    try { await send(`/api/clip/${c.id}/publish`, {}); } catch (err) { alert(err.message); return; }
    refresh();
  };

  return html`
    <div class="clip">
      <video key=${`${c.id}-${version}`} src=${`/api/clip/${c.id}/video?v=${version}`} autoPlay loop playsInline muted=${!sound} controls />
      <div>
        <input class="title" value=${title} maxLength="90" spellCheck="false" placeholder="title (20-90 characters)" onChange=${(e) => setTitle(e.target.value)} />
        <div class="row">
          <input value=${hook} maxLength="28" spellCheck="false" placeholder="opening caption, burned into the first seconds" onChange=${(e) => setHook(e.target.value)} disabled=${rendering} />
          <button class="small" onClick=${rehook} disabled=${rendering}>${rendering ? "Re-rendering…" : "Re-render caption"}</button>
        </div>
        <input value=${promptText} maxLength="140" spellCheck="false" placeholder="question to pin as the first comment" onChange=${(e) => setPromptText(e.target.value)} style=${{ width: "100%" }} />
        <div class="row">
          <button class="small" onClick=${saveText}>Save title & prompt</button>
          <button class="small" onClick=${copy}>${copied ? "Copied" : "Copy for upload"}</button>
          <span class="hint">${c.title_history?.length ? `retitled ${c.title_history.length}×, was “${c.title_history.at(-1).title}”` : ""}</span>
        </div>
        <div class="tags">${(c.hashtags || []).join(" ")}</div>
        <div class="desc">${c.description}</div>
        <dl>
          <dt>clip</dt><dd>${c.id} · ${c.generator}/${c.variant} · seed ${c.seed}</dd>
          <dt>shows</dt><dd>${c.render_desc || "—"}</dd>
          <dt>length</dt><dd>${fmt(c.duration_s)}s · ${fmt(c.loudness_lufs)} LUFS · sameness ${fmt(c.sameness, 3)}</dd>
          <dt>QC</dt><dd>hook ${qc.hook_strength ?? "—"}/5 · policy ${qc.policy_risk ?? "—"}${(qc.reasons || []).map((r) => html`<div key=${r} class="hint">${r}</div>`)}</dd>
        </dl>
        <div class="bar">
          ${ready ? html`
            <button class="ok" onClick=${() => { window.location.href = `/api/clip/${c.id}/video?download=1`; }}>Download clip</button>
            <button class="ok" onClick=${uploaded}>I uploaded it</button>
            <span class="hint">approved — fix the caption if you want, download, upload by hand, then mark it</span>`
          : html`
            <button class="ok" onClick=${() => decide(c.id, "approve")}>Approve <kbd>A</kbd></button>
            <button class="no" onClick=${() => decide(c.id, "reject")}>Reject <kbd>R</kbd></button>`}
          <span class="hint">${position} · <kbd>J</kbd> <kbd>K</kbd> to move</span>
        </div>
      </div>
    </div>`;
}

/* ---------- ClipDrawer: watch it and read everything known, from any list ---------- */

function ClipDrawer({ id, close, refresh, sound }) {
  const [c, setC] = useState(null);
  const [err, setErr] = useState(null);
  const load = useCallback(() => api(`/api/clip/${id}`).then(setC).catch((e) => setErr(e.message)), [id]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [close]);
  const act = async (path, body, confirmText) => {
    if (confirmText && !confirm(confirmText)) return;
    try { await send(path, body || {}); } catch (e) { alert(e.message); return; }
    await load(); refresh();
  };
  const skip = new Set(["variant", "seed", "impacts", "palette", "sim_attempts", "hash_a", "hash_b", "style"]);
  const facts = c ? Object.entries(c.facts || {}).filter(([k]) => !skip.has(k)) : [];
  const qc = c?.qc || {};
  return html`
    <div class="scrim" onClick=${close}></div>
    <div class="drawer" role="dialog">
      ${err ? html`<p class="empty">${err}</p>` : !c ? html`<p class="empty">loading…</p>` : html`
        <div class="bar">
          <span class="badge">${statusWord(c.status)}</span>
          ${c.deleted_at ? html`<span class="badge bad">in the bin</span>` : null}
          <span class="hint">${c.generator}/${c.variant} · seed ${c.seed} · ${when(c.created_at)}</span>
          <span class="grow"></span>
          <button class="small" onClick=${close}>Close <kbd>Esc</kbd></button>
        </div>
        <div class="clip">
          ${c.file.exists ? html`<video key=${c.id} src=${`/api/clip/${c.id}/video`} autoPlay loop playsInline muted=${!sound} controls />`
            : html`<div class="note">No file on disk any more${c.purged_at ? ` — purged ${when(c.purged_at)} by retention` : ""}. The record stays.</div>`}
          <div>
            <h1 style=${{ fontSize: 17 }}>${c.title || "(untitled)"}</h1>
            <div class="tags">${(c.hashtags || []).join(" ")}</div>
            <div class="desc">${c.description || ""}</div>
            ${c.hook_text ? html`<div class="hint">opening caption: <b>${c.hook_text}</b></div>` : null}
            ${c.comment_prompt ? html`<div class="hint">pinned comment: ${c.comment_prompt}</div>` : null}
            ${c.reject_reason ? html`<div class="bad" style=${{ fontSize: 13, margin: "8px 0" }}>rejected: ${c.reject_reason}</div>` : null}
            <div class="bar" style=${{ marginTop: 12 }}>
              ${c.file.exists ? html`<button class="small" onClick=${() => { window.location.href = `/api/clip/${c.id}/video?download=1`; }}>Download (${c.file.mb} MB)</button>` : null}
              ${c.deleted_at ? html`<button class="small" onClick=${() => act("/api/clips/unbin", { ids: [c.id] })}>Restore from bin</button>
                <button class="small no" onClick=${() => act("/api/clips/destroy", { ids: [c.id] }, "Delete this clip and its files for good?").then(close)}>Delete forever</button>`
              : html`<button class="small" onClick=${() => act("/api/clips/bin", { ids: [c.id] })}>Move to bin</button>`}
              ${!c.deleted_at && c.status === "qc_rejected" && c.file.exists && !(c.reject_reason || "").startsWith("too similar")
                ? html`<button class="small" onClick=${() => act(`/api/clip/${c.id}/restore`)}>Back to queue</button>` : null}
            </div>
          </div>
        </div>
        <h3 style=${{ fontSize: 13.5, fontWeight: 500, margin: "18px 0 6px" }}>What the render measured</h3>
        <dl class="facts">
          <dt>shows</dt><dd>${c.render_desc || "—"}</dd>
          <dt>length</dt><dd>${fmt(c.duration_s)}s · ${fmt(c.loudness_lufs)} LUFS · sameness ${fmt(c.sameness, 3)}</dd>
          ${facts.map(([k, v]) => html`<dt key=${k}>${k}</dt><dd>${typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>`)}
          ${c.file.path ? html`<dt>file</dt><dd>${c.file.path}${c.file.exists ? "" : " (gone)"}</dd>` : null}
        </dl>
        ${qc.verdict ? html`
          <h3 style=${{ fontSize: 13.5, fontWeight: 500, margin: "14px 0 6px" }}>QC</h3>
          <dl class="facts">
            <dt>verdict</dt><dd>${qc.verdict} · hook ${qc.hook_strength}/5 · policy ${qc.policy_risk}${qc.looks_templated ? " · looks templated" : ""}</dd>
            ${(qc.reasons || []).map((r, i) => html`<dt key=${i}></dt><dd class="hint">${r}</dd>`)}
          </dl>` : null}
        ${c.published_at || c.views != null ? html`
          <h3 style=${{ fontSize: 13.5, fontWeight: 500, margin: "14px 0 6px" }}>On the platform</h3>
          <dl class="facts">
            <dt>published</dt><dd>${when(c.published_at)}</dd>
            <dt>metrics</dt><dd>${c.views == null ? "none entered yet" : `${num(c.views)} views · ${pct(c.avg_view_pct)} viewed · ${pct(c.swipe_away_pct)} swiped · ${num(c.likes)} likes (${when(c.metrics_at)})`}</dd>
          </dl>` : null}
        ${c.title_history?.length ? html`
          <h3 style=${{ fontSize: 13.5, fontWeight: 500, margin: "14px 0 6px" }}>Earlier titles</h3>
          ${c.title_history.map((h, i) => html`<div key=${i} class="hint" style=${{ marginBottom: 4 }}>“${h.title}” until ${when(h.until)} by ${h.by} — ${h.views == null ? "no metrics then" : `${num(h.views)} views, ${pct(h.avg_view_pct)} viewed, ${pct(h.swipe_away_pct)} swiped`}${h.why ? ` · ${h.why}` : ""}</div>`)}` : null}
      `}
    </div>`;
}

/* ---------- Clips: the archive ---------- */

function Clips({ channelId, refresh, bin = false, open }) {
  const [filters, setFilters] = useState({});
  const [body, setBody] = useState(null);
  const [picked, setPicked] = useState(() => new Set());
  const load = useCallback(async () => {
    const params = new URLSearchParams({ channel: channelId });
    for (const [k, v] of Object.entries(filters)) if (v) params.set(k, v);
    if (bin) params.set("bin", "1");
    setBody(await api(`/api/clips?${params}`));
    setPicked(new Set());
  }, [channelId, filters, bin]);
  useEffect(() => { load().catch((err) => alert(err.message)); }, [load]);

  const toggle = (key, value) => setFilters((f) => ({ ...f, [key]: f[key] === value ? "" : value }));
  const restore = async (id) => {
    try { await send(`/api/clip/${id}/restore`, {}); } catch (err) { alert(err.message); return; }
    await load(); refresh();
  };
  const pick = (id) => setPicked((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const pickAll = (ids) => setPicked((p) => p.size === ids.length ? new Set() : new Set(ids));
  const act = async (path, confirmText) => {
    if (confirmText && !confirm(confirmText)) return;
    try { await send(path, { ids: [...picked] }); } catch (err) { alert(err.message); return; }
    await load(); refresh();
  };
  if (!body) return html`<p class="empty">loading…</p>`;
  const ids = body.clips.map((c) => c.id), n = picked.size;
  const chip = (label, key, value) => html`<button key=${key + value} class="small chip" aria-pressed=${filters[key] === value} onClick=${() => toggle(key, value)}>${label}</button>`;
  if (bin) return html`
    <h1>Bin</h1>
    <p class="lead">Binned clips are hidden everywhere and count for nothing, but their files are still here. Restore puts one back where it was; Delete forever removes the render and the record.</p>
    <div class="bar">
      <button class="small" disabled=${!n} onClick=${() => act("/api/clips/unbin")}>Restore ${n || ""}</button>
      <button class="small no" disabled=${!n} onClick=${() => act("/api/clips/destroy", `Delete ${n} clip(s) and their files for good? This cannot be undone.`)}>Delete forever ${n || ""}</button>
      <span class="grow"></span>
      <button class="small no" disabled=${!ids.length} onClick=${() => { setPicked(new Set(ids)); setTimeout(() => act("/api/clips/destroy", `Empty the bin — delete all ${ids.length} clip(s) and their files for good?`), 0); }}>Empty bin</button>
    </div>
    <${ClipTable} clips=${body.clips} picked=${picked} pick=${pick} pickAll=${() => pickAll(ids)} restore=${restore} bin=${true} open=${open} />`;
  return html`
    <h1>Every clip on this channel</h1>
    <p class="lead">Rejected clips keep their file for a few days, published ones for a month; the Download button says whether it is still there. Tick clips to move them to the Bin${body.binned ? ` (${body.binned} there now)` : ""}.</p>
    <div class="bar">
      <button class="small" disabled=${!n} onClick=${() => act("/api/clips/bin")}>Move to bin ${n || ""}</button>
      <span style=${{ width: 12 }}></span>
      ${body.statuses.map((s) => chip(statusWord(s), "status", s))}
      <span style=${{ width: 12 }}></span>
      ${Object.entries(body.modules).flatMap(([g, vs]) => vs.map((v) => chip(v, "variant", v)))}
      <span class="grow"></span>
      <input type="search" placeholder="search titles" defaultValue=${filters.q || ""} onKeyDown=${(e) => { if (e.key === "Enter") setFilters((f) => ({ ...f, q: e.target.value })); }} style=${{ width: 200 }} />
    </div>
    <${ClipTable} clips=${body.clips} picked=${picked} pick=${pick} pickAll=${() => pickAll(ids)} restore=${restore} open=${open} />`;
}

function ClipTable({ clips, picked, pick, pickAll, restore, bin = false, open }) {
  return html`
    <table>
      <thead><tr>
        <th style=${{ width: 28 }}><input type="checkbox" checked=${clips.length > 0 && picked.size === clips.length} onChange=${pickAll} title="select all" /></th>
        <th>Title</th><th>Module</th><th>Status</th><th>Views</th><th>Viewed</th><th>Swiped</th><th></th></tr></thead>
      <tbody>
        ${clips.map((c) => html`
          <tr key=${c.id} class="clickable" onClick=${(e) => { if (!e.target.closest("button, input")) open(c.id); }}>
            <td><input type="checkbox" checked=${picked.has(c.id)} onChange=${() => pick(c.id)} /></td>
            <td><div>${c.title || "(untitled)"} <button class="small" style=${{ marginLeft: 6 }} onClick=${() => open(c.id)}>View</button></div>
              <div class="hint">${c.id} · seed ${c.seed}${c.title_history?.length ? ` · retitled ${c.title_history.length}×` : ""}
                ${c.reject_reason ? html` · <span class="bad">${c.reject_reason.slice(0, 80)}</span>` : null}</div></td>
            <td class="hint">${c.variant}</td>
            <td><span class="badge">${statusWord(c.status)}</span></td>
            <td>${num(c.views)}</td><td>${pct(c.avg_view_pct)}</td><td>${pct(c.swipe_away_pct)}</td>
            <td style=${{ whiteSpace: "nowrap" }}>
              ${c.has_video ? html`<button class="small" onClick=${() => { window.location.href = `/api/clip/${c.id}/video?download=1`; }}>Download</button>` : html`<span class="hint">no file</span>`}
              ${!bin && c.status === "qc_rejected" && c.has_video && !(c.reject_reason || "").startsWith("too similar")
                ? html` <button class="small" onClick=${() => restore(c.id)}>Back to queue</button>` : null}
            </td>
          </tr>`)}
        ${!clips.length ? html`<tr><td colSpan="8" class="empty">${bin ? "The bin is empty." : "Nothing matches."}</td></tr>` : null}
      </tbody>
    </table>`;
}

/* ---------- Results: numbers, and the two levers left on a published clip ---------- */

function Results({ channelId, refresh, open }) {
  const [a, setA] = useState(null);
  const [published, setPublished] = useState(null);
  const load = useCallback(async () => {
    const q = `channel=${encodeURIComponent(channelId)}`;
    const [analytics, clips] = await Promise.all([api(`/api/analytics?${q}`), api(`/api/clips?${q}&status=published`)]);
    setA(analytics); setPublished(clips.clips);
  }, [channelId]);
  useEffect(() => { load().catch((err) => alert(err.message)); }, [load]);
  if (!a || !published) return html`<p class="empty">loading…</p>`;

  const max = Math.max(...(a.series || []).map((s) => s.views), 1);
  const bar = (g) => html`
    <div key=${g.key} style=${{ marginBottom: 13 }}>
      <div style=${{ display: "flex", fontSize: 12.5, marginBottom: 5 }}>
        <span class="grow">${g.key}</span><span>${pct(g.retained_median)}</span><span class="hint" style=${{ marginLeft: 8 }}>n=${g.n}</span></div>
      <div class="meter"><span style=${{ width: `${Math.max(2, g.retained_median || 0)}%` }}></span></div>
    </div>`;

  return html`
    <h1>How published clips did</h1>
    <p class="lead">Numbers come from YouTube Studio: enter them here as they come in. Two levers stay open on a published clip — its title, and what you learn for the next one.</p>
    ${a.n_with_metrics ? html`
      <div class="tiles">
        <div class="tile"><div class="label">Shorts views, 90 days</div><div class="value">${num(a.views_90d)}</div><div class="sub">${a.gate_tier2_pct}% of the 10M gate</div></div>
        <div class="tile"><div class="label">With metrics</div><div class="value">${a.n_with_metrics}</div><div class="sub">of ${a.n_published} published</div></div>
        <div class="tile"><div class="label">Median viewed</div><div class="value">${pct(a.retained_median)}</div><div class="sub">swiped away ${pct(a.swipe_away_median)}</div></div>
        <div class="tile"><div class="label">Best clip</div><div class="value">${num(a.best?.views)}</div><div class="sub">${a.best?.variant || "—"}</div></div>
      </div>
      <div class="card"><h3>Views per clip, in publish order</h3><div class="hint" style=${{ marginBottom: 14 }}>One clip usually carries a channel. Watch for the tall bar, not the average.</div>
        <div style=${{ display: "flex", alignItems: "flex-end", gap: 4, height: 120 }}>
          ${a.series.map((s, i) => html`<div key=${i} title=${`${s.title} · ${num(s.views)} views`} style=${{ flex: 1, height: `${Math.max(2, (s.views / max) * 100)}%`, background: s.views === max ? "var(--key)" : "#2b2b38", borderRadius: 2 }}></div>`)}
        </div></div>
      <div class="card"><h3>Viewed, by variant</h3><div class="hint" style=${{ marginBottom: 14 }}>n is shown because at this sample size n is most of the argument.</div>${a.by_variant.map(bar)}</div>`
    : html`<div class="note">No published clip has metrics yet. Enter the first ones below.</div>`}
    <div class="card">
      <h3>Published clips</h3>
      <div class="hint" style=${{ marginBottom: 10 }}>Retitle keeps the old title and the numbers at that moment, so the next entry reads as before/after.</div>
      <table>
        <thead><tr><th>Title</th><th>Caption</th><th>Views</th><th>Viewed</th><th>Swiped</th><th></th></tr></thead>
        <tbody>${published.map((c) => html`<${PublishedRow} key=${c.id} c=${c} open=${open} onChanged=${async () => { await load(); refresh(); }} />`)}
          ${!published.length ? html`<tr><td colSpan="6" class="empty">Nothing published yet.</td></tr>` : null}</tbody>
      </table>
    </div>`;
}

function PublishedRow({ c, onChanged, open }) {
  const [mode, setMode] = useState(null);
  const [title, setTitle] = useState(c.title || "");
  const [m, setM] = useState({ views: c.views ?? "", avg_view_pct: c.avg_view_pct ?? "", swipe_away_pct: c.swipe_away_pct ?? "", likes: "" });
  const retitle = async () => {
    try { const out = await send(`/api/clip/${c.id}/text`, { title: title.trim(), why: "changed on the Results screen" }, "PATCH");
      if (out.needs_manual_update) alert("Saved here. Change it in YouTube Studio too — nothing reaches YouTube by itself on a manual channel."); }
    catch (err) { alert(err.message); return; }
    setMode(null); onChanged();
  };
  const saveMetrics = async () => {
    try { await send(`/api/clip/${c.id}/metrics`, { views: Number(m.views), avg_view_pct: Number(m.avg_view_pct), swipe_away_pct: Number(m.swipe_away_pct), likes: Number(m.likes || 0) }); }
    catch (err) { alert(err.message); return; }
    setMode(null); onChanged();
  };
  const field = (k, label) => html`<input key=${k} type="number" step="any" placeholder=${label} value=${m[k]} onChange=${(e) => setM({ ...m, [k]: e.target.value })} style=${{ width: 92 }} />`;
  return html`
    <tr>
      <td>
        ${mode === "retitle" ? html`<div class="row"><input value=${title} maxLength="90" onChange=${(e) => setTitle(e.target.value)} /><button class="small ok" onClick=${retitle}>Save</button><button class="small" onClick=${() => setMode(null)}>Cancel</button></div>`
        : html`<div>${c.title}</div>`}
        <div class="hint">${c.id} · ${when(c.published_at)}${c.title_history?.length ? ` · was “${c.title_history.at(-1).title}” at ${num(c.title_history.at(-1).views)} views` : ""}</div>
      </td>
      <td class="hint">${c.hook_text || "—"}</td>
      ${mode === "metrics" ? html`<td colSpan="3"><div class="row">${field("views", "views")}${field("avg_view_pct", "% viewed")}${field("swipe_away_pct", "% swiped")}${field("likes", "likes")}<button class="small ok" onClick=${saveMetrics}>Save</button><button class="small" onClick=${() => setMode(null)}>Cancel</button></div></td>`
      : html`<td>${num(c.views)}</td><td>${pct(c.avg_view_pct)}</td><td>${pct(c.swipe_away_pct)}</td>`}
      <td style=${{ whiteSpace: "nowrap" }}>
        ${mode ? null : html`<button class="small" onClick=${() => open(c.id)}>View</button> <button class="small" onClick=${() => setMode("metrics")}>Enter metrics</button> <button class="small" onClick=${() => setMode("retitle")}>Retitle</button>${c.has_video ? html` <button class="small" onClick=${() => { window.location.href = `/api/clip/${c.id}/video?download=1`; }}>Download</button>` : null}`}
      </td>
    </tr>`;
}

/* ---------- Activity: runs are the chapters, events are the lines ---------- */

function Activity({ channelId }) {
  const [runs, setRuns] = useState(null);
  const [events, setEvents] = useState(null);
  const [level, setLevel] = useState("");
  const [actor, setActor] = useState("");
  useEffect(() => {
    const q = `channel=${encodeURIComponent(channelId)}`;
    Promise.all([api(`/api/runs?${q}`), api(`/api/logs?${q}&limit=300`)])
      .then(([r, l]) => { setRuns(r.runs); setEvents(l.events); })
      .catch((err) => alert(err.message));
  }, [channelId]);
  if (!runs || !events) return html`<p class="empty">loading…</p>`;

  // A run is a job this page or the CLI started; its events are the ones that
  // happened while it ran. Everything else — an agent over MCP, a keypress on
  // Today — is an event with no run around it, and shows as its own line.
  const t = (iso) => Date.parse(iso) || 0;
  const visible = events.filter((e) =>
    (!level || (level === "warn" ? ["warn", "error"].includes(e.level) : e.level === level)) &&
    (!actor || (actor === "agent" ? (e.actor === "mcp" || e.by === "agent") : actor === "human" ? (e.by === "human" || !e.actor) : true)));
  const inRun = new Set();
  const chapters = runs.map((r) => {
    const start = t(r.started_at), end = r.ended_at ? t(r.ended_at) + 1500 : Infinity;
    const inside = visible.filter((e) => { const at = t(e.at); return at >= start && at <= end; });
    inside.forEach((e) => inRun.add(e));
    return { at: r.started_at, run: r, events: inside };
  });
  const loose = visible.filter((e) => !inRun.has(e)).map((e) => ({ at: e.at, event: e }));
  const timeline = [...chapters, ...loose].sort((a, b) => t(b.at) - t(a.at));
  const detail = (e) => JSON.stringify(Object.fromEntries(Object.entries(e).filter(([k, v]) =>
    !["at", "level", "event", "channel", "clip", "actor"].includes(k) && v !== null))).slice(0, 180);
  const tone = (l) => l === "error" ? "bad" : l === "warn" ? "warn" : "";
  const chip = (label, on, set, value) => html`<button key=${label} class="small chip" aria-pressed=${on === value} onClick=${() => set(on === value ? "" : value)}>${label}</button>`;
  const line = (e) => html`
    <div key=${e.at + e.event} class="event">
      <span class="t">${clock(e.at)}</span>
      <span class=${tone(e.level)}>${e.event}${e.clip ? html` <span class="hint">${e.clip}</span>` : null}</span>
      <span class="d">${detail(e)}</span>
    </div>`;

  return html`
    <h1>What ran, and what happened</h1>
    <p class="lead">Each box is one job — a build, a re-render, a plan — with the events it produced inside. Lines outside a box came from the CLI, an agent over MCP, or a keypress on Today.</p>
    <div class="bar">
      ${chip("problems only", level, setLevel, "warn")}
      <span style=${{ width: 12 }}></span>
      ${chip("by an agent", actor, setActor, "agent")}${chip("by a person", actor, setActor, "human")}
    </div>
    ${timeline.map((item) => item.run ? html`
      <details key=${"run" + item.run.id} class="run" open=${item.run.status === "failed"}>
        <summary>
          <span class="hint">${when(item.run.started_at)}</span>
          <b>${item.run.kind}</b>
          <span class=${item.run.status === "failed" ? "bad" : item.run.status === "ok" ? "good" : "hint"}>${item.run.status}</span>
          <span class="hint grow">${item.run.detail || ""}</span>
          <span class="hint">${item.events.length} events${item.run.cost_usd ? ` · $${fmt(item.run.cost_usd, 4)}` : ""}</span>
        </summary>
        <div class="events">
          ${item.events.map(line)}
          ${item.run.log ? html`<pre class="captured">${item.run.log}</pre>` : null}
        </div>
      </details>`
    : html`<div key=${item.event.at + item.event.event} class="run" style=${{ padding: "0 14px" }}>${line(item.event)}</div>`)}
    ${!timeline.length ? html`<p class="empty">Nothing yet.</p>` : null}`;
}

/* ---------- Settings: the channel, and the rules its agents read ---------- */

function Settings({ snap, channelId, refresh, channels }) {
  const ch = snap.channel;
  const [form, setForm] = useState({ name: ch.name, handle: ch.handle || "", driver: ch.driver, cadence: ch.cadence, variants: (ch.variants || []).join(", ") });
  const [rules, setRules] = useState(null);
  const loadRules = useCallback(() => api(`/api/rules?channel=${encodeURIComponent(channelId)}`).then(setRules), [channelId]);
  useEffect(() => { loadRules().catch((err) => alert(err.message)); }, [loadRules]);

  const save = async (e) => {
    e.preventDefault();
    const body = { name: form.name, handle: form.handle || null, driver: form.driver, cadence: Number(form.cadence),
      variants: form.variants.split(",").map((s) => s.trim()).filter(Boolean) };
    try { await send(`/api/channels/${ch.id}`, body, "PATCH"); } catch (err) { alert(err.message); return; }
    refresh();
  };
  const pause = async () => {
    try { await send(`/api/channels/${ch.id}`, { active: !ch.active }, "PATCH"); } catch (err) { alert(err.message); return; }
    refresh();
  };
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  return html`
    <h1>${ch.name}</h1>
    <p class="lead">What the agents are allowed to make here, how it gets published, and the rules they read before every run.</p>
    <div class="card">
      <h3>Channel</h3>
      <form class="grid" onSubmit=${save}>
        <label>name</label><input value=${form.name} onChange=${set("name")} />
        <label>handle</label><input value=${form.handle} onChange=${set("handle")} placeholder="@handle" />
        <label>publish driver</label>
        <select value=${form.driver} onChange=${set("driver")}><option value="manual">manual — you upload, the page copies the file and text</option><option value="youtube">youtube — API upload (needs credentials)</option></select>
        <label>clips per day</label><input type="number" min="1" value=${form.cadence} onChange=${set("cadence")} style=${{ width: 90 }} />
        <label>allowed modules</label><input value=${form.variants} onChange=${set("variants")} placeholder="physics/marble_race, physics/funnel_drop — empty means every ready module" />
        <span></span><div class="row"><button type="submit">Save channel</button><button type="button" onClick=${pause}>${ch.active ? "Pause channel" : "Resume channel"}</button></div>
      </form>
    </div>
    <${Brains} refresh=${refresh} />
    <${FactorySettings} />
    ${rules ? html`<${Rules} rules=${rules} channelId=${channelId} reload=${loadRules} />` : null}
    <${AddChannel} onDone=${refresh} />`;
}

/* ---------- Brains: which model each built-in agent runs on, and how to plug in an external one ---------- */

function Brains({ refresh }) {
  const [b, setB] = useState(null);
  const [providers, setProviders] = useState([]);
  const [agents, setAgents] = useState({});
  const [tests, setTests] = useState({});
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(null);
  const load = useCallback(() => api("/api/brains").then((body) => {
    setB(body); setProviders(body.providers); setAgents(body.agents);
  }), []);
  useEffect(() => { load().catch((err) => alert(err.message)); }, [load]);
  if (!b) return null;

  const setP = (i, k, v) => setProviders((ps) => ps.map((p, j) => j === i ? { ...p, [k]: v } : p));
  const addPreset = (e) => {
    const id = e.target.value; e.target.value = "";
    if (!id) return;
    const preset = id === "custom" ? { id: "custom", kind: "openai", base_url: "", api_key_env: "", vision: true, json_mode: "object", models: [] }
      : b.presets.find((p) => p.id === id);
    if (providers.some((p) => p.id === preset.id)) { alert(`${preset.id} is already listed`); return; }
    setProviders([...providers, { ...preset, key_present: false }]);
  };
  const save = async () => {
    setSaving(true);
    try { const out = await send("/api/brains", { providers, agents }, "PUT"); setB(out); setProviders(out.providers); setAgents(out.agents); }
    catch (err) { alert(err.message); }
    setSaving(false); refresh();
  };
  const test = async (p) => {
    const model = (p.models && p.models[0]) || prompt(`Model to test ${p.id} with:`);
    if (!model) return;
    setTests((t) => ({ ...t, [p.id]: { pending: true } }));
    try {
      await send("/api/brains", { providers, agents }, "PUT");
      const r = await send("/api/brains/test", { provider: p.id, model });
      setTests((t) => ({ ...t, [p.id]: r }));
    } catch (err) { setTests((t) => ({ ...t, [p.id]: { ok: false, error: err.message } })); }
  };
  const copy = async (key, text) => { try { await navigator.clipboard.writeText(text); setCopied(key); setTimeout(() => setCopied(null), 1500); } catch { alert(text); } };
  const cmd = b.mcp_command.map((s) => s.includes(" ") ? `"${s}"` : s).join(" ");
  const external = [
    ["Codex", `codex mcp add shorts-factory -- ${cmd}`],
    ["Claude Code", `claude mcp add shorts-factory -- ${cmd}`],
    ["Gemini CLI (~/.gemini/settings.json)", JSON.stringify({ mcpServers: { "shorts-factory": { command: b.mcp_command[0], args: b.mcp_command.slice(1) } } }, null, 2)],
  ];
  const ready = b.readiness;

  return html`
    <div class="card">
      <h3>Brains</h3>
      <div class="hint" style=${{ marginBottom: 12 }}>Two ways to run an agent. <b>External</b>: any MCP-capable agent — Codex, Claude Code, Gemini CLI — reads the playbooks and calls this factory's tools; nothing to configure here beyond registering the server once. <b>Built-in</b>: the factory calls a model itself for Plan, Build and Digest; pick a provider and model per agent below. Keys never go through this page — only the name of the variable in <code>.env</code>.</div>

      <div class="hint" style=${{ margin: "12px 0 6px", color: "var(--ink)" }}>External agents — register this factory once, then use the playbooks</div>
      ${external.map(([name, text]) => html`
        <div key=${name} class="row">
          <span class="hint" style=${{ width: 210 }}>${name}</span>
          <pre class="captured" style=${{ margin: 0, flex: 1, maxHeight: 90, overflow: "auto" }}>${text}</pre>
          <button class="small" onClick=${() => copy(name, text)}>${copied === name ? "Copied" : "Copy"}</button>
        </div>`)}

      <div class="hint" style=${{ margin: "18px 0 6px", color: "var(--ink)" }}>Built-in providers</div>
      <table>
        <thead><tr><th>id</th><th>kind</th><th>endpoint</th><th>key variable</th><th>sees images</th><th>JSON</th><th>models (comma-separated)</th><th></th></tr></thead>
        <tbody>
          ${providers.map((p, i) => html`
            <tr key=${i}>
              <td><input value=${p.id} onChange=${(e) => setP(i, "id", e.target.value)} style=${{ width: 100 }} /></td>
              <td><select value=${p.kind} onChange=${(e) => setP(i, "kind", e.target.value)}><option value="anthropic">anthropic</option><option value="openai">openai-compatible</option></select></td>
              <td><input value=${p.base_url || ""} disabled=${p.kind === "anthropic"} placeholder="http://localhost:11434/v1" onChange=${(e) => setP(i, "base_url", e.target.value)} style=${{ width: 250 }} /></td>
              <td><input value=${p.api_key_env || ""} placeholder="none (local)" onChange=${(e) => setP(i, "api_key_env", e.target.value)} style=${{ width: 150 }} />
                <div class="hint">${!p.api_key_env ? "no key needed" : p.key_present ? html`<span class="good">set in .env</span>` : html`<span class="bad">not set in .env</span>`}</div></td>
              <td><input type="checkbox" checked=${!!p.vision} onChange=${(e) => setP(i, "vision", e.target.checked)} /></td>
              <td><select value=${p.json_mode} onChange=${(e) => setP(i, "json_mode", e.target.value)}><option value="schema">schema</option><option value="object">object</option><option value="none">none</option></select></td>
              <td><input value=${(p.models || []).join(", ")} onChange=${(e) => setP(i, "models", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} style=${{ width: 220 }} /></td>
              <td style=${{ whiteSpace: "nowrap" }}>
                <button class="small" onClick=${() => test(p)} disabled=${tests[p.id]?.pending}>${tests[p.id]?.pending ? "Testing…" : "Test"}</button>
                <button class="small" onClick=${() => setProviders(providers.filter((_, j) => j !== i))}>Remove</button>
                ${tests[p.id] && !tests[p.id].pending ? html`<div class=${"hint " + (tests[p.id].ok ? "good" : "bad")}>${tests[p.id].ok ? `ok · ${tests[p.id].latency_ms} ms · "${tests[p.id].reply}"` : tests[p.id].error}</div>` : null}
              </td>
            </tr>`)}
        </tbody>
      </table>
      <div class="row">
        <select onChange=${addPreset} defaultValue="">
          <option value="">Add a provider…</option>
          ${b.presets.map((p) => html`<option key=${p.id} value=${p.id}>${p.id}${p.free ? " (local, free)" : ""}</option>`)}
          <option value="custom">custom endpoint</option>
        </select>
      </div>

      <div class="hint" style=${{ margin: "18px 0 6px", color: "var(--ink)" }}>Which model each built-in agent uses</div>
      <table>
        <thead><tr><th>agent</th><th>does</th><th>provider</th><th>model</th><th>ready?</th></tr></thead>
        <tbody>
          ${Object.keys(agents).map((a) => {
            const [pid, model] = [agents[a].split("/")[0], agents[a].split("/").slice(1).join("/")];
            const prov = providers.find((p) => p.id === pid);
            const r = ready[a] || {};
            const does = { idea: "picks what to make", metadata: "writes the title", qc: "judges four frames — needs a model that sees images", analyst: "reads the numbers, proposes rules" }[a];
            return html`
              <tr key=${a}>
                <td><b>${a}</b></td><td class="hint">${does}</td>
                <td><select value=${pid} onChange=${(e) => setAgents({ ...agents, [a]: `${e.target.value}/${model}` })}>
                  ${providers.map((p) => html`<option key=${p.id} value=${p.id} disabled=${b.needs_vision.includes(a) && !p.vision}>${p.id}${b.needs_vision.includes(a) && !p.vision ? " (no images)" : ""}</option>`)}</select></td>
                <td><input list=${`models-${pid}`} value=${model} onChange=${(e) => setAgents({ ...agents, [a]: `${pid}/${e.target.value}` })} style=${{ width: 220 }} />
                  <datalist id=${`models-${pid}`}>${(prov?.models || []).map((m) => html`<option key=${m} value=${m} />`)}</datalist></td>
                <td>${r.ok ? html`<span class="good">ready${r.free ? " · free" : ""}</span>` : html`<span class="bad">${r.why || "—"}</span>`}</td>
              </tr>`;
          })}
        </tbody>
      </table>
      <div class="row" style=${{ marginTop: 10 }}>
        <button class="ok" onClick=${save} disabled=${saving}>${saving ? "Saving…" : "Save brains"}</button>
        <span class="hint">${b.overridden ? "set on this page (config.toml is the default underneath)" : "from config.toml"}</span>
      </div>
    </div>`;
}

/* ---------- FactorySettings: every knob, rendered from the schema ---------- */

function FactorySettings() {
  const [s, setS] = useState(null);
  const load = useCallback(() => api("/api/settings").then(setS), []);
  useEffect(() => { load().catch((err) => alert(err.message)); }, [load]);
  if (!s) return null;
  const put = async (f, value) => {
    try { setS(await send("/api/settings", { section: f.section, key: f.key, value }, "PUT")); }
    catch (err) { alert(err.message); }
  };
  const reset = async (f) => {
    try { setS(await api(`/api/settings/${f.section}/${f.key}`, { method: "DELETE" })); }
    catch (err) { alert(err.message); }
  };
  const groups = [...new Set(s.fields.map((f) => f.section))];
  return html`
    <div class="card">
      <h3>Factory settings</h3>
      <div class="hint" style=${{ marginBottom: 12 }}>config.toml is the default. A value changed here is stored in the database as an override, marked, and can be reset. Changes apply to the next render or QC, not to clips already made.</div>
      ${groups.map((g) => html`
        <div key=${g} class="hint" style=${{ margin: "12px 0 4px", color: "var(--ink)", textTransform: "uppercase", fontSize: 11, letterSpacing: ".08em" }}>${g}</div>
        ${s.fields.filter((f) => f.section === g).map((f) => html`
          <div key=${f.key} class="row" style=${{ alignItems: "flex-start" }}>
            <div style=${{ width: 260 }}><div style=${{ fontSize: 13 }}>${f.label}</div>${f.help ? html`<div class="hint">${f.help}</div>` : null}</div>
            ${f.type === "select" ? html`<select value=${String(f.value)} onChange=${(e) => put(f, e.target.value)}>${f.options.map((o) => html`<option key=${o} value=${String(o)}>${o}</option>`)}</select>`
            : f.type === "number" ? html`<input type="number" defaultValue=${f.value} min=${f.min} max=${f.max} step=${f.step} onBlur=${(e) => { if (String(e.target.value) !== String(f.value)) put(f, e.target.value); }} style=${{ width: 120, flex: "none" }} />`
            : html`<input defaultValue=${f.value} onBlur=${(e) => { if (e.target.value !== f.value) put(f, e.target.value); }} style=${{ width: 260, flex: "none" }} />`}
            ${f.overridden ? html`<span class="hint">override · default ${String(f.default)} <button class="small" onClick=${() => reset(f)}>reset</button></span>` : html`<span class="hint">default</span>`}
          </div>`)}`)}
    </div>`;
}

function Rules({ rules: r, channelId, reload }) {
  const [text, setText] = useState(r.text);
  useEffect(() => setText(r.text), [r.text]);
  const save = async () => { try { await send("/api/rules", { channel: channelId, text }, "PUT"); await reload(); } catch (err) { alert(err.message); } };
  const accept = async (rule) => { try { await send("/api/rules/accept", { channel: channelId, rules: [rule] }); await reload(); } catch (err) { alert(err.message); } };
  return html`
    <div class="card">
      <h3>Rules the agents read</h3>
      <div class="hint" style=${{ marginBottom: 10 }}>${r.path} — the Idea and Metadata agents read this on every run. The Analyst proposes additions on the right; nothing lands without you accepting it.</div>
      <div style=${{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 320px", gap: 18 }}>
        <div><textarea value=${text} spellCheck="false" onChange=${(e) => setText(e.target.value)} /><div class="row"><button onClick=${save}>Save rules</button></div></div>
        <div>
          ${r.proposals.map((p) => html`<div key=${p} class="card"><div style=${{ fontSize: 13.5, lineHeight: 1.6, marginBottom: 10 }}>${p}</div><button class="ok small" onClick=${() => accept(p)}>Accept</button></div>`)}
          ${!r.proposals.length ? html`<div class="note">No pending proposals${r.digest ? ` (last digest: ${r.digest.n_published} clips with metrics)` : ""}. The Analyst writes nothing below the sample threshold.</div>` : null}
        </div>
      </div>
    </div>`;
}

function AddChannel({ onDone }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [handle, setHandle] = useState("");
  const create = async (e) => {
    e.preventDefault();
    try { await send("/api/channels", { name, handle: handle || null }); } catch (err) { alert(err.message); return; }
    setOpen(false); setName(""); setHandle(""); onDone();
  };
  if (!open) return html`<button class="small" onClick=${() => setOpen(true)}>Add another channel</button>`;
  return html`
    <div class="card"><h3>New channel</h3>
      <form class="grid" onSubmit=${create}>
        <label>name</label><input value=${name} onChange=${(e) => setName(e.target.value)} placeholder="HODL Tales" required />
        <label>handle</label><input value=${handle} onChange=${(e) => setHandle(e.target.value)} placeholder="@handle (optional)" />
        <span></span><div class="row"><button type="submit">Create</button><button type="button" onClick=${() => setOpen(false)}>Cancel</button></div>
      </form>
    </div>`;
}

createRoot(document.getElementById("root")).render(html`<${App} />`);
