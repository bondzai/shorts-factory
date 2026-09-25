import { useEffect, useState } from "react";
import { api, q, Page as PageT } from "../lib/api";
import { when, clock, fmt } from "../lib/format";
import { toast } from "../lib/toast";
import { useQuery } from "../lib/route";
import { Toolbar, SearchBox, Chips, Pagination } from "../ui";
import type { Route } from "../lib/route";
import type { LogEvent, Run } from "../lib/types";

export function Activity({ channelId, route, navigate }: { channelId: string; route: Route; navigate: (v: string, p?: Record<string, string | number | undefined>) => void }) {
  const query = useQuery(route, navigate);
  const [runs, setRuns] = useState<Run[]>([]);
  const [events, setEvents] = useState<PageT<LogEvent> | null>(null);
  const level = query.get("level"), actor = query.get("actor");
  const page = Number(query.get("page", "1")), pageSize = Number(query.get("page_size", "25"));
  useEffect(() => {
    Promise.all([
      api<PageT<Run>>(`/api/runs?${q({ channel: channelId, page_size: 100 })}`),
      api<PageT<LogEvent>>(`/api/logs?${q({ channel: channelId, level: level === "warn" ? undefined : level, q: query.get("q"), page, page_size: pageSize })}`),
    ]).then(([r, l]) => { setRuns(r.items); setEvents(l); }).catch((e) => toast((e as Error).message, "error"));
  }, [channelId, level, page, pageSize, query.get("q")]);
  if (!events) return <p className="empty">Loading…</p>;

  const t = (iso: string) => Date.parse(iso) || 0;
  const visible = events.items.filter((e) =>
    (!level || (level === "warn" ? ["warn", "error"].includes(e.level) : e.level === level)) &&
    (!actor || (actor === "agent" ? (e.actor === "mcp" || e.by === "agent") : (e.by === "human" || !e.actor))));
  const inRun = new Set<LogEvent>();
  const chapters = runs.map((r) => { const start = t(r.started_at), end = r.ended_at ? t(r.ended_at) + 1500 : Infinity; const inside = visible.filter((e) => { const at = t(e.at); return at >= start && at <= end; }); inside.forEach((e) => inRun.add(e)); return { at: r.started_at, run: r, events: inside }; }).filter((c) => c.events.length);
  const loose = visible.filter((e) => !inRun.has(e)).map((e) => ({ at: e.at, event: e }));
  const timeline = [...chapters.map((c) => ({ ...c, event: undefined as LogEvent | undefined })), ...loose.map((l) => ({ ...l, run: undefined as Run | undefined, events: [] as LogEvent[] }))].sort((a, b) => t(b.at) - t(a.at));
  const detail = (e: LogEvent) => JSON.stringify(Object.fromEntries(Object.entries(e).filter(([k, v]) => !["at", "level", "event", "channel", "clip", "actor"].includes(k) && v !== null))).slice(0, 180);
  const tone = (l: string) => l === "error" ? "no-text" : l === "warn" ? "key-text" : "";
  const line = (e: LogEvent) => <div key={e.at + e.event} className="event"><span className="t">{clock(e.at)}</span><span className={tone(e.level)}>{e.event}{e.clip && <span className="hint"> {e.clip}</span>}</span><span className="d">{detail(e)}</span></div>;

  return (
    <>
      <p className="page-lead">Each box is one job (a build, a re-render, a plan) with the events it produced inside. Lines outside a box came from the command line, an agent, or a decision on Team.</p>
      <Toolbar total={events.total}>
        <SearchBox value={query.get("q")} onChange={(v) => query.set({ q: v, page: 1 })} placeholder="search events" />
        <Chips options={[{ value: "warn", label: "problems only" }]} value={level} onChange={(v) => query.set({ level: v, page: 1 })} all="everything" />
        <Chips options={[{ value: "agent", label: "by an agent" }, { value: "human", label: "by a person" }]} value={actor} onChange={(v) => query.set({ actor: v })} all={null} />
      </Toolbar>
      {timeline.map((item) => item.run ? (
        <details key={"run" + item.run.id} className="run" open={item.run.status === "failed"}>
          <summary><span className="hint">{when(item.run.started_at)}</span><b>{item.run.kind}</b><span className={item.run.status === "failed" ? "no-text" : item.run.status === "ok" ? "ok-text" : "dim"}>{item.run.status}</span><span className="hint grow">{item.run.detail || ""}</span><span className="hint">{item.events.length} events{item.run.cost_usd ? ` · $${fmt(item.run.cost_usd, 4)}` : ""}</span></summary>
          <div className="events">{item.events.map(line)}{item.run.log && <pre className="captured mt-3">{item.run.log}</pre>}</div>
        </details>
      ) : <div key={item.event!.at + item.event!.event} className="run" style={{ padding: "0 var(--s4)", border: "1px solid var(--line)", borderRadius: "var(--r2)", marginBottom: "var(--s2)" }}>{line(item.event!)}</div>)}
      {!timeline.length && <p className="empty">Nothing matches. Clear the search or the filters.</p>}
      <Pagination page={events.page} pageSize={events.page_size} total={events.total} onPage={(p) => query.set({ page: p })} onPageSize={(s) => query.set({ page_size: s, page: 1 })} />
    </>
  );
}
