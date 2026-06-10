"use client";

import { useEffect, useMemo, useState } from "react";
import { effectivePoints, fmt1, POSITION_COLOR, POSITIONS } from "@/lib/format";
import {
  assignLineup,
  createDraft,
  draftPlayer,
  type MockConfig,
  type MockState,
  onClock,
  recommendPick,
  results,
  runBotsUntilUser,
  simToEnd,
  teamPicks,
  totalPicks,
  userTeamIndex,
  type Variance,
} from "@/lib/mockdraft";
import type { Meta, Player, Position } from "@/lib/types";
import { PlayerRow } from "./PlayerRow";
import { PositionBadge } from "./ui";

const STORAGE = "mockdraft:v1";

export function MockDraft({ players, meta }: { players: Player[]; meta: Meta }) {
  const byId = useMemo(() => new Map(players.map((p) => [p.id, p])), [players]);
  const ranked = useMemo(
    () => [...players].sort((a, b) => (a.projection.overall_rank ?? 1e9) - (b.projection.overall_rank ?? 1e9)),
    [players],
  );

  const lineup = meta.league_config.lineup;
  const teams = meta.league_config.teams;
  const flexEligible = (meta.league_config.flex_eligible as Position[]) ?? ["RB", "WR", "TE"];
  const startersTotal =
    (["QB", "RB", "WR", "TE"] as Position[]).reduce((s, p) => s + (lineup[p] ?? 0), 0) + (lineup.FLEX ?? 0);

  const [slot, setSlot] = useState(6);
  const [rounds, setRounds] = useState(15);
  const [variance, setVariance] = useState<Variance>("med");
  const [state, setState] = useState<MockState | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE);
      if (raw) {
        const saved = JSON.parse(raw) as { state: MockState | null; slot: number; rounds: number; variance: Variance };
        if (saved.state) setState(saved.state);
        if (saved.slot) setSlot(saved.slot);
        if (saved.rounds) setRounds(saved.rounds);
        if (saved.variance) setVariance(saved.variance);
      }
    } catch {
      /* ignore */
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    try {
      localStorage.setItem(STORAGE, JSON.stringify({ state, slot, rounds, variance }));
    } catch {
      /* ignore */
    }
  }, [state, slot, rounds, variance, hydrated]);

  function start() {
    const config: MockConfig = { slot, teams, rounds, variance, lineup, flexEligible };
    setState(runBotsUntilUser(createDraft(config), players, byId));
  }
  function userDraft(id: string) {
    setState((prev) => (prev ? runBotsUntilUser(draftPlayer(prev, id), players, byId) : prev));
  }
  const finishToEnd = () => setState((prev) => (prev ? simToEnd(prev, players, byId) : prev));
  const reset = () => setState(null);

  const adpLabel = meta.adp_source === "espn" ? "ESPN" : meta.adp_source === "ffc" ? "FFC" : "market";

  if (!state) {
    return (
      <Setup
        slot={slot} setSlot={setSlot} rounds={rounds} setRounds={setRounds}
        variance={variance} setVariance={setVariance} teams={teams}
        startersTotal={startersTotal} onStart={start} adpLabel={adpLabel}
      />
    );
  }
  if (state.status === "done") {
    return <Results state={state} players={players} byId={byId} onNew={reset} onRerun={start} />;
  }
  return (
    <DraftPhase
      state={state} players={ranked} byId={byId} onDraft={userDraft}
      onSim={finishToEnd} onReset={reset} lineup={lineup} flexEligible={flexEligible}
    />
  );
}

// ----- setup ----------------------------------------------------------------------------

