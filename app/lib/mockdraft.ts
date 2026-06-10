// Mock-draft engine — pure functions over a serializable MockState. ADP-driven, need-aware bots
// with noise so runs vary but studs still go early. No projection logic here (the board order from
// the Python pipeline is read, never recomputed); this is draft bookkeeping + bot/recommender AI.
// Designed to be reused by a future Live Draft Mode.

import { effectivePoints } from "./format";
import type { Player, Position } from "./types";

export type Variance = "low" | "med" | "high";
export const STARTER_POSITIONS: Position[] = ["QB", "RB", "WR", "TE"];

export interface MockConfig {
  slot: number; // 1-based draft position of the user
  teams: number;
  rounds: number;
  variance: Variance;
  lineup: Record<string, number>; // {QB,RB,WR,TE,FLEX}
  flexEligible: Position[];
}

export interface Pick {
  overall: number; // 1-based overall pick
  round: number;
  teamIndex: number; // 0-based
  playerId: string;
}

export interface MockState {
  config: MockConfig;
  picks: Pick[];
  status: "drafting" | "done";
}

const VARIANCE_SIGMA: Record<Variance, number> = { low: 0.25, med: 0.5, high: 0.9 };
const ADP_WINDOW = 10; // bots consider the next ~10 by market when picking
const NO_ADP_OFFSET = 1000; // push players without ADP behind the market pool (bots follow ADP)

export const userTeamIndex = (c: MockConfig) => c.slot - 1;
export const totalPicks = (c: MockConfig) => c.teams * c.rounds;
const startersTotal = (lineup: Record<string, number>) =>
  STARTER_POSITIONS.reduce((s, p) => s + (lineup[p] ?? 0), 0) + (lineup.FLEX ?? 0);

/** Team on the clock for a 1-based overall pick (snake: odd rounds L→R, even R→L). */
export function teamOnClock(overall: number, teams: number): { round: number; teamIndex: number } {
  const round = Math.ceil(overall / teams);
  const idx = (overall - 1) % teams;
  return { round, teamIndex: round % 2 === 1 ? idx : teams - 1 - idx };
}

export function createDraft(config: MockConfig): MockState {
  return { config, picks: [], status: "drafting" };
}

export const draftedIds = (s: MockState) => new Set(s.picks.map((p) => p.playerId));

export function onClock(s: MockState): { overall: number; round: number; teamIndex: number } | null {
  const overall = s.picks.length + 1;
  if (overall > totalPicks(s.config)) return null;
  return { overall, ...teamOnClock(overall, s.config.teams) };
}

export function teamPicks(s: MockState, teamIndex: number): Pick[] {
  return s.picks.filter((p) => p.teamIndex === teamIndex);
}

function counts(s: MockState, teamIndex: number, byId: Map<string, Player>): Record<string, number> {
  const c: Record<string, number> = { QB: 0, RB: 0, WR: 0, TE: 0 };
  for (const pk of s.picks) {
    if (pk.teamIndex !== teamIndex) continue;
    const pos = byId.get(pk.playerId)?.position;
    if (pos) c[pos] = (c[pos] ?? 0) + 1;
  }
  return c;
}

/** Per-position cap that blocks unrealistic hoarding (no 3rd QB/TE) but lets RB/WR stack. */
function positionalCap(pos: Position, c: MockConfig): number {
  const benchSize = c.rounds - startersTotal(c.lineup);
  if (pos === "QB") return (c.lineup.QB ?? 1) + 1;
  if (pos === "TE") return (c.lineup.TE ?? 1) + 1;
  return (c.lineup[pos] ?? 0) + (c.lineup.FLEX ?? 0) + Math.max(0, benchSize); // RB/WR
}

function flexOpen(cnt: Record<string, number>, c: MockConfig): number {
  const overflow = c.flexEligible.reduce(
    (s, p) => s + Math.max(0, (cnt[p] ?? 0) - (c.lineup[p] ?? 0)),
    0,
  );
  return Math.max(0, (c.lineup.FLEX ?? 0) - overflow);
}

function isDraftable(pos: Position, cnt: Record<string, number>, c: MockConfig, teamSize: number): boolean {
  if (teamSize >= c.rounds) return false;
  return (cnt[pos] ?? 0) < positionalCap(pos, c);
}

