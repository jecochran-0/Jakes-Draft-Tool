import { POSITION_COLOR, valueTone } from "@/lib/format";
import type { Position } from "@/lib/types";

export function PositionBadge({ pos, size = 38 }: { pos: Position; size?: number }) {
  const c = POSITION_COLOR[pos];
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-xl font-semibold tabular"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.34,
        color: c,
        background: `${c}1f`,
        boxShadow: `inset 0 0 0 1px ${c}33`,
      }}
    >
      {pos}
    </span>
  );
}

export function TeamTag({ team }: { team: string }) {
  return (
    <span className="rounded-md bg-white/[0.04] px-1.5 py-0.5 text-[11px] font-medium tracking-wide text-ink-muted">
      {team || "FA"}
    </span>
  );
}

export function RookieTag() {
  return (
    <span className="rounded-md bg-lime-soft px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-lime">
      Rookie
    </span>
  );
}

export function ValueChip({ value }: { value: number | null | undefined }) {
  const tone = valueTone(value);
  if (value == null) return <span className="text-xs text-ink-faint">no ADP</span>;
  const up = value > 0;
  const color = tone === "steal" ? "#8FE06A" : tone === "reach" ? "#FF7E6B" : "#929C93";
  return (
    <span
      className="inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-xs font-semibold tabular"
      style={{ color, background: `${color}1a` }}
    >
      <span aria-hidden style={{ fontSize: 9 }}>{up ? "▲" : value < 0 ? "▼" : "•"}</span>
      {up ? `+${value}` : value}
    </span>
  );
}

export function Pill({
  active,
  onClick,
  children,
  accent,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  accent?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={
        "whitespace-nowrap rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors " +
        (active
          ? "text-base"
          : "bg-surface-2 text-ink-muted hover:bg-surface-3 hover:text-ink")
      }
      style={active ? { background: accent ?? "#C5F23D", color: "#10160F" } : undefined}
    >
      {children}
    </button>
  );
}

/** Tiny prior-seasons trend line. */
export function Sparkline({ values, width = 96, height = 30 }: { values: number[]; width?: number; height?: number }) {
  if (!values || values.length < 2) {
    return <div className="text-xs text-ink-faint">not enough history</div>;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pad = 3;
  const pts = values.map((v, i) => {
    const x = pad + (i / (values.length - 1)) * (width - pad * 2);
    const y = pad + (1 - (v - min) / span) * (height - pad * 2);
    return [x, y] as const;
  });
  const d = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  const rising = values[values.length - 1] >= values[0];
  const stroke = rising ? "#C5F23D" : "#FF7E6B";
  return (
    <svg width={width} height={height} className="overflow-visible">
      <path d={d} fill="none" stroke={stroke} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={last[0]} cy={last[1]} r={3} fill={stroke} />
    </svg>
  );
}
