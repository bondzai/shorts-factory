// Clips: the library. One list for everything the channel is making: a task
// until it has a clip, the clip from then on, and its numbers once it is
// published. One search, one status filter (the bin is one of the statuses),
// and a module filter only when there is more than one module to pick.
import { useCallback, useEffect, useState } from "react";
import { api, q, send } from "../lib/api";
import { num, pct, when, download, phaseWord, phaseTone, PHASE_ORDER } from "../lib/format";
import { act, toast } from "../lib/toast";
import { useList } from "../lib/useList";
import { useQuery } from "../lib/route";
import { Page, Toolbar, SearchBox, DataTable, Pagination, Badge, Card, Modal, StepStrip, Field, Column } from "../ui";
import { BinList } from "./Bin";
import type { Route } from "../lib/route";
import type { Clip, Snap, Task, TaskKind } from "../lib/types";

interface Analytics { n_with_metrics: number; n_published: number; views_90d: number; gate_tier2_pct: number; retained_median: number | null; swipe_away_median: number | null; best?: { views: number; variant: string }; series: { title: string; views: number }[]; by_variant: { key: string; retained_median: number | null; n: number }[] }

type Row = (Clip & { row_kind: "clip"; phase: string; key: string }) | (Task & { row_kind: "task"; phase: string; key: string });
interface WorkPage { items: Row[]; total: number; page: number; page_size: number; phases: { id: string; count: number }[]; modules: Record<string, string[]>; binned: number; kinds: Record<string, TaskKind>; stages: { id: string; blurb: string }[] }

type Nav = (v: string, p?: Record<string, string | number | undefined>) => void;

