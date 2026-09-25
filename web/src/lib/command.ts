// The command bar's grammar. Deterministic and small on purpose: no model
// guesses what you meant. A line becomes one of four things — go somewhere,
// open a clip, run a write (which always shows what it will do first), or
// "here is what I understand". Pure: the bar calls parse() on every keystroke.
import type { Snap } from "./types";
import type { SeasonView } from "../screens/Season";
import { plural } from "./format";

export interface Readiness { ok: boolean; why: string | null; provider?: string; model?: string }
export interface Brains { readiness: Record<string, Readiness>; agents: Record<string, string>; qc_enabled?: boolean }
export interface Stage { id: string; live: boolean; blurb?: string }
export interface Ctx { snap: Snap; season: SeasonView | null; brains: Brains | null; stages: Stage[] }

export type Action =
  | { type: "plan"; levels: string[] }
  | { type: "make"; count: number; stage: string | null }
  | { type: "job"; path: "/api/qc" | "/api/build" | "/api/publish" | "/api/digest"; ok: string }
  | { type: "import" };

export type Parsed =
  | { kind: "empty" }
  | { kind: "nav"; title: string; view: string; params?: Record<string, string> }
  | { kind: "clip"; title: string; id: string }
  | { kind: "write"; title: string; verb: string; lines: string[]; note?: string; blocked: string | null; action: Action }
  | { kind: "help"; title: string };

export interface Suggestion { text: string; label: string; hint: string }

/* What the bar understands, in the order the help lists it. */
export const GRAMMAR: { example: string; hint: string }[] = [
  { example: "plan L02..L04", hint: "queue season levels (plan alone: the next three ready)" },
  { example: "make 3 zigzag", hint: "queue ad-hoc clips, optionally on one stage" },
  { example: "import", hint: "queue jobs from a csv, json or yaml file" },
  { example: "run qc", hint: "judge the clips waiting for QC" },
  { example: "build", hint: "render every planned clip" },
  { example: "publish", hint: "publish approved clips" },
  { example: "digest", hint: "the Analyst reads the numbers" },
  { example: "open L05", hint: "a level on Season, or a clip by its id" },
  { example: "season · clips · settings", hint: "go to a screen" },
];

const NAV: Record<string, { title: string; view: string; params?: Record<string, string> }> = {
  team: { title: "Go to Team", view: "team" }, home: { title: "Go to Team", view: "team" }, office: { title: "Go to Team", view: "team" },
  season: { title: "Go to Season", view: "season" }, clips: { title: "Go to Clips", view: "clips" },
  settings: { title: "Go to Settings", view: "settings" }, docs: { title: "Open the docs", view: "settings", params: { tab: "docs" } },
  bin: { title: "Open the bin", view: "clips", params: { phase: "binned" } },
  brains: { title: "Open Settings → Brains", view: "settings", params: { tab: "brains" } },
  jobs: { title: "Open jobs and spend", view: "team", params: { panel: "jobs" } },
  log: { title: "Open the activity log", view: "team", params: { panel: "activity" } },
  activity: { title: "Open the activity log", view: "team", params: { panel: "activity" } },
};
const VERBS = ["plan", "make", "import", "run qc", "build", "publish", "digest", "open", ...Object.keys(NAV), "help"];

const levelNum = (s: string) => { const m = /^l(\d{1,3})$/i.exec(s.trim()); return m ? Number(m[1]) : null; };
const levelId = (n: number, season: SeasonView | null) => {
  const width = season?.levels[0]?.id.length ? season.levels[0].id.length - 1 : 2;
  return "L" + String(n).padStart(width, "0");
};

/** "L2..L4", "L02-L04", "L02 L05", "L02,L03" → ids, in season order. */
export function levelsFrom(text: string, season: SeasonView | null): string[] | string {
  const parts = text.split(/[\s,]+/).filter(Boolean);
  const out: string[] = [];
  for (const part of parts) {
    const range = /^(l\d{1,3})(?:\.\.|-|–)(l\d{1,3})$/i.exec(part);
    if (range) {
      const a = levelNum(range[1])!, b = levelNum(range[2])!;
      if (b < a) return `${part}: the range runs backwards`;
      if (b - a > 99) return `${part}: that is more than a season`;
      for (let n = a; n <= b; n++) out.push(levelId(n, season));
    } else if (levelNum(part) != null) out.push(levelId(levelNum(part)!, season));
    else return `“${part}” is not a level; levels look like L05 or L02..L04`;
  }
  return [...new Set(out)];
}

