// The office: one desk per member of the team. Agents that work the queue
// over MCP (Claude Code, Codex, anything that gives a name), the worker the
// console can start for them, and the built-in brains on the local model.
// Each desk says what it is, what it is doing now, and what it did today.
import { useEffect, useState } from "react";
import { api, q, send } from "../lib/api";
import { fmt, plural, when } from "../lib/format";
import { act, toast } from "../lib/toast";
import { StepStrip } from "../ui";
import type { Brains } from "../lib/command";
import type { Run, Task } from "../lib/types";

export interface Member {
  name: string; kind: "agent" | "builtin"; state: "working" | "ready" | "idle" | "away";
  task: Task | null; tasks: (Task & { doing: string })[]; doing: string | null; last_seen: string | null; channels: string[];
  today: { done: number; failed: number; clips: number; passed_qc: number; rejected_qc: number; cost_usd: number };
  recent: { id: number; kind: string; channel_id: string; status: string; finished_at: string | null; clip_id: string | null; title: string | null; summary: string }[];
}
export interface Feed { at: string; event: string; channel?: string; clip?: string; level?: string; line: string }
export interface Overview {
  at: string; members: Member[]; feed: Feed[];
  you: { waiting: number; to_upload: number; today: { approved: number; rejected: number; published: number } };
  channels: { id: string; name: string; active: boolean; phases: Record<string, number>; spend_usd: number }[];
  totals: { working: number; queued: number; to_decide: number; to_upload: number };
}
export interface WorkerRow { channel_id: string; agent: string; auto: boolean; state: "running" | "waiting" | "stopped"; pid: number | null; started_at: string | null; ended_at: string | null; runs: number; last_exit: number | null; last_error: string | null; log: string | null; tail: string[] }
export interface Integration { claude_code: string; mcp_json: Record<string, unknown>; codex_toml: string; cowork: string; prompt_command: string; tools_note: string }
export interface WorkersView { workers: WorkerRow[]; agents: string[]; available: Record<string, boolean>; in_container: boolean; integration: Integration }

const TOOL: Record<string, { title: string; what: string }> = {
  claude: { title: "Claude", what: "Claude Code over MCP" },
  codex: { title: "Codex", what: "Codex over MCP" },
  "factory-work": { title: "factory work", what: "the built-in pipeline, run from the command line" },
};
const BRAIN: Record<string, { title: string; job: string }> = {
  idea: { title: "Idea", job: "plans clips outside the season" },
  metadata: { title: "Metadata", job: "writes titles and words from the frames" },
  qc: { title: "QC", job: "judges each clip before you see it" },
  analyst: { title: "Analyst", job: "reads the numbers, writes the digest" },
};
/* The step a task is at, as a verb: "Claude is rendering L02". */
export const STEP_VERB: Record<string, string> = { claimed: "starting", rendered: "rendering", described: "writing the words for", qc: "judging", finished: "finishing" };

export const toolOf = (name: string) => Object.keys(TOOL).find((k) => name === k || name.startsWith(k + "-") || name.startsWith(k + " ")) || null;
export const displayName = (name: string) => { const t = toolOf(name); return t && name === t ? TOOL[t].title : name; };
const isToday = (iso?: string | null) => !!iso && new Date(iso).toDateString() === new Date().toDateString();
const ago = (iso: string | null) => {
  if (!iso) return "never seen";
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  return s < 60 ? "just now" : s < 3600 ? `${Math.floor(s / 60)} min ago` : s < 86400 ? `${Math.floor(s / 3600)} h ago` : when(iso);
};
const initials = (name: string) => name.replace(/[^a-z0-9]+/gi, " ").trim().split(" ").slice(0, 2).map((w) => w[0]?.toUpperCase() || "").join("") || "?";

type Tone = "working" | "ready" | "idle" | "away" | "off";
interface Desk {
  key: string; name: string; what: string; tone: Tone; state: string; why?: string | null; tasks: (Task & { doing: string })[];
  today: string; member?: Member; worker?: { agent: string; row?: WorkerRow; installed: boolean }; brain?: boolean;
}

/* Which console job keeps which brain busy. */
const BRAIN_JOB: Record<string, string> = { qc: "qc", analyst: "digest", idea: "plan", metadata: "build" };