export function Clips({ snap, channelId, refresh, onOpen, route, navigate }: {
  snap: Snap; channelId: string; refresh: () => Promise<void>; onOpen: (id: string) => void; route: Route; navigate: Nav;
}) {
  const query = useQuery(route, navigate);
  const phase = query.get("phase");
  const inBin = phase === "binned";
  const list = useList<Row>("/api/work", route, { channel: channelId, phase, variant: query.get("variant"), ...(inBin ? { page_size: 1 } : {}) },
    [snap.tasks?.queued, snap.tasks?.claimed, snap.tasks?.done, snap.tasks?.failed, snap.counts?.awaiting_approval, snap.counts?.approved]);
  const body = list.data as WorkPage | null;
  const [modal, setModal] = useState<"add" | "handoff" | null>(null);
  const [picked, setPicked] = useState<Set<string | number>>(new Set());
  useEffect(() => setPicked(new Set()), [list.data]);
  const rows = inBin ? [] : body?.items || [];
  const keys = rows.map((r) => r.key);
  const published = phase === "published";
  const [numbers, setNumbers] = useState<Analytics | null>(null);
  const loadNumbers = useCallback(() => {
    if (!published) return Promise.resolve();
    return api<Analytics>(`/api/analytics?${q({ channel: channelId })}`).then(setNumbers).catch((e) => toast((e as Error).message, "error"));
  }, [published, channelId]);
  useEffect(() => { loadNumbers(); }, [loadNumbers]);
  const after = async () => { setPicked(new Set()); list.reload(); await loadNumbers(); await refresh(); };
  // A selection can hold both kinds; each action takes the half it applies to.
  const pickedClips = rows.filter((r) => r.row_kind === "clip" && picked.has(r.key)).map((r) => r.id as string);
  const pickedTasks = rows.filter((r) => r.row_kind === "task" && picked.has(r.key) && ["queued", "claimed", "failed", "cancelled", "done"].includes(r.status)).map((r) => r.id as number);
  const bulk = (path: string, payload: unknown, confirmText?: string) => { if (confirmText && !window.confirm(confirmText)) return; act(() => send(path, payload), { after }); };
  const restore = (id: string) => act(() => send(`/api/clip/${id}/restore`), { ok: "Back to review", after });
  const cancel = (id: number) => act(() => api(`/api/tasks/${id}`, { method: "DELETE" }), { ok: "Cancelled", after });

  const columns: Column<Row>[] = [
    { key: "title", label: "What", sortable: true, render: (r) => <><span className="narrow-only"><Badge tone={phaseTone(r.phase)}>{phaseWord(r.phase)}</Badge></span>{r.row_kind === "clip"
        ? <><Title c={r} after={after} /><div className="hint">{r.id} · {r.variant} · seed {r.seed}{r.title_history?.length ? ` · retitled ${r.title_history.length}×` : ""}{r.reject_reason && <> · <span className="no-text">{r.reject_reason.slice(0, 80)}</span></>}</div></>
        : <><div><b>{r.params?.level_id ? `Level ${r.params.level_id}` : r.kind}</b> <span className="dim small">{r.params?.level_id ? r.kind : Object.entries(r.params).map(([k, v]) => `${k}=${typeof v === "object" ? "…" : v}`).join(" ")}</span></div>
            <div className="hint">#{r.id} · {r.meaning}{r.claimed_by ? ` · ${r.claimed_by}` : ""}{r.error ? <> · <span className="no-text">{r.error.slice(0, 80)}</span></> : r.result?.summary ? ` · ${r.result.summary.slice(0, 80)}` : ""}</div>
            {r.status === "claimed" && <StepStrip steps={r.steps} />}</>}</> },
    { key: "phase", label: "Status", sortable: true, wide: true, render: (r) => <Badge tone={phaseTone(r.phase)}>{phaseWord(r.phase)}</Badge> },
    { key: "views", label: "Views", sortable: true, align: "right", wide: true, render: (r) => r.row_kind === "clip" ? num(r.views) : "" },
    { key: "avg_view_pct", label: "Viewed", sortable: true, align: "right", wide: true, render: (r) => r.row_kind === "clip" ? pct(r.avg_view_pct) : "" },
    { key: "swipe_away_pct", label: "Swiped", sortable: true, align: "right", wide: true, render: (r) => r.row_kind === "clip" ? pct(r.swipe_away_pct) : "" },
    { key: "created_at", label: "Made", sortable: true, wide: true, render: (r) => <span className="dim small nowrap">{when(r.created_at)}</span> },
    { key: "actions", label: <span className="sr-only">Actions</span>, render: (r) => <span className="row actions">
        {r.row_kind === "clip" ? <>
          <button className="sm" onClick={() => onOpen(r.id)}>View</button>
          {r.has_video ? <button className="sm" onClick={() => download(r.id)}>Download</button> : <span className="hint">no file</span>}
          {r.status === "qc_rejected" && r.has_video && !(r.reject_reason || "").startsWith("too similar") && <button className="sm" onClick={() => restore(r.id)}>Back to review</button>}
          {r.status === "published" && <Metrics c={r} after={after} />}
        </> : ["queued", "claimed"].includes(r.status) ? <button className="sm" onClick={() => cancel(r.id)}>Cancel</button> : null}
      </span> },
  ];
  const sortKey = query.get("sort"), dir = query.get("dir");
  const onSort = (k: string) => query.set({ sort: k, dir: sortKey === k && dir !== "asc" ? "asc" : "desc", page: 1 });
  const counts = Object.fromEntries((body?.phases || []).map((p) => [p.id, p.count]));
  const modules = Object.values(body?.modules || {}).flat();
  const anyFilter = !!(query.get("q") || phase || query.get("variant"));

  return (
    <Page title="Clips"
      lead="Everything this channel has asked for, made and published. Open a row for the video and its details."
      action={<div className="row"><button className="primary" onClick={() => setModal("add")}>Add work</button><button onClick={() => setModal("handoff")}>Hand off to an agent</button></div>}>
      {modal === "add" && body && <Modal title="Add work" onClose={() => setModal(null)}><AddWork snap={snap} channelId={channelId} kinds={body.kinds} stages={body.stages || []} after={async () => { setModal(null); await after(); }} /></Modal>}
      {modal === "handoff" && <Modal title="Hand the queue to an agent" onClose={() => setModal(null)}><HandOff snap={snap} channelId={channelId} refresh={refresh} /></Modal>}
      {published && <Numbers a={numbers} />}
      <Toolbar total={inBin ? undefined : body?.total}>
        <SearchBox value={query.get("q")} onChange={(v) => query.set({ q: v, page: 1 })} placeholder="Search titles, ids, levels" />
        <label className="row"><span className="sr-only">Status</span>
          <select value={phase} onChange={(e) => query.set({ phase: e.target.value, page: 1, sort: undefined })}>
            <option value="">Any status</option>
            {PHASE_ORDER.filter((p) => counts[p] || p === phase).map((p) => <option key={p} value={p}>{phaseWord(p)} ({counts[p] || 0})</option>)}
            <option value="binned">In the bin ({body?.binned ?? 0})</option>
          </select></label>
        {modules.length > 1 && <label className="row"><span className="sr-only">Module</span>
          <select value={query.get("variant")} onChange={(e) => query.set({ variant: e.target.value, page: 1 })}>
            <option value="">Any module</option>{modules.map((m) => <option key={m} value={m}>{m}</option>)}
          </select></label>}
        {anyFilter && <button className="sm ghost" onClick={() => navigate("clips")}>Clear filters</button>}
      </Toolbar>
      {inBin ? <BinList channelId={channelId} refresh={refresh} onOpen={onOpen} route={route} navigate={navigate} /> : <>
        {(pickedClips.length > 0 || pickedTasks.length > 0) && (
          <div className="selection" role="region" aria-label="Selection">
            <span>{picked.size} selected</span>
            {pickedClips.length > 0 && <button className="sm" onClick={() => bulk("/api/clips/bin", { ids: pickedClips })}>Move {pickedClips.length} to the bin</button>}
            {pickedTasks.length > 0 && <button className="sm" onClick={() => bulk("/api/tasks/delete", { ids: pickedTasks }, `Remove ${pickedTasks.length} task(s) from the queue?`)}>Remove {pickedTasks.length} task{pickedTasks.length === 1 ? "" : "s"}</button>}
            <button className="sm ghost right" onClick={() => setPicked(new Set())}>Clear</button>
          </div>
        )}
        <DataTable label="Clips" columns={columns} rows={rows as (Row & { id: string | number })[]} loading={list.loading} sort={sortKey} dir={dir} onSort={onSort}
          onRow={(r) => { if (r.row_kind === "clip") onOpen(r.id as string); }}
          selectable selected={picked} onSelect={(id) => setPicked((p) => { const s = new Set(p); s.has(id) ? s.delete(id) : s.add(id); return s; })}
          onSelectAll={() => setPicked((p) => p.size === keys.length ? new Set() : new Set(keys))}
          empty={anyFilter ? <>Nothing matches. <button className="link" onClick={() => navigate("clips")}>Clear filters</button></> : "Nothing yet. Plan levels on Today or Season, or press Add work."} />
        {body && <div className="row wrap">
          <Pagination page={body.page} pageSize={body.page_size} total={body.total} onPage={(p) => query.set({ page: p })} onPageSize={(s) => query.set({ page_size: s, page: 1 })} />
          {(counts.done || counts.failed || counts.cancelled) ? <button className="sm ghost right" onClick={() => bulk("/api/tasks/clear", { channel: channelId }, "Remove every done, failed and cancelled task on this channel?")}>Clear finished tasks</button> : null}
        </div>}
      </>}
    </Page>
  );
}

