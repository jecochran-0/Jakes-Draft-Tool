"use client";

import { useEffect, useMemo, useState } from "react";
import { fmt1 } from "@/lib/format";
import {
  computeSoft,
  downloadOverrides,
  downloadTeams,
  FACTOR_LABEL,
  NEUTRAL,
  PLAYER_FACTORS,
  TEAM_FACTORS,
} from "@/lib/softsignals";
import type { Player, PlayerOverride, TeamSituation } from "@/lib/types";

const STORAGE_KEY = "softsignals:v1";
const round1 = (x: number) => Math.round(x * 10) / 10;

type TeamMap = Record<string, TeamSituation>;
type OverrideMap = Record<string, PlayerOverride>;

/** A 1-5 segmented selector; active cell tints green (lift), red (drag), or grey (neutral). */
function Rating({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  return (
    <div className="flex gap-1">
      {[1, 2, 3, 4, 5].map((n) => {
        const active = value === n;
        const color = n > NEUTRAL ? "#8FE06A" : n < NEUTRAL ? "#FF7E6B" : "#A7B0A6";
        return (
          <button
            key={n}
            onClick={() => onChange(n)}
            className={
              "h-7 w-7 rounded-md text-xs font-bold transition-colors " +
              (active ? "" : "bg-surface-2 text-ink-faint hover:bg-surface-3")
            }
            style={active ? { background: color, color: "#0B0F0C" } : undefined}
            aria-label={`${n} of 5`}
          >
            {n}
          </button>
        );
      })}
    </div>
  );
}

function FactorRow({ label, value, onChange }: { label: string; value: number; onChange: (n: number) => void }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-xs font-medium text-ink-muted">{label}</span>
      <Rating value={value} onChange={onChange} />
    </div>
  );
}

