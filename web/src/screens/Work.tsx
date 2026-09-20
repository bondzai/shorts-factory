// One list for everything the channel is making: a task until it has a
// clip, the clip from then on. What was asked for and what came of it are
// the same row at different stages, so they live on the same screen.
import { useEffect, useState } from "react";
import { api, q, send } from "../lib/api";
import { num, pct, when, download } from "../lib/format";
import { act } from "../lib/toast";
import { useList } from "../lib/useList";
import { useQuery } from "../lib/route";
import { Page, Toolbar, SearchBox, Chips, DataTable, Pagination, Badge, Modal, StepStrip, Field, Column } from "../ui";
import type { Route } from "../lib/route";
import type { Clip, Snap, Task, TaskKind } from "../lib/types";

type Row = (Clip & { row_kind: "clip"; phase: string; key: string }) | (Task & { row_kind: "task"; phase: string; key: string });
interface WorkPage { items: Row[]; total: number; page: number; page_size: number; phases: { id: string; count: number }[]; modules: Record<string, string[]>; binned: number; kinds: Record<string, TaskKind>; stages: { id: string; blurb: string }[] }

const PHASE: Record<string, { word: string; tone?: "ok" | "no" | "key" }> = {
  queued: { word: "queued" }, rendering: { word: "rendering", tone: "key" }, to_review: { word: "to review", tone: "key" },
  approved: { word: "approved", tone: "ok" }, published: { word: "published", tone: "ok" }, rejected: { word: "rejected", tone: "no" },
  failed: { word: "failed", tone: "no" }, cancelled: { word: "cancelled" }, done: { word: "done" },
};
const phaseWord = (s: string) => PHASE[s]?.word || s;

