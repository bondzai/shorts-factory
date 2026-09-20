import { useEffect, useState } from "react";
import { marked } from "marked";
import { api } from "../lib/api";
import { toast } from "../lib/toast";
import { Page } from "../ui";

export function Docs({ page, setPage }: { page: string; setPage: (id: string) => void }) {
  const [pages, setPages] = useState<{ id: string; title: string; text: string }[] | null>(null);
  useEffect(() => { api<{ pages: typeof pages }>("/api/docs").then((b) => setPages(b.pages)).catch((e) => toast((e as Error).message, "error")); }, []);
  if (!pages) return <Page title="Docs"><p className="empty">loading…</p></Page>;
  const current = pages.find((p) => p.id === page) || pages[0];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "200px minmax(0,1fr)", gap: "var(--s5)" }}>
      <div className="docnav">
        {pages.map((p) => <a key={p.id} aria-current={p.id === current.id ? "page" : undefined} onClick={() => setPage(p.id)}>{p.title}</a>)}
        <div className="hint mt-3">Pages live in <code>docs/*.md</code>; the Reference is generated from the code each time.</div>
      </div>
      <div className="prose" dangerouslySetInnerHTML={{ __html: marked.parse(current.text) as string }} />
    </div>
  );
}
