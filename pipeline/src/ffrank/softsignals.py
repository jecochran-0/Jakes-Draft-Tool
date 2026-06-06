"""Soft signals (spec §6b, §7, §8) — $0 human-in-the-loop LLM adjustment.

Situational judgment the stats can't see (scheme fit, coaching/OC changes, QB quality, role)
becomes a per-player `soft_score` multiplier: adjusted_points = base_points × soft_score. The
board then re-ranks on adjusted_points (ranking.ranking_metric already prefers it).

Cost = $0: the pipeline EMITS prompts; the user pastes them into a Claude chat and pastes the
JSON back. Three steps (see README / module functions):
  A. draft_team_table_prompt()  -> Claude drafts pipeline/data/team_situations.json (~32 rows)
  B. emit_player_prompts()       -> batched per-player prompts -> Claude -> data/soft_scores.json
  C. load_soft_scores()+apply_soft_scores() -> adjusted_points -> re-rank

Decisions: Vegas is an LLM INPUT fact only (no separate multiplier); soft_score is clamped to
[0.85, 1.15] in Python regardless of what the LLM returned.
"""
from __future__ import annotations

import json
from pathlib import Path

from .schema import Player, Situation
from .vegas import TEAM_ABBR

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
TEAM_TABLE_PATH = DATA_DIR / "team_situations.json"

NFL_TEAMS = sorted(set(TEAM_ABBR.values()))

SOFT_MIN, SOFT_MAX = 0.85, 1.15

# Neutral defaults for any team missing from the curated table.
_NEUTRAL_TEAM = {"qb_tier": 3, "oc_change": False, "scheme": "", "notes": ""}

# The analyst prompt — spec §7c, verbatim. Reused unchanged across every batch.
SYSTEM_PROMPT = """\
You are a fantasy football projection analyst. Your job is to assess
SITUATIONAL factors that raw statistics miss, and output a single
multiplier that adjusts a player's stat-based point projection.

You are NOT projecting points. A separate model already did that from
historical stats (for veterans) or draft capital and opportunity (for
rookies). Your ONLY job is to capture what the numbers can't see:
scheme fit, coaching changes, QB quality changes, and role changes.

## Output format
Respond with ONLY valid JSON, no preamble, no markdown. Return one
object per player. Echo the exact `id` you were given. Return ALL
players — do not skip any.

[
  { "id": "<echoed id>",
    "soft_score": <number between 0.85 and 1.15>,
    "soft_reasoning": "<one sentence, max 25 words, citing the
     specific factor(s) driving the adjustment>" }
]

## The multiplier scale
- 1.00 = neutral. Situation neither helps nor hurts beyond what stats
  already reflect. THIS IS YOUR DEFAULT. Most players are near 1.00.
- 1.01-1.07 = modest positive (good scheme fit, stable QB upgrade,
  expanded role).
- 1.08-1.15 = strong positive. RESERVE for clear, specific reasons
  (vacated 70%+ of team targets, elite scheme fit). This is the ceiling.
- 0.93-0.99 = modest negative (QB downgrade, new committee).
- 0.85-0.92 = strong negative. Reserve for clear reasons (lost starting
  role, major QB downgrade, scheme actively misfits the player).

## Hard rules
- NEVER output below 0.85 or above 1.15. Absolute bounds.
- Default to 1.00 when factors are mixed, unclear, or absent. Do not
  manufacture an adjustment to seem useful. 1.00 is a valid, common,
  correct answer.
- Base the score ONLY on the situational facts provided. Do NOT use
  outside knowledge of the player's stats or reputation — the stat
  model already accounts for production.
- Offsetting factors should net toward 1.00 (a scheme upgrade plus a
  QB downgrade is roughly neutral).
- Reasoning must name the specific factor, not be generic.
  Good: "New OC's zone-heavy scheme inflates RB volume."
  Bad: "Good situation this year."

## For ROOKIES specifically
The stat model gave this player a base projection from draft capital
and depth-chart opportunity. Your multiplier should reflect scheme fit
and role clarity ONLY — do not re-reward draft capital (already counted)
or penalize the simple fact of being a rookie (already counted).
"""


# ----- Team-situation table (step A) -----------------------------------------------------

def load_team_table(path: Path = TEAM_TABLE_PATH) -> dict[str, dict]:
    """team abbrev -> {qb_tier, oc_change, scheme, notes}. Neutral defaults for missing teams."""
    table: dict[str, dict] = {}
    if path.exists():
        rows = json.loads(path.read_text())
        for r in rows:
            team = r.get("team")
            if team:
                table[team] = {**_NEUTRAL_TEAM, **{k: r.get(k, _NEUTRAL_TEAM[k]) for k in _NEUTRAL_TEAM}}
    return table


def team_row(table: dict[str, dict], team: str) -> dict:
    return table.get(team, _NEUTRAL_TEAM)


def draft_team_table_prompt() -> str:
    """Prompt for Claude to draft the 32-team situation table (step A). Strict JSON out."""
    teams = ", ".join(NFL_TEAMS)
    return f"""\
You are building a fantasy-football team-situation reference table for the 2026 NFL season.
For EACH of the 32 teams below, assess the SLOW-MOVING situational facts that matter for
fantasy projections. Output ONLY a valid JSON array, no preamble, no markdown.

Teams (echo the exact abbreviation): {teams}

For each team return:
{{
  "team": "<abbrev>",
  "qb_tier": <integer 1-5, 1=elite (MVP-caliber), 3=average starter, 5=replacement/uncertain>,
  "oc_change": <true if the offensive coordinator/play-caller changed this offseason, else false>,
  "scheme": "<short phrase, e.g. 'zone-heavy run, play-action' or 'spread air-raid'>",
  "notes": "<one short clause on any role/scheme context that affects skill players>"
}}

Return all 32 teams. Base it on the most current information you have; if uncertain on a team,
use qb_tier 3, oc_change false, and say so in notes. JSON array only.
"""


