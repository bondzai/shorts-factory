import { useCallback, useEffect, useState } from "react";
import { api, q, send } from "../lib/api";
import { hex, rgb } from "../lib/format";
import { act, toast } from "../lib/toast";
import { Page, Card, Field, Chips, Tabs } from "../ui";
import { Docs } from "./Docs";
import type { Route } from "../lib/route";
import type { Channel, Snap } from "../lib/types";

const TABS = [
  { id: "channel", label: "Channel", meaning: "name, handle, driver, what it may make" },
  { id: "rules", label: "Rules", meaning: "what the agents read before every run" },
  { id: "directions", label: "Directions", meaning: "your own notes, appended to everything an agent reads" },
  { id: "brains", label: "Brains", meaning: "which model each agent runs on" },
  { id: "themes", label: "Themes", meaning: "seasons: colours, marbles, decorations" },
  { id: "factory", label: "Factory", meaning: "the knobs: gates, captions, retention, rounds" },
  { id: "alerts", label: "Alerts", meaning: "where you are told: Discord, Slack, Telegram" },
  { id: "docs", label: "Docs", meaning: "how it all works" },
];

export function Settings({ snap, channelId, refresh, route, navigate, theme }: { snap: Snap; channelId: string; refresh: () => Promise<void>; route: Route; navigate: (v: string, p?: Record<string, string | number | undefined>) => void; theme?: React.ReactNode }) {
  const tab = route.params.get("tab") || "channel";
  const current = TABS.find((t) => t.id === tab) || TABS[0];
  return (
    <Page title="Settings">
      <Tabs label="Settings" tabs={TABS} value={current.id} onChange={(id) => navigate("settings", id === "channel" ? {} : { tab: id })} />
      <p className="page-lead">{current.id === "channel" ? `${snap.channel.name}: ${current.meaning}` : current.meaning}</p>
      {current.id === "docs" && <Docs page={route.params.get("page") || ""} setPage={(id) => navigate("settings", { tab: "docs", page: id })} />}
      {current.id === "channel" && <><ChannelForm ch={snap.channel} refresh={refresh} /><YouTube channelId={channelId} driver={snap.channel.driver} refresh={refresh} /><AddChannel onDone={refresh} /></>}
      {current.id === "rules" && <Rules channelId={channelId} />}
      {current.id === "directions" && <Directions channelId={channelId} />}
      {current.id === "brains" && <Brains refresh={refresh} />}
      {current.id === "themes" && <Themes />}
      {current.id === "factory" && <FactorySettings />}
      {current.id === "alerts" && <Alerts />}
      {theme && <div className="row mt-3 appearance"><span className="hint">Appearance</span>{theme}</div>}
    </Page>
  );
}

function ChannelForm({ ch, refresh }: { ch: Channel; refresh: () => Promise<void> }) {
  const [form, setForm] = useState({ name: ch.name, handle: ch.handle || "", driver: ch.driver, cadence: String(ch.cadence), variants: (ch.variants || []).join(", ") });
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });
  const save = (e: React.FormEvent) => { e.preventDefault(); act(() => send(`/api/channels/${ch.id}`, { name: form.name, handle: form.handle || null, driver: form.driver, cadence: Number(form.cadence), variants: form.variants.split(",").map((s) => s.trim()).filter(Boolean) }, "PATCH"), { ok: "Channel saved", after: refresh }); };
  const pause = () => act(() => send(`/api/channels/${ch.id}`, { active: !ch.active }, "PATCH"), { after: refresh });
  return (
    <Card title="Channel">
      <form className="form" onSubmit={save}>
        <Field label="name"><input value={form.name} onChange={set("name")} /></Field>
        <Field label="handle"><input value={form.handle} onChange={set("handle")} placeholder="@handle" /></Field>
        <Field label="publish driver"><select value={form.driver} onChange={set("driver")}><option value="manual">manual — you upload, the page copies the file and text</option><option value="youtube">youtube — API upload (needs credentials)</option></select></Field>
        <Field label="clips per day"><input type="number" className="w-sm" min={1} value={form.cadence} onChange={set("cadence")} /></Field>
        <Field label="allowed modules" help="comma-separated generator/variant; empty means every ready module"><input value={form.variants} onChange={set("variants")} placeholder="physics/marble_race, physics/funnel_drop" /></Field>
        <div className="actions"><button type="submit" className="primary">Save channel</button><button type="button" onClick={pause}>{ch.active ? "Pause channel" : "Resume channel"}</button></div>
      </form>
    </Card>
  );
}

