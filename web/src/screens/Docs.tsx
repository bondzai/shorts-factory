import { useEffect, useState } from "react";
import { marked } from "marked";
import { api } from "../lib/api";
import { toast } from "../lib/toast";

export function Docs({ page, setPage }: { page: string; setPage: (id: string) => void }) {
  const [pages, setPages] = useState<{ id: string; title: string; text: string }[] | null>(null);
  useEffect(() => { api<{ pages: typeof pages }>("/api/docs").then((b) => setPages(b.pages)).catch((e) => toast((e as Error).message, "error")); }, []);
  if (!pages) return <p className="empty">Loading…</p>;
  const current = pages.find((p) => p.id === page) || pages[0];
  return (
    <div className="docs">
      <div className="docnav">
        {pages.map((p) => <a key={p.id} href={`#/settings?tab=docs&page=${encodeURIComponent(p.id)}`} aria-current={p.id === current.id ? "page" : undefined} onClick={(e) => { e.preventDefault(); setPage(p.id); }}>{p.title}</a>)}
        <div className="hint mt-3">Pages live in <code>docs/*.md</code>; the Reference is generated from the code each time.</div>
      </div>
      <div className="prose" dangerouslySetInnerHTML={{ __html: marked.parse(current.text) as string }} />
    </div>
  );
}
