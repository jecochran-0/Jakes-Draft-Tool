import type { Meta } from "@/lib/types";

export function Header({ meta, count }: { meta: Meta; count: number }) {
  const scoring =
    meta.scoring_config?.rec === 1 ? "PPR" : meta.scoring_config?.rec === 0.5 ? "Half-PPR" : "Standard";
  const teams = meta.league_config?.teams ?? 12;
  return (
    <header className="px-4 pt-7 pb-2">
      <div className="flex items-end justify-between">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-lime">
            Fantasy · {meta.season}
          </div>
          <h1 className="font-display text-[34px] font-semibold leading-none text-ink">
            Draft Room
          </h1>
        </div>
        <div className="flex flex-col items-end gap-1 pb-1 text-right">
          <span className="rounded-full bg-lime-soft px-2.5 py-1 text-xs font-semibold text-lime">
            {scoring}
          </span>
          <span className="text-[11px] text-ink-faint">
            {teams}-team · {count} players
          </span>
        </div>
      </div>
    </header>
  );
}
