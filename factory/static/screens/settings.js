import { html, useState, useEffect, useRef, useCallback, api, send, fmt, num, pct, when, clock, statusWord, channelQuery, toast, act, useCopy, download } from "../lib.js";
import { Screen, Card, Chip, StepStrip } from "../ui.js";

function Settings({ snap, channelId, refresh, channels }) {
  const ch = snap.channel;
  const [form, setForm] = useState({ name: ch.name, handle: ch.handle || "", driver: ch.driver, cadence: ch.cadence, variants: (ch.variants || []).join(", ") });
  const [rules, setRules] = useState(null);
  const loadRules = useCallback(() => api(`/api/rules?channel=${encodeURIComponent(channelId)}`).then(setRules), [channelId]);
  useEffect(() => { loadRules().catch((err) => toast(err.message, "error")); }, [loadRules]);

  const save = async (e) => {
    e.preventDefault();
    const body = { name: form.name, handle: form.handle || null, driver: form.driver, cadence: Number(form.cadence),
      variants: form.variants.split(",").map((s) => s.trim()).filter(Boolean) };
    try { await send(`/api/channels/${ch.id}`, body, "PATCH"); } catch (err) { toast(err.message, "error"); return; }
    refresh();
  };
  const pause = async () => {
    try { await send(`/api/channels/${ch.id}`, { active: !ch.active }, "PATCH"); } catch (err) { toast(err.message, "error"); return; }
    refresh();
  };
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  return html`
    <h1>${ch.name}</h1>
    <p class="lead">What the agents are allowed to make here, how it gets published, and the rules they read before every run.</p>
    <div class="card">
      <h3>Channel</h3>
      <form class="grid" onSubmit=${save}>
        <label>name</label><input value=${form.name} onChange=${set("name")} />
        <label>handle</label><input value=${form.handle} onChange=${set("handle")} placeholder="@handle" />
        <label>publish driver</label>
        <select value=${form.driver} onChange=${set("driver")}><option value="manual">manual — you upload, the page copies the file and text</option><option value="youtube">youtube — API upload (needs credentials)</option></select>
        <label>clips per day</label><input type="number" min="1" value=${form.cadence} onChange=${set("cadence")} style=${{ width: 90 }} />
        <label>allowed modules</label><input value=${form.variants} onChange=${set("variants")} placeholder="physics/marble_race, physics/funnel_drop — empty means every ready module" />
        <span></span><div class="row"><button type="submit">Save channel</button><button type="button" onClick=${pause}>${ch.active ? "Pause channel" : "Resume channel"}</button></div>
      </form>
    </div>
    <${Brains} refresh=${refresh} />
    <${Themes} />
    <${FactorySettings} />
    ${rules ? html`<${Rules} rules=${rules} channelId=${channelId} reload=${loadRules} />` : null}
    <${AddChannel} onDone=${refresh} />`;
}

/* ---------- Brains: which model each built-in agent runs on, and how to plug in an external one ---------- */

