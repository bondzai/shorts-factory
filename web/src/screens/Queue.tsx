import { useEffect, useState } from "react";
import { api, q, send } from "../lib/api";
import { when, statusWord } from "../lib/format";
import { act } from "../lib/toast";
import { useList } from "../lib/useList";
import { useQuery } from "../lib/route";
import { Page, Toolbar, SearchBox, Chips, DataTable, Pagination, Badge, Modal, Column } from "../ui";
import type { Route } from "../lib/route";
import type { Snap, Task, TaskKind } from "../lib/types";

export function Queue({ snap, channelId, refresh, onOpen, route, navigate }: {
  snap: Snap; channelId: string; refresh: () => Promise<void>; onOpen: (id: string) => void; route: Route; navigate: (v: string, p?: Record<string, string | number | undefined>) => void;
}) {
  const query = useQuery(route, navigate);
  const list = useList<Task>("/api/tasks", route, { channel: channelId, status: query.get("status"), kind: query.get("kind") }, [snap.tasks?.queued, snap.tasks?.claimed, snap.tasks?.done, snap.tasks?.failed]);
  const [kinds, setKinds] = useState<Record<string, TaskKind>>({});
  useEffect(() => { api<{ kinds: Record<string, TaskKind> }>(`/api/tasks?${q({ channel: channelId, page_size: 25 })}`).then((b) => setKinds(b.kinds)).catch(() => {}); }, [channelId]);
  const [modal, setModal] = useState<"add" | "handoff" | null>(null);
  const after = async () => { list.reload(); await refresh(); };
  const cancel = (id: number) => act(() => api(`/api/tasks/${id}`, { method: "DELETE" }), { ok: "Cancelled", after });
  const [picked, setPicked] = useState<Set<string | number>>(new Set());
  useEffect(() => setPicked(new Set()), [list.data]);
  const ids = (list.data?.items || []).map((t) => t.id);
  const n = picked.size;
  const bulk = (path: string, body: unknown, confirmText?: string) => { if (confirmText && !window.confirm(confirmText)) return; act(() => send(path, body), { after: async () => { setPicked(new Set()); await after(); } }); };
  const tone = (s: string) => s === "done" ? "ok" : s === "failed" ? "no" : s === "claimed" ? "key" : undefined;

  const columns: Column<Task>[] = [
    { key: "id", label: "#", sortable: true, width: "48px", render: (t) => <span className="dim">{t.id}</span> },
    { key: "kind", label: "task", sortable: true, render: (t) => <><b>{t.kind}</b><div className="hint">{t.meaning}</div></> },
    { key: "params", label: "parameters", render: (t) => <span className="dim small">{Object.entries(t.params).map(([k, v]) => `${k}=${v}`).join(" ") || "—"}</span> },
    { key: "status", label: "status", sortable: true, render: (t) => <><Badge tone={tone(t.status)}>{statusWord(t.status)}</Badge><div className="hint">{when(t.finished_at || t.claimed_at || t.created_at)}</div></> },
    { key: "claimed_by", label: "who", sortable: true, render: (t) => <span className="dim">{t.claimed_by || ""}</span> },
    { key: "result", label: "result", render: (t) => <span className="small">{t.error ? <span className="no-text">{t.error}</span> : (t.result?.summary || t.result?.detail || "")}{t.clip_id && <> <button className="sm" onClick={() => onOpen(t.clip_id!)}>View clip</button></>}</span> },
    { key: "actions", label: "", render: (t) => ["queued", "claimed"].includes(t.status) ? <button className="sm" onClick={() => cancel(t.id)}>Cancel</button> : null },
  ];

  return (
    <Page title="What agents will do next" lead="Any agent connected over MCP pulls the next task with its full instructions and reports back. Live progress is on Today; what every agent is told is under Settings → Directions."
      action={<div className="row"><button className="primary" onClick={() => setModal("add")}>Add work</button><button onClick={() => setModal("handoff")}>Hand off to an agent</button></div>}>
      {modal === "add" && <Modal title="Add work" onClose={() => setModal(null)}><AddWork snap={snap} channelId={channelId} kinds={kinds} after={async () => { setModal(null); list.reload(); await refresh(); }} /></Modal>}
      {modal === "handoff" && <Modal title="Hand the queue to an agent" onClose={() => setModal(null)}><HandOff snap={snap} channelId={channelId} refresh={refresh} /></Modal>}
      <Toolbar total={list.data?.total}>
        <button className="sm" disabled={!n} onClick={() => bulk("/api/tasks/cancel", { ids: [...picked] })}>Cancel {n || ""}</button>
        <button className="sm danger" disabled={!n} onClick={() => bulk("/api/tasks/delete", { ids: [...picked] }, `Delete ${n} task(s) from the queue? Clips they made stay.`)}>Delete {n || ""}</button>
        <button className="sm" onClick={() => bulk("/api/tasks/clear", { channel: channelId }, "Remove every done, failed and cancelled task on this channel?")}>Clear finished</button>
        <SearchBox value={query.get("q")} onChange={(v) => query.set({ q: v, page: 1 })} placeholder="search parameters, results, who" />
        <Chips options={["queued", "claimed", "done", "failed", "cancelled"].map((v) => ({ value: v }))} value={query.get("status")} onChange={(v) => query.set({ status: v, page: 1 })} />
        <Chips options={Object.keys(kinds).map((v) => ({ value: v }))} value={query.get("kind")} onChange={(v) => query.set({ kind: v, page: 1 })} all="any kind" />
      </Toolbar>
      <DataTable columns={columns} rows={list.data?.items || []} loading={list.loading} sort={query.get("sort")} dir={query.get("dir")}
        onSort={(k) => query.set({ sort: k, dir: query.get("sort") === k && query.get("dir") !== "asc" ? "asc" : "desc", page: 1 })}
        selectable selected={picked} onSelect={(id) => setPicked((p) => { const s = new Set(p); s.has(id) ? s.delete(id) : s.add(id); return s; })}
        onSelectAll={() => setPicked((p) => p.size === ids.length ? new Set() : new Set(ids))}
        empty="Nothing queued. Press Add work." />
      {list.data && <Pagination page={list.data.page} pageSize={list.data.page_size} total={list.data.total} onPage={(p) => query.set({ page: p })} onPageSize={(s) => query.set({ page_size: s, page: 1 })} />}
    </Page>
  );
}

