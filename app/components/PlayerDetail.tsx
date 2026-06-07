"use client";

import { useEffect } from "react";
import { effectivePoints, fmt0, fmt1, isAdjusted, pct, tierColor } from "@/lib/format";
import { FACTOR_LABEL, FACTORS, NEUTRAL } from "@/lib/softsignals";
import type { Player } from "@/lib/types";
import { PositionBadge, RookieTag, Sparkline, ValueChip } from "./ui";

function Stat({ label, value, accent }: { label: string; value: React.ReactNode; accent?: string }) {
  return (
    <div className="rounded-xl bg-surface-2 px-3 py-2.5">
      <div className="tabular text-lg font-bold leading-tight" style={{ color: accent ?? "#F2F5F0" }}>
        {value}
      </div>
      <div className="mt-0.5 text-[11px] font-medium uppercase tracking-wide text-ink-faint">{label}</div>
    </div>
  );
}

function Bar({ label, value }: { label: string; value: number | null }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-ink-muted">{label}</span>
        <span className="tabular font-medium text-ink">{pct(value)}</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
        <div
          className="h-full rounded-full bg-lime transition-all"
          style={{ width: `${Math.min(100, Math.round((value ?? 0) * 100))}%` }}
        />
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-ink-faint">{title}</h3>
      {children}
    </div>
  );
}

export function PlayerDetail({ player, onClose }: { player: Player | null; onClose: () => void }) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    if (player) {
      document.addEventListener("keydown", onKey);
      document.body.style.overflow = "hidden";
    }
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [player, onClose]);

  if (!player) return null;
  const proj = player.projection;
  const rs = player.raw_stats;
  const sit = player.situation;
  const mk = player.market;
  const softFactors = sit?.soft_factors
    ? FACTORS.filter((f) => sit.soft_factors![f] != null && sit.soft_factors![f] !== NEUTRAL).map(
        (f) => [f, sit.soft_factors![f]] as const,
      )
    : [];
  const tc = tierColor(proj.tier);
  const adjMult =
    proj.adjusted_points != null && proj.base_points
      ? proj.adjusted_points / proj.base_points
      : null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 backdrop-blur-sm sm:items-center"
      onClick={onClose}
    >
      <div
        className="animate-fade-up max-h-[92vh] w-full overflow-y-auto rounded-t-3xl bg-surface p-5 shadow-card sm:max-w-lg sm:rounded-3xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* grab handle (mobile) */}
        <div className="mx-auto mb-4 h-1 w-10 rounded-full bg-white/15 sm:hidden" />

        {/* header */}
        <div className="flex items-start gap-3">
          <PositionBadge pos={player.position} size={52} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="truncate text-xl font-bold text-ink">{player.name}</h2>
              {player.is_rookie && <RookieTag />}
            </div>
            <div className="mt-0.5 text-sm text-ink-muted">
              <span style={{ color: tc }} className="font-semibold">
                {player.position}
                {proj.position_rank}
              </span>
              {" · "}
              {player.team || "FA"}
              {player.age != null && ` · ${Math.round(player.age)} yo`}
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-full bg-surface-2 px-2.5 py-1 text-sm text-ink-muted hover:bg-surface-3"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* headline stats */}
        <div className="mt-4 grid grid-cols-4 gap-2">
          <Stat label="Proj" value={fmt1(effectivePoints(player))} accent="#C5F23D" />
          <Stat label="VORP" value={fmt0(proj.vorp)} />
          <Stat label="Overall" value={proj.overall_rank ? `#${proj.overall_rank}` : "—"} />
          <Stat label="Tier" value={proj.tier ?? "—"} accent={tc} />
        </div>

        <div className="mt-5 space-y-5">
          {/* projection breakdown */}
          <Section title="Projection">
            <div className="flex items-center justify-between rounded-xl bg-surface-2 px-3 py-3">
              <div>
                <div className="text-xs text-ink-faint">Base (stats)</div>
                <div className="tabular text-base font-semibold text-ink">{fmt1(proj.base_points)}</div>
              </div>
              <div className="text-ink-faint">→</div>
              <div className="text-right">
                <div className="text-xs text-ink-faint">
                  Adjusted{adjMult != null ? ` ×${adjMult.toFixed(3)}` : ""}
                </div>
                <div className="tabular text-base font-semibold" style={{ color: isAdjusted(player) ? "#C5F23D" : "#646E66" }}>
                  {proj.adjusted_points != null ? fmt1(proj.adjusted_points) : "no change"}
                </div>
              </div>
            </div>
          </Section>

          {/* recent production */}
          <Section title="Recent production">
            <div className="flex items-center justify-between rounded-xl bg-surface-2 px-3 py-3">
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                {rs.prior_seasons_points.map((v, i) => (
                  <span key={i} className="tabular text-ink">
                    {v.toFixed(0)}
                    <span className="ml-1 text-[10px] text-ink-faint">
                      {i === rs.prior_seasons_points.length - 1 ? "last" : `-${rs.prior_seasons_points.length - 1 - i}`}
                    </span>
                  </span>
                ))}
                {rs.prior_seasons_points.length === 0 && (
                  <span className="text-sm text-ink-faint">rookie — no NFL history</span>
                )}
              </div>
              <Sparkline values={rs.prior_seasons_points} />
            </div>
          </Section>

          {/* usage */}
          {(rs.snap_share != null || rs.target_share != null) && (
            <Section title="Usage (last season)">
              <div className="space-y-3 rounded-xl bg-surface-2 px-3 py-3">
                <Bar label="Snap share" value={rs.snap_share} />
                <Bar label="Target share" value={rs.target_share} />
              </div>
            </Section>
          )}

          {/* situation */}
          {sit && (softFactors.length > 0 || sit.vegas_team_total != null || sit.soft_score != null) && (
            <Section title="Situation">
              <div className="space-y-2 rounded-xl bg-surface-2 px-3 py-3 text-sm">
                {softFactors.map(([f, v]) => (
                  <Row key={f} k={FACTOR_LABEL[f]} v={`${v} / 5`} accent={v > NEUTRAL ? "#8FE06A" : "#FF7E6B"} />
                ))}
                <Row k="Vegas team total" v={sit.vegas_team_total != null ? sit.vegas_team_total.toFixed(1) : "n/a (offseason)"} />
                {sit.soft_score != null && <Row k="Soft score" v={`×${sit.soft_score}`} accent="#C5F23D" />}
                {sit.soft_reasoning && (
                  <p className="border-t border-line pt-2 text-xs leading-relaxed text-ink-muted">{sit.soft_reasoning}</p>
                )}
              </div>
            </Section>
          )}

          {/* market */}
          <Section title="Market (ADP)">
            <div className="grid grid-cols-3 gap-2">
              <Stat label="ADP" value={mk?.adp != null ? mk.adp.toFixed(1) : "—"} />
              <Stat label="ADP rank" value={mk?.adp_rank != null ? `#${mk.adp_rank}` : "—"} />
              <div className="rounded-xl bg-surface-2 px-3 py-2.5">
                <ValueChip value={mk?.value_vs_adp} />
                <div className="mt-1 text-[11px] font-medium uppercase tracking-wide text-ink-faint">Value vs ADP</div>
              </div>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}

function Row({ k, v, accent }: { k: string; v: string; accent?: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-ink-muted">{k}</span>
      <span className="tabular font-medium" style={{ color: accent ?? "#F2F5F0" }}>
        {v}
      </span>
    </div>
  );
}