function Setup({
  slot, setSlot, rounds, setRounds, variance, setVariance, teams, startersTotal, onStart, adpLabel,
}: {
  slot: number; setSlot: (n: number) => void; rounds: number; setRounds: (n: number) => void;
  variance: Variance; setVariance: (v: Variance) => void; teams: number; startersTotal: number;
  onStart: () => void; adpLabel: string;
}) {
  return (
    <div className="space-y-5 pb-4">
      <div className="rounded-2xl bg-surface p-4 shadow-card">
        <h2 className="text-lg font-bold text-ink">Mock draft</h2>
        <p className="mt-1 text-sm leading-relaxed text-ink-muted">
          Draft from your slot against bots drafting off <span className="font-semibold text-ink">{adpLabel} ADP</span>.
          Get a recommended pick (your board) each round, or sim the rest to see your roster and projected
          finish. Test strategies — RB-RB, Zero-RB — before draft day.
        </p>
      </div>

      <div className="rounded-2xl bg-surface p-4 shadow-card">
        <h3 className="mb-2 text-sm font-semibold text-ink">Your draft slot</h3>
        <div className="grid grid-cols-6 gap-2">
          {Array.from({ length: teams }, (_, i) => i + 1).map((n) => (
            <button
              key={n}
              onClick={() => setSlot(n)}
              className={
                "rounded-lg py-2 text-sm font-bold transition-colors " +
                (slot === n ? "bg-lime text-base" : "bg-surface-2 text-ink-muted hover:bg-surface-3")
              }
            >
              {n}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-2xl bg-surface p-4 shadow-card">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ink">Rounds</h3>
          <span className="tabular text-sm text-ink-muted">
            {rounds} <span className="text-ink-faint">({startersTotal} starters + {Math.max(0, rounds - startersTotal)} bench)</span>
          </span>
        </div>
        <input
          type="range" min={startersTotal} max={16} value={rounds}
          onChange={(e) => setRounds(Number(e.target.value))}
          className="mt-3 w-full accent-lime"
        />
      </div>

      <div className="rounded-2xl bg-surface p-4 shadow-card">
        <h3 className="mb-2 text-sm font-semibold text-ink">Bot variance</h3>
        <div className="flex gap-2">
          {(["low", "med", "high"] as Variance[]).map((v) => (
            <button
              key={v}
              onClick={() => setVariance(v)}
              className={
                "flex-1 rounded-lg py-2 text-sm font-semibold capitalize transition-colors " +
                (variance === v ? "bg-lime text-base" : "bg-surface-2 text-ink-muted hover:bg-surface-3")
              }
            >
              {v}
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs text-ink-faint">How far bots stray from ADP. Higher = more surprises (and reaches).</p>
      </div>

      <button
        onClick={onStart}
        className="w-full rounded-xl bg-lime py-3 text-base font-bold text-base transition-opacity hover:opacity-90"
      >
        Start mock draft
      </button>
    </div>
  );
}

// ----- draft phase ----------------------------------------------------------------------

function DraftPhase({
  state, players, byId, onDraft, onSim, onReset, lineup, flexEligible,
}: {
  state: MockState; players: Player[]; byId: Map<string, Player>;
  onDraft: (id: string) => void; onSim: () => void; onReset: () => void;
  lineup: Record<string, number>; flexEligible: Position[];
}) {
  const [query, setQuery] = useState("");
  const [pos, setPos] = useState<Position | "ALL">("ALL");
  const clock = onClock(state);
  const me = userTeamIndex(state.config);
  const drafted = useMemo(() => new Set(state.picks.map((p) => p.playerId)), [state.picks]);

  const recId = useMemo(() => recommendPick(state, players, byId), [state, players, byId]);
  const rec = recId ? byId.get(recId) : null;

  const q = query.trim().toLowerCase();
  const avail = players.filter(
    (p) => !drafted.has(p.id) && (pos === "ALL" || p.position === pos) && (!q || p.name.toLowerCase().includes(q)),
  );

  const myRoster = teamPicks(state, me).map((p) => byId.get(p.playerId)!).filter(Boolean);
  const { slots, startersPoints } = assignLineup(myRoster, lineup, flexEligible);
  const recent = state.picks.slice(-8);
  const [mode, setMode] = useState<"pick" | "board">("pick");

  return (
    <div className="space-y-3 pb-4">
      {/* on the clock */}
      <div className="rounded-2xl bg-lime/10 p-3.5 ring-1 ring-lime/30">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-lime">You're on the clock</div>
            <div className="mt-0.5 text-sm text-ink-muted">
              Round {clock?.round} · Pick {clock?.overall} of {totalPicks(state.config)}
            </div>
          </div>
          <div className="flex gap-2">
            <button onClick={onSim} className="rounded-lg bg-lime px-3 py-1.5 text-sm font-semibold text-base hover:opacity-90">
              Sim to end
            </button>
            <button onClick={onReset} className="rounded-lg bg-surface-2 px-3 py-1.5 text-sm font-semibold text-ink-muted hover:bg-surface-3">
              Reset
            </button>
          </div>
        </div>
      </div>

      {/* view toggle */}
      <div className="flex gap-2">
        {(["pick", "board"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={
              "flex-1 rounded-xl py-2 text-sm font-semibold transition-colors " +
              (mode === m ? "bg-lime text-base" : "bg-surface-2 text-ink-muted hover:bg-surface-3")
            }
          >
            {m === "pick" ? "Pick" : "Board"}
          </button>
        ))}
      </div>

      {mode === "board" && (
        <div className="rounded-2xl bg-surface p-3 shadow-card">
          <DraftBoard state={state} byId={byId} />
        </div>
      )}

      {mode === "pick" && (
        <>
      {/* recent picks ticker */}
      {recent.length > 0 && (
        <div className="flex gap-1.5 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {recent.map((pk) => {
            const pl = byId.get(pk.playerId);
            const mine = pk.teamIndex === me;
            return (
              <span
                key={pk.overall}
                className={"shrink-0 rounded-lg px-2 py-1 text-[11px] " + (mine ? "bg-lime/15 text-lime" : "bg-surface-2 text-ink-muted")}
              >
                <span className="text-ink-faint">{pk.overall}.</span> {pl?.name.split(" ").slice(-1)[0]} <span className="text-ink-faint">{pl?.position}</span>
              </span>
            );
          })}
        </div>
      )}

      {/* my roster strip */}
      <div className="rounded-2xl bg-surface p-3 shadow-card">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-ink-faint">Your roster</span>
          <span className="tabular text-sm font-semibold text-lime">{fmt1(startersPoints)} <span className="text-[10px] font-normal text-ink-faint">proj starters</span></span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {slots.map((sl, i) => (
            <span
              key={i}
              className={"rounded-md px-2 py-1 text-[11px] " + (sl.player ? "bg-surface-2 text-ink" : "bg-surface-2/50 text-ink-faint ring-1 ring-line")}
            >
              <span className="font-semibold text-ink-faint">{sl.slot}</span>{" "}
              {sl.player ? sl.player.name.split(" ").slice(-1)[0] : "—"}
            </span>
          ))}
        </div>
      </div>

      {/* recommended */}
      {rec && (
        <div className="rounded-2xl bg-surface p-3 shadow-card ring-1 ring-lime/40">
          <div className="mb-2 flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-lime">Recommended</span>
            <span className="text-[11px] text-ink-faint">best value for your needs</span>
          </div>
          <div className="flex items-center gap-3">
            <PositionBadge pos={rec.position} />
            <div className="min-w-0 flex-1">
              <div className="truncate text-[15px] font-semibold text-ink">{rec.name}</div>
              <div className="text-xs text-ink-muted">
                {rec.position}
                {rec.projection.position_rank} · {rec.team} · #{rec.projection.overall_rank} overall
                {rec.market?.adp != null && ` · ADP ${rec.market.adp.toFixed(1)}`}
              </div>
            </div>
            <span className="tabular text-lg font-bold text-lime">{fmt1(effectivePoints(rec))}</span>
            <button onClick={() => onDraft(rec.id)} className="rounded-lg bg-lime px-3 py-2 text-sm font-bold text-base hover:opacity-90">
              Draft
            </button>
          </div>
        </div>
      )}

      {/* search + position filter */}
      <div className="space-y-2">
        <div className="relative">
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint">⌕</span>
          <input
            value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search available…"
            className="w-full rounded-xl bg-surface-2 py-2.5 pl-9 pr-3 text-sm text-ink placeholder:text-ink-faint focus:outline-none focus:ring-1 focus:ring-lime/40"
          />
        </div>
        <div className="flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {(["ALL", ...POSITIONS] as const).map((p) => (
            <button
              key={p}
              onClick={() => setPos(p)}
              className={
                "shrink-0 rounded-full px-3 py-1 text-sm font-medium transition-colors " +
                (pos === p ? "bg-lime text-base" : "bg-surface-2 text-ink-muted hover:bg-surface-3")
              }
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* available board */}
      <div className="space-y-1.5">
        {avail.slice(0, 120).map((p) => (
          <PlayerRow key={p.id} player={p} rankMode="overall" onClick={() => onDraft(p.id)} />
        ))}
        {avail.length === 0 && <div className="py-12 text-center text-sm text-ink-faint">No players match.</div>}
      </div>
        </>
      )}
    </div>
  );
}

// ----- draft board grid -----------------------------------------------------------------

// Soft inner depth (top highlight → bottom shade) so saturated position fills read as premium
// tiles, not flat neon. Applied over the position color.
const CELL_SHEEN = "linear-gradient(180deg, rgba(255,255,255,0.16), rgba(255,255,255,0) 38%, rgba(0,0,0,0.22))";

function DraftBoard({
  state, byId, highlightClock = true,
}: {
  state: MockState; byId: Map<string, Player>; highlightClock?: boolean;
}) {
  const { teams, rounds } = state.config;
  const me = userTeamIndex(state.config);
  const clock = onClock(state);
  const cells = new Map<string, (typeof state.picks)[number]>();
  for (const pk of state.picks) cells.set(`${pk.round}:${pk.teamIndex}`, pk);
  const cols = Array.from({ length: teams }, (_, i) => i);
  const rows = Array.from({ length: rounds }, (_, i) => i + 1);

  const rail = "sticky left-0 z-10 flex w-8 shrink-0 items-center justify-center bg-surface";

  return (
    <div className="overflow-x-auto pb-1">
      <div className="inline-flex flex-col gap-[5px]">
        {/* team header (sticky round corner + team names) */}
        <div className="flex gap-[5px]">
          <div className={rail} />
          {cols.map((c) => (
            <div
              key={c}
              className={
                "w-[74px] shrink-0 truncate rounded-md px-1 py-0.5 text-center text-[11px] font-semibold " +
                (c === me ? "bg-lime text-base" : "text-ink-muted")
              }
            >
              {c === me ? "You" : `Tm ${c + 1}`}
            </div>
          ))}
        </div>
        {rows.map((r) => (
          <div key={r} className="flex gap-[5px]">
            <div className={rail + " text-[10px] font-bold text-ink-faint"}>{r}</div>
            {cols.map((c) => {
              const pk = cells.get(`${r}:${c}`);
              const within = ((r % 2 === 1) ? c : teams - 1 - c) + 1;
              const isClock = highlightClock && clock && clock.round === r && clock.teamIndex === c;
              const isMine = c === me;
              if (!pk) {
                return (
                  <div
                    key={c}
                    className={
                      "flex h-[48px] w-[74px] shrink-0 items-start justify-end rounded-lg px-1.5 py-1 ring-1 " +
                      (isClock ? "bg-lime/10 ring-2 ring-lime" : isMine ? "bg-lime/[0.04] ring-lime/25" : "bg-white/[0.02] ring-line")
                    }
                  >
                    <span className="tabular text-[9px] font-semibold text-ink-faint/60">{r}.{within}</span>
                  </div>
                );
              }
              const pl = byId.get(pk.playerId);
              const pos = pl?.position ?? "RB";
              const color = POSITION_COLOR[pos];
              const last = pl ? pl.name.split(" ").slice(-1)[0] : "?";
              return (
                <div
                  key={c}
                  className="h-[48px] w-[74px] shrink-0 overflow-hidden rounded-lg px-1.5 py-1"
                  style={{
                    backgroundColor: color,
                    backgroundImage: CELL_SHEEN,
                    boxShadow: isMine
                      ? "inset 0 0 0 2px #C5F23D, inset 0 0 0 3px rgba(0,0,0,0.25)"
                      : "inset 0 0 0 1px rgba(0,0,0,0.14)",
                  }}
                  title={pl?.name}
                >
                  <div className="flex items-center justify-between leading-none">
                    <span className="text-[8px] font-extrabold uppercase tracking-wide" style={{ color: "rgba(0,0,0,0.62)" }}>
                      {pos} · {pl?.team}
                    </span>
                    <span className="tabular text-[8px] font-bold" style={{ color: "rgba(0,0,0,0.45)" }}>{r}.{within}</span>
                  </div>
                  <div className="mt-1 truncate text-[12.5px] font-extrabold leading-tight" style={{ color: "#0a0d07" }}>
                    {last}
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

// ----- results --------------------------------------------------------------------------

function Results({
  state, players, byId, onNew, onRerun,
}: {
  state: MockState; players: Player[]; byId: Map<string, Player>;
  onNew: () => void; onRerun: () => void;
}) {
  const r = useMemo(() => results(state, players, byId), [state, players, byId]);
  const teamCount = state.config.teams;

  return (
    <div className="space-y-4 pb-4">
      <div className="rounded-2xl bg-surface p-5 text-center shadow-card">
        <div className="text-xs font-semibold uppercase tracking-wider text-ink-faint">Projected finish</div>
        <div className="mt-1 flex items-center justify-center gap-3">
          <span className="text-4xl font-bold text-lime">{ordinal(r.finishRank)}</span>
          <span className="text-ink-faint">of {teamCount}</span>
          <span className="rounded-xl bg-lime/15 px-3 py-1 text-2xl font-bold text-lime">{r.grade}</span>
        </div>
        <div className="mt-2 tabular text-sm text-ink-muted">{fmt1(r.myStartersPoints)} projected starter points</div>
        <div className="mt-4 flex justify-center gap-2">
          <button onClick={onRerun} className="rounded-lg bg-lime px-4 py-2 text-sm font-bold text-base hover:opacity-90">Re-run same settings</button>
          <button onClick={onNew} className="rounded-lg bg-surface-2 px-4 py-2 text-sm font-semibold text-ink-muted hover:bg-surface-3">New mock</button>
        </div>
      </div>

      {((r.bestSteal && r.bestSteal.valueVsAdp! > 0) || (r.biggestReach && r.biggestReach.valueVsAdp! < 0)) && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {r.bestSteal && r.bestSteal.valueVsAdp! > 0 && <ValueCard label="Best value (fell to you)" m={r.bestSteal} positive />}
          {r.biggestReach && r.biggestReach.valueVsAdp! < 0 && <ValueCard label="Biggest reach" m={r.biggestReach} positive={false} />}
        </div>
      )}

      <div className="rounded-2xl bg-surface p-4 shadow-card">
        <h3 className="mb-3 text-sm font-semibold text-ink">Starting lineup</h3>
        <div className="space-y-1.5">
          {r.slots.map((sl, i) => (
            <div key={i} className="flex items-center gap-3 rounded-xl bg-surface-2 px-3 py-2">
              <span className="w-12 shrink-0 text-xs font-semibold text-ink-faint">{sl.slot}</span>
              {sl.player ? (
                <>
                  <PositionBadge pos={sl.player.position} size={30} />
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">{sl.player.name}</span>
                  <span className="text-xs text-ink-faint">{sl.player.team}</span>
                  <span className="tabular text-sm font-semibold text-lime">{fmt1(effectivePoints(sl.player))}</span>
                </>
              ) : (
                <span className="text-sm text-ink-faint">empty</span>
              )}
            </div>
          ))}
        </div>
      </div>

      {r.bench.length > 0 && (
        <div className="rounded-2xl bg-surface p-4 shadow-card">
          <h3 className="mb-2 text-sm font-semibold text-ink">Bench</h3>
          <div className="flex flex-wrap gap-1.5">
            {r.bench.map((p) => (
              <span key={p.id} className="rounded-md bg-surface-2 px-2 py-1 text-xs text-ink-muted">
                {p.name} <span className="text-ink-faint">{p.position}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="rounded-2xl bg-surface p-4 shadow-card">
        <h3 className="mb-3 text-sm font-semibold text-ink">Full draft board</h3>
        <DraftBoard state={state} byId={byId} highlightClock={false} />
      </div>
    </div>
  );
}

function ValueCard({ label, m, positive }: { label: string; m: { player: Player; round: number; valueVsAdp: number | null }; positive: boolean }) {
  const color = positive ? "#8FE06A" : "#FF7E6B";
  return (
    <div className="rounded-2xl bg-surface p-3 shadow-card">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-ink">{m.player.name}</div>
      <div className="mt-0.5 flex items-center gap-2 text-xs text-ink-muted">
        <span>R{m.round} · {m.player.position}</span>
        {m.valueVsAdp != null && (
          <span className="rounded px-1.5 py-0.5 font-semibold" style={{ color, background: `${color}1a` }}>
            {m.valueVsAdp > 0 ? `+${m.valueVsAdp}` : m.valueVsAdp} vs ADP
          </span>
        )}
      </div>
    </div>
  );
}

function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}
