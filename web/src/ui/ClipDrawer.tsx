// One clip, in full: the video, what the render measured, QC's verdict, and
// what the platform did with it. Opened from any list of clips.
import { useCallback, useEffect, useState } from "react";
import { api, send } from "../lib/api";
import { fmt, num, pct, when, statusWord, download } from "../lib/format";
import { act } from "../lib/toast";
import { Badge, Drawer } from ".";
import type { ClipDetail } from "../lib/types";

export function ClipDrawer({ id, close, refresh, sound }: { id: string; close: () => void; refresh: () => Promise<void>; sound: boolean }) {
  const [c, setC] = useState<ClipDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => api<ClipDetail>(`/api/clip/${id}`).then(setC).catch((e) => setErr((e as Error).message)), [id]);
  useEffect(() => { load(); }, [load]);
  const run = (path: string, body?: unknown, confirmText?: string, then?: () => void) => {
    if (confirmText && !window.confirm(confirmText)) return;
    act(() => send(path, body), { after: async () => { await load(); await refresh(); then?.(); } });
  };
  const skip = new Set(["variant", "seed", "impacts", "palette", "sim_attempts", "hash_a", "hash_b", "style", "rounds", "finishes"]);
  const facts = c ? Object.entries(c.facts || {}).filter(([k]) => !skip.has(k)) : [];
  const rounds = (c?.facts?.rounds as Record<string, unknown>[] | undefined) || [];
  const qc = c?.qc || {};
  return (
    <Drawer onClose={close}>
      {err ? <p className="empty">{err}</p> : !c ? <p className="empty">loading…</p> : (
        <div className="stack gap-3">
          <div className="row wrap">
            <Badge>{statusWord(c.status)}</Badge>{c.deleted_at && <Badge tone="no">in the bin</Badge>}
            <span className="hint">{c.generator}/{c.variant} · seed {c.seed} · {when(c.created_at)}</span>
            <button className="sm right" onClick={close}>Close <kbd>Esc</kbd></button>
          </div>
          <div className="clip" style={{ gridTemplateColumns: "240px minmax(0,1fr)" }}>
            {c.file.exists ? <video key={c.id} src={`/api/clip/${c.id}/video`} autoPlay loop playsInline muted={!sound} controls />
              : <div className="hint">No file on disk any more{c.purged_at ? ` — purged ${when(c.purged_at)} by retention` : ""}. The record stays.</div>}
            <div className="stack">
              <h2>{c.title || "(untitled)"}</h2>
              <div className="tags">{(c.hashtags || []).join(" ")}</div>
              <div className="desc">{c.description || ""}</div>
              {c.hook_text && <div className="hint">opening caption: <b>{c.hook_text}</b></div>}
              {c.comment_prompt && <div className="hint">pinned comment: {c.comment_prompt}</div>}
              {c.reject_reason && <div className="no-text small">rejected: {c.reject_reason}</div>}
              <div className="row wrap">
                {c.file.exists && <button className="sm" onClick={() => download(c.id)}>Download ({c.file.mb} MB)</button>}
                {c.deleted_at
                  ? <><button className="sm" onClick={() => run("/api/clips/unbin", { ids: [c.id] })}>Restore from bin</button><button className="sm danger" onClick={() => run("/api/clips/destroy", { ids: [c.id] }, "Delete this clip and its files for good?", close)}>Delete forever</button></>
                  : <button className="sm" onClick={() => run("/api/clips/bin", { ids: [c.id] })}>Move to bin</button>}
                {!c.deleted_at && c.status === "qc_rejected" && c.file.exists && !(c.reject_reason || "").startsWith("too similar") && <button className="sm" onClick={() => run(`/api/clip/${c.id}/restore`)}>Back to queue</button>}
              </div>
              {!c.deleted_at && c.title && <TitleIdeas c={c} after={async () => { await load(); await refresh(); }} />}
            </div>
          </div>
          <h3>What the render measured</h3>
          <dl className="facts">
            <dt>shows</dt><dd>{c.render_desc || "—"}</dd>
            <dt>length</dt><dd>{fmt(c.duration_s)}s · {fmt(c.loudness_lufs)} LUFS · sameness {fmt(c.sameness, 3)}</dd>
            {rounds.map((r, i) => <span key={i} style={{ display: "contents" }}><dt>round {i + 1}</dt><dd>{String(r.stage)} · {String(r.winner)} wins{r.margin_s != null ? ` by ${r.margin_s}s` : ""} · {String(r.seconds)}s{Number(r.spinners) ? ` · ${r.spinners} spinner` : ""}</dd></span>)}
            {facts.map(([k, v]) => <span key={k} style={{ display: "contents" }}><dt>{k}</dt><dd>{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd></span>)}
            {c.file.path && <><dt>file</dt><dd>{c.file.path}{c.file.exists ? "" : " (gone)"}</dd></>}
          </dl>
          {qc.verdict && <><h3>QC</h3><dl className="facts"><dt>verdict</dt><dd>{qc.verdict} · hook {qc.hook_strength}/5 · policy {qc.policy_risk}{qc.looks_templated ? " · looks templated" : ""}</dd>{(qc.reasons || []).map((r, i) => <span key={i} style={{ display: "contents" }}><dt /><dd className="hint">{r}</dd></span>)}</dl></>}
          {(c.published_at || c.views != null) && <><h3>On the platform</h3><dl className="facts"><dt>published</dt><dd>{when(c.published_at)}</dd><dt>metrics</dt><dd>{c.views == null ? "none entered yet" : `${num(c.views)} views · ${pct(c.avg_view_pct)} viewed · ${pct(c.swipe_away_pct)} swiped · ${num(c.likes)} likes (${when(c.metrics_at)})`}</dd></dl></>}
          {c.title_history?.length > 0 && <><h3>Earlier titles</h3>{c.title_history.map((h, i) => <div key={i} className="hint">“{h.title}” until {when(h.until)} by {h.by} — {h.views == null ? "no metrics then" : `${num(h.views)} views, ${pct(h.avg_view_pct)} viewed, ${pct(h.swipe_away_pct)} swiped`}{h.why ? ` · ${h.why}` : ""}</div>)}</>}
        </div>
      )}
    </Drawer>
  );
}