function Brains({ refresh }) {
  const [b, setB] = useState(null);
  const [providers, setProviders] = useState([]);
  const [agents, setAgents] = useState({});
  const [tests, setTests] = useState({});
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(null);
  const load = useCallback(() => api("/api/brains").then((body) => {
    setB(body); setProviders(body.providers); setAgents(body.agents);
  }), []);
  useEffect(() => { load().catch((err) => toast(err.message, "error")); }, [load]);
  if (!b) return null;

  const setP = (i, k, v) => setProviders((ps) => ps.map((p, j) => j === i ? { ...p, [k]: v } : p));
  const addPreset = (e) => {
    const id = e.target.value; e.target.value = "";
    if (!id) return;
    const preset = id === "custom" ? { id: "custom", kind: "openai", base_url: "", api_key_env: "", vision: true, json_mode: "object", models: [] }
      : b.presets.find((p) => p.id === id);
    if (providers.some((p) => p.id === preset.id)) { toast(`${preset.id} is already listed`); return; }
    setProviders([...providers, { ...preset, key_present: false }]);
  };
  const save = async () => {
    setSaving(true);
    try { const out = await send("/api/brains", { providers, agents }, "PUT"); setB(out); setProviders(out.providers); setAgents(out.agents); }
    catch (err) { toast(err.message, "error"); }
    setSaving(false); refresh();
  };
  const test = async (p) => {
    const model = (p.models && p.models[0]) || prompt(`Model to test ${p.id} with:`);
    if (!model) return;
    setTests((t) => ({ ...t, [p.id]: { pending: true } }));
    try {
      await send("/api/brains", { providers, agents }, "PUT");
      const r = await send("/api/brains/test", { provider: p.id, model });
      setTests((t) => ({ ...t, [p.id]: r }));
    } catch (err) { setTests((t) => ({ ...t, [p.id]: { ok: false, error: err.message } })); }
  };
  const copy = async (key, text) => { try { await navigator.clipboard.writeText(text); setCopied(key); setTimeout(() => setCopied(null), 1500); } catch { toast("Could not reach the clipboard — select the text and copy it.", "error"); } };
  const cmd = b.mcp_command.map((s) => s.includes(" ") ? `"${s}"` : s).join(" ");
  const external = [
    ["Codex", `codex mcp add shorts-factory -- ${cmd}`],
    ["Claude Code", `claude mcp add shorts-factory -- ${cmd}`],
    ["Gemini CLI (~/.gemini/settings.json)", JSON.stringify({ mcpServers: { "shorts-factory": { command: b.mcp_command[0], args: b.mcp_command.slice(1) } } }, null, 2)],
  ];
  const ready = b.readiness;

  return html`
    <div class="card">
      <h3>Brains</h3>
      <div class="hint" style=${{ marginBottom: 12 }}>Two ways to run an agent. <b>External</b>: any MCP-capable agent — Codex, Claude Code, Gemini CLI — reads the playbooks and calls this factory's tools; nothing to configure here beyond registering the server once. <b>Built-in</b>: the factory calls a model itself for Plan, Build and Digest; pick a provider and model per agent below. Keys never go through this page — only the name of the variable in <code>.env</code>.</div>

      <div class="hint" style=${{ margin: "12px 0 6px", color: "var(--ink)" }}>External agents — register this factory once, then use the playbooks</div>
      ${external.map(([name, text]) => html`
        <div key=${name} class="row">
          <span class="hint" style=${{ width: 210 }}>${name}</span>
          <pre class="captured" style=${{ margin: 0, flex: 1, maxHeight: 90, overflow: "auto" }}>${text}</pre>
          <button class="small" onClick=${() => copy(name, text)}>${copied === name ? "Copied" : "Copy"}</button>
        </div>`)}

      <div class="hint" style=${{ margin: "18px 0 6px", color: "var(--ink)" }}>Built-in providers</div>
      <table>
        <thead><tr><th>id</th><th>kind</th><th>endpoint</th><th>key variable</th><th>sees images</th><th>JSON</th><th>models (comma-separated)</th><th></th></tr></thead>
        <tbody>
          ${providers.map((p, i) => html`
            <tr key=${i}>
              <td><input value=${p.id} onChange=${(e) => setP(i, "id", e.target.value)} style=${{ width: 100 }} /></td>
              <td><select value=${p.kind} onChange=${(e) => setP(i, "kind", e.target.value)}><option value="anthropic">anthropic</option><option value="openai">openai-compatible</option></select></td>
              <td><input value=${p.base_url || ""} disabled=${p.kind === "anthropic"} placeholder="http://localhost:11434/v1" onChange=${(e) => setP(i, "base_url", e.target.value)} style=${{ width: 250 }} /></td>
              <td><input value=${p.api_key_env || ""} placeholder="none (local)" onChange=${(e) => setP(i, "api_key_env", e.target.value)} style=${{ width: 150 }} />
                <div class="hint">${!p.api_key_env ? "no key needed" : p.key_present ? html`<span class="good">set in .env</span>` : html`<span class="bad">not set in .env</span>`}</div></td>
              <td><input type="checkbox" checked=${!!p.vision} onChange=${(e) => setP(i, "vision", e.target.checked)} /></td>
              <td><select value=${p.json_mode} onChange=${(e) => setP(i, "json_mode", e.target.value)}><option value="schema">schema</option><option value="object">object</option><option value="none">none</option></select></td>
              <td><input value=${(p.models || []).join(", ")} onChange=${(e) => setP(i, "models", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} style=${{ width: 220 }} /></td>
              <td style=${{ whiteSpace: "nowrap" }}>
                <button class="small" onClick=${() => test(p)} disabled=${tests[p.id]?.pending}>${tests[p.id]?.pending ? "Testing…" : "Test"}</button>
                <button class="small" onClick=${() => setProviders(providers.filter((_, j) => j !== i))}>Remove</button>
                ${tests[p.id] && !tests[p.id].pending ? html`<div class=${"hint " + (tests[p.id].ok ? "good" : "bad")}>${tests[p.id].ok ? `ok · ${tests[p.id].latency_ms} ms · "${tests[p.id].reply}"` : tests[p.id].error}</div>` : null}
              </td>
            </tr>`)}
        </tbody>
      </table>
      <div class="row">
        <select onChange=${addPreset} defaultValue="">
          <option value="">Add a provider…</option>
          ${b.presets.map((p) => html`<option key=${p.id} value=${p.id}>${p.id}${p.free ? " (local, free)" : ""}</option>`)}
          <option value="custom">custom endpoint</option>
        </select>
      </div>

      <div class="hint" style=${{ margin: "18px 0 6px", color: "var(--ink)" }}>Which model each built-in agent uses</div>
      <table>
        <thead><tr><th>agent</th><th>does</th><th>provider</th><th>model</th><th>ready?</th></tr></thead>
        <tbody>
          ${Object.keys(agents).map((a) => {
            const [pid, model] = [agents[a].split("/")[0], agents[a].split("/").slice(1).join("/")];
            const prov = providers.find((p) => p.id === pid);
            const r = ready[a] || {};
            const does = { idea: "picks what to make", metadata: "writes the title", qc: "judges four frames — needs a model that sees images", analyst: "reads the numbers, proposes rules" }[a];
            return html`
              <tr key=${a}>
                <td><b>${a}</b></td><td class="hint">${does}</td>
                <td><select value=${pid} onChange=${(e) => setAgents({ ...agents, [a]: `${e.target.value}/${model}` })}>
                  ${providers.map((p) => html`<option key=${p.id} value=${p.id} disabled=${b.needs_vision.includes(a) && !p.vision}>${p.id}${b.needs_vision.includes(a) && !p.vision ? " (no images)" : ""}</option>`)}</select></td>
                <td><input list=${`models-${pid}`} value=${model} onChange=${(e) => setAgents({ ...agents, [a]: `${pid}/${e.target.value}` })} style=${{ width: 220 }} />
                  <datalist id=${`models-${pid}`}>${(prov?.models || []).map((m) => html`<option key=${m} value=${m} />`)}</datalist></td>
                <td>${r.ok ? html`<span class="good">ready${r.free ? " · free" : ""}</span>` : html`<span class="bad">${r.why || "—"}</span>`}</td>
              </tr>`;
          })}
        </tbody>
      </table>
      <div class="row" style=${{ marginTop: 10 }}>
        <button class="ok" onClick=${save} disabled=${saving}>${saving ? "Saving…" : "Save brains"}</button>
        <span class="hint">${b.overridden ? "set on this page (config.toml is the default underneath)" : "from config.toml"}</span>
      </div>
    </div>`;
}

/* ---------- Themes: seasons, as data ---------- */

const hex = (rgb) => "#" + rgb.map((c) => Number(c).toString(16).padStart(2, "0")).join("");

const rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));

