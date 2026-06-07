"use client";

import { useMemo, useState } from "react";
import { POSITIONS, POSITION_COLOR, tierColor } from "@/lib/format";
import type { Contract, Player, Position } from "@/lib/types";
import { Header } from "./Header";
import { PlayerDetail } from "./PlayerDetail";
import { PlayerRow } from "./PlayerRow";
import { SoftSignals } from "./SoftSignals";
import { Pill } from "./ui";

type View = "overall" | "position" | "values" | "soft";

export function DraftRoom({ data }: { data: Contract }) {
  const players = data.players;
  const [view, setView] = useState<View>("overall");
  const [pos, setPos] = useState<Position>("RB");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Player | null>(null);

  const q = query.trim().toLowerCase();
  const byName = (p: Player) => !q || p.name.toLowerCase().includes(q);

  const overall = useMemo(
    () => players.filter(byName).sort((a, b) => (a.projection.overall_rank ?? 1e9) - (b.projection.overall_rank ?? 1e9)),
    [players, q],
  );

  const positionList = useMemo(
    () =>
      players
        .filter((p) => p.position === pos && byName(p))
        .sort((a, b) => (a.projection.position_rank ?? 1e9) - (b.projection.position_rank ?? 1e9)),
    [players, pos, q],
  );

  const { steals, reaches } = useMemo(() => {
    const priced = players.filter((p) => p.market?.value_vs_adp != null);
    const steals = [...priced].sort((a, b) => b.market!.value_vs_adp! - a.market!.value_vs_adp!).slice(0, 25);
    const reaches = [...priced].sort((a, b) => a.market!.value_vs_adp! - b.market!.value_vs_adp!).slice(0, 25);
    return { steals, reaches };
  }, [players]);

  return (
    <div className="mx-auto min-h-screen max-w-[680px] pb-24">
      <Header meta={data.meta} count={players.length} />

      {/* sticky controls */}
      <div className="sticky top-0 z-20 -mx-0 bg-base/85 px-4 pb-3 pt-2 backdrop-blur-md">
        <div className="flex gap-2 overflow-x-auto pb-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <Pill active={view === "overall"} onClick={() => setView("overall")}>
            Overall
          </Pill>
          <Pill active={view === "position"} onClick={() => setView("position")}>
            By Position
          </Pill>
          <Pill active={view === "values"} onClick={() => setView("values")}>
            Values
          </Pill>
          <Pill active={view === "soft"} onClick={() => setView("soft")}>
            Soft Signals
          </Pill>
        </div>

        {view === "position" && (
          <div className="flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {POSITIONS.map((p) => (
              <Pill key={p} active={pos === p} accent={POSITION_COLOR[p]} onClick={() => setPos(p)}>
                {p}
              </Pill>
            ))}
          </div>
        )}

        {(view === "overall" || view === "position") && (
          <div className="relative mt-1">
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint">⌕</span>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search players…"
              className="w-full rounded-xl bg-surface-2 py-2.5 pl-9 pr-3 text-sm text-ink placeholder:text-ink-faint focus:outline-none focus:ring-1 focus:ring-lime/40"
            />
          </div>
        )}
      </div>

      {/* body */}
      <div className="px-4">
        {view === "overall" && <List players={overall} rankMode="overall" onPick={setSelected} />}

        {view === "position" && <TieredList players={positionList} onPick={setSelected} />}

        {view === "values" && (
          <div className="space-y-6">
            <ValueGroup title="Best values" subtitle="We rank them earlier than the market drafts them" players={steals} onPick={setSelected} />
            <ValueGroup title="Biggest reaches" subtitle="Market drafts them earlier than we rank them" players={reaches} onPick={setSelected} />
          </div>
        )}

        {view === "soft" && <SoftSignals players={players} teamSituations={data.meta.team_situations} />}
      </div>

      <PlayerDetail player={selected} onClose={() => setSelected(null)} />
    </div>
  );
}

function List({ players, rankMode, onPick }: { players: Player[]; rankMode: "overall" | "position"; onPick: (p: Player) => void }) {
  if (players.length === 0) return <Empty />;
  return (
    <div className="space-y-1.5">
      {players.map((p) => (
        <PlayerRow key={p.id} player={p} rankMode={rankMode} onClick={() => onPick(p)} />
      ))}
    </div>
  );
}

function TieredList({ players, onPick }: { players: Player[]; onPick: (p: Player) => void }) {
  if (players.length === 0) return <Empty />;
  const out: React.ReactNode[] = [];
  let lastTier: number | null = null;
  for (const p of players) {
    const t = p.projection.tier ?? 0;
    if (t !== lastTier) {
      out.push(
        <div key={`t${t}`} className="flex items-center gap-2 px-1 pb-1.5 pt-4 first:pt-1">
          <span className="h-2 w-2 rounded-full" style={{ background: tierColor(t) }} />
          <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: tierColor(t) }}>
            Tier {t}
          </span>
          <span className="h-px flex-1 bg-line" />
        </div>,
      );
      lastTier = t;
    }
    out.push(<PlayerRow key={p.id} player={p} rankMode="position" onClick={() => onPick(p)} />);
  }
  return <div className="space-y-1.5">{out}</div>;
}

function ValueGroup({ title, subtitle, players, onPick }: { title: string; subtitle: string; players: Player[]; onPick: (p: Player) => void }) {
  return (
    <div>
      <h2 className="px-1 text-base font-bold text-ink">{title}</h2>
      <p className="mb-2.5 px-1 text-xs text-ink-muted">{subtitle}</p>
      <div className="space-y-1.5">
        {players.map((p) => (
          <PlayerRow key={p.id} player={p} rankMode="overall" onClick={() => onPick(p)} />
        ))}
      </div>
    </div>
  );
}

function Empty() {
  return <div className="py-16 text-center text-sm text-ink-faint">No players match.</div>;
}
