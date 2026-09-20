// The address bar is the state: #/clips?status=published&page=2. Refresh, back
// and a shared link all land on the same view with the same filters.
import { useCallback, useEffect, useState } from "react";

export interface Route { view: string; params: URLSearchParams }

function parse(): Route {
  const hash = window.location.hash.replace(/^#\/?/, "");
  const [view, query = ""] = hash.split("?");
  return { view: view || "today", params: new URLSearchParams(query) };
}

export function useRoute() {
  const [route, setRoute] = useState<Route>(parse);
  useEffect(() => {
    const onChange = () => setRoute(parse());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const navigate = useCallback((view: string, params?: Record<string, string | number | undefined>) => {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(params || {})) if (v !== undefined && v !== "" && v !== null) sp.set(k, String(v));
    const query = sp.toString();
    window.location.hash = `#/${view}${query ? "?" + query : ""}`;
  }, []);
  return { route, navigate };
}

/** Read and write one view's query parameters, keeping the rest. */
export function useQuery(route: Route, navigate: ReturnType<typeof useRoute>["navigate"]) {
  const get = (key: string, fallback = "") => route.params.get(key) ?? fallback;
  const set = (patch: Record<string, string | number | undefined>) => {
    const next: Record<string, string> = {};
    route.params.forEach((v, k) => { next[k] = v; });
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined || v === "" || v === null) delete next[k]; else next[k] = String(v);
    }
    navigate(route.view, next);
  };
  return { get, set };
}