export function Office({ team, workers, brains, runs, channelId, channelName, jobName, reloadWorkers, onOpen }: {
  team: Overview | null; workers: WorkersView | null; brains: Brains | null; runs: Run[]; channelId: string; channelName: string; jobName: string | null;
  reloadWorkers: () => void; onOpen: (id: string) => void;
}) {
  const members = team?.members || [];
  const row = workers?.workers.find((w) => w.channel_id === channelId);
  const desks: Desk[] = [];

  // Agents: every tool the console can start, and every name that has taken a task.
  const names = new Set<string>();
  for (const a of workers?.agents || []) if (workers?.available[a] || members.some((m) => toolOf(m.name) === a)) names.add(a);
  for (const m of members) if (!names.has(m.name)) names.add(m.name);
  for (const name of names) {
    const m = members.find((x) => x.name === name);
    const tool = toolOf(name);
    const canRun = !!tool && !!workers?.agents.includes(tool) && name === tool;
    const w = canRun && row?.agent === tool ? row : undefined;
    const held = m?.tasks || [];
    const tone: Tone = held.length ? "working" : w?.state === "running" ? "working" : w?.state === "waiting" ? "ready" : (m?.state as Tone) || "idle";
    const state = held.length ? (held.length > 1 ? `Working on ${held.length} tasks` : `Working on task #${held[0].id}`)
      : w?.state === "running" ? "Worker running, picking up a task"
      : w?.state === "waiting" ? "Waiting for work (auto)"
      : m ? (m.state === "away" ? `Offline · last seen ${ago(m.last_seen)}` : `Idle · last seen ${ago(m.last_seen)}`)
      : canRun ? "Idle · not started" : "Offline";
    const d = m?.today;
    const today = !d || (!d.done && !d.failed) ? "Nothing yet today."
      : `Today: ${plural(d.done, "task")} done${d.failed ? `, ${d.failed} failed` : ""}${d.clips ? ` · ${plural(d.clips, "clip")} (${d.passed_qc} passed QC${d.rejected_qc ? `, ${d.rejected_qc} rejected` : ""})` : ""}${d.cost_usd ? ` · $${fmt(d.cost_usd, 4)}` : ""}`;
    desks.push({
      key: "agent:" + name, name: displayName(name), tone, state, tasks: held, today, member: m,
      what: tool ? TOOL[tool].what + (canRun ? (w?.state === "running" || w?.state === "waiting" ? ` · worker on ${channelName}` : "") : "") : "an agent over MCP",
      worker: canRun ? { agent: tool!, row: w, installed: !!workers?.available[tool!] } : undefined,
      why: w?.last_error ? w.last_error : null,
    });
  }

  // Built-in brains: ready or not from the brains' own readiness check.
  const feed = team?.feed || [];
  const counted: Record<string, string> = {
    idea: plural(runs.filter((r) => r.kind === "plan" && isToday(r.started_at)).length, "planning run"),
    metadata: `${plural(feed.filter((f) => f.event === "clip.described" && isToday(f.at)).length, "clip")} worded`,
    qc: `${plural(feed.filter((f) => f.event === "clip.qc" && isToday(f.at)).length, "clip")} judged`,
    analyst: plural(runs.filter((r) => r.kind === "digest" && isToday(r.started_at)).length, "digest"),
  };
  for (const [name, r] of Object.entries(brains?.readiness || {})) {
    const b = BRAIN[name] || { title: name, job: "" };
    const off = name === "qc" && brains?.qc_enabled === false;
    const model = r.provider && r.model ? `${r.provider}/${r.model}` : brains?.agents[name] || "no model set";
    const busy = !!jobName && BRAIN_JOB[name] === jobName;
    desks.push({
      key: "brain:" + name, name: b.title, what: `Built-in brain · ${model}`, brain: true, tasks: [],
      tone: busy ? "working" : !r.ok ? "away" : off ? "off" : "ready",
      state: busy ? `Working: ${jobName} is running` : !r.ok ? "Not ready" : off ? "Switched off" : "Ready",
      why: !r.ok ? r.why : off ? "New clips wait in awaiting QC until you run QC." : b.job,
      today: `Today: ${counted[name] || "—"}.`,
    });
  }

  const queued = team?.totals.queued || 0;
  const agents = desks.filter((d) => !d.brain), brainDesks = desks.filter((d) => d.brain);
  return (
    <>
      <h3 className="desk-group">Agents <span className="hint">work the queue: they claim a task, make the clip, report back</span></h3>
      <div className="desks">
        {agents.map((d) => <DeskCard key={d.key} d={d} channelId={channelId} reload={reloadWorkers} onOpen={onOpen} workers={workers} />)}
        {!agents.length && <p className="hint">No agent has taken a task yet, and none is installed here. Connect one under Records.</p>}
      </div>
      {queued > 0 && !members.some((m) => m.tasks.length) && row?.state !== "running" && (
        <p className="hint mt-3">{plural(queued, "task")} queued and no agent on {queued === 1 ? "it" : "them"}. Start Claude on its desk, or run <code>factory work</code>.</p>
      )}
      {brainDesks.length > 0 && <>
        <h3 className="desk-group">Built-in brains <span className="hint">the local models the pipeline calls for words, judging and numbers</span></h3>
        <div className="desks">
          {brainDesks.map((d) => <DeskCard key={d.key} d={d} channelId={channelId} reload={reloadWorkers} onOpen={onOpen} workers={workers} />)}
        </div>
      </>}
    </>
  );
}