interface Provider { id: string; kind: string; base_url: string | null; api_key_env: string | null; vision: boolean; json_mode: string; models: string[]; free?: boolean; key_present?: boolean }
interface BrainsView { providers: Provider[]; agents: Record<string, string>; readiness: Record<string, { ok: boolean; why?: string | null; free?: boolean }>; needs_vision: string[]; presets: Provider[]; mcp_command: string[]; overridden: boolean }

function Brains({ refresh }: { refresh: () => Promise<void> }) {
  const [b, setB] = useState<BrainsView | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [agents, setAgents] = useState<Record<string, string>>({});
  const [tests, setTests] = useState<Record<string, { pending?: boolean; ok?: boolean; latency_ms?: number; reply?: string; error?: string }>>({});
  const [copied, setCopied] = useState<string | null>(null);
  const load = useCallback(() => api<BrainsView>("/api/brains").then((body) => { setB(body); setProviders(body.providers); setAgents(body.agents); }), []);
  useEffect(() => { load().catch((e) => toast((e as Error).message, "error")); }, [load]);
  if (!b) return null;
  const setP = (i: number, k: keyof Provider, v: unknown) => setProviders((ps) => ps.map((p, j) => j === i ? { ...p, [k]: v } : p));
  const save = () => act(() => send<BrainsView>("/api/brains", { providers, agents }, "PUT").then((out) => { setB(out); setProviders(out.providers); setAgents(out.agents); }), { ok: "Brains saved", after: refresh });
  const test = async (p: Provider) => {
    const model = p.models?.[0] || window.prompt(`Model to test ${p.id} with:`);
    if (!model) return;
    setTests((t) => ({ ...t, [p.id]: { pending: true } }));
    try { await send("/api/brains", { providers, agents }, "PUT"); const r = await send<typeof tests[string]>("/api/brains/test", { provider: p.id, model }); setTests((t) => ({ ...t, [p.id]: r })); }
    catch (err) { setTests((t) => ({ ...t, [p.id]: { ok: false, error: (err as Error).message } })); }
  };
  const copy = async (key: string, text: string) => { try { await navigator.clipboard.writeText(text); setCopied(key); setTimeout(() => setCopied(null), 1500); } catch { toast("Could not reach the clipboard.", "error"); } };
  const cmd = b.mcp_command.map((s) => s.includes(" ") ? `"${s}"` : s).join(" ");
  const external: [string, string][] = [["Codex", `codex mcp add shorts-factory -- ${cmd}`], ["Claude Code", `claude mcp add shorts-factory -- ${cmd}`], ["Gemini CLI (~/.gemini/settings.json)", JSON.stringify({ mcpServers: { "shorts-factory": { command: b.mcp_command[0], args: b.mcp_command.slice(1) } } }, null, 2)]];
  const does: Record<string, string> = { idea: "picks what to make", metadata: "writes the title", qc: "judges four frames — needs a model that sees images", analyst: "reads the numbers, proposes rules" };
  return (
    <Card title="Brains" hint="External: any MCP-capable agent registers this factory once and reads the playbooks. Built-in: the factory calls a model itself for Plan, Build and Digest; pick a provider and model per agent. Keys never go through this page — only the name of the variable in .env.">
      <h3 className="mt-3">External agents — register once, then use the playbooks</h3>
      {external.map(([name, text]) => <div key={name} className="row mt-3" style={{ alignItems: "flex-start" }}><span className="hint" style={{ width: 200, flex: "none" }}>{name}</span><pre className="captured grow" style={{ maxHeight: 90 }}>{text}</pre><button className="sm" onClick={() => copy(name, text)}>{copied === name ? "Copied" : "Copy"}</button></div>)}
      <h3 className="mt-3">Built-in providers</h3>
      <table className="data mt-3">
        <thead><tr><th>id</th><th>kind</th><th>endpoint</th><th>key variable</th><th>sees images</th><th>JSON</th><th>models</th><th /></tr></thead>
        <tbody>{providers.map((p, i) => (
          <tr key={i}>
            <td><input className="sm w-sm" value={p.id} onChange={(e) => setP(i, "id", e.target.value)} /></td>
            <td><select className="sm" value={p.kind} onChange={(e) => setP(i, "kind", e.target.value)}><option value="anthropic">anthropic</option><option value="openai">openai-compatible</option></select></td>
            <td><input className="sm w-lg" value={p.base_url || ""} disabled={p.kind === "anthropic"} placeholder="http://localhost:11434/v1" onChange={(e) => setP(i, "base_url", e.target.value)} /></td>
            <td><input className="sm w-md" value={p.api_key_env || ""} placeholder="none (local)" onChange={(e) => setP(i, "api_key_env", e.target.value)} /><div className="hint">{!p.api_key_env ? "no key needed" : p.key_present ? <span className="ok-text">set in .env</span> : <span className="no-text">not set in .env</span>}</div></td>
            <td><input type="checkbox" checked={!!p.vision} onChange={(e) => setP(i, "vision", e.target.checked)} /></td>
            <td><select className="sm" value={p.json_mode} onChange={(e) => setP(i, "json_mode", e.target.value)}>{["schema", "object", "none"].map((m) => <option key={m}>{m}</option>)}</select></td>
            <td><input className="sm w-md" value={(p.models || []).join(", ")} onChange={(e) => setP(i, "models", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} /></td>
            <td><span className="row"><button className="sm" onClick={() => test(p)} disabled={tests[p.id]?.pending}>{tests[p.id]?.pending ? "Testing…" : "Test"}</button><button className="sm" onClick={() => setProviders(providers.filter((_, j) => j !== i))}>Remove</button></span>
              {tests[p.id] && !tests[p.id].pending && <div className={"hint " + (tests[p.id].ok ? "ok-text" : "no-text")}>{tests[p.id].ok ? `ok · ${tests[p.id].latency_ms} ms · "${tests[p.id].reply}"` : tests[p.id].error}</div>}</td>
          </tr>))}</tbody>
      </table>
      <div className="row mt-3"><select defaultValue="" onChange={(e) => { const id = e.target.value; e.target.value = ""; if (!id) return; const preset = id === "custom" ? { id: "custom", kind: "openai", base_url: "", api_key_env: "", vision: true, json_mode: "object", models: [] } : b.presets.find((p) => p.id === id)!; if (providers.some((p) => p.id === preset.id)) { toast(`${preset.id} is already listed`, "error"); return; } setProviders([...providers, { ...preset, key_present: false }]); }}>
        <option value="">Add a provider…</option>{b.presets.map((p) => <option key={p.id} value={p.id}>{p.id}{p.free ? " (local, free)" : ""}</option>)}<option value="custom">custom endpoint</option></select></div>
      <h3 className="mt-3">Which model each built-in agent uses</h3>
      <table className="data mt-3">
        <thead><tr><th>agent</th><th>does</th><th>provider</th><th>model</th><th>ready?</th></tr></thead>
        <tbody>{Object.keys(agents).map((a) => { const [pid, ...rest] = agents[a].split("/"); const model = rest.join("/"); const prov = providers.find((p) => p.id === pid); const r = b.readiness[a] || { ok: false };
          return <tr key={a}><td><b>{a}</b></td><td className="dim">{does[a]}</td>
            <td><select className="sm" value={pid} onChange={(e) => setAgents({ ...agents, [a]: `${e.target.value}/${model}` })}>{providers.map((p) => <option key={p.id} value={p.id} disabled={b.needs_vision.includes(a) && !p.vision}>{p.id}{b.needs_vision.includes(a) && !p.vision ? " (no images)" : ""}</option>)}</select></td>
            <td><input className="sm w-md" list={`models-${pid}`} value={model} onChange={(e) => setAgents({ ...agents, [a]: `${pid}/${e.target.value}` })} /><datalist id={`models-${pid}`}>{(prov?.models || []).map((m) => <option key={m} value={m} />)}</datalist></td>
            <td>{r.ok ? <span className="ok-text">ready{r.free ? " · free" : ""}</span> : <span className="no-text">{r.why || "—"}</span>}</td></tr>; })}</tbody>
      </table>
      <div className="row mt-3"><button className="primary" onClick={save}>Save brains</button><span className="hint">{b.overridden ? "set on this page (config.toml is the default underneath)" : "from config.toml"}</span></div>
    </Card>
  );
}

interface Theme { id: string; name: string; decoration: string; window: string[] | null; enabled: boolean; palettes: number[][][]; marbles: [string, number[]][]; caption: number[] }
interface ThemesView { themes: Theme[]; active: string; today: string; force: string; decorations: string[]; overridden: boolean }

function Themes() {
  const [v, setV] = useState<ThemesView | null>(null);
  const [list, setList] = useState<Theme[]>([]);
  const [force, setForce] = useState("");
  useEffect(() => { api<ThemesView>("/api/themes").then((b) => { setV(b); setList(b.themes); setForce(b.force); }).catch((e) => toast((e as Error).message, "error")); }, []);
  if (!v) return null;
  const setT = (i: number, k: keyof Theme, val: unknown) => setList((ts) => ts.map((t, j) => j === i ? { ...t, [k]: val } : t));
  const save = () => act(() => send<ThemesView>("/api/themes", { themes: list, force }, "PUT").then((out) => { setV(out); setList(out.themes); setForce(out.force); }), { ok: "Themes saved" });
  const add = () => setList([...list, { id: `theme${list.length + 1}`, name: "New theme", decoration: "none", window: ["01-01", "01-07"], enabled: true, palettes: [[[18, 18, 26], [58, 58, 74]]], marbles: [["red", [232, 76, 74]], ["blue", [55, 138, 221]], ["gold", [240, 200, 80]]], caption: [255, 255, 255] }]);
  return (
    <Card title="Themes" hint={<>A theme is colours, marble names, a caption colour and a decoration, with a window in the calendar. Today is {v.today}; the active theme is <b>{v.active}</b>{force ? " (forced)" : " (by calendar)"}. Marble names end up in titles, so use words a viewer would say.</>}>
      <div className="row"><span className="hint" style={{ width: 120 }}>force a theme</span><select value={force} onChange={(e) => setForce(e.target.value)}><option value="">— by calendar —</option>{list.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></div>
      <table className="data mt-3">
        <thead><tr><th>on</th><th>id / name</th><th>window</th><th>decoration</th><th>backdrop → structure</th><th>marbles</th><th>caption</th><th /></tr></thead>
        <tbody>{list.map((t, i) => (
          <tr key={i}>
            <td><input type="checkbox" checked={t.enabled !== false} onChange={(e) => setT(i, "enabled", e.target.checked)} /></td>
            <td className="stack"><input className="sm w-sm" value={t.id} onChange={(e) => setT(i, "id", e.target.value)} /><input className="sm w-sm" value={t.name} onChange={(e) => setT(i, "name", e.target.value)} /></td>
            <td>{t.id === "default" ? <span className="hint">always</span> : <span className="row"><input className="sm" style={{ width: 64 }} value={t.window?.[0] || ""} placeholder="MM-DD" onChange={(e) => setT(i, "window", [e.target.value, t.window?.[1] || ""])} />–<input className="sm" style={{ width: 64 }} value={t.window?.[1] || ""} placeholder="MM-DD" onChange={(e) => setT(i, "window", [t.window?.[0] || "", e.target.value])} /></span>}</td>
            <td><select className="sm" value={t.decoration} onChange={(e) => setT(i, "decoration", e.target.value)}>{v.decorations.map((d) => <option key={d}>{d}</option>)}</select></td>
            <td className="stack">{t.palettes.map((p, k) => <span key={k} className="row"><input type="color" value={hex(p[0])} onChange={(e) => setT(i, "palettes", t.palettes.map((q2, m) => m === k ? [rgb(e.target.value), q2[1]] : q2))} /><input type="color" value={hex(p[1])} onChange={(e) => setT(i, "palettes", t.palettes.map((q2, m) => m === k ? [q2[0], rgb(e.target.value)] : q2))} />{t.palettes.length > 1 && <button className="sm ghost" onClick={() => setT(i, "palettes", t.palettes.filter((_, m) => m !== k))}>×</button>}</span>)}<button className="sm" onClick={() => setT(i, "palettes", [...t.palettes, [[18, 18, 26], [58, 58, 74]]])}>+ palette</button></td>
            <td className="stack">{t.marbles.map((m, k) => <span key={k} className="row"><input className="sm" style={{ width: 70 }} value={m[0]} onChange={(e) => setT(i, "marbles", t.marbles.map((q2, n) => n === k ? [e.target.value, q2[1]] : q2))} /><input type="color" value={hex(m[1])} onChange={(e) => setT(i, "marbles", t.marbles.map((q2, n) => n === k ? [q2[0], rgb(e.target.value)] : q2))} />{t.marbles.length > 3 && <button className="sm ghost" onClick={() => setT(i, "marbles", t.marbles.filter((_, n) => n !== k))}>×</button>}</span>)}<button className="sm" onClick={() => setT(i, "marbles", [...t.marbles, ["new", [200, 200, 200]]])}>+ marble</button></td>
            <td><input type="color" value={hex(t.caption)} onChange={(e) => setT(i, "caption", rgb(e.target.value))} /></td>
            <td>{t.id !== "default" && <button className="sm" onClick={() => setList(list.filter((_, j) => j !== i))}>Remove</button>}</td>
          </tr>))}</tbody>
      </table>
      <div className="row mt-3"><button className="primary" onClick={save}>Save themes</button><button className="sm" onClick={add}>Add a theme</button><span className="hint">{v.overridden ? "set on this page" : "shipped defaults"} · changes apply to the next render</span></div>
    </Card>
  );
}

interface SettingField { section: string; key: string; type: string; label: string; help?: string; min?: number; max?: number; step?: number; options?: (string | number)[]; value: unknown; default: unknown; overridden: boolean }

function FactorySettings() {
  const [s, setS] = useState<{ fields: SettingField[] } | null>(null);
  useEffect(() => { api<{ fields: SettingField[] }>("/api/settings").then(setS).catch((e) => toast((e as Error).message, "error")); }, []);
  if (!s) return null;
  const put = (f: SettingField, value: unknown) => act(() => send<{ fields: SettingField[] }>("/api/settings", { section: f.section, key: f.key, value }, "PUT").then(setS), { ok: `${f.label} saved` });
  const reset = (f: SettingField) => act(() => api<{ fields: SettingField[] }>(`/api/settings/${f.section}/${f.key}`, { method: "DELETE" }).then(setS));
  const groups = [...new Set(s.fields.map((f) => f.section))];
  return (
    <Card title="Factory settings" hint="config.toml is the default. A value changed here is stored in the database as an override, marked, and can be reset. Changes apply to the next render or QC, not to clips already made.">
      {groups.map((g) => (
        <div key={g} className="form mt-3">
          <div className="tiny faint" style={{ gridColumn: "1 / -1", textTransform: "uppercase", letterSpacing: ".08em" }}>{g}</div>
          {s.fields.filter((f) => f.section === g).map((f) => (
            <Field key={f.key} label={f.label} help={f.help}>
              <span className="row">
                {f.type === "select" ? <select value={String(f.value)} onChange={(e) => put(f, e.target.value)}>{f.options!.map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}</select>
                  : f.type === "number" ? <input type="number" className="w-sm" defaultValue={String(f.value)} min={f.min} max={f.max} step={f.step} onBlur={(e) => { if (e.target.value !== String(f.value)) put(f, e.target.value); }} />
                  : <input className="w-lg" defaultValue={String(f.value)} onBlur={(e) => { if (e.target.value !== f.value) put(f, e.target.value); }} />}
                {f.overridden ? <span className="hint">override · default {String(f.default)} <button className="sm ghost" onClick={() => reset(f)}>reset</button></span> : <span className="hint">default</span>}
              </span>
            </Field>
          ))}
        </div>
      ))}
    </Card>
  );
}

function Rules({ channelId }: { channelId: string }) {
  const [r, setR] = useState<{ path: string; text: string; proposals: string[]; digest: { n_published: number } | null } | null>(null);
  const [text, setText] = useState("");
  const load = useCallback(() => api<typeof r>(`/api/rules?${q({ channel: channelId })}`).then((b) => { setR(b); setText(b!.text); }), [channelId]);
  useEffect(() => { load().catch((e) => toast((e as Error).message, "error")); }, [load]);
  if (!r) return null;
  const save = () => act(() => send("/api/rules", { channel: channelId, text }, "PUT"), { ok: "Rules saved", after: load });
  const accept = (rule: string) => act(() => send("/api/rules/accept", { channel: channelId, rules: [rule] }), { ok: "Accepted", after: load });
  return (
    <Card title="Rules the agents read" hint={`${r.path} — the Idea and Metadata agents read this on every run. The Analyst proposes additions on the right; nothing lands without you accepting it.`}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 300px", gap: "var(--s4)" }}>
        <div className="stack"><textarea style={{ minHeight: 380, fontFamily: "ui-monospace, monospace", fontSize: "var(--f1)" }} value={text} spellCheck={false} onChange={(e) => setText(e.target.value)} /><div><button className="primary" onClick={save}>Save rules</button></div></div>
        <div className="stack">
          {r.proposals.map((p) => <Card key={p}><div className="small mb-3">{p}</div><button className="sm ok" onClick={() => accept(p)}>Accept</button></Card>)}
          {!r.proposals.length && <div className="hint">No pending proposals{r.digest ? ` (last digest: ${r.digest.n_published} clips with metrics)` : ""}. The Analyst writes nothing below the sample threshold.</div>}
        </div>
      </div>
    </Card>
  );
}

function Directions({ channelId }: { channelId: string }) {
  const [fields, setFields] = useState<{ key: string; label: string; placeholder: string; value: string }[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  useEffect(() => { api<{ fields: typeof fields }>(`/api/directions?${q({ channel: channelId })}`).then((b) => { setFields(b.fields); setValues(Object.fromEntries(b.fields.map((f) => [f.key, f.value]))); }).catch(() => {}); }, [channelId]);
  const save = () => act(() => send<{ fields: typeof fields }>("/api/directions", { channel: channelId, values }, "PUT").then((b) => setFields(b.fields)), { ok: "Directions saved" });
  return (
    <Card title="What every agent is told" hint="Five short notes in your own words. Appended to every playbook and every task's instructions; they win over anything that disagrees, so you never edit a playbook to change how titles sound. Applies to the next task an agent pulls.">
      <div className="form mt-3">
        {fields.map((f) => <Field key={f.key} label={f.label}><textarea rows={2} placeholder={f.placeholder} value={values[f.key] || ""} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} /></Field>)}
        <div className="actions"><button className="primary" onClick={save}>Save directions</button></div>
      </div>
    </Card>
  );
}

export function AddChannel({ onDone }: { onDone: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [handle, setHandle] = useState("");
  const create = (e: React.FormEvent) => { e.preventDefault(); act(() => send("/api/channels", { name, handle: handle || null }), { ok: "Channel created", after: async () => { setOpen(false); setName(""); setHandle(""); await onDone(); } }); };
  if (!open) return <button className="sm" onClick={() => setOpen(true)}>Add another channel</button>;
  return (
    <Card title="New channel">
      <form className="form" onSubmit={create}>
        <Field label="name"><input value={name} onChange={(e) => setName(e.target.value)} placeholder="HODL Tales" required /></Field>
        <Field label="handle"><input value={handle} onChange={(e) => setHandle(e.target.value)} placeholder="@handle (optional)" /></Field>
        <div className="actions"><button type="submit" className="primary">Create</button><button type="button" onClick={() => setOpen(false)}>Cancel</button></div>
      </form>
    </Card>
  );
}
export { Chips as _unusedChips };

interface NotifyView { sinks: { kind: string; where: string }[]; daily_at: string; on: string[] }

function Alerts() {
  const [v, setV] = useState<NotifyView | null>(null);
  useEffect(() => { api<NotifyView>("/api/notify").then(setV).catch((e) => toast((e as Error).message, "error")); }, []);
  const test = () => act(() => send<{ sent: boolean }>("/api/notify/test"), { ok: "Test sent — check the phone" });
  if (!v) return <p className="empty">loading…</p>;
  return (
    <>
      <Card title="Where alerts go" hint="Set in .env next to the password, never here: FACTORY_WEBHOOK_URL for Discord, Slack or ntfy; FACTORY_TELEGRAM_TOKEN and FACTORY_TELEGRAM_CHAT_ID for the Telegram bot. Restart the server after changing them.">
        {v.sinks.length ? v.sinks.map((s) => <div key={s.kind} className="row"><span className="badge ok">{s.kind}</span><span className="hint">{s.where}</span></div>) : <p className="hint">Nothing configured. Add one of the variables above and restart.</p>}
        <div className="actions mt-3"><button onClick={test} disabled={!v.sinks.length}>Send a test</button></div>
      </Card>
      <Card title="Telegram" hint="A bot you make with @BotFather. Put its token in .env, send it /start, put the chat id it answers with in .env, restart.">
        <p className="hint">After that a clip that passes QC arrives as the video with Approve and Reject under it, the daily reminder comes at {v.daily_at || "the configured time"}, and the bot answers /status, /queue, /clip, /approve, /reject and /daily.</p>
      </Card>
      <Card title="What is sent" hint="Set under [notify] on in config.toml.">
        <div className="row wrap">{v.on.map((e) => <span key={e} className="badge">{e}</span>)}</div>
      </Card>
    </>
  );
}


interface YouTubeView {
  driver: string; connected: boolean; client_secrets: boolean; privacy: string; slot: string;
  uploads_per_day: number; error?: string;
  account?: { id: string; title: string; handle?: string | null; subscribers?: number | null; videos?: number | null };
}

/* Connecting is a person's job: Google's consent screen opens on the machine
   running the server, and nothing here ever sees the password. */
function YouTube({ channelId, driver, refresh }: { channelId: string; driver: string; refresh: () => Promise<void> }) {
  const [v, setV] = useState<YouTubeView | null>(null);
  const [waiting, setWaiting] = useState(false);
  const load = useCallback(() => api<YouTubeView>(`/api/youtube?${q({ channel: channelId })}`).then(setV).catch(() => {}), [channelId]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!waiting) return;
    const id = setInterval(async () => {
      const out = await api<YouTubeView>(`/api/youtube?${q({ channel: channelId })}`).catch(() => null);
      if (out) { setV(out); if (out.connected) { setWaiting(false); toast(`Connected as ${out.account?.title || "YouTube"}`); } }
    }, 2000);
    const stop = setTimeout(() => setWaiting(false), 180000);
    return () => { clearInterval(id); clearTimeout(stop); };
  }, [waiting, channelId]);
  if (!v) return null;
  const connect = () => act(async () => { await send("/api/youtube/connect", { channel: channelId }); setWaiting(true); },
                            { ok: "Finish the sign-in in the browser window" });
  const disconnect = () => {
    if (!window.confirm("Forget this channel's YouTube token? Uploads stop until you connect again.")) return;
    act(() => send("/api/youtube/disconnect", { channel: channelId }), { ok: "Token forgotten", after: async () => { await load(); await refresh(); } });
  };
  return (
    <Card title="YouTube" hint={v.connected
      ? `Approved clips upload from Team: private now, public at ${v.slot}. About ${v.uploads_per_day} uploads a day fit YouTube's quota.`
      : "Connect this channel to upload from Team instead of by hand. One token per channel, kept in channels/ and gitignored."}>
      <div className="row wrap">
        <span className={"badge " + (v.connected ? "ok" : "")}>{v.connected ? "connected" : "not connected"}</span>
        {v.account && <span className="hint">{v.account.title}{v.account.videos != null ? ` · ${v.account.videos} videos` : ""}{v.account.subscribers != null ? ` · ${v.account.subscribers} subscribers` : ""}</span>}
        {waiting && <span className="hint">waiting for the browser…</span>}
        {v.error && <span className="no-text">{v.error}</span>}
        <span className="grow" />
        {v.connected
          ? <button className="sm danger" onClick={disconnect}>Disconnect</button>
          : <button className="sm primary" onClick={connect} disabled={!v.client_secrets || waiting}>Connect this channel</button>}
      </div>
      {!v.client_secrets && <p className="hint mt-3">First put an OAuth client for a Google Cloud project with the YouTube Data API v3 and YouTube Analytics API enabled at <code>client_secrets.json</code> in the project folder, then install the extra: <code>pip install -e '.[youtube]'</code>.</p>}
      {v.connected && driver !== "youtube" && <p className="hint mt-3">This channel still publishes with the <b>manual</b> driver — set <b>publish driver</b> above to <b>youtube</b> to upload from Team.</p>}
    </Card>
  );
}
