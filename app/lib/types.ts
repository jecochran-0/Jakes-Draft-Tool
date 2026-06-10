// Mirrors schema/contract.schema.json (the Python pipeline's output).

export type Position = "QB" | "RB" | "WR" | "TE";

export interface RawStats {
  last_season_points: number | null;
  games_played: number | null;
  snap_share: number | null;
  target_share: number | null;
  prior_seasons_points: number[];
}

export interface Situation {
  qb_tier: number | null;
  oc_change: boolean | null;
  vegas_team_total: number | null;
  soft_factors: Record<string, number> | null;
  soft_score: number | null;
  soft_reasoning: string | null;
}

export interface Projection {
  base_points: number;
  adjusted_points: number | null;
  vorp: number | null;
  overall_rank: number | null;
  position_rank: number | null;
  tier: number | null;
}

export interface Market {
  adp: number | null;
  adp_rank: number | null;
  value_vs_adp: number | null;
}

export interface Player {
  id: string;
  name: string;
  position: Position;
  team: string;
  age: number | null;
  is_rookie: boolean;
  new_env?: boolean; // rookie or team-changer: base is blind to their situation → soft at full strength
  raw_stats: RawStats;
  situation: Situation | null;
  projection: Projection;
  market: Market | null;
}

// Team-wide soft factors, each rated 1-5 (5=best, 3=neutral). Mirrors pipeline/data/team_situations.json.
export interface TeamSituation {
  qb?: number;
  ol?: number;
  scheme?: number;
  pace?: number;
  notes?: string;
}

// Per-player soft factors, 1-5. Mirrors pipeline/data/player_overrides.json.
export interface PlayerOverride {
  id: string;
  role?: number;
  competition?: number;
}

export interface Meta {
  generated_at: string;
  season: number;
  scoring_config: Record<string, number>;
  league_config: { teams: number; lineup: Record<string, number>; flex_eligible: string[] };
  team_situations?: Record<string, TeamSituation>;
}

export interface Contract {
  meta: Meta;
  players: Player[];
}
