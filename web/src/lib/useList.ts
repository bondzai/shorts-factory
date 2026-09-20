// One hook for every paged list: reads filters from the URL, fetches by the
// contract, exposes page/sort/search setters. Screens never build URLs.
import { useEffect, useState } from "react";
import { api, Page, q } from "./api";
import { toast } from "./toast";
import type { Route } from "./route";

export interface ListState<T> { data: Page<T> | null; loading: boolean; reload: () => void }

export function useList<T>(
  path: string, route: Route, extra: Record<string, string | number | boolean | undefined>, deps: unknown[] = [],
): ListState<T> & Record<string, unknown> {
  const [data, setData] = useState<Page<T> | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const params = {
    q: route.params.get("q") || undefined,
    sort: route.params.get("sort") || undefined,
    dir: route.params.get("dir") || undefined,
    page: route.params.get("page") || 1,
    page_size: route.params.get("page_size") || 25,
    ...extra,
  };
  const key = JSON.stringify(params);
  useEffect(() => {
    let live = true;
    setLoading(true);
    api<Page<T>>(`${path}?${q(params)}`)
      .then((body) => { if (live) { setData(body); setLoading(false); } })
      .catch((err) => { if (live) { toast((err as Error).message, "error"); setLoading(false); } });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, key, tick, ...deps]);
  return { data, loading, reload: () => setTick((t) => t + 1) };
}