export function Work({ snap, channelId, refresh, onOpen, route, navigate }: {
  snap: Snap; channelId: string; refresh: () => Promise<void>; onOpen: (id: string) => void; route: Route; navigate: (v: string, p?: Record<string, string | number | undefined>) => void;
}) {
  const query = useQuery(route, navigate);
  const list = useList<Row>("/api/work", route, { channel: channelId, phase: query.get("phase"), variant: query.get("variant") }, [snap.tasks?.queued, snap.tasks?.claimed, snap.tasks?.done, snap.tasks?.failed, snap.counts?.awaiting_approval, snap.counts?.approved]);
  const body = list.data as WorkPage | null;
  const [modal, setModal] = useState<"add" | "handoff" | null>(null);
  const [picked, setPicked] = useState<Set<string | number>>(new Set());
  useEffect(() => setPicked(new Set()), [list.data]);
  const rows = body?.items || [];
  const keys = rows.map((r) => r.key);
  const after = async () => { setPicked(new Set()); list.reload(); await refresh(); };
  // A selection can hold both kinds; each action takes the half it applies to.
  const pickedClips = rows.filter((r) => r.row_kind === "clip" && picked.has(r.key)).map((r) => r.id as string);
  const pickedTasks = rows.filter((r) => r.row_kind === "task" && picked.has(r.key) && ["queued", "claimed", "failed", "cancelled", "done"].includes(r.status)).map((r) => r.id as number);
  const bulk = (path: string, payload: unknown, confirmText?: string) => { if (confirmText && !window.confirm(confirmText)) return; act(() => send(path, payload), { after }); };
  const restore = (id: string) => act(() => send(`/api/clip/${id}/restore`), { ok: "Back to review", after });
  const cancel = (id: number) => act(() => api(`/api/tasks/${id}`, { method: "DELETE" }), { ok: "Cancelled", after });

  const columns: Column<Row>[] = [
    { key: "title", label: "What", sortable: true, render: (r) => r.row_kind === "clip"
        ? <><div>{r.title || "(untitled)"}</div><div className="hint">{r.id} · {r.generator}/{r.variant} · seed {r.seed}{r.title_history?.length ? ` · retitled ${r.title_history.length}×` : ""}{r.reject_reason && <> · <span className="no-text">{r.reject_reason.slice(0, 80)}</span></>}</div></>
        : <><div><b>{r.kind}</b> <span className="dim small">{Object.entries(r.params).map(([k, v]) => `${k}=${v}`).join(" ")}</span></div>
            <div className="hint">#{r.id} · {r.meaning}{r.claimed_by ? ` · ${r.claimed_by}` : ""}{r.error ? <> · <span className="no-text">{r.error.slice(0, 80)}</span></> : r.result?.summary ? ` · ${r.result.summary.slice(0, 80)}` : ""}</div>
            {r.status === "claimed" && <StepStrip steps={r.steps} />}</> },
    { key: "phase", label: "Phase", sortable: true, render: (r) => <Badge tone={PHASE[r.phase]?.tone}>{phaseWord(r.phase)}</Badge> },
    { key: "views", label: "Views", sortable: true, align: "right", render: (r) => r.row_kind === "clip" ? num(r.views) : "" },
    { key: "avg_view_pct", label: "Viewed", sortable: true, align: "right", render: (r) => r.row_kind === "clip" ? pct(r.avg_view_pct) : "" },
    { key: "swipe_away_pct", label: "Swiped", sortable: true, align: "right", render: (r) => r.row_kind === "clip" ? pct(r.swipe_away_pct) : "" },
    { key: "created_at", label: "Made", sortable: true, render: (r) => <span className="dim small">{when(r.created_at)}</span> },
    { key: "actions", label: "", render: (r) => <span className="row" style={{ whiteSpace: "nowrap" }}>
        {r.row_kind === "clip" ? <>
          <button className="sm" onClick={() => onOpen(r.id)}>View</button>
          {r.has_video ? <button className="sm" onClick={() => download(r.id)}>Download</button> : <span className="hint">no file</span>}
          {r.status === "qc_rejected" && r.has_video && !(r.reject_reason || "").startsWith("too similar") && <button className="sm" onClick={() => restore(r.id)}>Back to review</button>}
        </> : ["queued", "claimed"].includes(r.status) ? <button className="sm" onClick={() => cancel(r.id)}>Cancel</button> : null}
      </span> },
  ];
  const sortKey = query.get("sort"), dir = query.get("dir");
  const onSort = (k: string) => query.set({ sort: k, dir: sortKey === k && dir !== "asc" ? "asc" : "desc", page: 1 });

  return (
    <Page title="Everything this channel is making"
      lead={`One row per piece of work, from queued to published. Tick rows to act on them; binned clips are under Bin${body?.binned ? ` (${body.binned} there now)` : ""}.`}
      action={<div className="row"><button className="primary" onClick={() => setModal("add")}>Add work</button><button onClick={() => setModal("handoff")}>Hand off to an agent</button></div>}>
      {modal === "add" && body && <Modal title="Add work" onClose={() => setModal(null)}><AddWork snap={snap} channelId={channelId} kinds={body.kinds} stages={body.stages || []} after={async () => { setModal(null); await after(); }} /></Modal>}
      {modal === "handoff" && <Modal title="Hand the queue to an agent" onClose={() => setModal(null)}><HandOff snap={snap} channelId={channelId} refresh={refresh} /></Modal>}
      <Toolbar total={body?.total}>
        <button className="sm" disabled={!pickedClips.length} onClick={() => bulk("/api/clips/bin", { ids: pickedClips })}>Move to bin {pickedClips.length || ""}</button>
        <button className="sm" disabled={!pickedTasks.length} onClick={() => bulk("/api/tasks/delete", { ids: pickedTasks }, `Remove ${pickedTasks.length} task(s) from the queue?`)}>Remove task {pickedTasks.length || ""}</button>
        <button className="sm ghost" onClick={() => bulk("/api/tasks/clear", { channel: channelId }, "Remove every done, failed and cancelled task on this channel?")}>Clear finished tasks</button>
        <SearchBox value={query.get("q")} onChange={(v) => query.set({ q: v, page: 1 })} placeholder="search titles, ids, parameters, who" />
        <Chips options={(body?.phases || []).map((s) => ({ value: s.id, label: `${phaseWord(s.id)} ${s.count}` }))} value={query.get("phase")} onChange={(v) => query.set({ phase: v, page: 1 })} all="any phase" />
        <Chips options={Object.values(body?.modules || {}).flat().map((v) => ({ value: v }))} value={query.get("variant")} onChange={(v) => query.set({ variant: v, page: 1 })} all="any variant" />
      </Toolbar>
      <DataTable columns={columns} rows={rows as (Row & { id: string | number })[]} loading={list.loading} sort={sortKey} dir={dir} onSort={onSort}
        onRow={(r) => { if (r.row_kind === "clip") onOpen(r.id as string); }}
        selectable selected={picked} onSelect={(id) => setPicked((p) => { const s = new Set(p); s.has(id) ? s.delete(id) : s.add(id); return s; })}
        onSelectAll={() => setPicked((p) => p.size === keys.length ? new Set() : new Set(keys))} empty="Nothing yet. Press Add work." />
      {body && <Pagination page={body.page} pageSize={body.page_size} total={body.total} onPage={(p) => query.set({ page: p })} onPageSize={(s) => query.set({ page_size: s, page: 1 })} />}
    </Page>
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
        : <div className="hint mt-3">No built-in provider is ready (Settings → Brains), so an external agent works this queue.</div>}
    </div>
  );
}
