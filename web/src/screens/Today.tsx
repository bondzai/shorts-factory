import { useCallback, useEffect, useState } from "react";
import { api, q, send } from "../lib/api";
import { fmt, download } from "../lib/format";
import { act, toast } from "../lib/toast";
import { Page, Card, StepStrip } from "../ui";
import type { Clip, Snap, Task } from "../lib/types";

export function Today({ snap, channelId, refresh, sound, setSound, onOpen }: {
  snap: Snap; channelId: string; refresh: () => Promise<void>; sound: boolean; setSound: (v: boolean) => void; onOpen: (id: string) => void;
}) {
  const items = [...snap.queue, ...snap.approved];
  const [index, setIndex] = useState(0);
  const safe = Math.min(index, Math.max(0, items.length - 1));
  const current = items[safe];

  const decide = useCallback(async (id: string, what: "approve" | "reject") => {
    let body: Record<string, string> = {};
    if (what === "reject") {
      const reason = window.prompt("Why? This is what the next planner reads. Cancel keeps the clip.", "");
      if (reason === null) return;
      body = { reason: reason.trim() || "rejected in review" };
    }
    await act(() => send(`/api/clip/${id}/${what}`, body), { after: refresh });
  }, [refresh]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.target as HTMLElement)?.matches?.("input, textarea, select")) return;
      if (!current) return;
      const pending = current.status !== "approved";
      if (pending && /^[aA]$/.test(event.key)) decide(current.id, "approve");
      else if (pending && /^[rR]$/.test(event.key)) decide(current.id, "reject");
      else if (/^[jJ]$/.test(event.key)) setIndex((i) => Math.min(i + 1, items.length - 1));
      else if (/^[kK]$/.test(event.key)) setIndex((i) => Math.max(i - 1, 0));
      else if (event.key === " ") { event.preventDefault(); const p = document.querySelector("video"); if (p) p.paused ? p.play() : p.pause(); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [current, items.length, decide]);

  if (!items.length) {
    return (
      <Page title={`Nothing waiting on ${snap.channel.name}`}
        lead={snap.planned ? `${snap.planned} clip(s) are planned — press Build planned.` : snap.agents?.available ? "Press Plan to ask for ideas, then Build planned." : "Add work on the Clips screen; an agent renders it and it shows up here."}>
        <LiveNow snap={snap} channelId={channelId} />
        <Card hint="Every clip you have handled is under Clips, each with View and Download while its file is kept." />
      </Page>
    );
  }
  return (
    <Page title={`${snap.queue.length} to decide · ${snap.approved.length} to upload`}
      action={<button className="sm" onClick={() => setSound(!sound)}>Sound: {sound ? "on" : "off"}</button>}>
      <LiveNow snap={snap} channelId={channelId} />
      <ClipCard key={current.id} clip={current} sound={sound} refresh={refresh} decide={decide} channelId={channelId} position={`${safe + 1} of ${items.length}`} onOpen={onOpen} />
      <div className="strip">
        {items.map((c, i) => <button key={c.id} className="sm" aria-current={i === safe} onClick={() => setIndex(i)}>{c.status === "approved" ? "✓ " : ""}{i + 1}. {(c.title || c.id).slice(0, 32)}</button>)}
      </div>
    </Page>
  );
}

/* What is happening right now: each claimed task, who holds it, which step
   it is on. Fetched whenever the snapshot changes, so it moves at the same
   rate as the rest of the screen. */
