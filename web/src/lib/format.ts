export const fmt = (n: number | null | undefined, d = 1) => n == null ? "—" : Number(n).toFixed(d);
export const num = (n: number | null | undefined) => n == null ? "—" : Number(n).toLocaleString();
export const pct = (n: number | null | undefined) => n == null ? "—" : `${Number(n).toFixed(0)}%`;
export const when = (iso?: string | null) => iso ? iso.slice(0, 16).replace("T", " ") : "—";
export const clock = (iso?: string | null) => iso ? iso.slice(11, 19) : "";
export const statusWord = (s?: string | null) => (s || "").replace(/_/g, " ");
export const hex = (rgb: number[]) => "#" + rgb.map((c) => Number(c).toString(16).padStart(2, "0")).join("");
export const rgb = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
export const download = (clipId: string) => { window.location.href = `/api/clip/${clipId}/video?download=1`; };
