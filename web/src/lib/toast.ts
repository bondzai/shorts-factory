import { useEffect, useState } from "react";

export interface Toast { id: number; message: string; kind: "info" | "error" }
const listeners = new Set<(t: Toast) => void>();

export function toast(message: string, kind: Toast["kind"] = "info") {
  const item = { id: Date.now() + Math.random(), message, kind };
  listeners.forEach((fn) => fn(item));
}

export function useToasts() {
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(() => {
    const add = (t: Toast) => {
      setItems((list) => [...list, t]);
      setTimeout(() => setItems((list) => list.filter((x) => x.id !== t.id)), t.kind === "error" ? 6000 : 2500);
    };
    listeners.add(add);
    return () => { listeners.delete(add); };
  }, []);
  return items;
}

/** Run an action; failures become a toast, never a modal. */
export async function act<T>(fn: () => Promise<T>, opts: { ok?: string; after?: () => unknown } = {}): Promise<T | undefined> {
  try {
    const result = await fn();
    if (opts.ok) toast(opts.ok);
    if (opts.after) await opts.after();
    return result;
  } catch (err) {
    toast((err as Error).message, "error");
    return undefined;
  }
}
