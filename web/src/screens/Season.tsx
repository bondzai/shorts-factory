// Season: the channel's plan, level by level, and the table it adds up to.
// Tick ready levels and press Plan; blocked levels say what they wait for.
// Same functions as `factory season status|standings|plan`.
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, q, send, ApiError } from "../lib/api";
import { clipWord, clipTone, levelWord, levelTone, plural } from "../lib/format";
import { act, toast } from "../lib/toast";
import { useQuery } from "../lib/route";
import type { Route } from "../lib/route";
import { Page, Toolbar, DataTable, Badge, Card, ErrorNote, Column } from "../ui";

export interface Level {
  id: string; date: string; world: string; file_status: string; blocked_on: string | null; missing_input: string[]; note: string | null;
  status: string; reason: string | null; task_id: number | null; clip_id: string | null; clip_status: string | null; title?: string | null;
  story_attempts: number | null; copy_source: string | null; points: Record<string, number> | null; plannable: boolean;
}
export interface Problem { level_id: string | null; severity: "error" | "warning"; message: string }
export interface SeasonView {
  season: string; title: string; channel: string; levels: Level[]; counts: Record<string, number>; copy_sources: Record<string, number>;
  worlds: string[]; next_ready: string[]; problems: Problem[];
}
interface Standing { entrant_id: string; name: string; points: number; wins: number; races: number }

const STATUSES = ["ready", "planned", "rendered", "failed", "needs_input", "blocked"];

