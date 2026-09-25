// The team from the manager's chair: every agent across every channel, what
// it holds right now, how far along, what it got done today, and a feed of
// what just happened. Polls every three seconds; nothing here is edited.
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { clock, fmt, when } from "../lib/format";
import { Card, ErrorNote, StepStrip } from "../ui";
import { Orb } from "../ui/Orb";
import { Workers } from "./Workers";
import type { Task } from "../lib/types";

interface Member {
  name: string; kind: "agent" | "builtin"; state: "working" | "ready" | "idle" | "away";
  task: Task | null; tasks: (Task & { doing: string })[]; doing: string | null; last_seen: string | null; channels: string[];
  today: { done: number; failed: number; clips: number; passed_qc: number; rejected_qc: number; cost_usd: number };
  recent: { id: number; kind: string; channel_id: string; status: string; finished_at: string | null; clip_id: string | null; title: string | null; summary: string }[];
}
interface You { state: "needed" | "clear"; waiting: number; to_upload: number; today: { approved: number; rejected: number; published: number } }
interface Chan { id: string; name: string; active: boolean; phases: Record<string, number>; spend_usd: number }
interface Feed { at: string; event: string; channel?: string; clip?: string; level?: string; line: string }
interface Overview { at: string; members: Member[]; you: You; channels: Chan[]; feed: Feed[]; totals: { working: number; queued: number; to_decide: number; to_upload: number } }

const STATE_WORD: Record<Member["state"], string> = { working: "working", ready: "ready for the next task", idle: "idle", away: "away" };
const PHASES = ["queued", "rendering", "to_review", "approved", "published"];

export function Team({ navigate, onOpen, channelId }: { navigate: (v: string, p?: Record<string, string | number | undefined>) => void; onOpen: (id: string) => void; channelId: string }) {
  const [view, setView] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => api<Overview>("/api/team").then((b) => { if (alive) { setView(b); setError(null); } }).catch((e) => alive && setError((e as Error).message));
    load();
    const id = setInterval(load, 3000);
    return () => { alive = false; clearInterval(id); };
  }, []);
  if (!view) return error ? <ErrorNote message={`Could not load the team: ${error}`} /> : <p className="empty">Loading…</p>;
  const t = view.totals;
  const ago = (iso: string | null) => {
    if (!iso) return "never";
    const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
    return s < 60 ? "just now" : s < 3600 ? `${Math.floor(s / 60)} min ago` : s < 86400 ? `${Math.floor(s / 3600)} h ago` : when(iso);
  };

  return (
    <>
      <p className="page-lead">{t.working} in flight · {t.queued} queued · {t.to_decide} waiting for you · {t.to_upload} to publish</p>
      <div className="team">
        <div className="stack">
          <Workers channels={view.channels.map((c) => ({ id: c.id, name: c.name, queued: c.phases.queued || 0 }))} channelId={channelId} />
          <YouCard you={view.you} navigate={navigate} />
          {view.members.map((m) => <MemberCard key={m.name} m={m} ago={ago} onOpen={onOpen} />)}
          {!view.members.length && <Card hint="No agent has taken a task yet. Queue work on Clips and hand it off — whoever claims it appears here by the name it gives." />}
          <Card title="Channels" hint="Where every piece of work sits, per channel.">
            {view.channels.map((c) => (
              <div key={c.id} className="funnel">
                <b>{c.name}{c.active ? "" : <span className="hint"> (paused)</span>}</b>
                {PHASES.map((p) => <span key={p} className={"stage" + (c.phases[p] ? " on" : "")}><em>{c.phases[p] || 0}</em>{p.replace("_", " ")}</span>)}
                {(c.phases.rejected || c.phases.failed) ? <span className="stage bad"><em>{(c.phases.rejected || 0) + (c.phases.failed || 0)}</em>out</span> : null}
                <span className="hint right">${fmt(c.spend_usd, 4)}</span>
              </div>
            ))}
          </Card>
        </div>
        <Card title="Just happened" hint="The log, read out loud. Newest first.">
          <div className="feed">
            {view.feed.map((f, i) => (
              <div key={f.at + i} className={"item" + (f.level === "error" ? " no-text" : f.level === "warn" ? " key-text" : "")}>
                <span className="t">{clock(f.at)}</span>
                <span className="l">{f.channel && <span className="badge">{f.channel}</span>} {f.line}{f.clip && <button className="link" onClick={() => onOpen(f.clip!)}>open</button>}</span>
              </div>
            ))}
            {!view.feed.length && <p className="empty">Nothing has happened yet today.</p>}
          </div>
        </Card>
      </div>
    </>
  );
}