// Five ways to ask for the pick, one per angle, from the Title brain — and
// only the ones the server let through. Choosing one goes through retitle,
// so the old title and its numbers are kept, and the angle is kept with
// them: when the metrics arrive this is how we learn which angle earned.
interface Idea { angle: string; title: string; caption: string | null; why: string }
interface Dropped { angle: string; title: string; why: string }

function TitleIdeas({ c, after }: { c: ClipDetail; after: () => Promise<void> }) {
  const [ideas, setIdeas] = useState<Idea[] | null>(null);
  const [dropped, setDropped] = useState<Dropped[]>([]);
  const [busy, setBusy] = useState(false);
  const rerenderable = !c.published_at && c.status !== "published";
  const ask = () => act(async () => {
    setBusy(true);
    try {
      const out = await send<{ ideas: Idea[]; dropped: Dropped[] }>(`/api/clip/${c.id}/titles?captions=${rerenderable}`);
      setIdeas(out.ideas); setDropped(out.dropped);
      return out;
    } finally { setBusy(false); }
  }, { ok: "Ideas are in" });
  const use = (i: Idea) => act(() => send(`/api/clip/${c.id}/text`, { title: i.title, why: `angle: ${i.angle}` }, "PATCH"), { ok: "Retitled", after });
  const recaption = (i: Idea) => act(() => send(`/api/clip/${c.id}/hook`, { text: i.caption }), { ok: `Re-rendering with ${i.caption}`, after });
  return (
    <div className="stack gap-2">
      <div className="row"><button className="sm" disabled={busy} onClick={ask}>{busy ? "Thinking…" : ideas ? "Suggest again" : "Suggest titles"}</button>
        <span className="hint">five angles from the Title brain; the server drops any that tells the result, repeats a used opening, or breaks the channel's rules</span></div>
      {ideas && ideas.length === 0 && <div className="hint">Nothing survived the gates this time — see below for why, and try again.</div>}
      {ideas?.map((i) => (
        <div key={i.angle} className="row wrap">
          <Badge>{i.angle}</Badge><span className="grow">{i.title}</span>
          <button className="sm ok" onClick={() => use(i)}>Use title</button>
          {i.caption && rerenderable && <button className="sm" onClick={() => recaption(i)} title="Re-render the same race with this opening caption">Caption: {i.caption}</button>}
          <span className="hint" style={{ flexBasis: "100%" }}>{i.why}</span>
        </div>
      ))}
      {dropped.length > 0 && <details><summary className="hint">{dropped.length} dropped</summary>{dropped.map((d, n) => <div key={n} className="hint">{d.angle}: “{d.title}” — {d.why}</div>)}</details>}
    </div>
  );
}
