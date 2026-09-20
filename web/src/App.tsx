// The shell: a nav of screens named for what you do on them, one header with
// the channel and the actions that start work, and the screen the URL names.
import { useCallback, useEffect, useState } from "react";
import { api, q, send } from "./lib/api";
import { fmt, statusWord } from "./lib/format";
import { act } from "./lib/toast";
import { useRoute } from "./lib/route";
import { Toasts } from "./ui";
import { Today } from "./screens/Today";
import { Queue } from "./screens/Queue";
import { Clips, ClipDrawer } from "./screens/Clips";
import { Results } from "./screens/Results";
import { Activity } from "./screens/Activity";
import { Settings, AddChannel } from "./screens/Settings";
import { Docs } from "./screens/Docs";
import type { Channel, Snap } from "./lib/types";

const VIEWS = [
  { id: "today", name: "Today", meaning: "decide, then upload" },
  { id: "queue", name: "Queue", meaning: "what agents will do next" },
  { id: "clips", name: "Clips", meaning: "everything ever made" },
  { id: "results", name: "Results", meaning: "how published clips did" },
  { id: "activity", name: "Activity", meaning: "what ran, and what happened" },
  { id: "bin", name: "Bin", meaning: "what you threw away" },
  { id: "settings", name: "Settings", meaning: "this channel and its rules" },
  { id: "docs", name: "Docs", meaning: "how it all works" },
];

export default function App() {
  const { route, navigate } = useRoute();
  const [channels, setChannels] = useState<Channel[] | null>(null);
  const [channelId, setChannelId] = useState<string | null>(null);
  const [snap, setSnap] = useState<Snap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sound, setSound] = useState(false);
  const [openClip, setOpenClip] = useState<string | null>(null);

  const loadChannels = useCallback(async () => {
    const body = await api<{ channels: Channel[] }>("/api/channels");
    setChannels(body.channels);
    setChannelId((current) => (current && body.channels.some((c) => c.id === current)) ? current : (body.channels.find((c) => c.active) || body.channels[0])?.id ?? null);
  }, []);
  const refresh = useCallback(async () => {
    if (!channelId) return;
    try { setSnap(await api<Snap>(`/api/state?${q({ channel: channelId })}`)); setError(null); }
    catch (err) { setError((err as Error).message); }
  }, [channelId]);
  useEffect(() => { loadChannels().catch((err) => setError((err as Error).message)); }, [loadChannels]);
  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => { const id = setInterval(refresh, snap?.job?.running ? 1500 : 5000); return () => clearInterval(id); }, [refresh, snap?.job?.running]);
  const reload = useCallback(async () => { await loadChannels(); await refresh(); }, [loadChannels, refresh]);

  if (channels && !channels.length) return <div className="main"><div className="content"><p className="empty">No channels yet.</p><AddChannel onDone={reload} /></div></div>;
  const view = VIEWS.some((v) => v.id === route.view) ? route.view : "today";
  const queueCount = snap ? snap.queue.length + snap.approved.length : 0;
  const taskCount = (snap?.tasks?.queued || 0) + (snap?.tasks?.claimed || 0);
  const screenProps = { channelId: channelId!, refresh: reload, route, navigate, onOpen: setOpenClip };

  return (
    <div className="shell">
      <nav className="side">
        <div className="brand">shorts factory</div>
        {VIEWS.map((v) => (
          <a key={v.id} href={`#/${v.id}`} aria-current={view === v.id ? "page" : undefined}>
            <span className="name">{v.name}{v.id === "today" && queueCount > 0 && <span className="count">{queueCount}</span>}{v.id === "queue" && taskCount > 0 && <span className="count">{taskCount}</span>}</span>
            <span className="meaning">{v.meaning}</span>
          </a>
        ))}
      </nav>
      <div className="main">
        <Header channels={channels || []} channelId={channelId} setChannelId={setChannelId} snap={snap} refresh={reload} error={error} navigate={navigate} />
        <Toasts />
        <div className="content">
          {openClip && <ClipDrawer id={openClip} close={() => setOpenClip(null)} refresh={reload} sound={sound} />}
          {!snap ? <p className="empty">{error ? `cannot reach the server: ${error}` : "loading…"}</p>
            : view === "today" ? <Today snap={snap} {...screenProps} sound={sound} setSound={setSound} />
            : view === "queue" ? <Queue snap={snap} {...screenProps} />
            : view === "clips" ? <Clips {...screenProps} />
            : view === "bin" ? <Clips {...screenProps} bin />
            : view === "results" ? <Results {...screenProps} />
            : view === "activity" ? <Activity {...screenProps} />
            : view === "docs" ? <Docs page={route.params.get("page") || ""} setPage={(id) => navigate("docs", { page: id })} />
            : <Settings snap={snap} channelId={channelId!} refresh={reload} />}
        </div>
      </div>
    </div>
  );
}

function Header({ channels, channelId, setChannelId, snap, refresh, error, navigate }: {
  channels: Channel[]; channelId: string | null; setChannelId: (id: string) => void; snap: Snap | null; refresh: () => Promise<void>; error: string | null; navigate: (v: string) => void;
}) {
  const busy = !!snap?.job?.running;
  const job = snap?.job;
  const run = (path: string, body?: Record<string, unknown>) => act(() => send(path, { channel: channelId, ...(body || {}) }), { after: refresh });
  const counts = snap?.counts || {};
  const order = ["planned", "awaiting_approval", "approved", "published", "qc_rejected", "failed"];
  const agents = snap?.agents?.available;
  const manual = snap?.channel.driver === "manual";
  return (
    <header className="top">
      <select value={channelId || ""} onChange={(e) => setChannelId(e.target.value)}>{channels.map((c) => <option key={c.id} value={c.id}>{c.name}{c.queue ? ` · ${c.queue} waiting` : ""}{c.active ? "" : " (paused)"}</option>)}</select>
      {order.filter((k) => counts[k]).map((k) => <span key={k} className="pill">{statusWord(k)} <b>{counts[k]}</b></span>)}
      <span className="grow" />
      {agents ? (
        <>
          <button disabled={busy} onClick={() => run("/api/plan", { count: 1 })} title="Ask the built-in Idea agent for one clip">Plan 1</button>
          <button disabled={busy} onClick={() => run("/api/plan", { count: 3 })} title="Ask the built-in Idea agent for three clips">Plan 3</button>
          <button disabled={busy} onClick={() => run("/api/build")} title="Render, title and QC everything planned">Build planned</button>
          <button disabled={busy} onClick={() => run("/api/digest")} title="Ask the built-in Analyst what the numbers say">Digest</button>
        </>
      ) : <button onClick={() => navigate("queue")} title="No API key is set, so clips are made by an agent over MCP. The Queue screen hands it the work.">Make clips with an agent</button>}
      {!manual && <button disabled={busy} onClick={() => run("/api/publish")} title="Publish every approved clip through the channel's driver">Publish approved</button>}
      <span className="pill" title="this channel / all channels">${fmt(snap?.spend_usd, 4)} <span className="dim">/ ${fmt(snap?.spend_total_usd, 4)}</span></span>
      {error && <span className="job no-text">{error}</span>}
      {job && (job.running || job.log.length > 0) && <div className={"job" + (job.running ? " running" : "")}>{job.running ? `${job.name} is running on ${job.channel_id}… ` : "last job: "}{job.log[job.log.length - 1] || ""}</div>}
    </header>
  );
}
