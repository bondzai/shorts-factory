// An orb per team member. The hue comes from the name, so the same agent is
// the same colour on every visit; the state changes the light, not the colour:
// working swirls and breathes, ready glows, idle dims, away goes to grey.
export type OrbState = "working" | "ready" | "idle" | "away" | "needed" | "clear";

const hue = (name: string) => { let h = 0; for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h % 360; };

export function Orb({ name, state, label, size = 44, you }: { name: string; state: OrbState; label?: string; size?: number; you?: boolean }) {
  const h = you ? 36 : hue(name);
  const mode = state === "needed" ? "working" : state === "clear" ? "ready" : state;
  return (
    <span className={"orb " + mode} style={{ ["--h" as string]: h, width: size, height: size }} title={name}>
      <i className="swirl" /><i className="shine" />
      {label && <b>{label}</b>}
    </span>
  );
}
