import type { Player, PlayerOverride, TeamSituation } from "./types";

// Mirror of pipeline/src/ffrank/softsignals.py — keep the factor list, weights, and formula in sync.

export const SOFT_MIN = 0.85;
export const SOFT_MAX = 1.15;
export const NEUTRAL = 3; // 1-5 scale; 3 = neutral / no effect.
// Stay-put veterans get half their soft deviation (base_points already encodes their situation);
// rookies + team-changers (player.new_env) get full strength. Mirrors softsignals.py.
export const STAY_PUT_SOFT_WEIGHT = 0.5;

export const TEAM_FACTORS = ["qb", "ol", "scheme", "pace"] as const;
export const PLAYER_FACTORS = ["role", "competition"] as const;
export const FACTORS = [...TEAM_FACTORS, ...PLAYER_FACTORS] as const;
export type Factor = (typeof FACTORS)[number];

export const FACTOR_LABEL: Record<Factor, string> = {
  qb: "QB",
  ol: "OL",
  scheme: "Scheme",
  pace: "Pace",
  role: "Role",
  competition: "Competition",
};

// One-line explainers behind the ⓘ. Rate the CHANGE vs last year — the projection already
// reflects last season's situation, so 3 = no change = no effect, 5 = clear upgrade, 1 = decline.
export const FACTOR_INFO: Record<Factor, string> = {
  qb: "Change in QB play vs last year. 5 = clear upgrade, 1 = clear downgrade, 3 = same QB → no effect. Biggest lever for WR/TE; little for RBs; ignored for a QB rating his own team.",
  ol: "Change in the offensive line vs last year. 5 = materially better (key additions), 1 = materially worse (losses), 3 = unchanged. Biggest lever for RBs; negligible for WR/TE.",
  scheme: "Change in scheme / play-caller vs last year. 5 = new system that fits this position better, 1 = worse fit, 3 = same scheme.",
  pace: "Change in the offense's volume or pass-run lean vs last year. 5 = more favorable for this position, 1 = less favorable, 3 = unchanged.",
  role: "Change in this player's role/opportunity vs last year. 5 = bigger role (promotion, vacated touches), 1 = smaller role (new committee, lost a job), 3 = unchanged. Rookies: rate the role they're stepping into.",
  competition: "Change in target/touch competition vs last year. 5 = competition left (cleaner path), 1 = competition added (draft pick/signing), 3 = unchanged. Rookies: rate the room they land in.",
};

// Each position's weights SUM TO 0.15 → "everything maxed" lands exactly on the ±15% bound.
export const WEIGHTS: Record<string, Record<Factor, number>> = {
  RB: { qb: 0.0, ol: 0.05, scheme: 0.025, pace: 0.015, role: 0.04, competition: 0.02 },
  WR: { qb: 0.045, ol: 0.0, scheme: 0.03, pace: 0.02, role: 0.02, competition: 0.035 },
  TE: { qb: 0.04, ol: 0.0, scheme: 0.035, pace: 0.02, role: 0.035, competition: 0.02 },
  QB: { qb: 0.0, ol: 0.045, scheme: 0.04, pace: 0.03, role: 0.015, competition: 0.02 },
};

const clamp = (x: number) => Math.max(SOFT_MIN, Math.min(SOFT_MAX, x));
const round4 = (x: number) => Math.round(x * 1e4) / 1e4;

export type Ratings = Record<Factor, number>;

/** The six 1-5 ratings for a player: team factors from its team + its player overrides. */
export function playerRatings(
  player: Player,
  teamRatings: Record<string, TeamSituation>,
  overrides: Record<string, PlayerOverride>,
): Ratings {
  const t = teamRatings[player.team] ?? {};
  const o = overrides[player.id] ?? {};
  return {
    qb: t.qb ?? NEUTRAL,
    ol: t.ol ?? NEUTRAL,
    scheme: t.scheme ?? NEUTRAL,
    pace: t.pace ?? NEUTRAL,
    role: o.role ?? NEUTRAL,
    competition: o.competition ?? NEUTRAL,
  };
}

function reasoning(ratings: Ratings, weights: Record<Factor, number>): string {
  const lifts: string[] = [];
  const drags: string[] = [];
  for (const f of FACTORS) {
    if (ratings[f] === NEUTRAL || (weights[f] ?? 0) === 0) continue;
    const chip = `${FACTOR_LABEL[f]} ${ratings[f]}/5`;
    (ratings[f] > NEUTRAL ? lifts : drags).push(chip);
  }
  const parts: string[] = [];
  if (lifts.length) parts.push(lifts.join(", ") + " lift");
  if (drags.length) parts.push(drags.join(", ") + " drag");
  return parts.join("; ");
}

export interface SoftResult {
  soft: number;
  reasoning: string;
  effect: boolean; // false when ratings net to no change (player ranks on base)
  shrunk: boolean; // true when a stay-put vet's deviation was halved
  ratings: Ratings;
}

/** Position-weighted multiplier from a player's ratings, scaled by how blind the base is. */
export function computeSoft(
  player: Player,
  teamRatings: Record<string, TeamSituation>,
  overrides: Record<string, PlayerOverride>,
): SoftResult {
  const ratings = playerRatings(player, teamRatings, overrides);
  const weights = WEIGHTS[player.position] ?? ({} as Record<Factor, number>);
  let raw = FACTORS.reduce((s, f) => s + (weights[f] ?? 0) * ((ratings[f] - NEUTRAL) / 2), 0);
  const effect = Math.abs(raw) >= 1e-9;
  const shrunk = effect && !player.new_env;
  if (shrunk) raw *= STAY_PUT_SOFT_WEIGHT; // base already knows a stay-put vet → trust the rating half as much
  return { soft: round4(clamp(1 + raw)), reasoning: reasoning(ratings, weights), effect, shrunk, ratings };
}

function download(filename: string, body: unknown) {
  const blob = new Blob([JSON.stringify(body, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Emit pipeline/data/team_situations.json — only teams with a non-neutral factor or a note. */
export function downloadTeams(teamRatings: Record<string, TeamSituation>) {
  const rows = Object.entries(teamRatings)
    .map(([team, s]) => ({
      team,
      qb: s.qb ?? NEUTRAL,
      ol: s.ol ?? NEUTRAL,
      scheme: s.scheme ?? NEUTRAL,
      pace: s.pace ?? NEUTRAL,
      notes: s.notes ?? "",
    }))
    .filter((r) => r.qb !== NEUTRAL || r.ol !== NEUTRAL || r.scheme !== NEUTRAL || r.pace !== NEUTRAL || r.notes)
    .sort((a, b) => a.team.localeCompare(b.team));
  download("team_situations.json", rows);
}

/** Emit pipeline/data/player_overrides.json — only players with a non-neutral factor. */
export function downloadOverrides(overrides: Record<string, PlayerOverride>) {
  const rows = Object.values(overrides)
    .map((o) => ({ id: o.id, role: o.role ?? NEUTRAL, competition: o.competition ?? NEUTRAL }))
    .filter((r) => r.role !== NEUTRAL || r.competition !== NEUTRAL);
  download("player_overrides.json", rows);
}