export function SoftSignals({
  players,
  teamSituations = {},
}: {
  players: Player[];
  teamSituations?: TeamMap;
}) {
  const [tab, setTab] = useState<"teams" | "players">("teams");
  const [teamRatings, setTeamRatings] = useState<TeamMap>(teamSituations);
  const [overrides, setOverrides] = useState<OverrideMap>({});
  const [query, setQuery] = useState("");
  const [hydrated, setHydrated] = useState(false);

  // Hydrate from localStorage after mount (seeded from the committed team table otherwise).
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const saved = JSON.parse(raw);
        if (saved.teamRatings) setTeamRatings(saved.teamRatings);
        if (saved.overrides) setOverrides(saved.overrides);
      }
    } catch {
      /* ignore */
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ teamRatings, overrides }));
    } catch {
      /* ignore */
    }
  }, [teamRatings, overrides, hydrated]);

  const setTeamFactor = (team: string, f: (typeof TEAM_FACTORS)[number], v: number) =>
    setTeamRatings((p) => ({ ...p, [team]: { ...p[team], [f]: v } }));
  const setOverrideFactor = (id: string, f: (typeof PLAYER_FACTORS)[number], v: number) =>
    setOverrides((p) => ({ ...p, [id]: { ...(p[id] ?? { id }), [f]: v } }));

  const teams = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const p of players) if (p.team) counts[p.team] = (counts[p.team] ?? 0) + 1;
    return Object.keys(counts).sort();
  }, [players]);

  const ranked = useMemo(
    () => [...players].sort((a, b) => (a.projection.overall_rank ?? 1e9) - (b.projection.overall_rank ?? 1e9)),
    [players],
  );

  const q = query.trim().toLowerCase();
  const playerList = useMemo(
    () => ranked.filter((p) => !q || p.name.toLowerCase().includes(q)).slice(0, q ? 400 : 250),
    [ranked, q],
  );

  // Biggest net moves across the whole board under the current ratings.
  const moves = useMemo(() => {
    return ranked
      .map((p) => {
        const r = computeSoft(p, teamRatings, overrides);
        if (!r.effect) return null;
        const base = p.projection.base_points;
        const adjusted = round1(base * r.soft);
        return { p, soft: r.soft, reasoning: r.reasoning, base, adjusted, delta: adjusted - base };
      })
      .filter(Boolean)
      .sort((a, b) => Math.abs(b!.delta) - Math.abs(a!.delta)) as {
      p: Player;
      soft: number;
      reasoning: string;
      base: number;
      adjusted: number;
      delta: number;
    }[];
  }, [ranked, teamRatings, overrides]);

  const ratedTeams = teams.filter((t) => {
    const s = teamRatings[t];
    return s && TEAM_FACTORS.some((f) => s[f] != null && s[f] !== NEUTRAL);
  }).length;
  const ratedPlayers = Object.values(overrides).filter((o) =>
    PLAYER_FACTORS.some((f) => o[f] != null && o[f] !== NEUTRAL),
  ).length;

  return (
    <div className="space-y-5 pb-4">
      <div className="rounded-2xl bg-surface p-4 shadow-card">
        <h2 className="text-lg font-bold text-ink">Soft signals</h2>
        <p className="mt-1 text-sm leading-relaxed text-ink-muted">
          Rate the situational factors stats miss on a <span className="font-semibold text-ink">1–5</span> scale
          (3 = neutral). Team factors apply to everyone on the team; player factors are per-player. The board
          derives a multiplier from your ratings, clamped to ±15%. Download the two files into{" "}
          <span className="font-mono text-ink">pipeline/data/</span> and run{" "}
          <span className="font-mono text-ink">make board</span> to re-rank.
        </p>
      </div>

      {/* sub-tabs */}
      <div className="flex gap-2">
        {(["teams", "players"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={
              "flex-1 rounded-xl px-3 py-2 text-sm font-semibold capitalize transition-colors " +
              (tab === t ? "bg-lime text-base" : "bg-surface-2 text-ink-muted hover:bg-surface-3")
            }
          >
            {t}
            <span className="ml-1.5 text-xs font-normal opacity-70">
              {t === "teams" ? `${ratedTeams} rated` : `${ratedPlayers} rated`}
            </span>
          </button>
        ))}
      </div>

      {tab === "teams" && (
        <div className="space-y-2.5">
          {teams.map((team) => {
            const s = teamRatings[team] ?? {};
            return (
              <div key={team} className="rounded-2xl bg-surface p-4 shadow-card">
                <div className="mb-2.5 flex items-baseline gap-2">
                  <span className="text-base font-bold text-ink">{team}</span>
                  <span className="text-xs text-ink-faint">
                    {players.filter((p) => p.team === team).length} players
                  </span>
                </div>
                <div className="space-y-2">
                  {TEAM_FACTORS.map((f) => (
                    <FactorRow
                      key={f}
                      label={FACTOR_LABEL[f]}
                      value={s[f] ?? NEUTRAL}
                      onChange={(v) => setTeamFactor(team, f, v)}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {tab === "players" && (
        <div className="space-y-3">
          <div className="relative">
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint">⌕</span>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search players…"
              className="w-full rounded-xl bg-surface-2 py-2.5 pl-9 pr-3 text-sm text-ink placeholder:text-ink-faint focus:outline-none focus:ring-1 focus:ring-lime/40"
            />
          </div>
          <div className="space-y-2">
            {playerList.map((p) => {
              const r = computeSoft(p, teamRatings, overrides);
              const o = overrides[p.id] ?? { id: p.id };
              const adjusted = round1(p.projection.base_points * r.soft);
              const up = r.soft >= 1;
              const color = r.effect ? (up ? "#8FE06A" : "#FF7E6B") : "#646E66";
              return (
                <div key={p.id} className="rounded-2xl bg-surface p-3.5 shadow-card">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <span className="truncate text-sm font-semibold text-ink">
                      {p.name}
                      <span className="ml-1.5 text-xs font-normal text-ink-faint">
                        {p.position} · {p.team || "FA"}
                      </span>
                    </span>
                    <span className="flex shrink-0 items-center gap-2 tabular text-sm">
                      <span className="text-ink-faint">{fmt1(p.projection.base_points)}</span>
                      <span className="text-ink-faint">→</span>
                      <span className="font-semibold text-ink">{fmt1(adjusted)}</span>
                      <span className="rounded-md px-1.5 py-0.5 text-xs font-semibold" style={{ color, background: `${color}1a` }}>
                        ×{r.soft.toFixed(2)}
                      </span>
                    </span>
                  </div>
                  <div className="space-y-2">
                    {PLAYER_FACTORS.map((f) => (
                      <FactorRow
                        key={f}
                        label={FACTOR_LABEL[f]}
                        value={o[f] ?? NEUTRAL}
                        onChange={(v) => setOverrideFactor(p.id, f, v)}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* biggest moves */}
      <div className="rounded-2xl bg-surface p-4 shadow-card">
        <h3 className="mb-2 font-semibold text-ink">Biggest moves</h3>
        {moves.length === 0 ? (
          <p className="py-4 text-center text-sm text-ink-faint">
            Rate some teams or players to see their projected moves here.
          </p>
        ) : (
          <div className="space-y-1.5">
            {moves.slice(0, 30).map(({ p, soft, reasoning, base, adjusted, delta }) => {
              const up = delta >= 0;
              const color = up ? "#8FE06A" : "#FF7E6B";
              return (
                <div key={p.id} className="rounded-xl bg-surface-2 px-3 py-2.5">
                  <div className="flex items-center justify-between gap-3">
                    <span className="truncate text-sm font-semibold text-ink">
                      {p.name}
                      <span className="ml-1.5 text-xs font-normal text-ink-faint">{p.position} · {p.team}</span>
                    </span>
                    <span className="flex shrink-0 items-center gap-2 tabular text-sm">
                      <span className="text-ink-faint">{fmt1(base)}</span>
                      <span className="text-ink-faint">→</span>
                      <span className="font-semibold text-ink">{fmt1(adjusted)}</span>
                      <span className="rounded-md px-1.5 py-0.5 text-xs font-semibold" style={{ color, background: `${color}1a` }}>
                        ×{soft.toFixed(2)}
                      </span>
                    </span>
                  </div>
                  {reasoning && <p className="mt-1 text-xs leading-snug text-ink-muted">{reasoning}</p>}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* export */}
      <div className="rounded-2xl bg-surface p-4 shadow-card">
        <h3 className="mb-3 font-semibold text-ink">Export</h3>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => downloadTeams(teamRatings)}
            className="rounded-lg bg-lime px-3 py-1.5 text-sm font-semibold text-base transition-opacity hover:opacity-90"
          >
            Download team_situations.json
          </button>
          <button
            onClick={() => downloadOverrides(overrides)}
            className="rounded-lg bg-lime px-3 py-1.5 text-sm font-semibold text-base transition-opacity hover:opacity-90"
          >
            Download player_overrides.json
          </button>
        </div>
        <div className="mt-3 rounded-xl bg-base/50 p-3 text-xs leading-relaxed text-ink-faint ring-1 ring-line">
          Save both into <span className="font-mono text-ink-muted">pipeline/data/</span>, then run{" "}
          <span className="font-mono text-ink-muted">make board</span> to re-rank on adjusted points. Your ratings
          are also saved in this browser, so you can come back and keep editing.
        </div>
      </div>
    </div>
  );
}
