// The bin: clips thrown away but not yet gone. Restore puts one back where it
// was; Delete forever removes the render and the record.
import { useEffect, useState } from "react";
import { send } from "../lib/api";
import { num, pct, when, statusWord, download } from "../lib/format";
import { act } from "../lib/toast";
import { useList } from "../lib/useList";
import { useQuery } from "../lib/route";
import { Page, Toolbar, SearchBox, Chips, DataTable, Pagination, Badge, Column } from "../ui";
import type { Route } from "../lib/route";
import type { Clip } from "../lib/types";

interface BinPage { items: Clip[]; total: number; page: number; page_size: number; modules: Record<string, string[]> }

export function Bin({ channelId, refresh, onOpen, route, navigate }: {
  channelId: string; refresh: () => Promise<void>; onOpen: (id: string) => void; route: Route; navigate: (v: string, p?: Record<string, string | number | undefined>) => void;
}) {
  const query = useQuery(route, navigate);
  const list = useList<Clip>("/api/clips", route, { channel: channelId, variant: query.get("variant"), bin: true });
  const body = list.data as BinPage | null;
  const [picked, setPicked] = useState<Set<string | number>>(new Set());
  useEffect(() => setPicked(new Set()), [list.data]);
  const ids = (body?.items || []).map((c) => c.id);
  const after = async () => { list.reload(); await refresh(); };
  const bulk = (path: string, confirmText?: string) => { if (confirmText && !window.confirm(confirmText)) return; act(() => send(path, { ids: [...picked] }), { after }); };
  const n = picked.size;

  const columns: Column<Clip>[] = [
    { key: "title", label: "Title", sortable: true, render: (c) => <><div>{c.title || "(untitled)"}</div><div className="hint">{c.id} · seed {c.seed}{c.reject_reason && <> · <span className="no-text">{c.reject_reason.slice(0, 80)}</span></>}</div></> },
    { key: "variant", label: "Module", render: (c) => <span className="dim">{c.variant}</span> },
    { key: "status", label: "Was", sortable: true, render: (c) => <Badge>{statusWord(c.status)}</Badge> },
    { key: "views", label: "Views", sortable: true, align: "right", render: (c) => num(c.views) },
    { key: "avg_view_pct", label: "Viewed", sortable: true, align: "right", render: (c) => pct(c.avg_view_pct) },
    { key: "created_at", label: "Made", sortable: true, render: (c) => <span className="dim small">{when(c.created_at)}</span> },
    { key: "actions", label: "", render: (c) => <span className="row" style={{ whiteSpace: "nowrap" }}>
        <button className="sm" onClick={() => onOpen(c.id)}>View</button>
        {c.has_video ? <button className="sm" onClick={() => download(c.id)}>Download</button> : <span className="hint">no file</span>}
      </span> },
  ];
  const sortKey = query.get("sort"), dir = query.get("dir");
  const onSort = (k: string) => query.set({ sort: k, dir: sortKey === k && dir !== "asc" ? "asc" : "desc", page: 1 });

  return (
    <Page title="Bin"
      lead="Binned clips are hidden everywhere and count for nothing, but their files are still here. Restore puts one back where it was; Delete forever removes the render and the record."
      action={<span className="row"><button className="sm" disabled={!n} onClick={() => bulk("/api/clips/unbin")}>Restore {n || ""}</button><button className="sm danger" disabled={!n} onClick={() => bulk("/api/clips/destroy", `Delete ${n} clip(s) and their files for good? This cannot be undone.`)}>Delete forever {n || ""}</button></span>}>
      <Toolbar total={body?.total}>
        <SearchBox value={query.get("q")} onChange={(v) => query.set({ q: v, page: 1 })} placeholder="search titles, ids, descriptions" />
        <Chips options={Object.values(body?.modules || {}).flat().map((v) => ({ value: v }))} value={query.get("variant")} onChange={(v) => query.set({ variant: v, page: 1 })} all="any variant" />
      </Toolbar>
      <DataTable columns={columns} rows={body?.items || []} loading={list.loading} sort={sortKey} dir={dir} onSort={onSort} onRow={(c) => onOpen(c.id)}
        selectable selected={picked} onSelect={(id) => setPicked((p) => { const s = new Set(p); s.has(id) ? s.delete(id) : s.add(id); return s; })}
        onSelectAll={() => setPicked((p) => p.size === ids.length ? new Set() : new Set(ids))} empty="The bin is empty." />
      {body && <Pagination page={body.page} pageSize={body.page_size} total={body.total} onPage={(p) => query.set({ page: p })} onPageSize={(s) => query.set({ page_size: s, page: 1 })} />}
    </Page>
  );
}