function Themes() {
  const [v, setV] = useState(null);
  const [list, setList] = useState([]);
  const [force, setForce] = useState("");
  const [saving, setSaving] = useState(false);
  const load = useCallback(() => api("/api/themes").then((b) => { setV(b); setList(b.themes); setForce(b.force); }), []);
  useEffect(() => { load().catch((err) => toast(err.message, "error")); }, [load]);
  if (!v) return null;
  const setT = (i, k, val) => setList((ts) => ts.map((t, j) => j === i ? { ...t, [k]: val } : t));
  const save = async () => {
    setSaving(true);
    try { const out = await send("/api/themes", { themes: list, force }, "PUT"); setV(out); setList(out.themes); setForce(out.force); }
    catch (err) { toast(err.message, "error"); }
    setSaving(false);
  };
  const add = () => setList([...list, { id: `theme${list.length + 1}`, name: "New theme", decoration: "none", window: ["01-01", "01-07"], enabled: true,
    palettes: [[[18, 18, 26], [58, 58, 74]]], marbles: [["red", [232, 76, 74]], ["blue", [55, 138, 221]], ["gold", [240, 200, 80]]], caption: [255, 255, 255] }]);
  return html`
    <div class="card">
      <h3>Themes</h3>
      <div class="hint" style=${{ marginBottom: 10 }}>A theme is colours, marble names, a caption colour and a decoration, with a window in the calendar. Today is ${v.today}; the active theme is <b>${v.active}</b>${force ? " (forced)" : " (by calendar)"}. Marble names end up in titles, so use words a viewer would say.</div>
      <div class="row"><span class="hint" style=${{ width: 140 }}>force a theme</span>
        <select value=${force} onChange=${(e) => setForce(e.target.value)}><option value="">— by calendar —</option>${list.map((t) => html`<option key=${t.id} value=${t.id}>${t.name}</option>`)}</select></div>
      <table>
        <thead><tr><th>on</th><th>id / name</th><th>window</th><th>decoration</th><th>backdrop → structure</th><th>marbles</th><th>caption</th><th></th></tr></thead>
        <tbody>${list.map((t, i) => html`
          <tr key=${i}>
            <td><input type="checkbox" checked=${t.enabled !== false} onChange=${(e) => setT(i, "enabled", e.target.checked)} /></td>
            <td><input value=${t.id} onChange=${(e) => setT(i, "id", e.target.value)} style=${{ width: 90 }} /><br /><input value=${t.name} onChange=${(e) => setT(i, "name", e.target.value)} style=${{ width: 120, marginTop: 4 }} /></td>
            <td>${t.id === "default" ? html`<span class="hint">always</span>` : html`<input value=${t.window ? t.window[0] : ""} placeholder="MM-DD" onChange=${(e) => setT(i, "window", [e.target.value, t.window ? t.window[1] : ""])} style=${{ width: 64 }} /> – <input value=${t.window ? t.window[1] : ""} placeholder="MM-DD" onChange=${(e) => setT(i, "window", [t.window ? t.window[0] : "", e.target.value])} style=${{ width: 64 }} />`}</td>
            <td><select value=${t.decoration} onChange=${(e) => setT(i, "decoration", e.target.value)}>${v.decorations.map((d) => html`<option key=${d} value=${d}>${d}</option>`)}</select></td>
            <td>${t.palettes.map((p, k) => html`<div key=${k} class="row" style=${{ margin: "2px 0" }}>
              <input type="color" value=${hex(p[0])} onChange=${(e) => setT(i, "palettes", t.palettes.map((q, m) => m === k ? [rgb(e.target.value), q[1]] : q))} />
              <input type="color" value=${hex(p[1])} onChange=${(e) => setT(i, "palettes", t.palettes.map((q, m) => m === k ? [q[0], rgb(e.target.value)] : q))} />
              ${t.palettes.length > 1 ? html`<button class="small" onClick=${() => setT(i, "palettes", t.palettes.filter((_, m) => m !== k))}>×</button>` : null}</div>`)}
              <button class="small" onClick=${() => setT(i, "palettes", [...t.palettes, [[18, 18, 26], [58, 58, 74]]])}>+ palette</button></td>
            <td>${t.marbles.map((m, k) => html`<div key=${k} class="row" style=${{ margin: "2px 0" }}>
              <input value=${m[0]} onChange=${(e) => setT(i, "marbles", t.marbles.map((q, n) => n === k ? [e.target.value, q[1]] : q))} style=${{ width: 70 }} />
              <input type="color" value=${hex(m[1])} onChange=${(e) => setT(i, "marbles", t.marbles.map((q, n) => n === k ? [q[0], rgb(e.target.value)] : q))} />
              ${t.marbles.length > 3 ? html`<button class="small" onClick=${() => setT(i, "marbles", t.marbles.filter((_, n) => n !== k))}>×</button>` : null}</div>`)}
              <button class="small" onClick=${() => setT(i, "marbles", [...t.marbles, ["new", [200, 200, 200]]])}>+ marble</button></td>
            <td><input type="color" value=${hex(t.caption)} onChange=${(e) => setT(i, "caption", rgb(e.target.value))} /></td>
            <td>${t.id !== "default" ? html`<button class="small" onClick=${() => setList(list.filter((_, j) => j !== i))}>Remove</button>` : null}</td>
          </tr>`)}</tbody>
      </table>
      <div class="row" style=${{ marginTop: 10 }}>
        <button class="ok" onClick=${save} disabled=${saving}>${saving ? "Saving…" : "Save themes"}</button>
        <button class="small" onClick=${add}>Add a theme</button>
        <span class="hint">${v.overridden ? "set on this page" : "shipped defaults"} · changes apply to the next render</span>
      </div>
    </div>`;
}