const job = (snap: Snap) => snap.job?.running ? `Wait: ${snap.job.name} is running. The console runs one job at a time.` : null;
const brainName = (b: Brains | null, name: string) => { const r = b?.readiness[name]; return r?.model ? `${r.provider}/${r.model}` : b?.agents[name] || name; };

export function parse(input: string, ctx: Ctx): Parsed {
  const text = input.trim().replace(/\s+/g, " ");
  if (!text) return { kind: "empty" };
  const lower = text.toLowerCase();
  const [head, ...rest] = lower.split(" ");
  const arg = rest.join(" ");
  const { snap, season, brains } = ctx;
  const counts = snap.counts || {};

  if (NAV[lower]) return { kind: "nav", ...NAV[lower] };
  if (lower === "help" || lower === "?") return { kind: "help", title: "What I understand" };

  if (head === "plan") {
    if (!season) return { kind: "write", title: "Plan season levels", verb: "Plan", lines: ["Reading the season…"], blocked: "This channel has no season file, or it is still loading.", action: { type: "plan", levels: [] } };
    let ids: string[];
    if (!arg || arg === "next") ids = season.levels.filter((l) => l.plannable).slice(0, 3).map((l) => l.id);
    else {
      const got = levelsFrom(arg, season);
      if (typeof got === "string") return { kind: "write", title: "Plan season levels", verb: "Plan", lines: [], blocked: got, action: { type: "plan", levels: [] } };
      ids = got;
    }
    if (!ids.length) return { kind: "write", title: "Plan season levels", verb: "Plan", lines: [], blocked: "No level is ready to plan: every ready level is planned or made.", action: { type: "plan", levels: [] } };
    const byId = Object.fromEntries(season.levels.map((l) => [l.id, l]));
    const lines: string[] = [];
    let ok = 0;
    for (const id of ids) {
      const l = byId[id];
      if (!l) lines.push(`${id} — not in this season; it will be refused.`);
      else if (l.plannable) { ok++; lines.push(`${id} · ${l.date} · ${l.world} — will be queued`); }
      else lines.push(`${id} — ${l.status === "blocked" ? `blocked: ${l.blocked_on || "waits for work"}` : l.status === "needs_input" ? `needs input: ${l.missing_input.join(", ")}` : `already ${l.status}`}; it will be refused.`);
    }
    const shown = lines.length > 8 ? [...lines.slice(0, 7), `…and ${lines.length - 7} more`] : lines;
    return {
      kind: "write", title: `Plan ${ids.length === 1 ? ids[0] : `${ids[0]}–${ids[ids.length - 1]}`}`, verb: `Plan ${plural(ok, "level")}`,
      lines: shown, note: "Planning queues the work; Claude, a worker or `factory work` makes the clips.",
      blocked: ok ? null : "None of these levels can be planned.", action: { type: "plan", levels: ids },
    };
  }

  if (head === "make" || head === "queue") {
    const words = rest.filter(Boolean);
    let count = 1; let stage: string | null = null;
    for (const w of words) {
      if (/^\d+$/.test(w)) count = Number(w);
      else if (w === "clip" || w === "clips" || w === "on" || w === "x" || w === "×") continue;
      else stage = w;
    }
    const known = ctx.stages.find((s) => s.id === stage);
    const near = stage && !known ? ctx.stages.filter((s) => s.id.startsWith(stage!)).map((s) => s.id) : [];
    const blocked = count < 1 || count > 50 ? "Between 1 and 50 clips at a time."
      : near.length ? `Keep typing, or press Tab for ${near.slice(0, 4).join(", ")}.`
      : stage && ctx.stages.length && !known ? `No stage “${stage}”. Stages: ${ctx.stages.filter((s) => s.live).map((s) => s.id).join(", ")}.`
      : null;
    return {
      kind: "write", title: `Make ${plural(count, "clip")}${stage ? ` on ${stage}` : ""}`, verb: `Queue ${plural(count, "clip")}`,
      lines: [
        `${plural(count, "ad-hoc marble race")} ${stage ? `on the ${stage} stage` : "on a stage the maker picks"}, outside the season.`,
        ...(known && !known.live ? ["This stage is on trial: it renders, but has not passed stage QA."] : []),
      ],
      note: "Queued as make-clip tasks; Claude, a worker or `factory work` makes them.",
      blocked, action: { type: "make", count, stage },
    };
  }

  if (lower === "import" || head === "import") {
    return { kind: "write", title: "Import jobs from a file", verb: "Choose a file", lines: [
      "Pick a .csv, .json, .jsonl or .yaml file of jobs.", "Nothing is queued yet: you see every row checked first, then confirm.",
    ], blocked: null, action: { type: "import" } };
  }

  if (lower === "run qc" || lower === "qc") {
    const waiting = counts.awaiting_qc || 0;
    const qc = brains?.readiness.qc;
    const blocked = !waiting ? "Nothing is waiting for QC." : !brains ? "Checking the QC brain…" : !qc?.ok ? `The QC brain is not ready: ${qc?.why || "not set"}. Set it up in Settings → Brains.` : job(snap);
    return { kind: "write", title: "Run QC", verb: "Run QC", lines: [
      `Judge ${plural(waiting, "clip")} waiting for QC with ${brainName(brains, "qc")}. Nothing is re-rendered.`,
      brains?.qc_enabled === false ? "QC is switched off for new clips; this judges the ones already made." : "Passes go to your decisions; rejects go to the bin with a reason.",
    ], blocked, action: { type: "job", path: "/api/qc", ok: "QC started" } };
  }

  if (lower === "build") {
    const planned = counts.planned || 0;
    return { kind: "write", title: "Build planned clips", verb: `Build ${planned || ""}`.trim(), lines: [
      `Render, title${brains?.qc_enabled ? " and judge" : ""} ${plural(planned, "planned clip")} here, one after another.`,
      "Season levels and make-clip tasks are made by agents instead; this is for clips planned by the Idea brain.",
    ], blocked: planned ? job(snap) : "Nothing is planned.", action: { type: "job", path: "/api/build", ok: "Build started" } };
  }

  if (lower === "publish") {
    const approved = counts.approved || 0;
    const manual = snap.channel.driver === "manual";
    return { kind: "write", title: "Publish approved clips", verb: `Publish ${approved || ""}`.trim(), lines: manual
      ? [`${snap.channel.name} publishes by hand: download each approved clip under Your decisions, upload it in YouTube Studio, then mark it uploaded.`]
      : [`Publish ${plural(approved, "approved clip")} through ${snap.channel.driver}: private now, public at their slot.`],
      blocked: manual ? "This channel publishes by hand." : !approved ? "Nothing is approved." : job(snap),
      action: { type: "job", path: "/api/publish", ok: "Publishing started" } };
  }

  if (lower === "digest") {
    const r = brains?.readiness.analyst;
    return { kind: "write", title: "Write the digest", verb: "Write digest", lines: [
      `The Analyst (${brainName(brains, "analyst")}) reads this channel's numbers and says what they mean.`, "Its answer lands in Jobs and spend when it is done.",
    ], blocked: !brains ? "Checking the Analyst…" : !r?.ok ? `The Analyst is not ready: ${r?.why || "not set"}.` : job(snap), action: { type: "job", path: "/api/digest", ok: "Digest started" } };
  }

  if (head === "open" || head === "go") {
    if (!arg) return { kind: "help", title: "Open what? A level (open L05) or a clip id." };
    if (NAV[arg]) return { kind: "nav", ...NAV[arg] };
    const n = levelNum(arg);
    if (n != null) {
      const id = levelId(n, season);
      const known = season?.levels.find((l) => l.id === id);
      return { kind: "nav", title: known ? `Open ${id} on Season · ${known.world}, ${known.date}` : `Open ${id} on Season`, view: "season", params: { level: id } };
    }
    if (/^[0-9a-f]{6,16}$/i.test(arg)) {
      const all = [...snap.queue, ...snap.approved, ...(snap.recent || [])];
      const hit = all.find((c) => c.id.startsWith(arg.toLowerCase()));
      return { kind: "clip", title: `Open clip ${hit ? hit.id : arg}${hit?.title ? ` — ${hit.title}` : ""}`, id: hit ? hit.id : arg.toLowerCase() };
    }
    return { kind: "help", title: `I cannot open “${arg}”. Try a level (L05) or a clip id.` };
  }

  return { kind: "help", title: `I don't understand “${text}” yet.` };
}