function YouCard({ you, navigate }: { you: You; navigate: (v: string) => void }) {
  return (
    <div className={"member you" + (you.state === "needed" ? " needed" : "")}>
      <Orb name="you" state={you.state} label="you" you />
      <div className="body">
        <div className="row"><b>You</b><span className={"dot " + (you.state === "needed" ? "working" : "ready")} />
          <span className="hint">{you.state === "needed" ? `${you.waiting} clip${you.waiting === 1 ? "" : "s"} waiting for your decision` : "nothing waiting for you"}{you.to_upload ? ` · ${you.to_upload} approved, not yet uploaded` : ""}</span>
          {(you.waiting > 0 || you.to_upload > 0) && <button className="sm primary right" onClick={() => navigate("today")}>Go to Today</button>}
        </div>
        <div className="hint">today: approved {you.today.approved} · rejected {you.today.rejected} · marked uploaded {you.today.published}</div>
      </div>
    </div>
  );
}

function MemberCard({ m, ago, onOpen }: { m: Member; ago: (iso: string | null) => string; onOpen: (id: string) => void }) {
  const initials = m.name.replace(/[^a-z0-9]+/gi, " ").trim().split(" ").slice(0, 2).map((w) => w[0]?.toUpperCase() || "").join("") || "?";
  const d = m.today;
  return (
    <div className={"member " + m.state}>
      <Orb name={m.name} state={m.state} label={initials} />
      <div className="body">
        <div className="row wrap">
          <b>{m.name}</b><span className={"dot " + m.state} /><span className="hint">{m.tasks.length > 1 ? `working on ${m.tasks.length} tasks at once` : STATE_WORD[m.state]}</span>
          <span className="hint right">{m.state === "working" ? "" : `last seen ${ago(m.last_seen)}`}{m.channels.length ? ` · ${m.channels.join(", ")}` : ""}</span>
        </div>
        {m.tasks.map((t) => (
          <div key={t.id} className="stack mt-3">
            <div className="hint">{t.doing}{t.clip_id && <button className="link" onClick={() => onOpen(t.clip_id!)}>open clip</button>}</div>
            <StepStrip steps={t.steps} />
          </div>
        ))}
        <div className="hint mt-3">
          today: {d.done} done{d.failed ? <span className="no-text"> · {d.failed} failed</span> : ""}{d.clips ? ` · ${d.clips} clip${d.clips === 1 ? "" : "s"} (${d.passed_qc} passed QC${d.rejected_qc ? `, ${d.rejected_qc} rejected` : ""})` : ""}{d.cost_usd ? ` · $${fmt(d.cost_usd, 4)}` : ""}
        </div>
        {m.recent.length > 0 && (
          <details className="recent">
            <summary className="hint">last {m.recent.length} task{m.recent.length === 1 ? "" : "s"}</summary>
            {m.recent.map((r) => (
              <div key={r.id} className="row hint">
                <span className={r.status === "done" ? "ok-text" : "no-text"}>#{r.id}</span>
                <span>{r.kind} · {r.channel_id}</span>
                <span className="grow">{r.title || r.summary}</span>
                {r.clip_id && <button className="link" onClick={() => onOpen(r.clip_id!)}>open</button>}
                <span className="faint">{when(r.finished_at)}</span>
              </div>
            ))}
          </details>
        )}
      </div>
    </div>
  );
}