/* ---------- Docs: the hand-written pages, and a reference generated from the code ---------- */

function FactorySettings() {
  const [s, setS] = useState(null);
  const load = useCallback(() => api("/api/settings").then(setS), []);
  useEffect(() => { load().catch((err) => toast(err.message, "error")); }, [load]);
  if (!s) return null;
  const put = async (f, value) => {
    try { setS(await send("/api/settings", { section: f.section, key: f.key, value }, "PUT")); }
    catch (err) { toast(err.message, "error"); }
  };
  const reset = async (f) => {
    try { setS(await api(`/api/settings/${f.section}/${f.key}`, { method: "DELETE" })); }
    catch (err) { toast(err.message, "error"); }
  };
  const groups = [...new Set(s.fields.map((f) => f.section))];
  return html`
    <div class="card">
      <h3>Factory settings</h3>
      <div class="hint" style=${{ marginBottom: 12 }}>config.toml is the default. A value changed here is stored in the database as an override, marked, and can be reset. Changes apply to the next render or QC, not to clips already made.</div>
      ${groups.map((g) => html`
        <div key=${g} class="hint" style=${{ margin: "12px 0 4px", color: "var(--ink)", textTransform: "uppercase", fontSize: 11, letterSpacing: ".08em" }}>${g}</div>
        ${s.fields.filter((f) => f.section === g).map((f) => html`
          <div key=${f.key} class="row" style=${{ alignItems: "flex-start" }}>
            <div style=${{ width: 260 }}><div style=${{ fontSize: 13 }}>${f.label}</div>${f.help ? html`<div class="hint">${f.help}</div>` : null}</div>
            ${f.type === "select" ? html`<select value=${String(f.value)} onChange=${(e) => put(f, e.target.value)}>${f.options.map((o) => html`<option key=${o} value=${String(o)}>${o}</option>`)}</select>`
            : f.type === "number" ? html`<input type="number" defaultValue=${f.value} min=${f.min} max=${f.max} step=${f.step} onBlur=${(e) => { if (String(e.target.value) !== String(f.value)) put(f, e.target.value); }} style=${{ width: 120, flex: "none" }} />`
            : html`<input defaultValue=${f.value} onBlur=${(e) => { if (e.target.value !== f.value) put(f, e.target.value); }} style=${{ width: 260, flex: "none" }} />`}
            ${f.overridden ? html`<span class="hint">override · default ${String(f.default)} <button class="small" onClick=${() => reset(f)}>reset</button></span>` : html`<span class="hint">default</span>`}
          </div>`)}`)}
    </div>`;
}

