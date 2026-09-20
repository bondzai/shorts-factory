import { useCallback, useEffect, useState } from "react";
import { api, q, send } from "../lib/api";
import { num, pct, when, download } from "../lib/format";
import { act, toast } from "../lib/toast";
import { useList } from "../lib/useList";
import { useQuery } from "../lib/route";
import { Page, Toolbar, SearchBox, DataTable, Pagination, Card, Column } from "../ui";
import type { Route } from "../lib/route";
import type { Clip } from "../lib/types";

interface Analytics { n_with_metrics: number; n_published: number; views_90d: number; gate_tier2_pct: number; retained_median: number | null; swipe_away_median: number | null; best?: { views: number; variant: string }; series: { title: string; views: number }[]; by_variant: { key: string; retained_median: number | null; n: number }[] }

export function Results({ channelId, refresh, onOpen, route, navigate }: { channelId: string; refresh: () => Promise<void>; onOpen: (id: string) => void; route: Route; navigate: (v: string, p?: Record<string, string | number | undefined>) => void }) {
  const query = useQuery(route, navigate);
  const [a, setA] = useState<Analytics | null>(null);
  const load = useCallback(() => api<Analytics>(`/api/analytics?${q({ channel: channelId })}`).then(setA).catch((e) => toast((e as Error).message, "error")), [channelId]);
  useEffect(() => { load(); }, [load]);
  const list = useList<Clip>("/api/clips", route, { channel: channelId, status: "published" });
  const after = async () => { list.reload(); await load(); await refresh(); };
  const max = Math.max(...(a?.series || []).map((s) => s.views), 1);
  const sortKey = query.get("sort"), dir = query.get("dir");

  const columns: Column<Clip>[] = [
    { key: "title", label: "Title", sortable: true, render: (c) => <TitleCell c={c} after={after} /> },
    { key: "caption", label: "Caption", render: (c) => <span className="dim">{c.hook_text || "—"}</span> },
    { key: "views", label: "Views", sortable: true, align: "right", render: (c) => num(c.views) },
    { key: "avg_view_pct", label: "Viewed", sortable: true, align: "right", render: (c) => pct(c.avg_view_pct) },
    { key: "swipe_away_pct", label: "Swiped", sortable: true, align: "right", render: (c) => pct(c.swipe_away_pct) },
    { key: "actions", label: "", render: (c) => <MetricsCell c={c} after={after} onOpen={onOpen} /> },
  ];
  return (
    <Page title="How published clips did" lead="Numbers come from YouTube Studio: enter them here as they come in. Two levers stay open on a published clip — its title, and what you learn for the next one.">
      {a && a.n_with_metrics > 0 ? (
        <>
          <div className="tiles">
            <div className="tile"><div className="label">Shorts views, 90 days</div><div className="value">{num(a.views_90d)}</div><div className="sub">{a.gate_tier2_pct}% of the 10M gate</div></div>
            <div className="tile"><div className="label">With metrics</div><div className="value">{a.n_with_metrics}</div><div className="sub">of {a.n_published} published</div></div>
            <div className="tile"><div className="label">Median viewed</div><div className="value">{pct(a.retained_median)}</div><div className="sub">swiped away {pct(a.swipe_away_median)}</div></div>
            <div className="tile"><div className="label">Best clip</div><div className="value">{num(a.best?.views)}</div><div className="sub">{a.best?.variant || "—"}</div></div>
          </div>
          <Card title="Views per clip, in publish order" hint="One clip usually carries a channel. Watch for the tall bar, not the average.">
            <div className="row" style={{ alignItems: "flex-end", gap: 4, height: 120 }}>{a.series.map((s, i) => <div key={i} title={`${s.title} · ${num(s.views)} views`} className="grow" style={{ height: `${Math.max(2, (s.views / max) * 100)}%`, background: s.views === max ? "var(--key)" : "#2b2b38", borderRadius: 2 }} />)}</div>
          </Card>
          <Card title="Viewed, by variant" hint="n is shown because at this sample size n is most of the argument.">
            {a.by_variant.map((g) => <div key={g.key} className="mb-3"><div className="row small"><span className="grow">{g.key}</span><span>{pct(g.retained_median)}</span><span className="hint">n={g.n}</span></div><div className="meter"><span style={{ width: `${Math.max(2, g.retained_median || 0)}%` }} /></div></div>)}
          </Card>
        </>
      ) : <Card hint="No published clip has metrics yet. Enter the first ones below." />}
      <Toolbar total={list.data?.total}><SearchBox value={query.get("q")} onChange={(v) => query.set({ q: v, page: 1 })} placeholder="search published titles" /></Toolbar>
      <DataTable columns={columns} rows={list.data?.items || []} loading={list.loading} sort={sortKey} dir={dir} onSort={(k) => query.set({ sort: k, dir: sortKey === k && dir !== "asc" ? "asc" : "desc", page: 1 })} empty="Nothing published yet." />
      {list.data && <Pagination page={list.data.page} pageSize={list.data.page_size} total={list.data.total} onPage={(p) => query.set({ page: p })} onPageSize={(s) => query.set({ page_size: s, page: 1 })} />}
    </Page>
  );
}

function TitleCell({ c, after }: { c: Clip; after: () => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(c.title || "");
  const save = () => act(async () => {
    const out = await send<{ needs_manual_update?: boolean }>(`/api/clip/${c.id}/text`, { title: title.trim(), why: "changed on the Results screen" }, "PATCH");
    if (out.needs_manual_update) toast("Saved here. Change it in YouTube Studio too — nothing reaches YouTube by itself on a manual channel.");
  }, { after: async () => { setEditing(false); await after(); } });
  return editing
    ? <div className="row"><input className="grow" value={title} maxLength={90} onChange={(e) => setTitle(e.target.value)} /><button className="sm ok" onClick={save}>Save</button><button className="sm" onClick={() => setEditing(false)}>Cancel</button></div>
    : <><div>{c.title} <button className="sm ghost" onClick={() => setEditing(true)}>retitle</button></div><div className="hint">{c.id} · {when(c.published_at)}{c.title_history?.length ? ` · was “${c.title_history.at(-1)!.title}” at ${num(c.title_history.at(-1)!.views)} views` : ""}</div></>;
}

function MetricsCell({ c, after, onOpen }: { c: Clip; after: () => Promise<void>; onOpen: (id: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [m, setM] = useState({ views: String(c.views ?? ""), avg_view_pct: String(c.avg_view_pct ?? ""), swipe_away_pct: String(c.swipe_away_pct ?? ""), likes: "" });
  const save = () => act(() => send(`/api/clip/${c.id}/metrics`, { views: Number(m.views), avg_view_pct: Number(m.avg_view_pct), swipe_away_pct: Number(m.swipe_away_pct), likes: Number(m.likes || 0) }), { ok: "Metrics saved", after: async () => { setEditing(false); await after(); } });
  if (editing) return <div className="row wrap">{(["views", "avg_view_pct", "swipe_away_pct", "likes"] as const).map((k) => <input key={k} type="number" step="any" className="w-sm" placeholder={k.replace(/_/g, " ")} value={m[k]} onChange={(e) => setM({ ...m, [k]: e.target.value })} />)}<button className="sm ok" onClick={save}>Save</button><button className="sm" onClick={() => setEditing(false)}>Cancel</button></div>;
  return <span className="row" style={{ whiteSpace: "nowrap" }}><button className="sm" onClick={() => onOpen(c.id)}>View</button><button className="sm" onClick={() => setEditing(true)}>Enter metrics</button>{c.has_video && <button className="sm" onClick={() => download(c.id)}>Download</button>}</span>;
}
