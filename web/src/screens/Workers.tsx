// Workers: start an agent on a channel's queue from here, watch it, stop it.
// Auto keeps a worker on the channel: whenever tasks are queued and no agent
// is running, the server starts one. Below that, everything an outside
// agent needs, ready to copy.
import { useEffect, useState } from "react";
import { api, q, send } from "../lib/api";
import { act, toast } from "../lib/toast";
import { Card } from "../ui";

interface WorkerRow { channel_id: string; agent: string; auto: boolean; state: "running" | "waiting" | "stopped"; pid: number | null; started_at: string | null; ended_at: string | null; runs: number; last_exit: number | null; last_error: string | null; log: string | null; tail: string[] }
interface Integration { claude_code: string; mcp_json: Record<string, unknown>; codex_toml: string; cowork: string; prompt_command: string; tools_note: string }
interface View { workers: WorkerRow[]; agents: string[]; available: Record<string, boolean>; in_container: boolean; integration: Integration }

export function Workers({ channels, channelId }: { channels: { id: string; name: string; queued: number }[]; channelId: string }) {
  const [view, setView] = useState<View | null>(null);
  const [agent, setAgent] = useState<Record<string, string>>({});
  const [openLog, setOpenLog] = useState<string | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const load = () => api<View>(`/api/workers?${q({ channel: channelId })}`).then(setView).catch((e) => toast((e as Error).message, "error"));
  useEffect(() => { load(); const id = setInterval(load, 4000); return () => clearInterval(id); }, [channelId]);
  useEffect(() => {
    if (!openLog) return;
    const pull = () => api<{ lines: string[] }>(`/api/workers/${openLog}/log?lines=120`).then((b) => setLog(b.lines)).catch(() => {});
    pull(); const id = setInterval(pull, 3000); return () => clearInterval(id);
  }, [openLog]);
  if (!view) return null;
  const byChannel = Object.fromEntries(view.workers.map((w) => [w.channel_id, w]));
  const anyAgent = Object.values(view.available).some(Boolean);
  const start = (id: string, auto: boolean) => act(() => send("/api/workers/start", { channel: id, agent: agent[id] || (view.available.claude ? "claude" : view.agents[0]), auto }), { ok: auto ? "Auto worker on" : "Worker started", after: load });
  const stop = (id: string) => act(() => send("/api/workers/stop", { channel: id }), { ok: "Stopped", after: load });

  return (
    <>
      <Card title="Workers" hint={anyAgent
        ? "Start an agent on a channel's queue from here. Auto keeps one on the channel: whenever work is queued and nothing is running, the server starts the agent."
        : view.in_container
          ? "No agent binary inside the container. Run bin/cowork on the host, or connect an outside agent with the config below."
          : "Neither claude nor codex is on the server's PATH. Install one, or connect an outside agent with the config below."}>
        {channels.map((c) => {
          const w = byChannel[c.id];
          const state = w?.state || "stopped";
          const last = w?.tail?.length ? w.tail[w.tail.length - 1] : "";
          return (
            <div key={c.id} className="worker">
              <span className={"dot " + (state === "running" ? "working" : state === "waiting" ? "ready" : "away")} />
              <b>{c.name}</b>
              <span className="hint">{c.queued ? `${c.queued} queued` : "queue empty"}</span>
              <select className="sm" value={agent[c.id] || w?.agent || (view.available.claude ? "claude" : view.agents[0])} onChange={(e) => setAgent({ ...agent, [c.id]: e.target.value })} disabled={state === "running"}>
                {view.agents.map((a) => <option key={a} value={a} disabled={!view.available[a]}>{a}{view.available[a] ? "" : " (not installed)"}</option>)}
              </select>
              <label className="row small hint" title="start the agent whenever tasks are queued"><input type="checkbox" checked={!!w?.auto} onChange={(e) => e.target.checked ? start(c.id, true) : stop(c.id)} disabled={!anyAgent} /> auto</label>
              {state === "running"
                ? <button className="sm danger" onClick={() => stop(c.id)}>Stop</button>
                : <button className="sm ok" onClick={() => start(c.id, !!w?.auto)} disabled={!anyAgent}>Start now</button>}
              <span className="hint grow">
                {state === "running" ? `running (run ${w.runs})` : state === "waiting" ? "waiting for work" : w?.runs ? `stopped · ${w.runs} run${w.runs === 1 ? "" : "s"}` : "not started"}
                {w?.last_exit ? <span className="no-text"> · last exit {w.last_exit}</span> : null}
                {w?.last_error ? <span className="no-text"> · {w.last_error}</span> : null}
              </span>
              {w?.log && <button className="link" onClick={() => setOpenLog(openLog === c.id ? null : c.id)}>{openLog === c.id ? "hide log" : "log"}</button>}
              {last && openLog !== c.id && <div className="tail">{last.slice(0, 160)}</div>}
              {openLog === c.id && <pre className="captured tail-full">{log.join("\n") || "(nothing yet)"}</pre>}
            </div>
          );
        })}
      </Card>
      <Integrate it={view.integration} />
    </>
  );
}

function Integrate({ it }: { it: Integration }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const copy = async (key: string, text: string) => { try { await navigator.clipboard.writeText(text); setCopied(key); setTimeout(() => setCopied(null), 1500); } catch { toast("Could not reach the clipboard", "error"); } };
  const Block = ({ k, title, text, note }: { k: string; title: string; text: string; note?: string }) => (
    <div className="stack mt-3">
      <div className="row"><b className="small">{title}</b>{note && <span className="hint">{note}</span>}<button className="sm right" onClick={() => copy(k, text)}>{copied === k ? "Copied" : "Copy"}</button></div>
      <pre className="captured">{text}</pre>
    </div>
  );
  return (
    <Card title="Connect an outside agent" hint="Any MCP-capable agent can work the queue. Register the server, give it the prompt, and it appears on this screen by the name it gives." right={<button className="sm ghost" onClick={() => setOpen(!open)}>{open ? "hide" : "show"}</button>}>
      {open && (
        <>
          <Block k="cc" title="Claude Code" note="one command, once" text={it.claude_code} />
          <Block k="codex" title="Codex (~/.codex/config.toml)" text={it.codex_toml} />
          <Block k="json" title="Any MCP client (JSON)" note="Claude Desktop, Cursor, …" text={JSON.stringify(it.mcp_json, null, 2)} />
          <Block k="prompt" title="The prompt" note="prints the work playbook for this channel, fresh from the database" text={it.prompt_command} />
          <Block k="cowork" title="From a terminal on the host" text={it.cowork} />
        </>
      )}
    </Card>
  );
}