/** Need pressure for a position: a fresh open starter slot is the strongest pull; flex is mild. */
function needWeight(pos: Position, cnt: Record<string, number>, c: MockConfig, round: number): number {
  const openStarter = Math.max(0, (c.lineup[pos] ?? 0) - (cnt[pos] ?? 0)) > 0;
  const flexNeed = c.flexEligible.includes(pos) && flexOpen(cnt, c) > 0;
  let w = 1.0;
  if (openStarter) w += 1.5 * (1 + round / c.rounds); // chase starters harder late
  else if (flexNeed) w += 0.5;
  return w;
}

export function marketRank(p: Player): number {
  return p.market?.adp_rank ?? NO_ADP_OFFSET + (p.projection.overall_rank ?? 9999);
}

function gaussian(sigma: number): number {
  const u = 1 - Math.random();
  const v = Math.random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v) * sigma;
}

function available(s: MockState, players: Player[]): Player[] {
  const done = draftedIds(s);
  return players.filter((p) => !done.has(p.id));
}

/** Bot choice: need-weighted ADP within a window, with noise so reaches happen. */
export function botPick(s: MockState, players: Player[], byId: Map<string, Player>): string | null {
  const clock = onClock(s);
  if (!clock) return null;
  const cnt = counts(s, clock.teamIndex, byId);
  const size = teamPicks(s, clock.teamIndex).length;
  const pool = available(s, players)
    .filter((p) => isDraftable(p.position, cnt, s.config, size))
    .sort((a, b) => marketRank(a) - marketRank(b))
    .slice(0, ADP_WINDOW);
  if (pool.length === 0) return null;
  const sigma = VARIANCE_SIGMA[s.config.variance];
  let best: string | null = null;
  let bestScore = -Infinity;
  pool.forEach((p, i) => {
    const adpPriority = ADP_WINDOW - i; // earlier ADP = higher
    const score = adpPriority * needWeight(p.position, cnt, s.config, clock.round) * Math.max(0.01, 1 + gaussian(sigma));
    if (score > bestScore) {
      bestScore = score;
      best = p.id;
    }
  });
  return best;
}

/** User recommendation: best board value (overall_rank), nudged toward unfilled needs. */
export function recommendPick(s: MockState, players: Player[], byId: Map<string, Player>): string | null {
  const clock = onClock(s);
  if (!clock) return null;
  const cnt = counts(s, clock.teamIndex, byId);
  const size = teamPicks(s, clock.teamIndex).length;
  const pool = available(s, players).filter((p) => isDraftable(p.position, cnt, s.config, size));
  if (pool.length === 0) return null;
  const NEED_BONUS = 8;
  const FLEX_BONUS = 4;
  const adjRank = (p: Player) => {
    const base = p.projection.overall_rank ?? 9999;
    const openStarter = Math.max(0, (s.config.lineup[p.position] ?? 0) - (cnt[p.position] ?? 0)) > 0;
    const flexNeed = s.config.flexEligible.includes(p.position) && flexOpen(cnt, s.config) > 0;
    return base - (openStarter ? NEED_BONUS : flexNeed ? FLEX_BONUS : 0);
  };
  return pool.reduce((best, p) => (adjRank(p) < adjRank(best) ? p : best)).id;
}

/** Append a pick for whoever is on the clock. No validation beyond "undrafted" (the user may override needs). */
export function draftPlayer(s: MockState, playerId: string): MockState {
  const clock = onClock(s);
  if (!clock || draftedIds(s).has(playerId)) return s;
  const picks = [...s.picks, { overall: clock.overall, round: clock.round, teamIndex: clock.teamIndex, playerId }];
  const status = picks.length >= totalPicks(s.config) ? "done" : "drafting";
  return { ...s, picks, status };
}

/** Advance through bot picks until it's the user's turn (or the draft ends). */
export function runBotsUntilUser(s: MockState, players: Player[], byId: Map<string, Player>): MockState {
  let state = s;
  let guard = 0;
  while (state.status === "drafting" && guard++ < totalPicks(state.config) + 1) {
    const clock = onClock(state);
    if (!clock || clock.teamIndex === userTeamIndex(state.config)) break;
    const pick = botPick(state, players, byId);
    if (!pick) break;
    state = draftPlayer(state, pick);
  }
  return state;
}