/** Completions for what is typed so far: verbs first, then the verb's own. */
export function suggest(input: string, ctx: Ctx): Suggestion[] {
  const text = input.replace(/^\s+/, "").toLowerCase();
  const [head, ...rest] = text.split(/\s+/);
  const arg = rest.join(" ");
  const next = ctx.season?.levels.filter((l) => l.plannable) || [];
  const range = next.length > 1 ? `${next[0].id}..${next[Math.min(2, next.length - 1)].id}` : next[0]?.id || "L01";
  const live = ctx.stages.filter((s) => s.live);
  const base: Suggestion[] = [
    { text: `plan ${range}`, label: `plan ${range}`, hint: next.length ? "the next ready levels" : "queue season levels" },
    { text: `make 3 ${live[0]?.id || "zigzag"}`, label: `make 3 ${live[0]?.id || "zigzag"}`, hint: "ad-hoc clips on a stage" },
    { text: "import", label: "import", hint: "queue jobs from a file" },
    { text: "run qc", label: "run qc", hint: `${ctx.snap.counts?.awaiting_qc || 0} waiting` },
    { text: "build", label: "build", hint: `${ctx.snap.counts?.planned || 0} planned` },
    { text: "publish", label: "publish", hint: `${ctx.snap.counts?.approved || 0} approved` },
    { text: "digest", label: "digest", hint: "the Analyst's read" },
    { text: `open ${next[0]?.id || "L01"}`, label: `open ${next[0]?.id || "L01"}`, hint: "a level or a clip id" },
    { text: "season", label: "season", hint: "go to Season" },
    { text: "clips", label: "clips", hint: "go to Clips" },
    { text: "settings", label: "settings", hint: "go to Settings" },
  ];
  if (!text.trim()) return base;
  if (!rest.length) {
    return base.filter((s) => s.text.startsWith(head) || s.text.split(" ")[0].startsWith(head))
      .concat(VERBS.filter((v) => v.startsWith(head) && !base.some((b) => b.text.split(" ")[0] === v.split(" ")[0]))
        .map((v) => ({ text: v, label: v, hint: "" })));
  }
  if (head === "plan") {
    const out: Suggestion[] = [];
    if (next.length) out.push({ text: `plan ${range}`, label: `plan ${range}`, hint: "the next ready levels" });
    next.slice(0, 6).forEach((l) => out.push({ text: `plan ${l.id}`, label: `plan ${l.id}`, hint: `${l.world} · ${l.date}` }));
    return out.filter((s) => s.text.startsWith(text.trimEnd()) || !arg);
  }
  if (head === "make" || head === "queue") {
    const words = rest.filter(Boolean);
    const n = words.find((w) => /^\d+$/.test(w)) || "3";
    const partial = words.find((w) => !/^\d+$/.test(w)) || "";
    return ctx.stages.filter((s) => s.id.startsWith(partial)).slice(0, 10)
      .map((s) => ({ text: `make ${n} ${s.id}`, label: `make ${n} ${s.id}`, hint: s.live ? (s.blurb || "").slice(0, 60) : "trial stage" }));
  }
  if (head === "open") {
    const out: Suggestion[] = [];
    (ctx.season?.levels || []).filter((l) => l.id.toLowerCase().startsWith(arg)).slice(0, 5)
      .forEach((l) => out.push({ text: `open ${l.id}`, label: `open ${l.id}`, hint: `${l.world} · ${l.status}` }));
    [...ctx.snap.queue, ...ctx.snap.approved].filter((c) => c.id.startsWith(arg)).slice(0, 5)
      .forEach((c) => out.push({ text: `open ${c.id}`, label: `open ${c.id}`, hint: c.title || "clip" }));
    return out;
  }
  if (head === "run") return [{ text: "run qc", label: "run qc", hint: "judge the clips waiting for QC" }];
  return [];
}
