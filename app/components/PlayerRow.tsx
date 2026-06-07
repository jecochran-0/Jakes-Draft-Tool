"use client";

import { ageLabel, effectivePoints, fmt0, fmt1, isAdjusted, tierColor } from "@/lib/format";
import type { Player } from "@/lib/types";
import { PositionBadge, RookieTag, TeamTag, ValueChip } from "./ui";

export function PlayerRow({
  player,
  rankMode,
  onClick,
}: {
  player: Player;
  rankMode: "overall" | "position";
  onClick: () => void;
}) {
  const proj = player.projection;
  const rank = rankMode === "overall" ? proj.overall_rank : proj.position_rank;
  const tc = tierColor(proj.tier);
  const adp = player.market?.adp;

  return (
    <button
      onClick={onClick}
      className="group flex w-full items-center gap-3 rounded-2xl bg-surface px-3 py-2.5 text-left shadow-card transition-colors hover:bg-surface-2"
    >
      {/* rank + tier accent */}
      <div className="flex w-9 shrink-0 items-center gap-2">
        <span className="h-8 w-[3px] rounded-full" style={{ background: tc }} />
        <span className="tabular text-[15px] font-semibold text-ink-muted">{rank ?? "—"}</span>
      </div>

      <PositionBadge pos={player.position} />

      {/* name + meta */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-[15px] font-semibold text-ink">{player.name}</span>
          {player.is_rookie && <RookieTag />}
        </div>
        <div className="mt-0.5 flex items-center gap-1.5 whitespace-nowrap text-xs text-ink-muted">
          <span style={{ color: tierColor(proj.tier) }} className="font-semibold">
            {player.position}
            {proj.position_rank ?? ""}
          </span>
          <span className="text-ink-faint">·</span>
          <TeamTag team={player.team} />
          <span className="text-ink-faint">·</span>
          <span className="text-ink-faint">{ageLabel(player.age)}</span>
        </div>
      </div>

      {/* adp rail (desktop) */}
      <div className="hidden w-11 shrink-0 flex-col items-end sm:flex">
        <span className="tabular text-sm font-medium text-ink">{adp != null ? adp.toFixed(1) : "—"}</span>
        <span className="text-[10px] text-ink-faint">ADP</span>
      </div>

      {/* projection + value */}
      <div className="flex w-[68px] shrink-0 flex-col items-end">
        <div className="flex items-baseline gap-1">
          <span className="tabular text-[19px] font-bold leading-none text-lime">
            {fmt1(effectivePoints(player))}
          </span>
          {isAdjusted(player) && <span className="text-lime" style={{ fontSize: 9 }}>★</span>}
        </div>
        <div className="mt-1.5 flex items-center gap-1.5">
          {proj.vorp != null && (
            <span className="tabular text-[11px] text-ink-faint">{fmt0(proj.vorp)}</span>
          )}
          <ValueChip value={player.market?.value_vs_adp} />
        </div>
      </div>
    </button>
  );
}
