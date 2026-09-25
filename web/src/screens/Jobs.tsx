// Jobs and spend: the jobs the console runs itself, the last job's log, and
// what the brains have cost. A secondary panel on Team; the command bar runs
// the same jobs (run qc, build, publish, digest).
import { send } from "../lib/api";
import { fmt, when } from "../lib/format";
import { act } from "../lib/toast";
import type { Brains } from "../lib/command";
import type { Snap } from "../lib/types";

export function Jobs({ snap, channelId, refresh, brains }: { snap: Snap; channelId: string; refresh: () => Promise<void>; brains: Brains | null }) {
  const busy = !!snap.job?.running;
  const manual = snap.channel.driver === "manual";
  const counts = snap.counts || {};
  const run = (path: string, body?: Record<string, unknown>) => act(() => send(path, { channel: channelId, ...(body || {}) }), { after: refresh });
  const ready = (name: string) => brains?.readiness[name];
  const why = (name: string, label: string) => !brains ? "Checking the brains…" : ready(name)?.ok ? null : `${label} is not ready: ${ready(name)?.why || "not set"} (Settings → Brains).`;
  const rows: { name: string; what: string; button: string; go: () => void; off?: string | null }[] = [
    { name: "Build planned", what: `Render, title and judge every planned clip (${counts.planned || 0} planned).`, button: "Build", go: () => run("/api/build"), off: counts.planned ? null : "Nothing is planned." },
    { name: "Run QC", what: `Judge clips made while QC was off (${counts.awaiting_qc || 0} waiting).`, button: "Run QC", go: () => run("/api/qc"), off: !counts.awaiting_qc ? "Nothing is waiting for QC." : why("qc", "The QC brain") },
    ...(!manual ? [{ name: "Publish approved", what: `Publish every approved clip through ${snap.channel.driver} (${counts.approved || 0} approved).`, button: "Publish", go: () => { if (window.confirm("Publish every approved clip?")) run("/api/publish"); }, off: counts.approved ? null : "Nothing is approved." }] : []),
    { name: "Ask for ideas", what: "The Idea brain plans clips outside the season.", button: "Plan 1", go: () => run("/api/plan", { count: 1 }), off: why("idea", "The Idea brain") },
    { name: "Ask for three ideas", what: "Same, three clips.", button: "Plan 3", go: () => run("/api/plan", { count: 3 }), off: why("idea", "The Idea brain") },
    { name: "Digest", what: "The Analyst reads the numbers and says what they mean.", button: "Digest", go: () => run("/api/digest"), off: why("analyst", "The Analyst") },
  ];
  const job = snap.job;
  return (
    <div className="panel-body">
      <p className="hint mb-3">The console runs one job at a time. Season levels and ad-hoc clips are queued for agents instead: plan them under Your decisions or with the command bar.</p>
      <div className="jobs">
        {rows.map((r) => (
          <div key={r.name} className="job-row">
            <div className="grow"><b className="small">{r.name}</b><div className="hint">{r.what}</div>{r.off && <div className="hint">{r.off}</div>}</div>
            <button className="sm" disabled={busy || !!r.off} onClick={r.go}>{r.button}</button>
          </div>
        ))}
      </div>
      {busy && <p className="hint mt-3">A job is running; the buttons come back when it ends.</p>}
      {job && (job.running || job.log.length > 0) && (
        <div className="mt-3">
          <div className="row mb-3"><b className="small">{job.running ? `${job.name} is running on ${job.channel_id}` : `Last job: ${job.name || "—"}`}</b>{!job.running && job.finished_at && <span className="hint">finished {when(job.finished_at)}</span>}</div>
          <pre className="captured" style={{ maxHeight: 260 }}>{job.log.join("\n") || "(no output yet)"}</pre>
        </div>
      )}
      <div className="tiles mt-3">
        <div className="tile"><div className="label">Spend, this channel</div><div className="value">${fmt(snap.spend_usd, 4)}</div></div>
        <div className="tile"><div className="label">Spend, all channels</div><div className="value">${fmt(snap.spend_total_usd, 4)}</div></div>
      </div>
    </div>
  );
}
