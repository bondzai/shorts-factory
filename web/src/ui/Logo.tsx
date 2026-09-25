// The mark: a marble crossing a chequered line. Inline so it takes the theme's ink.
export function Logo({ size = 22 }: { size?: number }) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} aria-hidden="true" style={{ flexShrink: 0 }}>
      <rect width="64" height="64" rx="14" fill="var(--panel2)" />
      <g fill="var(--ink)" opacity=".9">
        <rect x="10" y="44" width="6" height="6" /><rect x="22" y="44" width="6" height="6" /><rect x="34" y="44" width="6" height="6" /><rect x="46" y="44" width="6" height="6" />
        <rect x="16" y="50" width="6" height="6" /><rect x="28" y="50" width="6" height="6" /><rect x="40" y="50" width="6" height="6" />
      </g>
      <path d="M10 14 L50 14 L14 30 L54 30" fill="none" stroke="var(--faint)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="40" cy="30" r="9" fill="var(--brand)" />
      <circle cx="37" cy="27" r="3" fill="#fff4d6" />
    </svg>
  );
}
