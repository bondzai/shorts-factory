import { html, useState, useEffect, useRef, useCallback, api, send, fmt, num, pct, when, clock, statusWord, channelQuery, toast, act, useCopy, download } from "../lib.js";
import { Screen, Card, Chip, StepStrip } from "../ui.js";

function Queue({ snap, channelId, refresh, open }) {
  const [body, setBody] = useState(null);
  const [kind, setKind] = useState("make-clip");
  const [params, setParams] = useState({});
  const [count, setCount] = useState(1);
  const [standing, setStanding] = useState("");
  const [copied, setCopied] = useState(false);
  const load = useCallback(() => api(`/api/tasks?channel=${encodeURIComponent(channelId)}`).then(setBody), [channelId]);
  useEffect(() => { load().catch((err) => toast(err.message, "error")); }, [load, snap?.tasks?.queued, snap?.tasks?.claimed, snap?.tasks?.done]);
  useEffect(() => { api(`/api/playbook/work?channel=${encodeURIComponent(channelId)}`).then((b) => setStanding(b.text)).catch(() => {}); }, [channelId]);
  if (!body) return html`<p class="empty">loading…</p>`;

  const spec = body.kinds[kind] || { params: {} };
  const variants = snap.channel.variants || [];
  const add = async (e) => {
    e.preventDefault();
    try { await send("/api/tasks", { channel: channelId, kind, params, count: Number(count) }); }
    catch (err) { toast(err.message, "error"); return; }
    setParams({}); setCount(1); await load(); refresh();
  };
  const cancel = async (id) => {
    try { await api(`/api/tasks/${id}`, { method: "DELETE" }); } catch (err) { toast(err.message, "error"); return; }
    await load(); refresh();
  };
  const runBuiltin = async () => {
    try { await send("/api/tasks/work", { channel: channelId }); } catch (err) { toast(err.message, "error"); return; }
    refresh();
  };
  const copy = async () => { try { await navigator.clipboard.writeText(standing); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { toast("Could not reach the clipboard — select the text and copy it.", "error"); } };
  const tone = (s) => s === "done" ? "good" : s === "failed" ? "bad" : s === "claimed" ? "warn" : "";
  const active = body.tasks.filter((t) => t.status === "claimed");
  const strip = (t) => html`<${StepStrip} steps=${t.steps} when=${when} />`;
  const paramInput = (k) => {
    if (k === "background") return html`<label key=${k} class="row" style=${{ margin: 0, gap: 6 }} title="backdrop colour; unticked lets the theme choose">
      <input type="checkbox" checked=${!!params.background} onChange=${(e) => setParams({ ...params, background: e.target.checked ? "#1a1a2a" : "" })} />
      <span class="hint">backdrop</span>
      ${params.background ? html`<input type="color" value=${params.background} onChange=${(e) => setParams({ ...params, background: e.target.value })} />` : null}
    </label>`;
    if (k === "variant") return html`<select key=${k} value=${params.variant || ""} onChange=${(e) => setParams({ ...params, variant: e.target.value, generator: e.target.value.split("/")[0] })}>
      <option value="">variant…</option>${variants.map((v) => html`<option key=${v} value=${v.split("/")[1]}>${v}</option>`)}</select>`;
    if (k === "course") return html`<select key=${k} value=${params.course || ""} onChange=${(e) => setParams({ ...params, course: e.target.value })} title="the shape of the descent; empty lets the seed choose">
      <option value="">any course</option><option value="zigzag">zigzag</option><option value="pegboard">pegboard</option><option value="bumpers">bumpers</option></select>`;
    if (k === "generator") return null;
    return html`<input key=${k} placeholder=${k} value=${params[k] ?? ""} onChange=${(e) => setParams({ ...params, [k]: e.target.value })} style=${{ width: 110, flex: "none" }} />`;
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
        ${kind === "make-clip" ? html`<label class="row" style=${{ margin: 0, gap: 6 }}><span class="hint">×</span><input type="number" min="1" max="50" value=${count} onChange=${(e) => setCount(e.target.value)} style=${{ width: 64, flex: "none" }} title="how many" /></label>` : null}
        <button type="submit" class="ok">Add to queue</button>
        <span class="hint">${spec.builtin ? "built-in agents can do this" : "needs an external agent's judgement"}</span>
      </form>
    </div>
    <${Directions} channelId=${channelId} />
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

/* ---------- Directions: what every agent is told, without touching a playbook ---------- */

function Directions({ channelId }) {
  const [d, setD] = useState(null);
  const [values, setValues] = useState({});
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState(false);
  useEffect(() => { api(`/api/directions?channel=${encodeURIComponent(channelId)}`).then((b) => { setD(b); setValues(Object.fromEntries(b.fields.map((f) => [f.key, f.value]))); }).catch(() => {}); }, [channelId]);
  if (!d) return null;
  const filled = d.fields.filter((f) => f.value).length;
  const save = async () => {
    try { const out = await send("/api/directions", { channel: channelId, values }, "PUT"); setD(out); setSaved(true); setTimeout(() => setSaved(false), 1500); }
    catch (err) { toast(err.message, "error"); }
  };
  return html`
    <div class="card">
      <div class="row" style=${{ margin: 0, cursor: "pointer" }} onClick=${() => setOpen(!open)}>
        <h3 style=${{ margin: 0 }}>What every agent is told</h3>
        <span class="hint">${filled ? `${filled} of ${d.fields.length} set` : "nothing yet — the playbooks alone"} · ${open ? "hide" : "edit"}</span>
      </div>
      ${open ? html`
        <div class="hint" style=${{ margin: "8px 0 12px" }}>Five short notes in your own words. They are appended to every playbook and every task's instructions, and they win over anything in the playbook that disagrees — so you never edit a playbook to change how titles sound.</div>
        ${d.fields.map((f) => html`
          <div key=${f.key} class="row" style=${{ alignItems: "flex-start" }}>
            <div style=${{ width: 220, flex: "none" }}><div style=${{ fontSize: 13 }}>${f.label}</div></div>
            <textarea rows="2" placeholder=${f.placeholder} value=${values[f.key] || ""} onChange=${(e) => setValues({ ...values, [f.key]: e.target.value })} style=${{ minHeight: 0, font: "inherit", fontSize: 13 }}></textarea>
          </div>`)}
        <div class="row"><button class="ok" onClick=${save}>${saved ? "Saved" : "Save directions"}</button><span class="hint">applies to the next task an agent pulls</span></div>` : null}
    </div>`;
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
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { toast("Select the text and copy it."); }
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

export { Queue, Directions, Playbooks };