// The channel's numbers, shown when the list is filtered to published clips:
// the same rows, summed up. Metrics come from YouTube Studio or `factory
// pull-metrics`; a clip with none contributes nothing here.
function Numbers({ a }: { a: Analytics | null }) {
  if (!a) return null;
  if (!a.n_with_metrics) return <Card hint="No published clip has metrics yet. Enter the first ones with the Enter metrics button on a row." />;
  const max = Math.max(...a.series.map((s) => s.views), 1);
  return (
    <>
      <div className="tiles">
        <div className="tile"><div className="label">Shorts views, 90 days</div><div className="value">{num(a.views_90d)}</div><div className="sub">{a.gate_tier2_pct}% of the 10M gate</div></div>
        <div className="tile"><div className="label">With metrics</div><div className="value">{a.n_with_metrics}</div><div className="sub">of {a.n_published} published</div></div>
        <div className="tile"><div className="label">Median viewed</div><div className="value">{pct(a.retained_median)}</div><div className="sub">swiped away {pct(a.swipe_away_median)}</div></div>
        <div className="tile"><div className="label">Best clip</div><div className="value">{num(a.best?.views)}</div><div className="sub">{a.best?.variant || "\u2014"}</div></div>
      </div>
      <Card title="Views per clip, in publish order" hint="One clip usually carries a channel. Watch for the tall bar, not the average.">
        <div className="row" style={{ alignItems: "flex-end", gap: 4, height: 120 }}>{a.series.map((s, i) => <div key={i} title={`${s.title} \u00b7 ${num(s.views)} views`} className="grow" style={{ height: `${Math.max(2, (s.views / max) * 100)}%`, background: s.views === max ? "var(--key)" : "var(--line)", borderRadius: 2 }} />)}</div>
      </Card>
      <Card title="Viewed, by variant" hint="n is shown because at this sample size n is most of the argument.">
        {a.by_variant.map((g) => <div key={g.key} className="mb-3"><div className="row small"><span className="grow">{g.key}</span><span>{pct(g.retained_median)}</span><span className="hint">n={g.n}</span></div><div className="meter"><span style={{ width: `${Math.max(2, g.retained_median || 0)}%` }} /></div></div>)}
      </Card>
    </>
  );
}

