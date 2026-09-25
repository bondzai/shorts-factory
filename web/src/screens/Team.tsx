// Team: the home page, the office you walk into. A briefing in plain words,
// then the decisions only you can make, then the desks — who is working on
// what — and, below the fold, jobs, spend and the log. The command bar in
// the header runs everything here by name.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, q, send, ApiError } from "../lib/api";
import { clock, plural } from "../lib/format";
import { act, toast } from "../lib/toast";
import type { Route } from "../lib/route";
import { Todo } from "../ui";
import { Flow } from "../ui/Review";
import type { Brains } from "../lib/command";
import type { Run, Snap } from "../lib/types";
import type { SeasonView } from "./Season";
import { Office, Integrate, loadWorkers, displayName, STEP_VERB } from "./Office";
import type { Overview, WorkersView } from "./Office";
import { Jobs } from "./Jobs";
import { Activity } from "./Activity";

type Nav = (v: string, p?: Record<string, string | number | undefined>) => void;

export function Team({ snap, channelId, refresh, route, navigate, onOpen, sound, setSound }: {
  snap: Snap; channelId: string; refresh: () => Promise<void>; route: Route; navigate: Nav; onOpen: (id: string) => void;
  sound: boolean; setSound: (v: boolean) => void;
}) {
  const [team, setTeam] = useState<Overview | null>(null);
  const [teamError, setTeamError] = useState<string | null>(null);
  const [workers, setWorkers] = useState<WorkersView | null>(null);
  const [brains, setBrains] = useState<Brains | null>(null);
  const [season, setSeason] = useState<SeasonView | null | "none">(null);
  const [runs, setRuns] = useState<Run[]>([]);

  useEffect(() => {
    let alive = true;
    const load = () => api<Overview>("/api/team").then((b) => { if (alive) { setTeam(b); setTeamError(null); } }).catch((e) => alive && setTeamError((e as Error).message));
    load(); const id = setInterval(load, 4000);
    return () => { alive = false; clearInterval(id); };
  }, []);
  const reloadWorkers = useCallback(() => { loadWorkers(channelId).then(setWorkers).catch((e) => toast((e as Error).message, "error")); }, [channelId]);
  useEffect(() => { reloadWorkers(); const id = setInterval(reloadWorkers, 5000); return () => clearInterval(id); }, [reloadWorkers]);
  const loadSeason = useCallback(() => api<SeasonView>(`/api/season?${q({ channel: channelId })}`).then(setSeason)
    .catch((e) => { if (e instanceof ApiError && e.status === 404) setSeason("none"); }), [channelId]);
  useEffect(() => { loadSeason(); }, [loadSeason, snap.tasks?.queued, snap.tasks?.done, snap.queue.length]);
  const jobRunning = !!snap.job?.running;
  useEffect(() => {
    api<Brains>("/api/brains").then(setBrains).catch(() => {});
    api<{ items: Run[] }>(`/api/runs?${q({ channel: channelId, page_size: 50 })}`).then((b) => setRuns(b.items)).catch(() => {});
  }, [channelId, jobRunning]);

  const reloadAll = useCallback(async () => { await refresh(); await loadSeason(); }, [refresh, loadSeason]);
  const seasonView = season && season !== "none" ? season : null;
  const panel = route.params.get("panel") || "";

  return (
    <>
      <Briefing snap={snap} team={team} brains={brains} season={seasonView} />
      <Decisions snap={snap} channelId={channelId} refresh={reloadAll} navigate={navigate} onOpen={onOpen} sound={sound} setSound={setSound}
        brains={brains} season={seasonView} noSeason={season === "none"} />

      <section className="section" aria-labelledby="office-h">
        <div className="section-head">
          <h2 id="office-h">The office</h2>
          {team && <span className="hint">{plural(team.totals.working, "task")} in progress · {team.totals.queued} queued</span>}
        </div>
        {teamError && !team ? <p className="no-text small">Could not load the team: {teamError}</p>
          : <Office team={team} workers={workers} brains={brains} runs={runs} channelId={channelId} channelName={snap.channel.name}
              jobName={snap.job?.running ? snap.job.name : null} reloadWorkers={reloadWorkers} onOpen={onOpen} />}
      </section>

      <section className="section" aria-labelledby="more-h">
        <div className="section-head"><h2 id="more-h">Records</h2><span className="hint">Jobs, spend, what happened</span></div>
        <Panel id="jobs" title="Jobs and spend" note={snap.job?.running ? `${snap.job.name} running` : `$${snap.spend_usd.toFixed(4)} spent`} want={panel}>
          <Jobs snap={snap} channelId={channelId} refresh={refresh} brains={brains} />
        </Panel>
        <Panel id="feed" title="Just happened" note={team?.feed[0] ? `last at ${clock(team.feed[0].at)}` : undefined} want={panel}>
          <Feed team={team} onOpen={onOpen} />
        </Panel>
        <Panel id="activity" title="Activity log" note="every job and event, searchable" want={panel}>
          <div className="panel-body"><Activity channelId={channelId} route={route} navigate={navigate} /></div>
        </Panel>
        {workers && <Panel id="connect" title="Connect an outside agent" note="Claude Code, Codex, any MCP client" want={panel}><Integrate it={workers.integration} /></Panel>}
      </section>
    </>
  );
}