/** Autopick everyone (bots + the user via the recommender) to the final pick. */
export function simToEnd(s: MockState, players: Player[], byId: Map<string, Player>): MockState {
  let state = s;
  let guard = 0;
  while (state.status === "drafting" && guard++ < totalPicks(state.config) + 1) {
    const clock = onClock(state);
    if (!clock) break;
    const pick =
      clock.teamIndex === userTeamIndex(state.config)
        ? recommendPick(state, players, byId)
        : botPick(state, players, byId);
    if (!pick) break;
    state = draftPlayer(state, pick);
  }
  return state;
}

// ----- results -------------------------------------------------------------------------

export interface LineupSlot {
  slot: string; // QB / RB1 / WR2 / TE / FLEX
  player: Player | null;
}

/** Greedily fill the starting lineup by effective points; the rest is bench. */
export function assignLineup(roster: Player[], lineup: Record<string, number>, flexEligible: Position[]) {
  const sorted = [...roster].sort((a, b) => effectivePoints(b) - effectivePoints(a));
  const used = new Set<string>();
  const slots: LineupSlot[] = [];
  for (const pos of STARTER_POSITIONS) {
    for (let i = 0; i < (lineup[pos] ?? 0); i++) {
      const pick = sorted.find((p) => p.position === pos && !used.has(p.id));
      if (pick) used.add(pick.id);
      slots.push({ slot: (lineup[pos] ?? 0) > 1 ? `${pos}${i + 1}` : pos, player: pick ?? null });
    }
  }
  for (let i = 0; i < (lineup.FLEX ?? 0); i++) {
    const pick = sorted.find((p) => flexEligible.includes(p.position) && !used.has(p.id));
    if (pick) used.add(pick.id);
    slots.push({ slot: "FLEX", player: pick ?? null });
  }
  const bench = sorted.filter((p) => !used.has(p.id));
  const startersPoints = slots.reduce((s, sl) => s + (sl.player ? effectivePoints(sl.player) : 0), 0);
  return { slots, bench, startersPoints };
}

export interface MyPick {
  overall: number;
  round: number;
  player: Player;
  valueVsAdp: number | null; // your pick - adp_rank; + = he fell past ADP to you (value), - = you reached
}

export interface MockResults {
  finishRank: number; // 1..teams
  teamPoints: number[]; // by team index
  myStartersPoints: number;
  slots: LineupSlot[];
  bench: Player[];
  myPicks: MyPick[];
  bestSteal: MyPick | null;
  biggestReach: MyPick | null;
  grade: string;
}

export function results(s: MockState, players: Player[], byId: Map<string, Player>): MockResults {
  const c = s.config;
  const rosterOf = (ti: number) =>
    s.picks.filter((p) => p.teamIndex === ti).map((p) => byId.get(p.playerId)!).filter(Boolean);
  const teamPoints = Array.from({ length: c.teams }, (_, ti) =>
    assignLineup(rosterOf(ti), c.lineup, c.flexEligible).startersPoints,
  );
  const me = userTeamIndex(c);
  const myLineup = assignLineup(rosterOf(me), c.lineup, c.flexEligible);
  const finishRank = 1 + teamPoints.filter((pts, ti) => ti !== me && pts > teamPoints[me]).length;

  const myPicks: MyPick[] = s.picks
    .filter((p) => p.teamIndex === me)
    .map((p) => {
      const player = byId.get(p.playerId)!;
      const adpRank = player.market?.adp_rank ?? null;
      return { overall: p.overall, round: p.round, player, valueVsAdp: adpRank != null ? p.overall - adpRank : null };
    });
  const valued = myPicks.filter((m) => m.valueVsAdp != null);
  const bestSteal = valued.length ? valued.reduce((a, b) => (b.valueVsAdp! > a.valueVsAdp! ? b : a)) : null;
  const biggestReach = valued.length ? valued.reduce((a, b) => (b.valueVsAdp! < a.valueVsAdp! ? b : a)) : null;

  const grade = finishRank <= 2 ? "A" : finishRank <= 4 ? "B+" : finishRank <= 6 ? "B" : finishRank <= 8 ? "C" : "D";
  return {
    finishRank,
    teamPoints,
    myStartersPoints: myLineup.startersPoints,
    slots: myLineup.slots,
    bench: myLineup.bench,
    myPicks,
    bestSteal,
    biggestReach,
    grade,
  };
}
