import { html, useState, useEffect, useRef, useCallback, api, send, fmt, num, pct, when, clock, statusWord, channelQuery, toast, act, useCopy, download } from "../lib.js";
import { Screen, Card, Chip, StepStrip } from "../ui.js";

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
  useEffect(() => { load().catch((err) => toast(err.message, "error")); }, [load]);

  const toggle = (key, value) => setFilters((f) => ({ ...f, [key]: f[key] === value ? "" : value }));
  const restore = async (id) => {
    try { await send(`/api/clip/${id}/restore`, {}); } catch (err) { toast(err.message, "error"); return; }
    await load(); refresh();
  };
  const pick = (id) => setPicked((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const pickAll = (ids) => setPicked((p) => p.size === ids.length ? new Set() : new Set(ids));
  const act = async (path, confirmText) => {
    if (confirmText && !confirm(confirmText)) return;
    try { await send(path, { ids: [...picked] }); } catch (err) { toast(err.message, "error"); return; }
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
              ${c.has_video ? html`<button class="small" onClick=${() => { download(c.id); }}>Download</button>` : html`<span class="hint">no file</span>`}
              ${!bin && c.status === "qc_rejected" && c.has_video && !(c.reject_reason || "").startsWith("too similar")
                ? html` <button class="small" onClick=${() => restore(c.id)}>Back to queue</button>` : null}
            </td>
          </tr>`)}
        ${!clips.length ? html`<tr><td colSpan="8" class="empty">${bin ? "The bin is empty." : "Nothing matches."}</td></tr>` : null}
      </tbody>
    </table>`;
}

/* ---------- Results: numbers, and the two levers left on a published clip ---------- */

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
    try { await send(path, body || {}); } catch (e) { toast(e.message); return; }
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
              ${c.file.exists ? html`<button class="small" onClick=${() => { download(c.id); }}>Download (${c.file.mb} MB)</button>` : null}
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

export { Clips, ClipTable, ClipDrawer };