/* The greeting and one paragraph of what matters, from the numbers. */
function Briefing({ snap, team, brains, season }: { snap: Snap; team: Overview | null; brains: Brains | null; season: SeasonView | null }) {
  const hour = new Date().getHours();
  const hello = hour < 5 ? "Working late." : hour < 12 ? "Good morning." : hour < 18 ? "Good afternoon." : "Good evening.";
  const review = snap.queue.length;
  const qcWait = snap.counts?.awaiting_qc || 0;
  const approved = snap.approved.length;
  const manual = snap.channel.driver === "manual";
  const parts: string[] = [];
  if (review) parts.push(`${plural(review, "clip")} ${review === 1 ? "waits" : "wait"} for your decision`);
  if (qcWait) parts.push(brains?.qc_enabled === false ? `QC is off, and ${plural(qcWait, "clip")} ${qcWait === 1 ? "is" : "are"} waiting for it` : `${plural(qcWait, "clip")} ${qcWait === 1 ? "waits" : "wait"} for QC`);
  if (approved) parts.push(`${plural(approved, "approved clip")} ${approved === 1 ? "is" : "are"} ready to ${manual ? "upload" : "publish"}`);
  if (season) {
    const next = season.levels.filter((l) => l.plannable).slice(0, 3);
    if (next.length) parts.push(`${runs(next.map((l) => l.id))} ${next.length === 1 ? "is" : "are"} ready to plan`);
  }
  const doing: string[] = [];
  for (const m of team?.members || []) {
    for (const t of m.tasks.slice(0, 2)) {
      const step = t.steps.find((s) => s.state === "current");
      doing.push(`${displayName(m.name)} is ${STEP_VERB[step?.name || ""] || "working on"} ${t.params?.level_id || `task #${t.id}`}`);
    }
  }
  if (snap.job?.running) doing.push(`the console is running ${snap.job.name}`);
  const queued = team?.totals.queued || 0;
  const first = parts.length ? parts.join("; ") + "." : "Nothing needs you.";
  const second = doing.length ? cap(doing.join(", and ")) + "."
    : queued ? `${plural(queued, "task")} ${queued === 1 ? "is" : "are"} queued and nobody is on ${queued === 1 ? "it" : "them"} yet.`
    : "The office is quiet.";
  return (
    <header className="briefing">
      <h1>{hello}</h1>
      <p className="brief" aria-live="polite">{first} {second}</p>
    </header>
  );
}
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/* The inbox: every item that needs you, in the order it pays to do it. */
function Decisions({ snap, channelId, refresh, navigate, onOpen, sound, setSound, brains, season, noSeason }: {
  snap: Snap; channelId: string; refresh: () => Promise<void>; navigate: Nav; onOpen: (id: string) => void; sound: boolean; setSound: (v: boolean) => void;
  brains: Brains | null; season: SeasonView | null; noSeason: boolean;
}) {
  const review = snap.queue;
  const approved = snap.approved;
  const waitingQc = snap.counts?.awaiting_qc || 0;
  const busy = !!snap.job?.running;
  const auto = snap.channel.driver !== "manual";
  const next = season?.levels.filter((l) => l.plannable).slice(0, 3) || [];

  const decide = useCallback(async (id: string, what: "approve" | "reject") => {
    let body: Record<string, string> = {};
    if (what === "reject") {
      const reason = window.prompt("Why? This is what the next planner reads. Cancel keeps the clip.", "");
      if (reason === null) return;
      body = { reason: reason.trim() || "rejected in review" };
    }
    await act(() => send(`/api/clip/${id}/${what}`, body), { after: refresh });
  }, [refresh]);
  const publishAll = () => {
    if (!window.confirm(`Publish ${plural(approved.length, "approved clip")} through ${snap.channel.driver}?`)) return;
    act(() => send("/api/publish", { channel: channelId }), { ok: "Publishing started", after: refresh });
  };
  const count = review.length + (waitingQc ? 1 : 0) + (approved.length ? 1 : 0) + (next.length ? 1 : 0);

  return (
    <section className="section" aria-labelledby="decisions-h">
      <div className="section-head">
        <h2 id="decisions-h">Your decisions</h2>
        {review.length > 0 && <button className="sm ghost right" onClick={() => setSound(!sound)} aria-pressed={sound}>Sound {sound ? "on" : "off"}</button>}
      </div>
      {!count ? (
        <p className="calm"><span className="ok-text" aria-hidden>✓</span> Nothing needs your decision. {noSeason ? "Queue work with the command bar." : "The season is planned as far as it can be."}</p>
      ) : (
        <div className="todos">
          {review.length > 0 && (
            <Todo title="Needs review" count={review.length} hint="Watch it, fix the words if they are off, then approve or reject. Rejections teach the planner.">
              <Flow items={review} keys sound={sound} refresh={refresh} decide={decide} channelId={channelId} onOpen={onOpen} auto={auto} />
            </Todo>
          )}
          {waitingQc > 0 && <QcTodo count={waitingQc} busy={busy} brains={brains} channelId={channelId} refresh={refresh} navigate={navigate} />}
          {approved.length > 0 && (
            <Todo title={auto ? "Ready to publish" : "Ready to upload"} count={approved.length}
              hint={auto ? "Approved clips go up private and turn public at their slot." : "Download each one, upload it in YouTube Studio, then mark it uploaded."}
              action={auto ? <button className="primary" disabled={busy} onClick={publishAll}>Publish {approved.length}</button> : undefined}>
              {auto && busy && <p className="hint mb-3">Wait for the running job to finish before publishing.</p>}
              <Flow items={approved} keys={!review.length} sound={sound} refresh={refresh} decide={decide} channelId={channelId} onOpen={onOpen} auto={auto} />
            </Todo>
          )}
          {next.length > 0 && season && <NextInSeason season={season} next={next} channelId={channelId} refresh={refresh} navigate={navigate} />}
        </div>
      )}
    </section>
  );
}

/* Clips made while QC was off. The reason the button cannot run is on the
   card, not in a tooltip. */
function QcTodo({ count, busy, brains, channelId, refresh, navigate }: { count: number; busy: boolean; brains: Brains | null; channelId: string; refresh: () => Promise<void>; navigate: Nav }) {
  const brain = brains ? (brains.readiness.qc || { ok: false, why: "no QC brain is set" }) : null;
  const why = !brain ? "Checking the QC brain…" : !brain.ok ? `The QC brain is not ready: ${brain.why}.` : busy ? "Wait for the running job to finish." : null;
  return (
    <Todo title="Waiting for QC" count={count}
      hint={`${brains?.qc_enabled === false ? "QC is switched off, so new clips stop here. " : ""}Run QC judges them; nothing is re-rendered.`}
      action={<button className="primary" disabled={!!why} onClick={() => act(() => send("/api/qc", { channel: channelId }), { ok: "QC started", after: refresh })}>Run QC</button>}>
      <div className="row wrap">
        {why && <span className={brain && !brain.ok ? "no-text small" : "hint"}>{why}</span>}
        {brain && !brain.ok && <button className="link" onClick={() => navigate("settings", { tab: "brains" })}>Set up brains</button>}
        <button className="link right" onClick={() => navigate("clips", { phase: "awaiting_qc" })}>See {count === 1 ? "it" : "them"} in Clips</button>
      </div>
    </Todo>
  );
}

/* The season is the plan: the next ready levels and one button that queues
   them. An agent or `factory work` makes them after that. */
function NextInSeason({ season, next, channelId, refresh, navigate }: { season: SeasonView; next: SeasonView["levels"]; channelId: string; refresh: () => Promise<void>; navigate: Nav }) {
  const [busy, setBusy] = useState(false);
  const waiting = season.levels.filter((l) => l.status === "planned").length;
  const label = next.length === 1 ? next[0].id : `${next[0].id}–${next[next.length - 1].id}`;
  const plan = async () => {
    setBusy(true);
    try {
      const out = await act(() => send<{ queued: number; results: { level: string; queued: boolean; reason: string | null }[] }>("/api/season/plan", { channel: channelId, levels: next.map((l) => l.id) }));
      if (out) {
        const refused = out.results.filter((r) => !r.queued);
        toast(out.queued ? `Queued ${plural(out.queued, "level")}. Claude, a worker or \`factory work\` makes them next.` : `Nothing queued: ${refused[0]?.reason}`, out.queued ? "info" : "error");
        await refresh();
      }
    } finally { setBusy(false); }
  };
  return (
    <Todo title="Next in the season" hint={waiting ? `${plural(waiting, "level")} already planned, waiting to be made.` : "Planning queues these levels; an agent or `factory work` makes them."}
      action={<button className="primary" disabled={busy} onClick={plan}>{busy ? "Planning…" : `Plan ${label}`}</button>}>
      <ul className="levels-mini">
        {next.map((l) => <li key={l.id}><b>{l.id}</b><span className="dim">{l.date}</span><span className="grow truncate">{l.world}{l.note ? <span className="hint"> · {l.note}</span> : null}</span></li>)}
      </ul>
      <button className="link left" onClick={() => navigate("season")}>Choose other levels on Season</button>
    </Todo>
  );
}

function Feed({ team, onOpen }: { team: Overview | null; onOpen: (id: string) => void }) {
  if (!team) return <div className="panel-body"><p className="hint">Loading…</p></div>;
  return (
    <div className="panel-body">
      {team.channels.map((c) => (
        <div key={c.id} className="funnel">
          <b>{c.name}{c.active ? "" : <span className="hint"> (paused)</span>}</b>
          {["queued", "rendering", "awaiting_qc", "to_review", "approved", "published"].map((p) => <span key={p} className={"stage" + (c.phases[p] ? " on" : "")}><em>{c.phases[p] || 0}</em>{p.replace("_", " ")}</span>)}
          {(c.phases.rejected || c.phases.failed) ? <span className="stage bad"><em>{(c.phases.rejected || 0) + (c.phases.failed || 0)}</em>out</span> : null}
        </div>
      ))}
      <div className="feed mt-3">
        {team.feed.map((f, i) => (
          <div key={f.at + i} className={"item" + (f.level === "error" ? " no-text" : f.level === "warn" ? " key-text" : "")}>
            <span className="t">{clock(f.at)}</span>
            <span className="l">{f.line}{f.clip && <button className="link" onClick={() => onOpen(f.clip!)}>open</button>}</span>
          </div>
        ))}
        {!team.feed.length && <p className="hint">Nothing has happened yet today.</p>}
      </div>
    </div>
  );
}

/* A collapsed record. Opens itself when the address asks for it
   (#/team?panel=jobs), so old links to Agents → Jobs still land. */
function Panel({ id, title, note, want, children }: { id: string; title: string; note?: string; want: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(want === id);
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (want !== id) return;
    setOpen(true);
    // Wait for the decisions above to take their height, then bring it into view.
    const t = window.setTimeout(() => ref.current?.scrollIntoView({ block: "start", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }), 500);
    return () => window.clearTimeout(t);
  }, [want, id]);
  return (
    <details className="panel" id={`panel-${id}`} ref={ref} open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary><span className="panel-title">{title}</span>{note && <span className="hint">{note}</span>}</summary>
      {open && children}
    </details>
  );
}

// "L02–L04, L21, L29": a dash only for levels that really are consecutive,
// so a list of three never reads as the fifteen levels between them.
function runs(ids: string[]): string {
  const n = (id: string) => parseInt(id.replace(/\D/g, ""), 10);
  const out: string[] = [];
  for (let i = 0; i < ids.length; ) {
    let j = i;
    while (j + 1 < ids.length && n(ids[j + 1]) === n(ids[j]) + 1) j++;
    out.push(j - i >= 2 ? `${ids[i]}–${ids[j]}` : ids.slice(i, j + 1).join(", "));
    i = j + 1;
  }
  return out.join(", ");
}