# ----- Per-player prompts (step B) -------------------------------------------------------

def _player_kind(p: Player) -> str:
    return "Rookie" if p.is_rookie else "Veteran"


def situation_facts(p: Player, row: dict) -> str:
    """The §7d per-player facts block fed under the system prompt.

    Vegas team total is deliberately NOT included: it's applied mechanically in
    vegas.finalize_adjusted (for rookies/team-changers). Putting it here too would double-count
    it. The LLM's job is the rest — scheme fit, coaching/QB changes, role clarity.
    """
    oc = "CHANGED" if row.get("oc_change") else "stable"
    scheme = row.get("scheme") or "n/a"
    tgt = p.raw_stats.target_share
    snap = p.raw_stats.snap_share
    tgt_str = f"{tgt:.0%}" if tgt is not None else "n/a"
    snap_str = f"{snap:.0%}" if snap is not None else "n/a"
    age = f"{p.age:.0f}" if p.age is not None else "n/a"
    return (
        f"id: {p.id}\n"
        f"Player: {p.name} | {p.position} | {p.team} | Age {age} | {_player_kind(p)}\n"
        f"Situational facts:\n"
        f"- Offensive coordinator: {oc} (scheme: {scheme})\n"
        f"- QB tier (1=elite, 5=replacement): {row.get('qb_tier', 3)}\n"
        f"- Role signals last year: snap share {snap_str}, target share {tgt_str}\n"
        f"- Team note: {row.get('notes') or 'n/a'}"
    )


def emit_player_prompts(players: list[Player], table: dict[str, dict], out_dir: Path,
                        batch_size: int = 45, limit: int = 200) -> list[Path]:
    """Write batched prompt files for the top `limit` players (by overall_rank). Returns paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ranked = sorted(players, key=lambda p: p.projection.overall_rank or 10**9)[:limit]
    batches = [ranked[i:i + batch_size] for i in range(0, len(ranked), batch_size)]
    paths: list[Path] = []
    for n, batch in enumerate(batches, 1):
        facts = "\n\n".join(situation_facts(p, team_row(table, p.team)) for p in batch)
        body = (
            f"{SYSTEM_PROMPT}\n\n"
            f"## Players to score — batch {n} of {len(batches)} ({len(batch)} players)\n\n"
            f"{facts}\n"
        )
        path = out_dir / f"soft_batch_{n}.txt"
        path.write_text(body)
        paths.append(path)
    return paths


# ----- Merge scores (step C) -------------------------------------------------------------

def _clamp(x: float) -> float:
    return max(SOFT_MIN, min(SOFT_MAX, x))


def load_soft_scores(path: Path) -> dict[str, tuple[float, str]]:
    """Parse the pasted [{id, soft_score, soft_reasoning}] array; clamp scores; key by id."""
    rows = json.loads(Path(path).read_text())
    scores: dict[str, tuple[float, str]] = {}
    for r in rows:
        pid = r.get("id")
        if pid is None or r.get("soft_score") is None:
            continue
        scores[pid] = (_clamp(float(r["soft_score"])), r.get("soft_reasoning", ""))
    return scores


def attach_situation(players: list[Player], table: dict[str, dict]) -> None:
    """Copy qb_tier / oc_change from the team table onto each player's situation (LLM-independent)."""
    for p in players:
        row = team_row(table, p.team)
        if p.situation is None:
            p.situation = Situation()
        p.situation.qb_tier = row.get("qb_tier")
        p.situation.oc_change = bool(row.get("oc_change"))


def apply_soft_scores(players: list[Player], scores: dict[str, tuple[float, str]]) -> int:
    """Set soft_score/reasoning for matched players. adjusted_points is computed later by
    vegas.finalize_adjusted (which composes soft x Vegas). Returns count matched."""
    n = 0
    for p in players:
        hit = scores.get(p.id)
        if hit is None:
            continue
        soft, reasoning = hit
        if p.situation is None:
            p.situation = Situation()
        p.situation.soft_score = soft
        p.situation.soft_reasoning = reasoning
        n += 1
    return n


def audit(players: list[Player], top: int = 15) -> list[Player]:
    """Biggest LLM movers by |adjusted − base| (spec §9), for human review of outliers."""
    moved = [p for p in players if p.projection.adjusted_points is not None]
    moved.sort(key=lambda p: abs(p.projection.adjusted_points - p.projection.base_points), reverse=True)
    return moved[:top]


# ----- CLI: step A (draft the team table) ------------------------------------------------

def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Soft-signals helpers (step A: draft the team table)")
    ap.add_argument("command", choices=["draft-team-table"])
    ap.parse_args()

    out_dir = Path(__file__).resolve().parents[2] / "output" / "prompts"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "team_table_prompt.txt"
    path.write_text(draft_team_table_prompt())
    print(f"Wrote team-table draft prompt -> {path}")
    print("Paste it into a Claude chat, then save the JSON array to:")
    print(f"  {TEAM_TABLE_PATH}")


if __name__ == "__main__":
    main()
