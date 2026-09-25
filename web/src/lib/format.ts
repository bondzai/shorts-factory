export const fmt = (n: number | null | undefined, d = 1) => n == null ? "—" : Number(n).toFixed(d);
export const num = (n: number | null | undefined) => n == null ? "—" : Number(n).toLocaleString();
export const pct = (n: number | null | undefined) => n == null ? "—" : `${Number(n).toFixed(0)}%`;
export const when = (iso?: string | null) => iso ? iso.slice(0, 16).replace("T", " ") : "—";
export const clock = (iso?: string | null) => iso ? iso.slice(11, 19) : "";
export const statusWord = (s?: string | null) => (s || "").replace(/_/g, " ");
export const hex = (rgb: number[]) => "#" + rgb.map((c) => Number(c).toString(16).padStart(2, "0")).join("");
export const rgb = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
export const download = (clipId: string) => { window.location.href = `/api/clip/${clipId}/video?download=1`; };

/* Plain words for the machinery's states: what the operator sees, never the
   column value. One map per kind of thing, so every screen says the same. */
type Tone = "ok" | "no" | "key" | undefined;
const CLIP: Record<string, [string, Tone]> = {
  planned: ["Queued", undefined], rendered: ["Being made", "key"], described: ["Being made", "key"],
  awaiting_qc: ["Waiting for QC", "key"], awaiting_approval: ["Needs review", "key"],
  approved: ["Ready to publish", "ok"], published: ["Published", "ok"],
  qc_rejected: ["Rejected by QC", "no"], rejected: ["Rejected", "no"], failed: ["Failed", "no"],
};
const PHASE: Record<string, [string, Tone]> = {
  queued: ["Queued", undefined], rendering: ["Being made", "key"], awaiting_qc: ["Waiting for QC", "key"],
  to_review: ["Needs review", "key"], approved: ["Ready to publish", "ok"], published: ["Published", "ok"],
  rejected: ["Rejected", "no"], failed: ["Failed", "no"], cancelled: ["Cancelled", undefined], done: ["Done", undefined],
  binned: ["In the bin", undefined],
};
const LEVEL: Record<string, [string, Tone]> = {
  ready: ["Ready", "ok"], blocked: ["Blocked", undefined], needs_input: ["Needs your input", "key"],
  planned: ["Planned", "key"], rendered: ["Made", "ok"], failed: ["Failed", "no"],
};
const look = (map: Record<string, [string, Tone]>, s?: string | null): [string, Tone] => {
  const key = (s || "").replace(/ \(binned\)$/, "");
  const hit = map[key];
  const word = hit ? hit[0] : statusWord(key);
  return [key !== s ? `${word} (in the bin)` : word, hit?.[1]];
};
export const clipWord = (s?: string | null) => look(CLIP, s)[0];
export const clipTone = (s?: string | null) => look(CLIP, s)[1];
export const phaseWord = (s?: string | null) => look(PHASE, s)[0];
export const phaseTone = (s?: string | null) => look(PHASE, s)[1];
export const levelWord = (s?: string | null) => look(LEVEL, s)[0];
export const levelTone = (s?: string | null) => look(LEVEL, s)[1];
export const PHASE_ORDER = ["to_review", "awaiting_qc", "approved", "queued", "rendering", "published", "rejected", "failed", "cancelled", "done"];
export const plural = (n: number, one: string, many = one + "s") => `${n} ${n === 1 ? one : many}`;
