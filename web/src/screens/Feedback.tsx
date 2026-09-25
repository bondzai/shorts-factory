// Feedback: what the numbers taught this channel. The operator reads YouTube
// Studio, enters a clip's numbers on Clips, and writes down here what they
// showed and what to change. A lesson moves open → testing → adopted (or
// dropped); only adopted ones reach the playbooks and the copy brain.
import { useCallback, useEffect, useState } from "react";
import { api, q, send } from "../lib/api";
import { num, pct, when, plural } from "../lib/format";
import { act, toast } from "../lib/toast";
import { useList } from "../lib/useList";
import { useQuery } from "../lib/route";
import { Page, Toolbar, SearchBox, DataTable, Pagination, Badge, Chips, Drawer, Column } from "../ui";
import { Metrics } from "./Clips";
import type { Route } from "../lib/route";
import type { Clip } from "../lib/types";

interface Numbers { title: string | null; hook_text: string | null; level_id: string | null; variant: string | null; stage: string | null; status: string; views: number | null; avg_view_pct: number | null; swipe_away_pct: number | null; likes: number | null; metrics_at: string | null; taken_at: string }
export interface Lesson {
  id: number; channel_id: string; created_at: string; updated_at: string; created_by: string | null; source: string;
  area: string; observation: string; evidence: string; clip_ids: string[]; action: string; status: string; result: string;
  metrics: Record<string, Numbers>;
}
interface LessonPage { items: Lesson[]; total: number; page: number; page_size: number; counts: Record<string, number>; areas: string[]; statuses: string[] }

const AREAS = ["title", "hook", "caption", "stage", "length", "pacing", "skills", "other"];
const STATUS: Record<string, { word: string; tone?: "ok" | "no" | "key"; means: string }> = {
  open: { word: "Open", means: "Noticed, not acted on yet. Nothing changes." },
  testing: { word: "Testing", tone: "key", means: "Trying the change on the next clips. The brains are not told yet." },
  adopted: { word: "Adopted", tone: "ok", means: "Kept. Appended to every playbook, and title, hook and caption lessons go to the copy and title brains." },
  dropped: { word: "Dropped", means: "It did not hold. Kept for the record; reaches nobody." },
};
const SOURCE: Record<string, string> = { manual: "you", analyst: "the Analyst", agent: "an agent" };

type Nav = (v: string, p?: Record<string, string | number | undefined>) => void;