function LiveNow({ snap, channelId }: { snap: Snap; channelId: string }) {
  const [active, setActive] = useState<Task[]>([]);
  const claimed = snap.tasks?.claimed || 0;
  useEffect(() => {
    if (!claimed) { setActive([]); return; }
    api<{ items: Task[] }>(`/api/tasks?${q({ channel: channelId, status: "claimed", page_size: 25 })}`).then((b) => setActive(b.items)).catch(() => {});
  }, [channelId, claimed, snap.job?.log?.length]);
  if (!active.length && !snap.job?.running) return null;
  return (
    <Card title="Now" accent>
      {snap.job?.running && <div className="hint">{snap.job.name} is running · {snap.job.log[snap.job.log.length - 1] || ""}</div>}
      {active.map((t) => { const cur = t.steps.find((s) => s.state === "current"); const done = t.steps.filter((s) => s.state === "done").length;
        return <div key={t.id} className="stack mt-3"><div className="row"><b>#{t.id} {t.kind}</b><span className="hint">{t.claimed_by} is at <b>{cur ? cur.name : "…"}</b> — step {done + 1} of {t.steps.length}</span></div><StepStrip steps={t.steps} /></div>; })}
    </Card>
  );
}

function ClipCard({ clip: c, sound, refresh, decide, position, channelId, onOpen }: {
  clip: Clip; sound: boolean; refresh: () => Promise<void>; decide: (id: string, what: "approve" | "reject") => void; position: string; channelId: string; onOpen: (id: string) => void;
}) {
  const ready = c.status === "approved";
  const [title, setTitle] = useState(c.title || "");
  const [hook, setHook] = useState(c.hook_text || "");
  const [backdrop, setBackdrop] = useState(String(c.facts?.backdrop || "#1a1a2a"));
  const [customBackdrop, setCustomBackdrop] = useState(false);
  const [prompt, setPrompt] = useState(c.comment_prompt || "");
  const [rendering, setRendering] = useState(false);
  const [version, setVersion] = useState(0);
  const [copied, setCopied] = useState(false);
  const [slot, setSlot] = useState<string>("");
  useEffect(() => { api<{ schedule_text: string }>(`/api/clip/${c.id}/upload_text`).then((b) => setSlot(b.schedule_text)).catch(() => {}); }, [c.id]);
  const qc = c.qc || {};

  const saveText = () => act(async () => {
    const body: Record<string, string> = { comment_prompt: prompt.trim() };
    if (title.trim() !== (c.title || "")) body.title = title.trim();
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
    if (!window.confirm("Mark this clip as uploaded? It moves to published and leaves this screen.")) return;
    act(() => send(`/api/clip/${c.id}/publish`), { ok: "Marked as uploaded", after: refresh });
  };

  return (
    <div className="clip">
      <video key={`${c.id}-${version}`} src={`/api/clip/${c.id}/video?v=${version}`} autoPlay loop playsInline muted={!sound} controls />
      <div className="stack">
        <input className="title" value={title} maxLength={90} spellCheck={false} placeholder="title (20-90 characters)" onChange={(e) => setTitle(e.target.value)} />
        <div className="row wrap">
          <input className="grow" value={hook} maxLength={28} spellCheck={false} placeholder="opening caption, burned into the first seconds" onChange={(e) => setHook(e.target.value)} disabled={rendering} />
          <label className="row small dim" title="tick to choose the backdrop colour; untick to go back to the theme">
            <input type="checkbox" checked={customBackdrop} onChange={(e) => setCustomBackdrop(e.target.checked)} disabled={rendering || c.status === "published"} /> backdrop
            {customBackdrop && <input type="color" value={backdrop} onChange={(e) => setBackdrop(e.target.value)} />}
          </label>
          <button className="sm" onClick={rerender} disabled={rendering}>{rendering ? "Re-rendering…" : "Re-render"}</button>
        </div>
        <input value={prompt} maxLength={140} spellCheck={false} placeholder="question to pin as the first comment" onChange={(e) => setPrompt(e.target.value)} />
        <div className="row wrap">
          <button className="sm" onClick={saveText}>Save title & prompt</button>
          <button className="sm" onClick={copy}>{copied ? "Copied" : "Copy for upload"}</button>
          <button className="sm ghost" onClick={() => onOpen(c.id)}>Details</button>
          {c.title_history?.length ? <span className="hint">retitled {c.title_history.length}×</span> : null}
        </div>
        <div className="tags">{(c.hashtags || []).join(" ")}</div>
        <div className="desc">{c.description}</div>
        <dl className="facts">
          <dt>clip</dt><dd>{c.id} · {c.generator}/{c.variant} · seed {c.seed}</dd>
          <dt>shows</dt><dd>{c.render_desc || "—"}</dd>
          <dt>length</dt><dd>{fmt(c.duration_s)}s · {fmt(c.loudness_lufs)} LUFS · sameness {fmt(c.sameness, 3)}</dd>
          <dt>QC</dt><dd>hook {qc.hook_strength ?? "—"}/5 · policy {qc.policy_risk ?? "—"}{(qc.reasons || []).map((r) => <div key={r} className="hint">{r}</div>)}</dd>
        </dl>
        <div className="row wrap">
          {ready ? (
            <>
              <button className="ok" onClick={() => download(c.id)}>Download clip</button>
              <button className="ok" onClick={uploaded}>I uploaded it</button>
              <span className="hint">approved — download, upload by hand{slot ? `, schedule for ${slot}` : ""}, then mark it</span>
            </>
          ) : (
            <>
              <button className="ok" onClick={() => decide(c.id, "approve")}>Approve <kbd>A</kbd></button>
              <button className="danger" onClick={() => decide(c.id, "reject")}>Reject <kbd>R</kbd></button>
            </>
          )}
          <span className="hint right">{position} · <kbd>J</kbd> <kbd>K</kbd> to move</span>
        </div>
      </div>
    </div>
  );
}
