// The shell: five places named for what the operator came to do, a header
// that says which channel and what is running, and the screen the URL names.
// The machinery (agents, jobs, logs, spend) lives on Agents, not up here.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, q } from "./lib/api";
import { toast } from "./lib/toast";
import { useRoute } from "./lib/route";
import { ErrorNote, Toasts } from "./ui";
import { Logo } from "./ui/Logo";
import { useTheme } from "./lib/theme";
import { ThemeSwitch } from "./ui/ThemeSwitch";
import { Today } from "./screens/Today";
import { Season } from "./screens/Season";
import { Clips } from "./screens/Clips";
import { Agents } from "./screens/Agents";
import { ClipDrawer } from "./ui/ClipDrawer";
import { Settings, AddChannel } from "./screens/Settings";
import type { Channel, Snap } from "./lib/types";

const VIEWS = [
  { id: "today", name: "Today", meaning: "what needs you now" },
  { id: "season", name: "Season", meaning: "levels and the table" },
  { id: "clips", name: "Clips", meaning: "every clip, and the bin" },
  { id: "agents", name: "Agents", meaning: "who is working, jobs, logs" },
  { id: "settings", name: "Settings", meaning: "channel, rules, docs" },
];

export default function App() {
  const { route, navigate } = useRoute();
  const [channels, setChannels] = useState<Channel[] | null>(null);
  const [channelId, setChannelId] = useState<string | null>(null);
  const [snap, setSnap] = useState<Snap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sound, setSound] = useState(false);
  const [openClip, setOpenClip] = useState<string | null>(null);
  const [theme, setTheme] = useTheme();

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

  // A job's end is news: say how it ended, once, instead of keeping the log in
  // the header.
  const wasRunning = useRef(false);
  useEffect(() => {
    const job = snap?.job;
    if (!job) return;
    if (wasRunning.current && !job.running) {
      const last = (job.log[job.log.length - 1] || "").replace(/^\d\d:\d\d:\d\d\s+/, "");
      toast(`Finished: ${last || "done"}`, /failed/.test(last) ? "error" : "info");
    }
    wasRunning.current = job.running;
  }, [snap?.job]);

  const view = VIEWS.some((v) => v.id === route.view) ? route.view : "today";
  useEffect(() => { document.title = `${VIEWS.find((v) => v.id === view)?.name} · shorts factory`; }, [view]);

  if (channels && !channels.length) {
    return <div className="main"><div className="content"><h1 className="mb-3">Add your first channel</h1><AddChannel onDone={reload} /></div></div>;
  }
  const toReview = snap?.queue.length || 0;
  const screenProps = { channelId: channelId!, refresh: reload, route, navigate, onOpen: setOpenClip };

  return (
    <div className="shell">
      <a className="skip" href="#content">Skip to content</a>
      <nav className="side" aria-label="Main">
        <div className="brand"><Logo /><span>shorts factory</span></div>
        <div className="nav-items">
          {VIEWS.map((v) => (
            <a key={v.id} href={`#/${v.id}`} aria-current={view === v.id ? "page" : undefined}>
              <span className="name">{v.name}{v.id === "today" && toReview > 0 && <span className="count" aria-label={`${toReview} to review`}>{toReview}</span>}</span>
              <span className="meaning">{v.meaning}</span>
            </a>
          ))}
        </div>
        <div className="foot">
          <a className="docs-link" href="#/settings?tab=docs">Docs</a>
          <ThemeSwitch theme={theme} setTheme={setTheme} />
        </div>
      </nav>
      <div className="main">
        <Header channels={channels || []} channelId={channelId} setChannelId={setChannelId} snap={snap} navigate={navigate} />
        <Toasts />
        <main className="content" id="content">
          {openClip && <ClipDrawer id={openClip} close={() => setOpenClip(null)} refresh={reload} sound={sound} />}
          {error && snap && <ErrorNote message={`Lost touch with the server: ${error}. Showing what was last loaded.`} retry={reload} />}
          {!snap ? (error ? <ErrorNote message={`Cannot reach the server: ${error}. Is \`factory serve\` running?`} retry={reload} /> : <p className="empty">Loading…</p>)
            : view === "today" ? <Today snap={snap} {...screenProps} sound={sound} setSound={setSound} />
            : view === "season" ? <Season {...screenProps} />
            : view === "clips" ? <Clips snap={snap} {...screenProps} />
            : view === "agents" ? <Agents snap={snap} {...screenProps} />
            : <Settings snap={snap} channelId={channelId!} refresh={reload} route={route} navigate={navigate} theme={<ThemeSwitch theme={theme} setTheme={setTheme} />} />}
        </main>
      </div>
    </div>
  );
}

/* The channel, and the one job running right now. Nothing else: counts live
   on Today, spend and the job buttons on Agents. */
function Header({ channels, channelId, setChannelId, snap, navigate }: {
  channels: Channel[]; channelId: string | null; setChannelId: (id: string) => void; snap: Snap | null; navigate: (v: string, p?: Record<string, string>) => void;
}) {
  const job = snap?.job;
  const current = channels.find((c) => c.id === channelId);
  const last = job?.running ? (job.log[job.log.length - 1] || "").replace(/^\d\d:\d\d:\d\d\s+/, "") : "";
  return (
    <header className="top">
      {channels.length > 1
        ? <label className="row"><span className="sr-only">Channel</span><select value={channelId || ""} onChange={(e) => setChannelId(e.target.value)}>{channels.map((c) => <option key={c.id} value={c.id}>{c.name}{c.active ? "" : " (paused)"}</option>)}</select></label>
        : <span className="channel-name">{current?.name || snap?.channel.name || ""}{current && !current.active && <span className="hint"> · paused</span>}</span>}
      {job?.running && (
        <button type="button" className="running" onClick={() => navigate("agents", { tab: "jobs" })} title="See the job's log on Agents">
          <span className="dot working" aria-hidden />
          <span className="truncate"><b>{JOB_WORD[job.name || ""] || job.name}</b>{last && <span className="dim"> · {last}</span>}</span>
        </button>
      )}
    </header>
  );
}

const JOB_WORD: Record<string, string> = { plan: "Planning", build: "Building", qc: "Running QC", publish: "Publishing", digest: "Writing the digest", rehook: "Re-rendering", work: "Making clips" };