// A published title is still a lever: it can be changed after the fact, and
// what each one earned is kept so the change can be judged.
function Title({ c, after }: { c: Clip; after: () => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(c.title || "");
  const save = () => act(async () => {
    const out = await send<{ needs_manual_update?: boolean }>(`/api/clip/${c.id}/text`, { title: title.trim(), why: "changed on the Clips screen" }, "PATCH");
    if (out.needs_manual_update) toast("Saved here. Change it in YouTube Studio too \u2014 nothing reaches YouTube by itself on a manual channel.");
  }, { after: async () => { setEditing(false); await after(); } });
  if (editing) return <div className="row" onClick={(e) => e.stopPropagation()}><input className="grow" value={title} maxLength={90} autoFocus onChange={(e) => setTitle(e.target.value)} /><button className="sm ok" onClick={save}>Save</button><button className="sm" onClick={() => setEditing(false)}>Cancel</button></div>;
  return <div>{c.title || "(untitled)"}{c.status === "published" && <button className="sm ghost" onClick={(e) => { e.stopPropagation(); setEditing(true); }}>retitle</button>}</div>;
}

// The numbers from YouTube Studio. In a dialog rather than in the row: four
// fields do not fit in a cell, and typing them is a deliberate act anyway.
const FIELDS = [
  { key: "views", label: "Views", help: "Total views on the clip." },
  { key: "avg_view_pct", label: "Viewed %", help: "Average percentage viewed \u2014 Studio calls it average view duration / length." },
  { key: "swipe_away_pct", label: "Swiped away %", help: "How many left in the first moments. Studio does not show it directly; the pull-metrics command derives it." },
  { key: "likes", label: "Likes", help: "Optional." },
] as const;

function Metrics({ c, after }: { c: Clip; after: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [m, setM] = useState({ views: String(c.views ?? ""), avg_view_pct: String(c.avg_view_pct ?? ""), swipe_away_pct: String(c.swipe_away_pct ?? ""), likes: String(c.likes ?? "") });
  const save = (e: React.FormEvent) => {
    e.preventDefault();
    act(() => send(`/api/clip/${c.id}/metrics`, { views: Number(m.views), avg_view_pct: Number(m.avg_view_pct), swipe_away_pct: Number(m.swipe_away_pct), likes: Number(m.likes || 0) }),
      { ok: "Metrics saved", after: async () => { setOpen(false); await after(); } });
  };
  return (
    <>
      <button className="sm" onClick={(e) => { e.stopPropagation(); setOpen(true); }}>{c.views == null ? "Enter metrics" : "Edit metrics"}</button>
      {open && <Modal title="Numbers from YouTube Studio" onClose={() => setOpen(false)}>
        <form className="form" onSubmit={save}>
          <p className="hint">{c.title || c.id} \u00b7 published {when(c.published_at)}</p>
          {FIELDS.map((f) => (
            <Field key={f.key} label={f.label} help={f.help}>
              <input type="number" step="any" className="w-sm" value={m[f.key]} onChange={(e) => setM({ ...m, [f.key]: e.target.value })} />
            </Field>
          ))}
          <div className="actions"><button type="submit" className="primary">Save</button><button type="button" onClick={() => setOpen(false)}>Cancel</button></div>
        </form>
      </Modal>}
    </>
  );
}

function AddWork({ snap, channelId, kinds, stages, after }: { snap: Snap; channelId: string; kinds: Record<string, TaskKind>; stages: { id: string; blurb: string }[]; after: () => Promise<void> }) {
  const [kind, setKind] = useState("make-clip");
  const [variant, setVariant] = useState("");
  const [stage, setStage] = useState("");
  const [seed, setSeed] = useState("");
  const [customBackdrop, setCustomBackdrop] = useState(false);
  const [backdrop, setBackdrop] = useState("#1a1a2a");
  const [count, setCount] = useState(1);
  const spec = kinds[kind] || { params: {}, builtin: false, meaning: "" };
  const variants = snap.channel.variants || [];
  const isClip = kind === "make-clip";
  const n = seed ? 1 : Math.max(1, Math.min(50, Number(count) || 1));
  const params: Record<string, string> = {};
  if (isClip) {
    if (variant) { params.variant = variant.split("/")[1]; params.generator = variant.split("/")[0]; }
    if (stage) params.stage = stage;
    if (seed) params.seed = seed;
    if (customBackdrop) params.background = backdrop;
  }
  const add = (e: React.FormEvent) => { e.preventDefault(); act(() => send("/api/tasks", { channel: channelId, kind, params, count: n }), { ok: n === 1 ? "Queued 1 task" : `Queued ${n} tasks`, after }); };
  return (
    <form className="form" onSubmit={add} style={{ maxWidth: "none" }}>
      <Field label="What to do" help={spec.meaning}>
        <select value={kind} onChange={(e) => setKind(e.target.value)}>{Object.keys(kinds).map((k) => <option key={k} value={k}>{k}</option>)}</select>
      </Field>
      {isClip && <>
        <Field label="Format" help="The generator and its variant. Leave on the channel's default unless you are trying something else.">
          <select value={variant} onChange={(e) => setVariant(e.target.value)}><option value="">Channel default ({variants[0] || "physics/marble_race"})</option>{variants.map((v) => <option key={v} value={v}>{v}</option>)}</select>
        </Field>
        <Field label="Stage" help={stages.find((c) => c.id === stage)?.blurb || "Which track the marbles run. Any lets each seed pick, which keeps the channel varied."}>
          <select value={stage} onChange={(e) => setStage(e.target.value)}><option value="">Any — the seed decides</option>{stages.map((c) => <option key={c.id} value={c.id}>{c.id} — {c.blurb}</option>)}</select>
        </Field>
        <Field label="Seed" help={seed ? "This exact race, every time. Use it to re-make a race you liked with a new caption or backdrop." : "Empty = a fresh random race. Set a number only to reproduce a specific race."}>
          <input className="w-md" inputMode="numeric" pattern="[0-9]*" placeholder="leave empty for a new race" value={seed} onChange={(e) => setSeed(e.target.value.replace(/[^0-9]/g, ""))} />
        </Field>
        <Field label="Backdrop" help={customBackdrop ? "This colour behind the stage; the theme still picks marbles and decorations." : "Unticked = the current theme's palette (Settings → Themes)."}>
          <label className="row small"><input type="checkbox" checked={customBackdrop} onChange={(e) => setCustomBackdrop(e.target.checked)} /> choose a colour {customBackdrop && <input type="color" value={backdrop} onChange={(e) => setBackdrop(e.target.value)} />}</label>
        </Field>
        <Field label="How many" help={seed ? "One — a fixed seed would make the same race again." : "Each is a separate task with its own random race."}>
          <input type="number" className="w-sm" min={1} max={50} value={seed ? 1 : count} disabled={!!seed} onChange={(e) => setCount(Number(e.target.value))} />
        </Field>
      </>}
      <div className="actions">
        <button type="submit" className="primary">{isClip ? (n === 1 ? "Queue 1 clip" : `Queue ${n} clips`) : `Queue ${kind}`}</button>
        <span className="hint" style={{ alignSelf: "center" }}>{spec.builtin ? "the built-in agents can do this, or any agent over MCP" : "needs an agent's judgement — hand it off over MCP"}</span>
      </div>
    </form>
  );
}

function HandOff({ snap, channelId, refresh }: { snap: Snap; channelId: string; refresh: () => Promise<void> }) {
  const [text, setText] = useState("");
  const [copied, setCopied] = useState(false);
  useEffect(() => { api<{ text: string }>(`/api/playbook/work?${q({ channel: channelId })}`).then((b) => setText(b.text)).catch(() => {}); }, [channelId]);
  const copy = async () => { try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* shown below */ } };
  return (
    <div className="stack">
      <div className="row"><span className="hint grow">Paste this into Codex, Claude Code or any MCP-connected agent. It is the same for every task and every model — the task carries its own playbook.</span><button className="sm ok" onClick={copy} disabled={!text}>{copied ? "Copied" : "Copy"}</button></div>
      <pre className="captured" style={{ maxHeight: 260 }}>{text || "loading…"}</pre>
      {snap.agents?.available
        ? <div className="row mt-3"><button onClick={() => act(() => send("/api/tasks/work", { channel: channelId }), { after: refresh })} disabled={snap.job?.running}>Run with built-in agents</button><span className="hint">does every make-clip task in the queue, in a job</span></div>
        : <div className="hint mt-3">Or let the console run the agent for you: <a href="#/agents">Agents → Workers</a> starts Claude Code or Codex on this queue, with an auto mode that watches for new work.</div>}
    </div>
  );
}
