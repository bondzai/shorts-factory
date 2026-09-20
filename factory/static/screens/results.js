import { html, useState, useEffect, useRef, useCallback, api, send, fmt, num, pct, when, clock, statusWord, channelQuery, toast, act, useCopy, download } from "../lib.js";
import { Screen, Card, Chip, StepStrip } from "../ui.js";

function Results({ channelId, refresh, open }) {
  const [a, setA] = useState(null);
  const [published, setPublished] = useState(null);
  const load = useCallback(async () => {
    const q = `channel=${encodeURIComponent(channelId)}`;
    const [analytics, clips] = await Promise.all([api(`/api/analytics?${q}`), api(`/api/clips?${q}&status=published`)]);
    setA(analytics); setPublished(clips.clips);
  }, [channelId]);
  useEffect(() => { load().catch((err) => toast(err.message, "error")); }, [load]);
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
      if (out.needs_manual_update) toast("Saved here. Change it in YouTube Studio too — nothing reaches YouTube by itself on a manual channel."); }
    catch (err) { toast(err.message, "error"); return; }
    setMode(null); onChanged();
  };
  const saveMetrics = async () => {
    try { await send(`/api/clip/${c.id}/metrics`, { views: Number(m.views), avg_view_pct: Number(m.avg_view_pct), swipe_away_pct: Number(m.swipe_away_pct), likes: Number(m.likes || 0) }); }
    catch (err) { toast(err.message, "error"); return; }
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
        ${mode ? null : html`<button class="small" onClick=${() => open(c.id)}>View</button> <button class="small" onClick=${() => setMode("metrics")}>Enter metrics</button> <button class="small" onClick=${() => setMode("retitle")}>Retitle</button>${c.has_video ? html` <button class="small" onClick=${() => { download(c.id); }}>Download</button>` : null}`}
      </td>
    </tr>`;
}

/* ---------- Activity: runs are the chapters, events are the lines ---------- */

export { Results, PublishedRow };