export function Season({ channelId, refresh, onOpen, route, navigate }: {
  channelId: string; refresh: () => Promise<void>; onOpen: (id: string) => void; route: Route; navigate: (v: string, p?: Record<string, string | number | undefined>) => void;
}) {
  const query = useQuery(route, navigate);
  const [view, setView] = useState<SeasonView | null>(null);
  const [table, setTable] = useState<Standing[] | null>(null);
  const [missing, setMissing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string | number>>(new Set());
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, t] = await Promise.all([
        api<SeasonView>(`/api/season?${q({ channel: channelId })}`),
        api<{ table: Standing[] }>(`/api/season/standings?${q({ channel: channelId })}`),
      ]);
      setView(s); setTable(t.table); setMissing(null); setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setMissing(e.message); else setError((e as Error).message);
    }
  }, [channelId]);
  useEffect(() => { load(); }, [load]);

  // ?level=L05 is what the command bar's `open L05` lands on: that one row.
  const world = query.get("world"), status = query.get("status"), only = query.get("level");
  const rows = useMemo(() => (view?.levels || []).filter((l) => (!only || l.id === only) && (!world || l.world === world) && (!status || l.status === status)), [view, world, status, only]);

  if (missing) {
    return (
      <Page title="Season">
        <Card title="This channel has no season yet" hint={missing}>
          <p className="small">A season is a file, <code>channels/&lt;channel&gt;/season/s0.yaml</code>, that lists every level: its date, world, stage and cast. Once it is there, this screen shows each level and plans the ready ones.</p>
          <p className="mt-3"><a href="#/settings?tab=docs">Read how seasons work</a></p>
        </Card>
      </Page>
    );
  }
  if (error && !view) return <Page title="Season"><ErrorNote message={`Could not read the season: ${error}`} retry={load} /></Page>;
  if (!view) return <Page title="Season"><p className="empty">Loading…</p></Page>;

  const count = (s: string) => view.levels.filter((l) => l.status === s).length;
  const made = count("rendered");
  const selected = [...picked].map(String);
  const plan = async (ids: string[]) => {
    setBusy(true);
    try {
      const out = await act(() => send<{ queued: number; results: { level: string; queued: boolean; reason: string | null }[] }>("/api/season/plan", { channel: channelId, levels: ids }));
      if (out) {
        const refused = out.results.filter((r) => !r.queued);
        if (out.queued) toast(`Queued ${plural(out.queued, "level")}. An agent or \`factory work\` makes them next.`);
        refused.forEach((r) => toast(`${r.level} not queued: ${r.reason}`, "error"));
        setPicked(new Set());
        await load(); await refresh();
      }
    } finally { setBusy(false); }
  };
  const errors = view.problems.filter((p) => p.severity === "error");
  const warnings = view.problems.filter((p) => p.severity !== "error");

  const columns: Column<Level>[] = [
    { key: "id", label: "Level", width: "92px", render: (l) => <><b>{l.id}</b><div className="hint nowrap">{l.date}</div></> },
    { key: "world", label: "World", wide: true, render: (l) => <span className="dim">{l.world}</span> },
    { key: "status", label: "Status", render: (l) => <>
        <Badge tone={levelTone(l.status)}>{levelWord(l.status)}</Badge>
        {l.status === "blocked" && l.blocked_on && <div className="hint wait">Waits for: {l.blocked_on}</div>}
        {l.status === "needs_input" && l.missing_input.length > 0 && <div className="hint wait">Fill in: {l.missing_input.join(", ")}</div>}
        {l.status === "failed" && l.reason && <div className="hint no-text wait">{l.reason.slice(0, 140)}</div>}
      </> },
    { key: "clip", label: "Clip", render: (l) => l.clip_id
        ? <><button className="link left" onClick={() => onOpen(l.clip_id!)}>{l.title || l.clip_id}</button><div><Badge tone={clipTone(l.clip_status)}>{clipWord(l.clip_status)}</Badge></div></>
        : l.task_id ? <span className="hint">task #{l.task_id}</span> : <span className="faint">—</span> },
    { key: "tries", label: "Story tries", wide: true, align: "right", render: (l) => l.story_attempts ?? <span className="faint">—</span> },
    { key: "copy", label: "Copy", wide: true, render: (l) => l.copy_source ? <span className="dim">{l.copy_source}</span> : <span className="faint">—</span> },
  ];

  const summary = [
    `${view.levels.length} levels`, made && `${made} made`, count("planned") && `${count("planned")} planned`,
    count("ready") && `${count("ready")} ready`, count("needs_input") && `${count("needs_input")} need your input`, count("blocked") && `${count("blocked")} blocked`,
  ].filter(Boolean).join(" · ");

  return (
    <Page title={view.title || `Season ${view.season}`} lead={summary}
      action={<button className="primary" disabled={!selected.length || busy} onClick={() => plan(selected)}>{busy ? "Planning…" : selected.length ? `Plan ${plural(selected.length, "level")}` : "Plan selected"}</button>}>
      {error && <ErrorNote message={`Could not refresh: ${error}`} retry={load} />}
      {errors.length > 0 && (
        <Card title={`The season file has ${plural(errors.length, "problem")}`} hint="Levels with an error are refused by Plan until the file is fixed. `factory season check` prints the same list.">
          <ul className="problems">{errors.slice(0, 8).map((p, i) => <li key={i}><b>{p.level_id || "season"}</b> {p.message}</li>)}</ul>
          {errors.length > 8 && <p className="hint">…and {errors.length - 8} more.</p>}
        </Card>
      )}
      <div className="season">
        <section className="season-levels" aria-label="Levels">
          <Toolbar total={rows.length}>
            {only && <span className="pill">Showing <b>{only}</b><button className="link" onClick={() => query.set({ level: undefined })}>Show all levels</button></span>}
            <label className="row"><span className="hint">World</span>
              <select value={world} onChange={(e) => query.set({ world: e.target.value })}>
                <option value="">All worlds</option>{view.worlds.map((w) => <option key={w} value={w}>{w}</option>)}
              </select></label>
            <label className="row"><span className="hint">Status</span>
              <select value={status} onChange={(e) => query.set({ status: e.target.value })}>
                <option value="">Any status</option>{STATUSES.filter((s) => count(s)).map((s) => <option key={s} value={s}>{levelWord(s)} ({count(s)})</option>)}
              </select></label>
            {!selected.length && view.next_ready.length > 0 && <span className="hint">Tick ready levels to plan them.</span>}
            {selected.length > 0 && <button className="sm ghost" onClick={() => setPicked(new Set())}>Clear selection</button>}
          </Toolbar>
          <DataTable label="Levels" columns={columns} rows={rows} selectable selected={picked} canSelect={(l) => l.plannable}
            onSelect={(id) => setPicked((p) => { const s = new Set(p); s.has(id) ? s.delete(id) : s.add(id); return s; })}
            onSelectAll={() => { const ids = rows.filter((l) => l.plannable).map((l) => l.id); setPicked((p) => ids.every((i) => p.has(i)) ? new Set() : new Set(ids)); }}
            empty="No level matches these filters." />
          {warnings.length > 0 && (
            <details className="mt-3"><summary className="hint">{plural(warnings.length, "warning")} from the season check</summary>
              <ul className="problems">{warnings.map((p, i) => <li key={i}><b>{p.level_id || "season"}</b> {p.message}</li>)}</ul>
            </details>
          )}
        </section>
        <aside className="season-table" aria-label="Standings">
          <Card title="Standings" hint={made ? "Points from approved races." : "The table fills in as level clips are approved."}>
            {table && table.length ? (
              <table className="data compact">
                <thead><tr><th>#</th><th>Entrant</th><th style={{ textAlign: "right" }}>Points</th><th style={{ textAlign: "right" }}>Wins</th><th style={{ textAlign: "right" }}>Races</th></tr></thead>
                <tbody>{table.map((r, i) => <tr key={r.entrant_id}><td className="faint">{i + 1}</td><td>{r.name}</td><td className="num"><b>{r.points}</b></td><td className="num">{r.wins}</td><td className="num">{r.races}</td></tr>)}</tbody>
              </table>
            ) : <p className="hint">No entrants yet.</p>}
          </Card>
          {Object.keys(view.copy_sources).length > 0 && (
            <Card title="Where the words came from" hint="Per made level: the local brain, the template fallback, or a mix.">
              {Object.entries(view.copy_sources).map(([k, v]) => <div key={k} className="row small"><span className="grow">{k}</span><b>{v}</b></div>)}
            </Card>
          )}
        </aside>
      </div>
    </Page>
  );
}