export function Feedback({ channelId, route, navigate }: { channelId: string; route: Route; navigate: Nav }) {
  const query = useQuery(route, navigate);
  const status = query.get("status"), area = query.get("area");
  const list = useList<Lesson>("/api/feedback", route, { channel: channelId, status, area }, [channelId]);
  const body = list.data as LessonPage | null;
  const rows = body?.items || [];
  const counts = body?.counts || {};
  const all = Object.values(counts).reduce((a, b) => a + b, 0);
  const anyFilter = !!(status || area || query.get("q"));
  // The editor lives in the URL: ?open=<id> or ?new=1 (&clip=<id> to start
  // from a clip), so the clip drawer's shortcut and a reload both land here.
  const openId = query.get("open"), isNew = query.get("new") === "1";
  const [editing, setEditing] = useState<Lesson | null>(null);
  useEffect(() => {
    if (!openId) { setEditing(null); return; }
    const found = rows.find((r) => String(r.id) === openId);
    if (found) { setEditing(found); return; }
    api<Lesson>(`/api/feedback/${openId}`).then(setEditing).catch((e) => { toast((e as Error).message, "error"); query.set({ open: undefined }); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openId]);
  const close = () => query.set({ open: undefined, new: undefined, clip: undefined });
  const done = () => { close(); list.reload(); };

  const columns: Column<Lesson>[] = [
    { key: "observation", label: "Lesson", render: (r) => <>
        <span className="narrow-only row"><Badge tone={STATUS[r.status]?.tone}>{STATUS[r.status]?.word || r.status}</Badge><span className="hint">{r.area}</span></span>
        <div className="lesson-obs">{r.observation}</div>
        {r.action && <div className="small">→ {r.action}</div>}
        {(r.evidence || r.result) && <div className="hint">{r.evidence}{r.evidence && r.result ? " · " : ""}{r.result && <>result: {r.result}</>}</div>}
      </> },
    { key: "area", label: "Area", wide: true, render: (r) => <span className="small">{r.area}</span> },
    { key: "status", label: "Status", wide: true, render: (r) => <Badge tone={STATUS[r.status]?.tone}>{STATUS[r.status]?.word || r.status}</Badge> },
    { key: "clips", label: "Clips", wide: true, align: "right", render: (r) => <span className="small">{r.clip_ids.length || "—"}</span> },
    { key: "updated_at", label: "Changed", wide: true, render: (r) => <span className="dim small nowrap">{when(r.updated_at)}{r.source !== "manual" && <div className="hint">by {SOURCE[r.source] || r.source}</div>}</span> },
  ];

  return (
    <Page title="Feedback"
      lead="What the numbers taught this channel. Only adopted lessons reach the brains: they are added to every playbook, and title, hook and caption lessons go to the copy and title brains."
      action={<button className="primary" onClick={() => query.set({ new: "1", open: undefined, clip: undefined })}>Record a lesson</button>}>
      {(isNew || editing) && (
        <Drawer onClose={close}>
          <LessonEditor key={editing?.id ?? "new"} lesson={isNew ? null : editing} startClip={isNew ? query.get("clip") : ""}
            channelId={channelId} onClose={close} onDone={done} />
        </Drawer>
      )}
      <Toolbar total={body?.total}>
        <SearchBox value={query.get("q")} onChange={(v) => query.set({ q: v, page: 1 })} placeholder="Search lessons" />
        <Chips value={status} onChange={(v) => query.set({ status: v, page: 1 })} all={`all (${all})`}
          options={Object.keys(STATUS).map((s) => ({ value: s, label: `${STATUS[s].word.toLowerCase()} (${counts[s] || 0})` }))} />
        <label className="row"><span className="sr-only">Area</span>
          <select value={area} onChange={(e) => query.set({ area: e.target.value, page: 1 })}>
            <option value="">Any area</option>{AREAS.map((a) => <option key={a} value={a}>{a}</option>)}
          </select></label>
        {anyFilter && <button className="sm ghost" onClick={() => navigate("feedback")}>Clear filters</button>}
      </Toolbar>
      <DataTable label="Lessons" columns={columns} rows={rows} loading={list.loading}
        onRow={(r) => query.set({ open: r.id, new: undefined, clip: undefined })}
        empty={anyFilter ? <>Nothing matches. <button className="link" onClick={() => navigate("feedback")}>Clear filters</button></>
          : <div className="stack" style={{ alignItems: "center" }}>
              <span>No lessons yet.</span>
              <span className="hint" style={{ maxWidth: "60ch" }}>Enter a published clip's numbers from YouTube Studio on Clips, then write down what they showed — for example “captions that name a colour get swiped away” — and what to try instead.</span>
            </div>} />
      {body && body.total > 0 && <Pagination page={body.page} pageSize={body.page_size} total={body.total} onPage={(p) => query.set({ page: p })} onPageSize={(s) => query.set({ page_size: s, page: 1 })} />}
    </Page>
  );
}

// --- the form -------------------------------------------------------------------

function LessonEditor({ lesson, startClip, channelId, onClose, onDone }: {
  lesson: Lesson | null; startClip: string; channelId: string; onClose: () => void; onDone: () => void;
}) {
  const [f, setF] = useState({
    observation: lesson?.observation || "", area: lesson?.area || "other", evidence: lesson?.evidence || "",
    action: lesson?.action || "", status: lesson?.status || "open", result: lesson?.result || "",
  });
  const [clips, setClips] = useState<string[]>(lesson?.clip_ids || (startClip ? [startClip] : []));
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!f.observation.trim()) { toast("Say what the numbers showed first.", "error"); return; }
    setBusy(true);
    await act(() => lesson ? send(`/api/feedback/${lesson.id}`, { ...f, clip_ids: clips }, "PATCH") : send("/api/feedback", { channel: channelId, ...f, clip_ids: clips }),
      { ok: lesson ? "Lesson saved" : "Lesson recorded", after: onDone });
    setBusy(false);
  };
  const remove = () => {
    if (!lesson || !window.confirm("Delete this lesson for good? If it was adopted, the brains stop hearing it.")) return;
    act(() => api(`/api/feedback/${lesson.id}`, { method: "DELETE" }), { ok: "Lesson deleted", after: onDone });
  };
  return (
    <form className="stack gap-3 lesson-form" onSubmit={save}>
      <div className="row">
        <h2 className="grow">{lesson ? `Lesson #${lesson.id}` : "Record a lesson"}</h2>
        <button type="button" className="sm" onClick={onClose}>Close <kbd>Esc</kbd></button>
      </div>
      {lesson && <div className="hint">recorded {when(lesson.created_at)} by {SOURCE[lesson.source] || lesson.source}{lesson.created_by && lesson.source !== "manual" ? ` (${lesson.created_by})` : ""} · changed {when(lesson.updated_at)}</div>}

      <Block label="What did the numbers show?" help="One observation, in plain words." htmlFor="obs">
        <textarea id="obs" required rows={3} value={f.observation} onChange={set("observation")} placeholder="Captions that name a colour get swiped away in the first second" />
      </Block>
      <Block label="Area" help="Title, hook and caption lessons also go to the copy and title brains once adopted." htmlFor="area">
        <select id="area" value={f.area} onChange={set("area")}>{AREAS.map((a) => <option key={a} value={a}>{a}</option>)}</select>
      </Block>
      <Block label="Clips it came from" help="Their numbers are copied into the lesson when you link them, so the evidence stays put when Studio is read again.">
        <ClipLinker channelId={channelId} ids={clips} setIds={setClips} frozen={lesson?.metrics || {}} />
      </Block>
      <Block label="Evidence" help="The metric and the values, e.g. swipe-away 62% on L03 vs 48% channel median." htmlFor="ev">
        <textarea id="ev" rows={2} value={f.evidence} onChange={set("evidence")} />
      </Block>
      <Block label="What to change or test" htmlFor="act">
        <textarea id="act" rows={2} value={f.action} onChange={set("action")} placeholder="Open with a verb, never a colour" />
      </Block>
      <Block label="Status" help={STATUS[f.status]?.means}>
        <div className="row wrap" role="radiogroup" aria-label="Status">
          {Object.keys(STATUS).map((s) => <button key={s} type="button" role="radio" aria-checked={f.status === s} aria-pressed={f.status === s} className="chip seg" onClick={() => setF({ ...f, status: s })}>{STATUS[s].word}</button>)}
        </div>
      </Block>
      <Block label="What happened after" help="Fill in once the change has run on a few clips." htmlFor="res">
        <textarea id="res" rows={2} value={f.result} onChange={set("result")} />
      </Block>
      <div className="row wrap lesson-actions">
        <button type="submit" className="primary" disabled={busy}>{lesson ? "Save lesson" : "Record lesson"}</button>
        <button type="button" onClick={onClose}>Cancel</button>
        {lesson && <button type="button" className="danger right" onClick={remove}>Delete</button>}
      </div>
    </form>
  );
}

