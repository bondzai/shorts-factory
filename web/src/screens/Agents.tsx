// Agents: the machinery in one place. Who is working and on what (Team and
// Workers), the jobs the console can start itself and what they cost (Jobs),
// and the record of everything that ran (Activity).
import { api, send } from "../lib/api";
import { fmt } from "../lib/format";
import { act } from "../lib/toast";
import { useQuery } from "../lib/route";
import type { Route } from "../lib/route";
import { useEffect, useState } from "react";
import { Page, Card, Tabs } from "../ui";
import { Team } from "./Team";
import { Activity } from "./Activity";
import type { Snap } from "../lib/types";

type Nav = (v: string, p?: Record<string, string | number | undefined>) => void;

const TABS = [
  { id: "team", label: "Team" },
  { id: "jobs", label: "Jobs and spend" },
  { id: "activity", label: "Activity log" },
];

export function Agents({ snap, channelId, refresh, onOpen, route, navigate }: {
  snap: Snap; channelId: string; refresh: () => Promise<void>; onOpen: (id: string) => void; route: Route; navigate: Nav;
}) {
  const query = useQuery(route, navigate);
  const tab = TABS.some((t) => t.id === query.get("tab")) ? query.get("tab") : "team";
  return (
    <Page title="Agents">
      <Tabs label="Agents" tabs={TABS} value={tab} onChange={(id) => navigate("agents", id === "team" ? {} : { tab: id })} />
      {tab === "team" && <Team navigate={navigate} onOpen={onOpen} channelId={channelId} />}
      {tab === "jobs" && <Jobs snap={snap} channelId={channelId} refresh={refresh} />}
      {tab === "activity" && <Activity channelId={channelId} route={route} navigate={navigate} />}
    </Page>
  );
}

/* The jobs the console runs itself. One at a time; the header shows the one
   running. The Idea agent and the Analyst need a brain with a key; Build, QC
   and Publish need none of that to start. */
function Jobs({ snap, channelId, refresh }: { snap: Snap; channelId: string; refresh: () => Promise<void> }) {
  const busy = !!snap.job?.running;
  const agents = snap.agents?.available;
  const manual = snap.channel.driver === "manual";
  const counts = snap.counts || {};
  const run = (path: string, body?: Record<string, unknown>) => act(() => send(path, { channel: channelId, ...(body || {}) }), { after: refresh });
  const [brains, setBrains] = useState<Record<string, { ok: boolean; why: string | null }> | null>(null);
  useEffect(() => { api<{ readiness: Record<string, { ok: boolean; why: string | null }> }>("/api/brains").then((b) => setBrains(b.readiness)).catch(() => {}); }, []);
  const qcWhy = brains && !brains.qc?.ok ? brains.qc?.why : null;
  const rows: { name: string; what: string; button: string; go: () => void; off?: string | null }[] = [
    { name: "Build planned", what: `Render, title and judge every planned clip (${counts.planned || 0} planned).`, button: "Build", go: () => run("/api/build"), off: counts.planned ? null : "Nothing is planned." },
    { name: "Run QC", what: `Judge clips made while QC was off (${counts.awaiting_qc || 0} waiting).`, button: "Run QC", go: () => run("/api/qc"), off: !counts.awaiting_qc ? "Nothing is waiting for QC." : qcWhy ? `QC brain not ready: ${qcWhy}` : null },
    ...(!manual ? [{ name: "Publish approved", what: `Publish every approved clip through ${snap.channel.driver} (${counts.approved || 0} approved).`, button: "Publish", go: () => { if (window.confirm("Publish every approved clip?")) run("/api/publish"); }, off: counts.approved ? null : "Nothing is approved." }] : []),
    { name: "Ask for ideas", what: "The built-in Idea agent plans one clip outside the season.", button: "Plan 1", go: () => run("/api/plan", { count: 1 }), off: agents ? null : "Needs an API key for the built-in agents (Settings → Brains)." },
    { name: "Ask for three ideas", what: "Same, three clips.", button: "Plan 3", go: () => run("/api/plan", { count: 3 }), off: agents ? null : "Needs an API key for the built-in agents." },
    { name: "Digest", what: "The Analyst reads the numbers and says what they mean.", button: "Digest", go: () => run("/api/digest"), off: agents ? null : "Needs an API key for the built-in agents." },
  ];
  const job = snap.job;
  return (
    <>
      <Card title="Run a job" hint="The console runs one job at a time. Season levels are planned on Today or Season; these are the other jobs.">
        <div className="jobs">
          {rows.map((r) => (
            <div key={r.name} className="job-row">
              <div className="grow"><b className="small">{r.name}</b><div className="hint">{r.what}</div>{r.off && <div className="hint faint">{r.off}</div>}</div>
              <button className="sm" disabled={busy || !!r.off} onClick={r.go}>{r.button}</button>
            </div>
          ))}
        </div>
        {busy && <p className="hint mt-3">A job is running; the buttons come back when it ends.</p>}
      </Card>
      {job && (job.running || job.log.length > 0) && (
        <Card title={job.running ? `${job.name} is running` : `Last job: ${job.name || "—"}`} hint={job.running ? `on ${job.channel_id}` : job.finished_at ? `finished ${job.finished_at.slice(0, 16).replace("T", " ")}` : undefined}>
          <pre className="captured" style={{ maxHeight: 260 }}>{job.log.join("\n") || "(no output yet)"}</pre>
        </Card>
      )}
      <Card title="Spend" hint="What the brains have cost, from each run's receipt.">
        <div className="tiles">
          <div className="tile"><div className="label">This channel</div><div className="value">${fmt(snap.spend_usd, 4)}</div></div>
          <div className="tile"><div className="label">All channels</div><div className="value">${fmt(snap.spend_total_usd, 4)}</div></div>
        </div>
      </Card>
    </>
  );
}
