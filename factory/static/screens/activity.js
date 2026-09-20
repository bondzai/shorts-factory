import { html, useState, useEffect, useRef, useCallback, api, send, fmt, num, pct, when, clock, statusWord, channelQuery, toast, act, useCopy, download } from "../lib.js";
import { Screen, Card, Chip, StepStrip } from "../ui.js";

function Activity({ channelId }) {
  const [runs, setRuns] = useState(null);
  const [events, setEvents] = useState(null);
  const [level, setLevel] = useState("");
  const [actor, setActor] = useState("");
  useEffect(() => {
    const q = `channel=${encodeURIComponent(channelId)}`;
    Promise.all([api(`/api/runs?${q}`), api(`/api/logs?${q}&limit=300`)])
      .then(([r, l]) => { setRuns(r.runs); setEvents(l.events); })
      .catch((err) => toast(err.message, "error"));
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

export { Activity };
