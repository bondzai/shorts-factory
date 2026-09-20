// The few pieces every screen is built from. A screen that needs a fourth
// kind of button is a screen that is doing too much.

import { html, useToasts } from "./lib.js";

export function Screen({ title, lead, children }) {
  return html`<h1>${title}</h1>${lead ? html`<p class="lead">${lead}</p>` : null}${children}`;
}

export function Card({ title, hint, children, accent = false }) {
  return html`<div class=${"card" + (accent ? " accent" : "")}>${title ? html`<h3>${title}</h3>` : null}${hint ? html`<div class="hint mb">${hint}</div>` : null}${children}</div>`;
}

export function Chip({ on, onClick, children, title }) {
  return html`<button class="small chip" aria-pressed=${!!on} onClick=${onClick} title=${title}>${children}</button>`;
}

export function Toasts() {
  const items = useToasts();
  if (!items.length) return null;
  return html`<div class="toasts">${items.map((t) => html`<div key=${t.id} class=${"toast " + t.kind}>${t.message}</div>`)}</div>`;
}

export function StepStrip({ steps, when }) {
  return html`
    <div class="steps">
      ${steps.map((s, i) => html`
        <span key=${s.name} class=${"step " + s.state} title=${s.at ? `${s.by || ""} · ${when(s.at)}` : ""}>
          <i></i>${s.name}${s.note ? html` <em>${s.note}</em>` : null}${s.state === "current" && s.by ? html` <em>← ${s.by}</em>` : null}
        </span>${i < steps.length - 1 ? html`<span class="step-line"></span>` : null}`)}
    </div>`;
}
