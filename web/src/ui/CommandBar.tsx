// The command bar: type what you want, see what will happen, press Enter.
// ⌘K / Ctrl-K from anywhere. Every write shows its preview first and runs
// only on Enter or its button; navigation just goes. The grammar lives in
// lib/command.ts; this file is the input, the list and the import dialog.
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { api, q, send, ApiError } from "../lib/api";
import { plural } from "../lib/format";
import { act, toast } from "../lib/toast";
import { GRAMMAR, parse, suggest } from "../lib/command";
import type { Brains, Parsed, Stage } from "../lib/command";
import type { SeasonView } from "../screens/Season";
import type { Snap } from "../lib/types";
import { Modal } from "./index";

type Nav = (v: string, p?: Record<string, string | number | undefined>) => void;
interface Receipt { batch_id: string | null; source: string; dry_run: boolean; accepted: number; refused: number; note: string | null; rows: { row: number; ref: string | null; level: string | null; queued: boolean; task_ids: number[]; reason: string | null }[] }

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

export function CommandBar({ snap, channelId, refresh, navigate, onOpen }: {
  snap: Snap; channelId: string; refresh: () => Promise<void>; navigate: Nav; onOpen: (id: string) => void;
}) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(-1);
  const [busy, setBusy] = useState(false);
  const [season, setSeason] = useState<SeasonView | null>(null);
  const [brains, setBrains] = useState<Brains | null>(null);
  const [stages, setStages] = useState<Stage[]>([]);
  const [check, setCheck] = useState<{ key: string; receipt?: Receipt; error?: string } | null>(null);
  const [importing, setImporting] = useState<{ file: File; receipt: Receipt } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const listId = useId();

  // What the grammar needs to preview honestly: the season, the brains, the stages.
  const load = useCallback(() => {
    api<SeasonView>(`/api/season?${q({ channel: channelId })}`).then(setSeason)
      .catch((e) => { if (e instanceof ApiError && e.status === 404) setSeason(null); });
    api<Brains>("/api/brains").then(setBrains).catch(() => {});
    api<{ stages: Stage[] }>(`/api/work?${q({ channel: channelId, page_size: 1 })}`).then((b) => setStages(b.stages || [])).catch(() => {});
  }, [channelId]);
  useEffect(() => { if (open) load(); }, [open, load, snap.tasks?.queued]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === "k") {
        e.preventDefault(); input.current?.focus(); input.current?.select(); setOpen(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const ctx = useMemo(() => ({ snap, season, brains, stages }), [snap, season, brains, stages]);
  const parsed: Parsed = useMemo(() => parse(text, ctx), [text, ctx]);
  const options = useMemo(() => suggest(text, ctx).filter((s) => s.text !== text.trim().toLowerCase()).slice(0, 8), [text, ctx]);
  useEffect(() => { setHi(-1); }, [text]);

  // `make` is checked by the server before Enter means anything: a dry run of
  // the same rows, so the preview says exactly what will be queued.
  const makeKey = parsed.kind === "write" && parsed.action.type === "make" && !parsed.blocked ? JSON.stringify(parsed.action) : null;
  useEffect(() => {
    if (!makeKey) { setCheck(null); return; }
    const a = JSON.parse(makeKey) as { count: number; stage: string | null };
    let live = true;
    const t = window.setTimeout(() => {
      send<Receipt>("/api/tasks/batch", { channel: channelId, jobs: [{ count: a.count, ...(a.stage ? { stage: a.stage } : {}) }], dry_run: true })
        .then((r) => live && setCheck({ key: makeKey, receipt: r }))
        .catch((e) => live && setCheck({ key: makeKey, error: (e as Error).message }));
    }, 250);
    return () => { live = false; window.clearTimeout(t); };
  }, [makeKey, channelId]);
  const makeProblem = makeKey ? (!check || check.key !== makeKey ? "Checking…" : check.error || check.receipt?.rows.find((r) => r.reason)?.reason || null) : null;

  const done = () => { setText(""); setOpen(false); input.current?.blur(); };

  const run = async () => {
    if (busy) return;
    const p = parsed;
    if (p.kind === "nav") { navigate(p.view, p.params); done(); return; }
    if (p.kind === "clip") { onOpen(p.id); done(); return; }
    if (p.kind !== "write" || p.blocked || makeProblem) return;
    const a = p.action;
    if (a.type === "import") { picker.current?.click(); return; }
    setBusy(true);
    try {
      if (a.type === "plan") {
        const known = new Set((season?.levels || []).map((l) => l.id));
        const out = await act(() => send<{ queued: number; results: { level: string; queued: boolean; reason: string | null }[] }>("/api/season/plan", { channel: channelId, levels: a.levels.filter((id) => known.has(id)) }));
        if (out) {
          toast(out.queued ? `Queued ${plural(out.queued, "level")}. Claude, a worker or \`factory work\` makes them next.` : `Nothing queued: ${out.results.find((r) => !r.queued)?.reason || "no level could be planned"}`, out.queued ? "info" : "error");
          await refresh(); done();
        }
      } else if (a.type === "make") {
        const out = await act(() => send<Receipt>("/api/tasks/batch", { channel: channelId, jobs: [{ count: a.count, ...(a.stage ? { stage: a.stage } : {}) }], dry_run: false }));
        if (out) {
          const n = out.rows.reduce((s, r) => s + r.task_ids.length, 0);
          toast(n ? `Queued ${plural(n, "clip")}${a.stage ? ` on ${a.stage}` : ""}.` : `Nothing queued: ${out.rows[0]?.reason || out.note}`, n ? "info" : "error");
          await refresh(); done();
        }
      } else if (a.type === "job") {
        const out = await act(() => send(a.path, { channel: channelId }), { ok: a.ok, after: refresh });
        if (out !== undefined) done();
      }
    } finally { setBusy(false); }
  };

  const chooseFile = async (file: File | undefined) => {
    if (picker.current) picker.current.value = "";
    if (!file) return;
    const receipt = await upload(file, channelId, true, false).catch((e) => { toast((e as Error).message, "error"); return null; });
    if (receipt) { setImporting({ file, receipt }); setOpen(false); }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setHi((i) => Math.min(i + 1, options.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setHi((i) => Math.max(i - 1, -1)); }
    else if (e.key === "Tab" && open && options.length && text.trim() && !e.shiftKey) { e.preventDefault(); setText(options[Math.max(hi, 0)].text); }
    else if (e.key === "Enter") {
      e.preventDefault();
      if (hi >= 0 && options[hi]) { setText(options[hi].text); setOpen(true); }
      else run();
    } else if (e.key === "Escape") {
      if (text) setText(""); else { setOpen(false); input.current?.blur(); }
    } else setOpen(true);
  };

  const active = hi >= 0 ? `${listId}-${hi}` : undefined;
  return (
    <div className="cmd" ref={box}>
      <label className="sr-only" htmlFor={`${listId}-input`}>Command</label>
      <div className="cmd-field">
        <svg className="cmd-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="currentColor" d="M6.5 1a5.5 5.5 0 0 1 4.38 8.82l3.65 3.65a.75.75 0 1 1-1.06 1.06l-3.65-3.65A5.5 5.5 0 1 1 6.5 1Zm0 1.5a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z" /></svg>
        <input id={`${listId}-input`} ref={input} className="cmd-input" type="text" autoComplete="off" spellCheck={false}
          role="combobox" aria-expanded={open} aria-controls={listId} aria-activedescendant={active} aria-autocomplete="list"
          placeholder="Tell the office what to do — plan L02..L04, make 3 zigzag, import…"
          value={text} onChange={(e) => { setText(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} onKeyDown={onKeyDown} />
        <kbd className="cmd-kbd" aria-hidden>{isMac ? "⌘" : "Ctrl"} K</kbd>
      </div>
      <input ref={picker} type="file" hidden accept=".csv,.json,.jsonl,.yaml,.yml" onChange={(e) => chooseFile(e.target.files?.[0])} />
      {open && (
        <div className="cmd-pop" role="dialog" aria-label="Command preview">
          <Preview parsed={parsed} busy={busy} makeProblem={makeProblem} run={run} />
          {options.length > 0 && (
            <ul className="cmd-list" role="listbox" id={listId} aria-label="Suggestions">
              {options.map((o, i) => (
                <li key={o.text} id={`${listId}-${i}`} role="option" aria-selected={i === hi}
                  onMouseDown={(e) => { e.preventDefault(); setText(o.text); input.current?.focus(); }} onMouseEnter={() => setHi(i)}>
                  <span className="mono">{o.label}</span><span className="hint">{o.hint}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="cmd-foot hint"><span><kbd>↑</kbd><kbd>↓</kbd> choose</span><span><kbd>Tab</kbd> complete</span><span><kbd>Enter</kbd> run</span><span><kbd>Esc</kbd> close</span></div>
        </div>
      )}
      {importing && <ImportDialog file={importing.file} first={importing.receipt} channelId={channelId}
        close={() => setImporting(null)} after={async () => { setImporting(null); setText(""); await refresh(); }} />}
    </div>
  );
}

function Preview({ parsed, busy, makeProblem, run }: { parsed: Parsed; busy: boolean; makeProblem: string | null; run: () => void }) {
  if (parsed.kind === "empty") return <div className="cmd-preview"><p className="hint">Type a command, or pick one below. Writes show what they will do before they run.</p></div>;
  if (parsed.kind === "help") {
    return (
      <div className="cmd-preview" aria-live="polite">
        <b>{parsed.title}</b>
        <dl className="cmd-grammar">{GRAMMAR.map((g) => <div key={g.example}><dt className="mono">{g.example}</dt><dd>{g.hint}</dd></div>)}</dl>
      </div>
    );
  }
  if (parsed.kind === "nav" || parsed.kind === "clip") {
    return <div className="cmd-preview" aria-live="polite"><div className="row"><b className="grow">{parsed.title}</b><span className="hint"><kbd>Enter</kbd> to go</span></div></div>;
  }
  const stop = parsed.blocked || (makeProblem && makeProblem !== "Checking…" ? makeProblem : null);
  return (
    <div className={"cmd-preview write" + (stop ? " blocked" : "")} aria-live="polite">
      <b>{parsed.title}</b>
      <ul className="cmd-lines">{parsed.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
      {parsed.note && <p className="hint mt-3">{parsed.note}</p>}
      <div className="row wrap mt-3">
        {stop ? <span className="key-text small grow">{stop}</span>
          : <span className="hint grow">{makeProblem === "Checking…" ? "Checking with the server…" : <>Nothing happens until you press <kbd>Enter</kbd>.</>}</span>}
        <button type="button" className="sm primary" disabled={!!stop || busy || !!makeProblem} onMouseDown={(e) => e.preventDefault()} onClick={run}>{busy ? "Working…" : parsed.verb}</button>
      </div>
    </div>
  );
}

async function upload(file: File, channel: string, dryRun: boolean, partial: boolean): Promise<Receipt> {
  const form = new FormData();
  form.append("file", file, file.name);
  form.append("channel", channel);
  form.append("dry_run", String(dryRun));
  form.append("partial", String(partial));
  return api<Receipt>("/api/tasks/import", { method: "POST", body: form });
}

/* The dry-run receipt, row by row, then one button that queues it. */
function ImportDialog({ file, first, channelId, close, after }: { file: File; first: Receipt; channelId: string; close: () => void; after: () => Promise<void> }) {
  const [partial, setPartial] = useState(false);
  const [busy, setBusy] = useState(false);
  const r = first;
  const can = r.accepted > 0 && (!r.refused || partial);
  const confirm = async () => {
    setBusy(true);
    try {
      const out = await upload(file, channelId, false, partial);
      const n = out.rows.reduce((s, x) => s + x.task_ids.length, 0);
      if (out.batch_id) { toast(`Imported ${file.name}: ${plural(n, "task")} queued${out.refused ? `, ${out.refused} row(s) left out` : ""}.`); await after(); }
      else toast(out.note || "Nothing was queued.", "error");
    } catch (e) { toast((e as Error).message, "error"); }
    finally { setBusy(false); }
  };
  return (
    <Modal title={`Import ${file.name}`} onClose={close}>
      <p className="small mb-3">{r.refused
        ? `${plural(r.accepted, "row")} can be queued; ${plural(r.refused, "row")} cannot. Nothing is queued yet.`
        : `All ${plural(r.accepted, "row")} check out. Nothing is queued yet.`}</p>
      <div className="table-box">
        <table className="data compact">
          <thead><tr><th>Row</th><th>Level or ref</th><th>Check</th></tr></thead>
          <tbody>{r.rows.map((x, i) => (
            <tr key={i}><td className="num">{x.row}</td><td>{x.level || x.ref || <span className="faint">—</span>}</td>
              <td>{x.reason ? <span className="no-text">{x.reason}</span> : <span className="ok-text">ok</span>}</td></tr>
          ))}</tbody>
        </table>
      </div>
      {r.refused > 0 && r.accepted > 0 && (
        <label className="row small mt-3"><input type="checkbox" checked={partial} onChange={(e) => setPartial(e.target.checked)} /> Queue the {plural(r.accepted, "row")} that {r.accepted === 1 ? "passes" : "pass"} and leave the rest out</label>
      )}
      <div className="row mt-3">
        <span className="hint grow">Same checks as <code>factory tasks import</code>. Importing the same ref twice queues it once.</span>
        <button type="button" onClick={close}>Cancel</button>
        <button type="button" className="primary" disabled={!can || busy} onClick={confirm}>{busy ? "Queueing…" : `Queue ${plural(r.accepted, "row")}`}</button>
      </div>
    </Modal>
  );
}
