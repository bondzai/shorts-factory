// Shared by every screen: the fetch wrapper, formatters, and the three
// things a screen does over and over — run an action and show what happened,
// copy text, download a clip. No screen talks to fetch() or alert() itself.

import React, { useState, useEffect, useRef, useCallback } from "https://esm.sh/react@18.3.1";
import htm from "https://esm.sh/htm@3.1.1";

export { React, useState, useEffect, useRef, useCallback };
export const html = htm.bind(React.createElement);

export async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || res.statusText);
  }
  return res.json();
}
export const send = (path, body, method = "POST") => api(path, {
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}),
});
export const fmt = (n, d = 1) => (n === null || n === undefined) ? "—" : Number(n).toFixed(d);
export const num = (n) => (n === null || n === undefined) ? "—" : Number(n).toLocaleString();
export const pct = (n) => (n === null || n === undefined) ? "—" : `${Number(n).toFixed(0)}%`;
export const when = (iso) => iso ? iso.slice(0, 16).replace("T", " ") : "—";
export const clock = (iso) => iso ? iso.slice(11, 19) : "";
export const statusWord = (s) => (s || "").replace(/_/g, " ");
export const channelQuery = (channelId) => `channel=${encodeURIComponent(channelId)}`;

// --- toasts: what happened, without a modal in the way ---------------------
const listeners = new Set();
export function toast(message, kind = "info") {
  const item = { id: Date.now() + Math.random(), message: String(message), kind };
  listeners.forEach((fn) => fn(item));
}
export function useToasts() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    const add = (item) => {
      setItems((list) => [...list, item]);
      setTimeout(() => setItems((list) => list.filter((t) => t.id !== item.id)), item.kind === "error" ? 6000 : 2500);
    };
    listeners.add(add);
    return () => listeners.delete(add);
  }, []);
  return items;
}

// --- run an action: report failure as a toast, then refresh -----------------
export async function act(fn, { after, ok } = {}) {
  try {
    const result = await fn();
    if (ok) toast(ok);
    if (after) await after();
    return result;
  } catch (err) {
    toast(err.message, "error");
    return undefined;
  }
}

export function useCopy() {
  const [copied, setCopied] = useState(false);
  const copy = useCallback(async (text) => {
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); }
    catch { toast("Could not reach the clipboard — select the text and copy it.", "error"); }
  }, []);
  return [copied, copy];
}

export const download = (clipId) => { window.location.href = `/api/clip/${clipId}/video?download=1`; };
