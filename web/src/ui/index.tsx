// The pieces every screen is built from. A screen that needs another one
// is a screen that is doing too much.
import { ReactNode, useEffect, useRef, useState } from "react";
import { useToasts } from "../lib/toast";
import { when } from "../lib/format";
import type { Step } from "../lib/types";

/* Page: title row, optional lead, then whatever the screen is. */
export function Page({ title, lead, action, children }: { title: ReactNode; lead?: ReactNode; action?: ReactNode; children?: ReactNode }) {
  return (
    <>
      <div className="page-title"><h1>{title}</h1>{action && <div className="right">{action}</div>}</div>
      {lead && <p className="page-lead">{lead}</p>}
      {children}
    </>
  );
}

/* Toolbar: search, filters, sort, count — in that order, always. */
export function Toolbar({ total, children }: { total?: number | null; children?: ReactNode }) {
  return <div className="toolbar">{children}{total != null && <span className="total">{total.toLocaleString()} result{total === 1 ? "" : "s"}</span>}</div>;
}

export function SearchBox({ value, onChange, placeholder = "search" }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  const [text, setText] = useState(value);
  const timer = useRef<number>();
  useEffect(() => setText(value), [value]);
  return (
    <input type="search" className="w-md" placeholder={placeholder} value={text}
      onChange={(e) => { setText(e.target.value); window.clearTimeout(timer.current); timer.current = window.setTimeout(() => onChange(e.target.value), 300); }} />
  );
}

export function Chips({ options, value, onChange, all = "all" }: { options: { value: string; label?: string }[]; value: string; onChange: (v: string) => void; all?: string | null }) {
  return (
    <div className="row wrap">
      {all !== null && <button className="sm chip" aria-pressed={!value} onClick={() => onChange("")}>{all}</button>}
      {options.map((o) => <button key={o.value} className="sm chip" aria-pressed={value === o.value} onClick={() => onChange(value === o.value ? "" : o.value)}>{o.label ?? o.value}</button>)}
    </div>
  );
}

export interface Column<T> { key: string; label: ReactNode; sortable?: boolean; render: (row: T) => ReactNode; width?: string; align?: "right" }
export function DataTable<T extends { id: string | number }>({ columns, rows, sort, dir, onSort, onRow, empty = "Nothing matches.", loading, selectable, selected, onSelect, onSelectAll }: {
  columns: Column<T>[]; rows: T[]; sort?: string; dir?: string; onSort?: (key: string) => void; onRow?: (row: T) => void;
  empty?: ReactNode; loading?: boolean; selectable?: boolean; selected?: Set<string | number>; onSelect?: (id: string | number) => void; onSelectAll?: () => void;
}) {
  return (
    <table className="data">
      <thead><tr>
        {selectable && <th style={{ width: 28 }}><input type="checkbox" checked={rows.length > 0 && rows.every((r) => selected?.has(r.id))} onChange={onSelectAll} title="select all on this page" /></th>}
        {columns.map((c) => (
          <th key={c.key} className={c.sortable ? "sortable" : undefined} style={{ width: c.width, textAlign: c.align }} onClick={c.sortable && onSort ? () => onSort(c.key) : undefined}>
            {c.label}{sort === c.key ? (dir === "asc" ? " ↑" : " ↓") : ""}
          </th>
        ))}
      </tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id} className={onRow ? "clickable" : undefined} onClick={onRow ? (e) => { if (!(e.target as HTMLElement).closest("button, input, a, select")) onRow(r); } : undefined}>
            {selectable && <td><input type="checkbox" checked={!!selected?.has(r.id)} onChange={() => onSelect?.(r.id)} /></td>}
            {columns.map((c) => <td key={c.key} style={{ textAlign: c.align }}>{c.render(r)}</td>)}
          </tr>
        ))}
        {!rows.length && <tr><td colSpan={columns.length + (selectable ? 1 : 0)} className="empty">{loading ? "loading…" : empty}</td></tr>}
      </tbody>
    </table>
  );
}

export function Pagination({ page, pageSize, total, onPage, onPageSize }: { page: number; pageSize: number; total: number; onPage: (p: number) => void; onPageSize: (s: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const window_ = [...new Set([1, page - 1, page, page + 1, pages].filter((p) => p >= 1 && p <= pages))].sort((a, b) => a - b);
  return (
    <div className="pagination">
      <button className="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>‹</button>
      <div className="pages">
        {window_.map((p, i) => (
          <span key={p} className="row">
            {i > 0 && window_[i - 1] !== p - 1 && <span className="faint">…</span>}
            <button className="sm chip" aria-pressed={p === page} onClick={() => onPage(p)}>{p}</button>
          </span>
        ))}
      </div>
      <button className="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>›</button>
      <span>{total === 0 ? "0" : `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)}`} of {total.toLocaleString()}</span>
      <select className="sm right" value={pageSize} onChange={(e) => onPageSize(Number(e.target.value))}>
        {[25, 50, 100].map((s) => <option key={s} value={s}>{s} / page</option>)}
      </select>
    </div>
  );
}

export function Card({ title, hint, accent, children, right }: { title?: ReactNode; hint?: ReactNode; accent?: boolean; children?: ReactNode; right?: ReactNode }) {
  return (
    <div className={"card" + (accent ? " accent" : "")}>
      {(title || right) && <div className="row"><h3>{title}</h3>{right && <span className="right">{right}</span>}</div>}
      {hint && <div className="hint">{hint}</div>}
      {children}
    </div>
  );
}

export function Drawer({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return <><div className="scrim" onClick={onClose} /><div className="drawer" role="dialog">{children}</div></>;
}

/* Modal: a centred dialog for one short form. A list screen stays a list;
   the thing that creates a row opens here and closes when it is done. */
export function Modal({ title, onClose, children }: { title: ReactNode; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="modal" role="dialog" aria-modal="true">
        <div className="row mb-3"><h2>{title}</h2><button className="sm ghost right" onClick={onClose} aria-label="close">✕</button></div>
        {children}
      </div>
    </>
  );
}

export function Field({ label, help, children }: { label: ReactNode; help?: ReactNode; children: ReactNode }) {
  return <><label>{label}</label><div className="field">{children}{help && <span className="help">{help}</span>}</div></>;
}

export function Toasts() {
  const items = useToasts();
  if (!items.length) return null;
  return <div className="toasts">{items.map((t) => <div key={t.id} className={"toast " + t.kind}>{t.message}</div>)}</div>;
}

export function StepStrip({ steps }: { steps: Step[] }) {
  return (
    <div className="steps">
      {steps.map((s, i) => (
        <span key={s.name} className="row" style={{ gap: 4 }}>
          <span className={"step " + s.state} title={s.at ? `${s.by || ""} · ${when(s.at)}` : ""}>
            <i />{s.name}{s.note && <em> {s.note}</em>}{s.state === "current" && s.by && <em> ← {s.by}</em>}
          </span>
          {i < steps.length - 1 && <span className="step-line" />}
        </span>
      ))}
    </div>
  );
}

export const Badge = ({ tone, children }: { tone?: "ok" | "no" | "key"; children: ReactNode }) => <span className={"badge" + (tone ? " " + tone : "")}>{children}</span>;
