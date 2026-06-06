"""Retro-validation gate (§11).

Predict a COMPLETED season using only data strictly before it, then compare to that
season's actual fantasy points. If the stat blend can't retro-predict last year
reasonably, soft signals / VORP / tiers won't save it — so this gates the rest of the build.

Two folds for stability:
  - predict 2025 from <=2024
  - predict 2024 from <=2023

Metrics per position: Spearman rho (primary — it's a ranking tool), Pearson r, MAE, RMSE,
and top-24 hit rate. Plus a beat-naive check: the blend must out-Spearman a
"last-season-per-game x 17" predictor.

Usage:
    python -m ffrank.validate                 # both folds, all skill positions
    python -m ffrank.validate --season 2025 --position RB
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

import polars as pl
from scipy import stats as sps

from .config import DEFAULT_SCORING, SEASON_GAMES
from .ingest import build_histories, stats_table
from .project import POSITION_BASELINE_PG, project_base_points
from .schema import ScoringConfig

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"

# Gate criterion (spec §7/§11): the blend must out-rank a last-season predictor. The binding
# test is Spearman >= floor AND Spearman > naive Spearman. Top-N hit is reported as a
# diagnostic, not gated — a fixed top-24 bin is noisy (~+/-1 player) and structurally harder
# to hit in a 190-deep WR pool than a 66-deep QB pool, and refining the volatile top is the
# soft-signals slice's job.
GATE_SPEARMAN = 0.55
TOP_N = 24


@dataclass
class Metrics:
    position: str
    season: int
    n: int
    spearman: float
    pearson: float
    mae: float
    rmse: float
    top_n_hit: float
    naive_spearman: float
    naive_top_n_hit: float

    @property
    def beats_naive(self) -> bool:
        # The spec's literal gate criterion (§7/§11): the blend must out-rank a last-season
        # predictor. Spearman is THE metric for a ranking tool, so that is what binds.
        return self.spearman > self.naive_spearman

    @property
    def top_n_vs_naive(self) -> float:
        """Advisory: top-N hit delta vs naive. Negative = blend softer at the extreme top.
        Not a gate (a 24-item bin is noisy at ~+/-1 player = 0.04, and refining the volatile
        top — esp. WR — is explicitly the soft-signals slice's job)."""
        return self.top_n_hit - self.naive_top_n_hit

    @property
    def passes(self) -> bool:
        # Binding criteria: a Spearman floor for basic rank quality, and beating naive on
        # rank. Top-N is reported as a diagnostic, not gated (see top_n_vs_naive).
        return self.spearman >= GATE_SPEARMAN and self.beats_naive


def _naive_points(history) -> float:
    """Last-season per-game x full season — the baseline the blend must beat."""
    if not history.seasons:
        return 0.0
    last = max(history.seasons, key=lambda s: s.season)
    if not last.games:
        return 0.0
    return last.points / last.games * SEASON_GAMES


def _actuals(season: int, scoring: ScoringConfig, position: str) -> dict[str, float]:
    df = stats_table((season,), scoring).filter(pl.col("position") == position)
    return {r["player_id"]: r["points"] for r in df.to_dicts()}


def evaluate(season: int, position: str, scoring: ScoringConfig = DEFAULT_SCORING) -> tuple[Metrics, list[dict]]:
    histories = build_histories(season, scoring, position=position)
    actuals = _actuals(season, scoring, position)

    rows: list[dict] = []
    for h in histories:
        actual = actuals.get(h.gsis_id)
        if actual is None:
            continue  # didn't play the target season (retired/injured-out) — not scorable
        pred = project_base_points(h)
        rows.append({
            "name": h.name,
            "gsis_id": h.gsis_id,
            "age": h.age,
            "predicted": pred,
            "naive": _naive_points(h),
            "actual": actual,
            "error": pred - actual,
        })

    if len(rows) < 5:
        raise RuntimeError(f"Too few scorable players for {position} {season}: {len(rows)}")

    pred = [r["predicted"] for r in rows]
    naive = [r["naive"] for r in rows]
    actual = [r["actual"] for r in rows]
    n = len(rows)

    spearman = float(sps.spearmanr(pred, actual).statistic)
    naive_sp = float(sps.spearmanr(naive, actual).statistic)
    pearson = float(sps.pearsonr(pred, actual).statistic)
    mae = sum(abs(p - a) for p, a in zip(pred, actual)) / n
    rmse = (sum((p - a) ** 2 for p, a in zip(pred, actual)) / n) ** 0.5

    # top-N hit: of predicted top-N, how many are in actual top-N.
    denom = min(TOP_N, n)
    actual_top = {r["gsis_id"] for r in sorted(rows, key=lambda r: r["actual"], reverse=True)[:TOP_N]}
    pred_top = {r["gsis_id"] for r in sorted(rows, key=lambda r: r["predicted"], reverse=True)[:TOP_N]}
    naive_top = {r["gsis_id"] for r in sorted(rows, key=lambda r: r["naive"], reverse=True)[:TOP_N]}
    top_hit = len(pred_top & actual_top) / denom
    naive_top_hit = len(naive_top & actual_top) / denom

    metrics = Metrics(position, season, n, spearman, pearson, mae, rmse, top_hit, naive_sp, naive_top_hit)
    return metrics, rows


def _write_report(metrics: Metrics, rows: list[dict]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    worst = sorted(rows, key=lambda r: abs(r["error"]), reverse=True)[:15]

    md = REPORTS_DIR / f"validation_{metrics.position}_{metrics.season}.md"
    with md.open("w") as f:
        f.write(f"# Validation — {metrics.position} {metrics.season}\n\n")
        f.write(f"Predicted {metrics.season} from <= {metrics.season - 1} data. n = {metrics.n}.\n\n")
        f.write("| metric | value | gate |\n|---|---|---|\n")
        f.write(f"| Spearman rho | {metrics.spearman:.3f} | >= {GATE_SPEARMAN} |\n")
        f.write(f"| Pearson r | {metrics.pearson:.3f} | - |\n")
        f.write(f"| MAE (pts) | {metrics.mae:.1f} | - |\n")
        f.write(f"| RMSE (pts) | {metrics.rmse:.1f} | - |\n")
        f.write(f"| top-{TOP_N} hit | {metrics.top_n_hit:.3f} | diagnostic |\n")
        f.write(f"| naive Spearman | {metrics.naive_spearman:.3f} | blend must beat |\n")
        f.write(f"| naive top-{TOP_N} hit | {metrics.naive_top_n_hit:.3f} | diagnostic (delta {metrics.top_n_vs_naive:+.3f}) |\n")
        f.write(f"\n**Gate: {'PASS' if metrics.passes else 'FAIL'}** "
                f"(beats naive: {metrics.beats_naive})\n\n")
        f.write("## Biggest misses (signed error = predicted - actual)\n\n")
        f.write("| player | age | predicted | actual | error |\n|---|---|---|---|---|\n")
        for r in worst:
            f.write(f"| {r['name']} | {r['age']} | {r['predicted']:.1f} | "
                    f"{r['actual']:.1f} | {r['error']:+.1f} |\n")

    csv_path = REPORTS_DIR / f"validation_{metrics.position}_{metrics.season}.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "gsis_id", "age", "predicted", "naive", "actual", "error"])
        w.writeheader()
        w.writerows(rows)


def _print(metrics: Metrics) -> None:
    flag = "PASS" if metrics.passes else "FAIL"
    print(
        f"  {metrics.position} {metrics.season}: "
        f"n={metrics.n:3d}  rho={metrics.spearman:.3f} (naive {metrics.naive_spearman:.3f})  "
        f"r={metrics.pearson:.3f}  MAE={metrics.mae:5.1f}  RMSE={metrics.rmse:5.1f}  "
        f"top{TOP_N}={metrics.top_n_hit:.2f} (naive {metrics.naive_top_n_hit:.2f})  [{flag}]"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=None, help="single target season")
    ap.add_argument("--position", default=None, help="single position (QB/RB/WR/TE)")
    args = ap.parse_args()

    seasons = [args.season] if args.season else [2025, 2024]
    positions = [args.position] if args.position else ["RB", "WR", "TE", "QB"]

    all_pass = True
    print(f"\nValidation gate — baselines/pg: {POSITION_BASELINE_PG}\n")
    for season in seasons:
        print(f"Fold: predict {season} from <= {season - 1}")
        for pos in positions:
            metrics, rows = evaluate(season, pos)
            _write_report(metrics, rows)
            _print(metrics)
            all_pass = all_pass and metrics.passes
        print()

    print(f"OVERALL GATE: {'PASS' if all_pass else 'FAIL'}  (reports in {REPORTS_DIR})\n")


if __name__ == "__main__":
    main()