function AddWork({ snap, channelId, kinds, after }: { snap: Snap; channelId: string; kinds: Record<string, TaskKind>; after: () => Promise<void> }) {
  const [kind, setKind] = useState("make-clip");
  const [params, setParams] = useState<Record<string, string>>({});
  const [count, setCount] = useState(1);
  const spec = kinds[kind] || { params: {}, builtin: false, meaning: "" };
  const variants = snap.channel.variants || [];
  const add = (e: React.FormEvent) => { e.preventDefault(); act(() => send("/api/tasks", { channel: channelId, kind, params, count: Number(count) }), { ok: `Queued ${count}`, after: async () => { setParams({}); setCount(1); await after(); } }); };
  const input = (k: string) => {
    if (k === "generator") return null;
    if (k === "variant") return <select key={k} value={params.variant || ""} onChange={(e) => setParams({ ...params, variant: e.target.value, generator: e.target.value.split("/")[0] })}><option value="">variant…</option>{variants.map((v) => <option key={v} value={v.split("/")[1]}>{v}</option>)}</select>;
    if (k === "course") return <select key={k} value={params.course || ""} onChange={(e) => setParams({ ...params, course: e.target.value })} title="the shape of the descent; empty lets the seed choose"><option value="">any course</option>{["zigzag", "pegboard", "bumpers"].map((c) => <option key={c} value={c}>{c}</option>)}</select>;
    if (k === "background") return <label key={k} className="row small dim" title="backdrop colour; unticked lets the theme choose"><input type="checkbox" checked={!!params.background} onChange={(e) => setParams({ ...params, background: e.target.checked ? "#1a1a2a" : "" })} /> backdrop{params.background && <input type="color" value={params.background} onChange={(e) => setParams({ ...params, background: e.target.value })} />}</label>;
    return <input key={k} className="w-sm" placeholder={k} value={params[k] ?? ""} onChange={(e) => setParams({ ...params, [k]: e.target.value })} />;
  };
  return (
    <form className="stack" onSubmit={add}>
      <select value={kind} onChange={(e) => { setKind(e.target.value); setParams({}); }}>{Object.entries(kinds).map(([k, v]) => <option key={k} value={k}>{k} — {v.meaning}</option>)}</select>
      <div className="row wrap">
        {Object.keys(spec.params).map(input)}
        {kind === "make-clip" && <label className="row small dim">×<input type="number" className="w-sm" min={1} max={50} value={count} onChange={(e) => setCount(Number(e.target.value))} /></label>}
      </div>
      <div className="row"><button type="submit" className="primary">Add to queue</button><span className="hint">{spec.builtin ? "built-in agents can do this" : "needs an external agent's judgement"}</span></div>
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