function Block({ label, help, htmlFor, children }: { label: string; help?: React.ReactNode; htmlFor?: string; children: React.ReactNode }) {
  return (
    <div className="lesson-field">
      {htmlFor ? <label htmlFor={htmlFor}>{label}</label> : <span className="label">{label}</span>}
      {children}
      {help && <span className="hint">{help}</span>}
    </div>
  );
}

// --- linking clips ------------------------------------------------------------------

const line = (n: { views?: number | null; avg_view_pct?: number | null; swipe_away_pct?: number | null } | undefined) =>
  !n || n.views == null ? null : `${num(n.views)} views · ${pct(n.avg_view_pct)} viewed · ${pct(n.swipe_away_pct)} swiped`;

function ClipLinker({ channelId, ids, setIds, frozen }: { channelId: string; ids: string[]; setIds: (ids: string[]) => void; frozen: Record<string, Numbers> }) {
  // Clips linked before this edit show the numbers frozen on the lesson; ones
  // linked now show today's, which is what they will be frozen at on save.
  const [live, setLive] = useState<Record<string, Numbers>>({});
  const fresh = ids.filter((id) => !frozen[id]);
  const freshKey = fresh.join(",");
  const loadLive = useCallback(() => {
    if (!freshKey) return Promise.resolve();
    return api<{ clips: Record<string, Numbers> }>(`/api/feedback/evidence?${q({ clips: freshKey })}`).then((b) => setLive(b.clips)).catch((e) => toast((e as Error).message, "error"));
  }, [freshKey]);
  useEffect(() => { loadLive(); }, [loadLive]);

  const [text, setText] = useState("");
  const [found, setFound] = useState<Clip[] | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    const t = window.setTimeout(() => {
      api<{ items: Clip[] }>(`/api/clips?${q({ channel: channelId, status: "published", q: text, sort: "published_at", dir: "desc", page: 1, page_size: 25 })}`)
        .then((b) => { if (alive) setFound(b.items); }).catch((e) => toast((e as Error).message, "error"));
    }, 250);
    return () => { alive = false; window.clearTimeout(t); };
  }, [channelId, text, tick]);
  const afterMetrics = async () => { setTick((n) => n + 1); await loadLive(); };
  const choices = (found || []).filter((c) => !ids.includes(c.id)).slice(0, 6);

  return (
    <div className="stack">
      {ids.length > 0 && <ul className="clip-list" aria-label="Linked clips">
        {ids.map((id) => {
          const n = frozen[id] || live[id];
          return (
            <li key={id}>
              <div className="grow">
                <div className="clip-title">{n?.title || "(untitled)"}</div>
                <div className="hint">{[n?.level_id, n?.stage, id].filter(Boolean).join(" · ")}</div>
                <div className="small nums">{line(n) || <span className="dim">no metrics yet</span>}
                  <span className="hint"> {frozen[id] ? `· as of ${when(frozen[id].taken_at)}` : "· now"}</span></div>
              </div>
              <button type="button" className="sm ghost" onClick={() => setIds(ids.filter((x) => x !== id))} aria-label={`Unlink ${n?.title || id}`}>Unlink</button>
            </li>
          );
        })}
      </ul>}
      <input type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder="Find a published clip by title, id or level" aria-label="Find a published clip" />
      {found && !choices.length && <div className="hint">{found.length ? "Every match is already linked." : text ? "No published clip matches." : "Nothing published on this channel yet."}</div>}
      {choices.length > 0 && <ul className="clip-list pick" aria-label="Published clips">
        {choices.map((c) => (
          <li key={c.id}>
            <div className="grow">
              <div className="clip-title">{c.title || "(untitled)"}</div>
              <div className="small nums">{line(c) || <span className="dim">no metrics yet</span>}<span className="hint"> · {c.id}{c.published_at ? ` · ${when(c.published_at).slice(0, 10)}` : ""}</span></div>
            </div>
            {c.views == null && <Metrics c={c} after={afterMetrics} label="Enter metrics" />}
            <button type="button" className="sm" onClick={() => setIds([...ids, c.id])}>Link</button>
          </li>
        ))}
      </ul>}
      {ids.length > 0 && <span className="hint">{plural(ids.length, "clip")} linked</span>}
    </div>
  );
}
