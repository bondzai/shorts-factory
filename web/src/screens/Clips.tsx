import { useCallback, useEffect, useState } from "react";
import { api, send } from "../lib/api";
import { fmt, num, pct, when, statusWord, download } from "../lib/format";
import { act } from "../lib/toast";
import { useList } from "../lib/useList";
import { useQuery } from "../lib/route";
import { Page, Toolbar, SearchBox, Chips, DataTable, Pagination, Badge, Drawer, Column } from "../ui";
import type { Route } from "../lib/route";
import type { Clip, ClipDetail } from "../lib/types";

interface ClipsPage { items: Clip[]; total: number; page: number; page_size: number; statuses: string[]; modules: Record<string, string[]>; binned: number }

export function Clips({ channelId, refresh, bin = false, onOpen, route, navigate }: {
  channelId: string; refresh: () => Promise<void>; bin?: boolean; onOpen: (id: string) => void; route: Route; navigate: (v: string, p?: Record<string, string | number | undefined>) => void;
}) {
  const query = useQuery(route, navigate);
  const list = useList<Clip>("/api/clips", route, { channel: channelId, status: query.get("status"), variant: query.get("variant"), bin: bin || undefined });
  const body = list.data as ClipsPage | null;
  const [picked, setPicked] = useState<Set<string | number>>(new Set());
  useEffect(() => setPicked(new Set()), [list.data]);
  const ids = (body?.items || []).map((c) => c.id);
  const after = async () => { list.reload(); await refresh(); };
  const bulk = (path: string, confirmText?: string) => { if (confirmText && !window.confirm(confirmText)) return; act(() => send(path, { ids: [...picked] }), { after }); };
  const restore = (id: string) => act(() => send(`/api/clip/${id}/restore`), { ok: "Back in the queue", after });
  const n = picked.size;

  const columns: Column<Clip>[] = [
    { key: "title", label: "Title", sortable: true, render: (c) => <><div>{c.title || "(untitled)"}</div><div className="hint">{c.id} · seed {c.seed}{c.title_history?.length ? ` · retitled ${c.title_history.length}×` : ""}{c.reject_reason && <> · <span className="no-text">{c.reject_reason.slice(0, 80)}</span></>}</div></> },
    { key: "variant", label: "Module", render: (c) => <span className="dim">{c.variant}</span> },
    { key: "status", label: "Status", sortable: true, render: (c) => <Badge>{statusWord(c.status)}</Badge> },
    { key: "views", label: "Views", sortable: true, align: "right", render: (c) => num(c.views) },
    { key: "avg_view_pct", label: "Viewed", sortable: true, align: "right", render: (c) => pct(c.avg_view_pct) },
    { key: "swipe_away_pct", label: "Swiped", sortable: true, align: "right", render: (c) => pct(c.swipe_away_pct) },
    { key: "created_at", label: "Made", sortable: true, render: (c) => <span className="dim small">{when(c.created_at)}</span> },
    { key: "actions", label: "", render: (c) => <span className="row" style={{ whiteSpace: "nowrap" }}>
        <button className="sm" onClick={() => onOpen(c.id)}>View</button>
        {c.has_video ? <button className="sm" onClick={() => download(c.id)}>Download</button> : <span className="hint">no file</span>}
        {!bin && c.status === "qc_rejected" && c.has_video && !(c.reject_reason || "").startsWith("too similar") && <button className="sm" onClick={() => restore(c.id)}>Back to queue</button>}
      </span> },
  ];
  const sortKey = query.get("sort"), dir = query.get("dir");
  const onSort = (k: string) => query.set({ sort: k, dir: sortKey === k && dir !== "asc" ? "asc" : "desc", page: 1 });

  return (
    <Page title={bin ? "Bin" : "Every clip on this channel"}
      lead={bin ? "Binned clips are hidden everywhere and count for nothing, but their files are still here. Restore puts one back where it was; Delete forever removes the render and the record."
                : `Rejected clips keep their file for a few days, published ones for a month. Tick clips to move them to the Bin${body?.binned ? ` (${body.binned} there now)` : ""}.`}
      action={bin
        ? <span className="row"><button className="sm" disabled={!n} onClick={() => bulk("/api/clips/unbin")}>Restore {n || ""}</button><button className="sm danger" disabled={!n} onClick={() => bulk("/api/clips/destroy", `Delete ${n} clip(s) and their files for good? This cannot be undone.`)}>Delete forever {n || ""}</button></span>
        : <button className="sm" disabled={!n} onClick={() => bulk("/api/clips/bin")}>Move to bin {n || ""}</button>}>
      <Toolbar total={body?.total}>
        <SearchBox value={query.get("q")} onChange={(v) => query.set({ q: v, page: 1 })} placeholder="search titles, ids, descriptions" />
        {!bin && <Chips options={(body?.statuses || []).map((s) => ({ value: s, label: statusWord(s) }))} value={query.get("status")} onChange={(v) => query.set({ status: v, page: 1 })} all="any status" />}
        <Chips options={Object.values(body?.modules || {}).flat().map((v) => ({ value: v }))} value={query.get("variant")} onChange={(v) => query.set({ variant: v, page: 1 })} all="any variant" />
      </Toolbar>
      <DataTable columns={columns} rows={body?.items || []} loading={list.loading} sort={sortKey} dir={dir} onSort={onSort} onRow={(c) => onOpen(c.id)}
        selectable selected={picked} onSelect={(id) => setPicked((p) => { const s = new Set(p); s.has(id) ? s.delete(id) : s.add(id); return s; })}
        onSelectAll={() => setPicked((p) => p.size === ids.length ? new Set() : new Set(ids))} empty={bin ? "The bin is empty." : "Nothing matches."} />
      {body && <Pagination page={body.page} pageSize={body.page_size} total={body.total} onPage={(p) => query.set({ page: p })} onPageSize={(s) => query.set({ page_size: s, page: 1 })} />}
    </Page>
  );
}

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
