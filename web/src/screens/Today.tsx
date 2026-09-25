// Today: the short list of what needs the operator, in the order it pays to
// do it. Each item has one button that moves it along; an item with nothing
// in it shrinks to a line that says what happens next.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, q, send, ApiError } from "../lib/api";
import { fmt, download, plural } from "../lib/format";
import { act, toast } from "../lib/toast";
import { Page, Card, StepStrip, Todo } from "../ui";
import type { Clip, Snap, Task } from "../lib/types";
import type { SeasonView } from "./Season";

type Nav = (v: string, p?: Record<string, string | number | undefined>) => void;

export function Today({ snap, channelId, refresh, sound, setSound, onOpen, navigate }: {
  snap: Snap; channelId: string; refresh: () => Promise<void>; sound: boolean; setSound: (v: boolean) => void; onOpen: (id: string) => void; navigate: Nav;
}) {
  const review = snap.queue;
  const approved = snap.approved;
  const waitingQc = snap.counts?.awaiting_qc || 0;
  const busy = !!snap.job?.running;
  const auto = snap.channel.driver !== "manual";

  const decide = useCallback(async (id: string, what: "approve" | "reject") => {
    let body: Record<string, string> = {};
    if (what === "reject") {
      const reason = window.prompt("Why? This is what the next planner reads. Cancel keeps the clip.", "");
      if (reason === null) return;
      body = { reason: reason.trim() || "rejected in review" };
    }
    await act(() => send(`/api/clip/${id}/${what}`, body), { after: refresh });
  }, [refresh]);

  const needs = (review.length ? 1 : 0) + (waitingQc ? 1 : 0) + (approved.length ? 1 : 0);
  const publishAll = () => {
    if (!window.confirm(`Publish ${plural(approved.length, "approved clip")} through ${snap.channel.driver}?`)) return;
    act(() => send("/api/publish", { channel: channelId }), { ok: "Publishing started", after: refresh });
  };

  return (
    <Page title="Today" lead={needs ? `${plural(needs, "thing needs", "things need")} you. Start at the top.` : "Nothing needs you right now."}>
      <div className="todos">
        {review.length > 0 ? (
          <Todo title="Needs review" count={review.length} hint="Watch it, fix the words if they are off, then approve or reject. Rejections teach the planner."
            action={<button className="sm ghost" onClick={() => setSound(!sound)} aria-pressed={sound}>Sound {sound ? "on" : "off"}</button>}>
            <Flow items={review} keys sound={sound} refresh={refresh} decide={decide} channelId={channelId} onOpen={onOpen} auto={auto} />
          </Todo>
        ) : <Todo done title="Nothing to review" doneText="New clips land here once they are made and judged." />}

        {waitingQc > 0 && <QcTodo count={waitingQc} busy={busy} channelId={channelId} refresh={refresh} navigate={navigate} />}

        {approved.length > 0 ? (
          <Todo title="Ready to publish" count={approved.length}
            hint={auto ? "Approved clips go up private and turn public at their slot." : "Download each one, upload it in YouTube Studio, then mark it uploaded."}
            action={auto ? <button className="primary" disabled={busy} onClick={publishAll}>Publish {approved.length}</button> : undefined}>
            {auto && busy && <p className="hint mb-3">Wait for the running job to finish before publishing.</p>}
            <Flow items={approved} keys={!review.length} sound={sound} refresh={refresh} decide={decide} channelId={channelId} onOpen={onOpen} auto={auto} />
          </Todo>
        ) : <Todo done title="Nothing to publish" doneText="Clips you approve wait here until they go up." />}

        <NextInSeason channelId={channelId} snap={snap} refresh={refresh} navigate={navigate} />
      </div>
      <LiveNow snap={snap} channelId={channelId} navigate={navigate} />
    </Page>
  );
}

/* Clips made while QC was off. The button needs the QC brain; when it cannot
   run, the reason is on the card, not in a tooltip. */
function QcTodo({ count, busy, channelId, refresh, navigate }: { count: number; busy: boolean; channelId: string; refresh: () => Promise<void>; navigate: Nav }) {
  const [brain, setBrain] = useState<{ ok: boolean; why?: string | null } | null>(null);
  useEffect(() => {
    api<{ readiness: Record<string, { ok: boolean; why: string | null }> }>("/api/brains")
      .then((b) => setBrain(b.readiness.qc || { ok: false, why: "no QC brain is set" }))
      .catch((e) => setBrain({ ok: false, why: (e as Error).message }));
  }, []);
  const why = !brain ? "Checking the QC brain…" : !brain.ok ? `The QC brain is not ready: ${brain.why}.` : busy ? "Wait for the running job to finish." : null;
  return (
    <Todo title="Waiting for QC" count={count} hint="Made while QC was switched off. Run QC judges them; nothing is re-rendered."
      action={<button className="primary" disabled={!!why} onClick={() => act(() => send("/api/qc", { channel: channelId }), { ok: "QC started", after: refresh })}>Run QC</button>}>
      <div className="row wrap">
        {why && <span className={brain && !brain.ok ? "no-text small" : "hint"}>{why}</span>}
        {brain && !brain.ok && <button className="link" onClick={() => navigate("settings", { tab: "brains" })}>Set up brains</button>}
        <button className="link right" onClick={() => navigate("clips", { phase: "awaiting_qc" })}>See {count === 1 ? "it" : "them"} in Clips</button>
      </div>
    </Todo>
  );
}