function Rules({ rules: r, channelId, reload }) {
  const [text, setText] = useState(r.text);
  useEffect(() => setText(r.text), [r.text]);
  const save = async () => { try { await send("/api/rules", { channel: channelId, text }, "PUT"); await reload(); } catch (err) { toast(err.message, "error"); } };
  const accept = async (rule) => { try { await send("/api/rules/accept", { channel: channelId, rules: [rule] }); await reload(); } catch (err) { toast(err.message, "error"); } };
  return html`
    <div class="card">
      <h3>Rules the agents read</h3>
      <div class="hint" style=${{ marginBottom: 10 }}>${r.path} — the Idea and Metadata agents read this on every run. The Analyst proposes additions on the right; nothing lands without you accepting it.</div>
      <div style=${{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 320px", gap: 18 }}>
        <div><textarea value=${text} spellCheck="false" onChange=${(e) => setText(e.target.value)} /><div class="row"><button onClick=${save}>Save rules</button></div></div>
        <div>
          ${r.proposals.map((p) => html`<div key=${p} class="card"><div style=${{ fontSize: 13.5, lineHeight: 1.6, marginBottom: 10 }}>${p}</div><button class="ok small" onClick=${() => accept(p)}>Accept</button></div>`)}
          ${!r.proposals.length ? html`<div class="note">No pending proposals${r.digest ? ` (last digest: ${r.digest.n_published} clips with metrics)` : ""}. The Analyst writes nothing below the sample threshold.</div>` : null}
        </div>
      </div>
    </div>`;
}

function AddChannel({ onDone }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [handle, setHandle] = useState("");
  const create = async (e) => {
    e.preventDefault();
    try { await send("/api/channels", { name, handle: handle || null }); } catch (err) { toast(err.message, "error"); return; }
    setOpen(false); setName(""); setHandle(""); onDone();
  };
  if (!open) return html`<button class="small" onClick=${() => setOpen(true)}>Add another channel</button>`;
  return html`
    <div class="card"><h3>New channel</h3>
      <form class="grid" onSubmit=${create}>
        <label>name</label><input value=${name} onChange=${(e) => setName(e.target.value)} placeholder="HODL Tales" required />
        <label>handle</label><input value=${handle} onChange=${(e) => setHandle(e.target.value)} placeholder="@handle (optional)" />
        <span></span><div class="row"><button type="submit">Create</button><button type="button" onClick=${() => setOpen(false)}>Cancel</button></div>
      </form>
    </div>`;
}

export { Settings, Brains, Themes, FactorySettings, Rules, AddChannel };
