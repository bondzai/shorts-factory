import { html, useState, useEffect, useRef, useCallback, api, send, fmt, num, pct, when, clock, statusWord, channelQuery, toast, act, useCopy, download } from "../lib.js";
import { Screen, Card, Chip, StepStrip } from "../ui.js";

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
    try { await send(`/api/clip/${id}/${what}`, body); } catch (err) { toast(err.message, "error"); }
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
  const [backdrop, setBackdrop] = useState((c.facts && c.facts.backdrop) || "");
  const [customBackdrop, setCustomBackdrop] = useState(false);
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
      if (out.needs_manual_update) toast("Saved. This clip is published on a manual channel — change the title in YouTube Studio too.");
    } catch (err) { toast(err.message, "error"); return; }
    refresh();
  };
  const rehook = async () => {
    const text = hook.trim();
    const body = { text };
    if (customBackdrop) body.background = backdrop || "";
    if (!text && !customBackdrop) { toast("Change the caption or tick a backdrop first."); return; }
    try { await send(`/api/clip/${c.id}/hook`, body); } catch (err) { toast(err.message, "error"); return; }
    setRendering(true);
    // Wait here, not on another screen. A race re-renders in about a minute.
    for (let tick = 0; tick < 240; tick++) {
      await new Promise((r) => setTimeout(r, 1500));
      let latest;
      try { latest = await api(`/api/state?${channelQuery(channelId)}`); } catch { continue; }
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
    catch { toast("Could not reach the clipboard — select the text and copy it.", "error"); }
  };
  const uploaded = async () => {
    if (!confirm("Mark this clip as uploaded? It moves to published and leaves this screen.")) return;
    try { await send(`/api/clip/${c.id}/publish`, {}); } catch (err) { toast(err.message, "error"); return; }
    refresh();
  };

  return html`
    <div class="clip">
      <video key=${`${c.id}-${version}`} src=${`/api/clip/${c.id}/video?v=${version}`} autoPlay loop playsInline muted=${!sound} controls />
      <div>
        <input class="title" value=${title} maxLength="90" spellCheck="false" placeholder="title (20-90 characters)" onChange=${(e) => setTitle(e.target.value)} />
        <div class="row">
          <input value=${hook} maxLength="28" spellCheck="false" placeholder="opening caption, burned into the first seconds" onChange=${(e) => setHook(e.target.value)} disabled=${rendering} />
          <label class="row" style=${{ margin: 0, gap: 6, flex: "none" }} title="tick to choose the backdrop colour; untick to go back to the theme">
            <input type="checkbox" checked=${customBackdrop} onChange=${(e) => setCustomBackdrop(e.target.checked)} disabled=${rendering || c.status === "published"} />
            <span class="hint">backdrop</span>
            ${customBackdrop ? html`<input type="color" value=${backdrop || "#1a1a2a"} onChange=${(e) => setBackdrop(e.target.value)} />` : null}
          </label>
          <button class="small" onClick=${rehook} disabled=${rendering}>${rendering ? "Re-rendering…" : "Re-render"}</button>
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
            <button class="ok" onClick=${() => { download(c.id); }}>Download clip</button>
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

export { Today, ClipCard };
