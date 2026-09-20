import { html, useState, useEffect, useRef, useCallback, api, send, fmt, num, pct, when, clock, statusWord, channelQuery, toast, act, useCopy, download } from "../lib.js";
import { Screen, Card, Chip, StepStrip } from "../ui.js";
import { marked } from "https://esm.sh/marked@12";

function Docs() {
  const [pages, setPages] = useState(null);
  const [current, setCurrent] = useState(null);
  useEffect(() => { api("/api/docs").then((b) => { setPages(b.pages); setCurrent(b.pages[0]?.id); }).catch((err) => toast(err.message, "error")); }, []);
  if (!pages) return html`<p class="empty">loading…</p>`;
  const page = pages.find((p) => p.id === current) || pages[0];
  return html`
    <div style=${{ display: "grid", gridTemplateColumns: "200px minmax(0,1fr)", gap: 24 }}>
      <div>
        ${pages.map((p) => html`<a key=${p.id} class="docnav" aria-current=${p.id === page.id} onClick=${() => setCurrent(p.id)}>${p.title}</a>`)}
        <div class="hint" style=${{ marginTop: 14 }}>Pages live in <code>docs/*.md</code>; the Reference is generated from the code each time.</div>
      </div>
      <div class="prose" dangerouslySetInnerHTML=${{ __html: marked.parse(page.text) }}></div>
    </div>`;
}

/* ---------- FactorySettings: every knob, rendered from the schema ---------- */

export { Docs };