/* The season is the plan: the next ready levels, and one button that queues
   them. `factory work` or an agent makes them after that. */
function NextInSeason({ channelId, snap, refresh, navigate }: { channelId: string; snap: Snap; refresh: () => Promise<void>; navigate: Nav }) {
  const [season, setSeason] = useState<SeasonView | null>(null);
  const [missing, setMissing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api<SeasonView>(`/api/season?${q({ channel: channelId })}`)
    .then((b) => { setSeason(b); setMissing(null); setError(null); })
    .catch((e) => { if (e instanceof ApiError && e.status === 404) setMissing(e.message); else setError((e as Error).message); }), [channelId]);
  useEffect(() => { load(); }, [load, snap.tasks?.queued, snap.tasks?.done]);

  if (missing) return <Todo done title="No season" doneText="This channel has no season file; add work on Clips instead." />;
  if (error) return <Todo title="Next in the season" hint={<span className="no-text">Could not read the season: {error}</span>} action={<button className="sm" onClick={load}>Try again</button>} />;
  if (!season) return <Todo title="Next in the season" hint="Loading…" />;
  const next = season.levels.filter((l) => l.plannable).slice(0, 3);
  const waiting = season.levels.filter((l) => l.status === "planned").length;
  const label = next.length === 1 ? next[0].id : next.length ? `${next[0].id}–${next[next.length - 1].id}` : "";
  const plan = async () => {
    setBusy(true);
    try {
      const out = await act(() => send<{ queued: number; results: { level: string; queued: boolean; reason: string | null }[] }>("/api/season/plan", { channel: channelId, levels: next.map((l) => l.id) }));
      if (out) {
        const refused = out.results.filter((r) => !r.queued);
        toast(out.queued ? `Queued ${plural(out.queued, "level")}. An agent or \`factory work\` makes them next.` : `Nothing queued: ${refused[0]?.reason}`, out.queued ? "info" : "error");
        await load(); await refresh();
      }
    } finally { setBusy(false); }
  };
  if (!next.length) {
    return <Todo done title="Season is fully planned" doneText={<>Every ready level is planned or made. <button className="link" onClick={() => navigate("season")}>Open Season</button></>} />;
  }
  return (
    <Todo title="Next in the season" hint={waiting ? `${plural(waiting, "level")} already planned, waiting to be made.` : "Planning queues these levels; an agent or `factory work` makes them."}
      action={<button className="primary" disabled={busy} onClick={plan}>{busy ? "Planning…" : `Plan ${label}`}</button>}>
      <ul className="levels-mini">
        {next.map((l) => <li key={l.id}><b>{l.id}</b><span className="dim">{l.date}</span><span className="grow truncate">{l.world}{l.note ? <span className="hint"> · {l.note}</span> : null}</span></li>)}
      </ul>
      <button className="link" onClick={() => navigate("season")}>Choose other levels on Season</button>
    </Todo>
  );
}

/* A carousel over one list of clips: the card, a strip to jump, and J/K. */
function Flow({ items, keys, sound, refresh, decide, channelId, onOpen, auto }: {
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

/* What agents are doing right now: each claimed task and its step. Quiet: no
   button competes with the to-do list. */
function LiveNow({ snap, channelId, navigate }: { snap: Snap; channelId: string; navigate: Nav }) {
  const [active, setActive] = useState<Task[]>([]);
  const claimed = snap.tasks?.claimed || 0;
  const queued = snap.tasks?.queued || 0;
  useEffect(() => {
    if (!claimed) { setActive([]); return; }
    api<{ items: Task[] }>(`/api/tasks?${q({ channel: channelId, status: "claimed", page_size: 25 })}`).then((b) => setActive(b.items)).catch(() => {});
  }, [channelId, claimed, snap.job?.log?.length]);
  if (!active.length && !queued) return null;
  return (
    <Card title="Being made" right={<button className="link" onClick={() => navigate("agents")}>See agents</button>}
      hint={queued ? `${plural(queued, "task")} queued${active.length ? `, ${active.length} in progress.` : ". No agent has picked them up yet: start one on Agents, or run `factory work`."}` : undefined}>
      {active.map((t) => {
        const cur = t.steps.find((s) => s.state === "current");
        const done = t.steps.filter((s) => s.state === "done").length;
        return <div key={t.id} className="stack mt-3"><div className="row wrap"><b>{t.params?.level_id || `#${t.id}`}</b><span className="hint">{t.claimed_by} · {cur ? cur.name : "…"} — step {done + 1} of {t.steps.length}</span></div><StepStrip steps={t.steps} /></div>;
      })}
    </Card>
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
