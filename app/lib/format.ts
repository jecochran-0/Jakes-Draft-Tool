import type { Player, Position } from "./types";

export const POSITIONS: Position[] = ["QB", "RB", "WR", "TE"];

export const POSITION_COLOR: Record<Position, string> = {
  QB: "#F5A623",
  RB: "#8FE06A",
  WR: "#4FA8FF",
  TE: "#C77DFF",
};

// Tier accent ramp (tier 1 = brightest lime, descending through teal/blue/violet).
const TIER_RAMP = [
  "#C5F23D", "#9FE36B", "#6FD09A", "#4FB8C9",
  "#4F9BE6", "#6E86E8", "#9A7CE6", "#C56FCB",
];

export function tierColor(tier: number | null | undefined): string {
  if (!tier || tier < 1) return "#646E66";
  return TIER_RAMP[Math.min(tier - 1, TIER_RAMP.length - 1)];
}

// The points the board ranks on: adjusted if the pipeline set it, else base.
export function effectivePoints(p: Player): number {
  const adj = p.projection.adjusted_points;
  return adj != null ? adj : p.projection.base_points;
}

export function isAdjusted(p: Player): boolean {
  return p.projection.adjusted_points != null;
}

export function fmt1(n: number | null | undefined): string {
  return n == null ? "—" : n.toFixed(1);
}

export function fmt0(n: number | null | undefined): string {
  return n == null ? "—" : Math.round(n).toString();
}

export function pct(n: number | null | undefined): string {
  return n == null ? "—" : `${Math.round(n * 100)}%`;
}

export type ValueTone = "steal" | "reach" | "neutral";

export function valueTone(v: number | null | undefined): ValueTone {
  if (v == null) return "neutral";
  if (v >= 5) return "steal";
  if (v <= -5) return "reach";
  return "neutral";
}

export function teamLogoText(team: string): string {
  return team || "FA";
}

export function ageLabel(age: number | null): string {
  return age == null ? "" : `${Math.round(age)} yo`;
}
