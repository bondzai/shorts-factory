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
