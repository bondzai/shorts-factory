// The review flow: one clip at a time, its words editable in place, Approve
// or Reject, and A/R/J/K on the keyboard. Team's "Your decisions" uses it for
// clips to review and for approved clips on a hand-published channel.
import { useEffect, useRef, useState } from "react";
import { api, q, send } from "../lib/api";
import { fmt, download } from "../lib/format";
import { act, toast } from "../lib/toast";
import type { Clip, Snap } from "../lib/types";

/* A carousel over one list of clips: the card, a strip to jump, and J/K. */
export function Flow({ items, keys, sound, refresh, decide, channelId, onOpen, auto }: {
  items: Clip[]; keys: boolean; sound: boolean; refresh: () => Promise<void>; decide: (id: string, what: "approve" | "reject") => void; channelId: string; onOpen: (id: string) => void; auto: boolean;
}) {
  const [index, setIndex] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const safe = Math.min(index, Math.max(0, items.length - 1));
  const current = items[safe];
  useEffect(() => {
    if (!keys) return;
    const onKey = (event: KeyboardEvent) => {
      if ((event.target as HTMLElement)?.matches?.("input, textarea, select, button")) return;
      if (event.metaKey || event.ctrlKey || event.altKey || !current) return;
      if (document.querySelector(".drawer, .modal")) return;
      const pending = current.status !== "approved";
      if (pending && /^[aA]$/.test(event.key)) decide(current.id, "approve");
      else if (pending && /^[rR]$/.test(event.key)) decide(current.id, "reject");
      else if (/^[jJ]$/.test(event.key)) setIndex((i) => Math.min(i + 1, items.length - 1));
      else if (/^[kK]$/.test(event.key)) setIndex((i) => Math.max(i - 1, 0));
      else if (event.key === " ") { const p = box.current?.querySelector("video"); if (p) { event.preventDefault(); p.paused ? p.play() : p.pause(); } }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [keys, current, items.length, decide]);
  if (!current) return null;
  return (
    <div ref={box}>
      <ClipCard key={current.id} clip={current} sound={sound} refresh={refresh} decide={decide} channelId={channelId} onOpen={onOpen} auto={auto}
        position={items.length > 1 ? `${safe + 1} of ${items.length}` : ""} keys={keys} />
      {items.length > 1 && (
        <div className="strip" role="group" aria-label="Jump to clip">
          {items.map((c, i) => <button key={c.id} className="sm" aria-current={i === safe} onClick={() => setIndex(i)}>{i + 1}. {(c.title || c.id).slice(0, 32)}</button>)}
        </div>
      )}
    </div>
  );
}

function ClipCard({ clip: c, sound, refresh, decide, position, channelId, onOpen, auto, keys }: {
  clip: Clip; sound: boolean; refresh: () => Promise<void>; decide: (id: string, what: "approve" | "reject") => void; position: string; channelId: string; onOpen: (id: string) => void; auto: boolean; keys: boolean;
}) {
  const ready = c.status === "approved";
  const [title, setTitle] = useState(c.title || "");
  const [hook, setHook] = useState(c.hook_text || "");
  const [backdrop, setBackdrop] = useState(String(c.facts?.backdrop || "#1a1a2a"));
  const [customBackdrop, setCustomBackdrop] = useState(false);
  const [prompt, setPrompt] = useState(c.comment_prompt || "");
  const [desc, setDesc] = useState(c.description || "");
  const [rendering, setRendering] = useState(false);
  const [version, setVersion] = useState(0);
  const [copied, setCopied] = useState(false);
  const [slot, setSlot] = useState<string>("");
  useEffect(() => { api<{ schedule_text: string }>(`/api/clip/${c.id}/upload_text`).then((b) => setSlot(b.schedule_text)).catch(() => {}); }, [c.id]);
  const qc = c.qc || {};

  const saveText = () => act(async () => {
    const body: Record<string, string> = { comment_prompt: prompt.trim() };
    if (title.trim() !== (c.title || "")) body.title = title.trim();
    if (desc.trim() !== (c.description || "")) body.description = desc.trim();
    const out = await send<{ needs_manual_update?: boolean }>(`/api/clip/${c.id}/text`, body, "PATCH");
    if (out.needs_manual_update) toast("Saved. This clip is published on a manual channel — change the title in YouTube Studio too.");
  }, { ok: "Saved", after: refresh });

  const rerender = async () => {
    const text = hook.trim();
    if (!text && !customBackdrop) { toast("Change the caption or tick a backdrop first.", "error"); return; }
    const body: Record<string, string> = { text };
    if (customBackdrop) body.background = backdrop;
    const started = await act(() => send(`/api/clip/${c.id}/hook`, body));
    if (started === undefined) return;
    setRendering(true);
    for (let tick = 0; tick < 240; tick++) {
      await new Promise((r) => setTimeout(r, 1500));
      try { const s = await api<Snap>(`/api/state?${q({ channel: channelId })}`); if (!s.job.running) break; } catch { /* keep waiting */ }
    }
    setRendering(false); setVersion((v) => v + 1); await refresh();
  };
  const copy = async () => {
    // The server lays it out under headings (TITLE, DESCRIPTION, HASHTAGS,
    // PINNED COMMENT, SCHEDULE, METADATA) so nothing lands in the wrong box.
    try {
      const out = await api<{ text: string }>(`/api/clip/${c.id}/upload_text`);
      await navigator.clipboard.writeText(out.text); setCopied(true); setTimeout(() => setCopied(false), 1500);
    } catch { toast("Could not reach the clipboard — open Details and copy from there.", "error"); }
  };
  const uploaded = () => {
    const ask = auto
      ? `Upload this clip to YouTube now?\n\nIt goes up private and YouTube makes it public at ${slot || "the next slot"}.`
      : "Mark this clip as uploaded? It moves to published and leaves this screen.";
    if (!window.confirm(ask)) return;
    act(() => send<{ detail: string }>(`/api/clip/${c.id}/publish`),
        { ok: auto ? "Uploaded to YouTube" : "Marked as uploaded", after: refresh });
  };

  return (
    <div className="clip">
      <video key={`${c.id}-${version}`} src={`/api/clip/${c.id}/video?v=${version}`} autoPlay loop playsInline muted={!sound} controls />
      <div className="stack">
        <input className="title" aria-label="Title" value={title} maxLength={90} spellCheck={false} placeholder="title (20-90 characters)" onChange={(e) => setTitle(e.target.value)} />
        <div className="row wrap">
          <input className="grow" aria-label="Opening caption" value={hook} maxLength={28} spellCheck={false} placeholder="opening caption, burned into the first seconds" onChange={(e) => setHook(e.target.value)} disabled={rendering} />
          <label className="row small dim" title="tick to choose the backdrop colour; untick to go back to the theme">
            <input type="checkbox" checked={customBackdrop} onChange={(e) => setCustomBackdrop(e.target.checked)} disabled={rendering || c.status === "published"} /> backdrop
            {customBackdrop && <input type="color" value={backdrop} onChange={(e) => setBackdrop(e.target.value)} />}
          </label>
          <button className="sm" onClick={rerender} disabled={rendering}>{rendering ? "Re-rendering…" : "Re-render"}</button>
        </div>
        <textarea aria-label="Description" value={desc} maxLength={900} spellCheck={false} rows={4} placeholder="description (20-900 characters); the first sentence shows in the feed and is checked like a title" onChange={(e) => setDesc(e.target.value)} />
        <input aria-label="Pinned comment" value={prompt} maxLength={140} spellCheck={false} placeholder="question to pin as the first comment" onChange={(e) => setPrompt(e.target.value)} />
        <div className="row wrap">
          <button className="sm" onClick={saveText}>Save text</button>
          <button className="sm" onClick={copy}>{copied ? "Copied" : "Copy for upload"}</button>
          <button className="sm ghost" onClick={() => onOpen(c.id)}>Details</button>
          {c.title_history?.length ? <span className="hint">retitled {c.title_history.length}×</span> : null}
        </div>
        <div className="tags">{(c.hashtags || []).join(" ")}</div>
        <dl className="facts">
          <dt>clip</dt><dd>{c.id} · {c.generator}/{c.variant} · seed {c.seed}</dd>
          <dt>shows</dt><dd>{c.render_desc || "—"}</dd>
          <dt>length</dt><dd>{fmt(c.duration_s)}s · {fmt(c.loudness_lufs)} LUFS · sameness {fmt(c.sameness, 3)}</dd>
          <dt>QC</dt><dd>{qc.verdict ? <>hook {qc.hook_strength ?? "—"}/5 · policy {qc.policy_risk ?? "—"}</> : "not judged"}{(qc.reasons || []).map((r) => <div key={r} className="hint">{r}</div>)}</dd>
        </dl>
        <div className="row wrap">
          {ready ? (
            <>
              <button onClick={() => download(c.id)}>Download</button>
              <button className={auto ? "" : "primary"} onClick={uploaded}>{auto ? "Upload this one now" : "I uploaded it"}</button>
              <span className="hint">{auto
                ? `approved — uploads private, public at ${slot || "the next slot"}`
                : `approved — download, upload by hand${slot ? `, schedule for ${slot}` : ""}, then mark it`}</span>
            </>
          ) : (
            <>
              <button className="primary" onClick={() => decide(c.id, "approve")}>Approve{keys && <kbd>A</kbd>}</button>
              <button className="danger" onClick={() => decide(c.id, "reject")}>Reject{keys && <kbd>R</kbd>}</button>
            </>
          )}
          {position && <span className="hint right">{position}{keys && <> · <kbd>J</kbd> <kbd>K</kbd> to move</>}</span>}
        </div>
      </div>
    </div>
  );
}