function DeskCard({ d, channelId, reload, onOpen, workers }: { d: Desk; channelId: string; reload: () => void; onOpen: (id: string) => void; workers: WorkersView | null }) {
  const [logOpen, setLogOpen] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  const w = d.worker;
  useEffect(() => {
    if (!logOpen) return;
    const pull = () => api<{ lines: string[] }>(`/api/workers/${channelId}/log?lines=120`).then((b) => setLog(b.lines)).catch(() => {});
    pull(); const id = setInterval(pull, 3000); return () => clearInterval(id);
  }, [logOpen, channelId]);
  const start = (auto: boolean) => act(() => send("/api/workers/start", { channel: channelId, agent: w!.agent, auto }), { ok: auto ? "Auto worker on" : "Worker started", after: reload });
  const stop = () => act(() => send("/api/workers/stop", { channel: channelId }), { ok: "Stopped", after: reload });
  const running = w?.row?.state === "running";
  const otherRunning = !!workers?.workers.find((x) => x.channel_id === channelId && x.agent !== w?.agent && x.state !== "stopped");
  return (
    <article className={`desk ${d.tone}`} aria-label={`${d.name}: ${d.state}`}>
      <header className="desk-head">
        <span className={"avatar" + (d.brain ? " brain" : "")} aria-hidden>{initials(d.name)}</span>
        <div className="grow">
          <h3>{d.name}</h3>
          <p className="desk-what">{d.what}</p>
        </div>
      </header>
      <p className="desk-state"><span className={`dot ${d.tone}`} aria-hidden />{d.state}</p>
      {d.why && <p className={"hint" + (d.tone === "away" && d.brain ? " key-text" : "")}>{d.why}</p>}
      {d.tasks.map((t) => (
        <div key={t.id} className="desk-task">
          <div className="hint">{t.params?.level_id ? <b>{t.params.level_id} </b> : null}{t.doing}{t.clip_id && <button className="link" onClick={() => onOpen(t.clip_id!)}>open clip</button>}</div>
          <StepStrip steps={t.steps} />
        </div>
      ))}
      <p className="desk-today hint">{d.today}</p>
      {d.member && d.member.recent.length > 0 && (
        <details className="desk-recent">
          <summary className="hint">Last {plural(d.member.recent.length, "task")}</summary>
          {d.member.recent.map((r) => (
            <div key={r.id} className="row hint">
              <span className={r.status === "done" ? "ok-text" : r.status === "cancelled" ? "" : "no-text"}>#{r.id}</span>
              <span className="grow truncate" title={r.summary || r.title || ""}>{r.title || r.summary || r.kind}</span>
              {r.clip_id && <button className="link" onClick={() => onOpen(r.clip_id!)}>open</button>}
            </div>
          ))}
        </details>
      )}
      {w && (
        <footer className="desk-foot">
          {!w.installed ? <span className="hint">{w.agent} is not installed on this machine.</span> : <>
            {running || w.row?.state === "waiting"
              ? <button className="sm danger" onClick={stop}>Stop</button>
              : <button className="sm" onClick={() => start(!!w.row?.auto)} disabled={otherRunning} title={otherRunning ? "Another worker is on this channel" : undefined}>Start on this channel</button>}
            <label className="row small hint"><input type="checkbox" checked={!!w.row?.auto} disabled={otherRunning} onChange={(e) => e.target.checked ? start(true) : stop()} /> auto</label>
            {w.row?.log && <button className="link right" onClick={() => setLogOpen(!logOpen)} aria-expanded={logOpen}>{logOpen ? "Hide log" : "Log"}</button>}
          </>}
          {logOpen && <pre className="captured desk-log">{log.join("\n") || "(nothing yet)"}</pre>}
          {!logOpen && w.row?.tail?.length ? <div className="desk-tail">{w.row.tail[w.row.tail.length - 1].slice(0, 160)}</div> : null}
        </footer>
      )}
    </article>
  );
}

/* Everything an outside agent needs, ready to copy. */
export function Integrate({ it }: { it: Integration }) {
  const [copied, setCopied] = useState<string | null>(null);
  const copy = async (key: string, text: string) => { try { await navigator.clipboard.writeText(text); setCopied(key); setTimeout(() => setCopied(null), 1500); } catch { toast("Could not reach the clipboard", "error"); } };
  const Block = ({ k, title, text, note }: { k: string; title: string; text: string; note?: string }) => (
    <div className="stack mt-3">
      <div className="row"><b className="small">{title}</b>{note && <span className="hint">{note}</span>}<button className="sm right" onClick={() => copy(k, text)}>{copied === k ? "Copied" : "Copy"}</button></div>
      <pre className="captured">{text}</pre>
    </div>
  );
  return (
    <div className="panel-body">
      <p className="hint">Any MCP-capable agent can work the queue. Register the server, give it the prompt, and it gets a desk here under the name it gives.</p>
      <Block k="cc" title="Claude Code" note="one command, once" text={it.claude_code} />
      <Block k="codex" title="Codex (~/.codex/config.toml)" text={it.codex_toml} />
      <Block k="json" title="Any MCP client (JSON)" note="Claude Desktop, Cursor, …" text={JSON.stringify(it.mcp_json, null, 2)} />
      <Block k="prompt" title="The prompt" note="prints the work playbook for this channel" text={it.prompt_command} />
      <Block k="cowork" title="From a terminal on the host" text={it.cowork} />
    </div>
  );
}

export const loadWorkers = (channelId: string) => api<WorkersView>(`/api/workers?${q({ channel: channelId })}`);
