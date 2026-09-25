// The bin, as Clips shows it when the status filter says "In the bin": clips
// thrown away but not yet gone. Restore puts one back where it was; Delete
// forever removes the render and the record.
import { useEffect, useState } from "react";
import { send } from "../lib/api";
import { num, pct, when, clipWord, download } from "../lib/format";
import { act } from "../lib/toast";
import { useList } from "../lib/useList";
import { useQuery } from "../lib/route";
import { DataTable, Pagination, Badge, Column } from "../ui";
import type { Route } from "../lib/route";
import type { Clip } from "../lib/types";

interface BinPage { items: Clip[]; total: number; page: number; page_size: number; modules: Record<string, string[]> }

export function BinList({ channelId, refresh, onOpen, route, navigate }: {
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
    { key: "variant", label: "Module", wide: true, render: (c) => <span className="dim">{c.variant}</span> },
    { key: "status", label: "Was", sortable: true, render: (c) => <Badge>{clipWord(c.status)}</Badge> },
    { key: "views", label: "Views", sortable: true, align: "right", wide: true, render: (c) => num(c.views) },
    { key: "avg_view_pct", label: "Viewed", sortable: true, align: "right", wide: true, render: (c) => pct(c.avg_view_pct) },
    { key: "created_at", label: "Made", sortable: true, wide: true, render: (c) => <span className="dim small nowrap">{when(c.created_at)}</span> },
    { key: "actions", label: <span className="sr-only">Actions</span>, render: (c) => <span className="row actions">
        <button className="sm" onClick={() => onOpen(c.id)}>View</button>
        {c.has_video ? <button className="sm" onClick={() => download(c.id)}>Download</button> : <span className="hint">no file</span>}
      </span> },
  ];
  const sortKey = query.get("sort"), dir = query.get("dir");
  const onSort = (k: string) => query.set({ sort: k, dir: sortKey === k && dir !== "asc" ? "asc" : "desc", page: 1 });

  return (
    <>
      <div className="selection quiet" role="region" aria-label="Bin actions">
        <span className="hint grow">Binned clips are hidden everywhere else and count for nothing; their files are kept until you delete them.</span>
        <button className="sm" disabled={!n} onClick={() => bulk("/api/clips/unbin")}>Restore{n ? ` ${n}` : ""}</button>
        <button className="sm danger" disabled={!n} onClick={() => bulk("/api/clips/destroy", `Delete ${n} clip(s) and their files for good? This cannot be undone.`)}>Delete forever{n ? ` ${n}` : ""}</button>
      </div>
      <DataTable label="Clips in the bin" columns={columns} rows={body?.items || []} loading={list.loading} sort={sortKey} dir={dir} onSort={onSort} onRow={(c) => onOpen(c.id)}
        selectable selected={picked} onSelect={(id) => setPicked((p) => { const s = new Set(p); s.has(id) ? s.delete(id) : s.add(id); return s; })}
        onSelectAll={() => setPicked((p) => p.size === ids.length ? new Set() : new Set(ids))} empty="The bin is empty. Clips you move to the bin wait here until you restore or delete them." />
      {body && <Pagination page={body.page} pageSize={body.page_size} total={body.total} onPage={(p) => query.set({ page: p })} onPageSize={(s) => query.set({ page_size: s, page: 1 })} />}
    </>
  );
}
