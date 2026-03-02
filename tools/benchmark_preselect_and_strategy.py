#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.engine import ScoringEngine


TARGET_SONGS = {
    "P": "雨が降ったって",
    "G": "Dead end",
    "B": "東京タワーはどこから見える？",
    "Y": "流れ弾",
    "R": "ノックをするな！",
}


def _find_song_keys(engine: ScoringEngine) -> dict[str, str]:
    out: dict[str, str] = {}
    for color, name in TARGET_SONGS.items():
        hit = next((s for s in engine._songs if s["color"] == color and name in s["name"]), None)
        if hit is None:
            continue
        out[color] = str(hit["key"])
    return out


def _run_case(engine: ScoringEngine, payload: dict[str, Any]) -> dict[str, Any]:
    t0 = time.perf_counter()
    out = engine.optimize(payload)
    elapsed = time.perf_counter() - t0
    top = out["teams"][0]
    return {
        "elapsed_sec": round(elapsed, 3),
        "candidate_count": int(out["meta"]["candidate_count"]),
        "preselected_count": int(out["meta"]["preselected_count"]),
        "top1_codes": list(top["team_codes"]),
        "top1_plus2": int(top["result"]["distribution"]["+2sigma"]),
        "top1_median": int(top["result"]["distribution"]["median"]),
        "meta": out["meta"],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Benchmark preselect leakage and candidate strategy impact.")
    ap.add_argument("--trials", type=int, default=500, help="MonteCarlo trials per team")
    ap.add_argument("--group-power", type=int, default=1_800_000)
    ap.add_argument("--default-member-point", type=int, default=15_000)
    ap.add_argument("--seed", type=int, default=20260227)
    ap.add_argument(
        "--out-dir",
        default="update/bench_preselect_strategy",
        help="Output directory for JSON/MD reports",
    )
    args = ap.parse_args()

    engine = ScoringEngine()
    engine.ensure_loaded()
    songs = _find_song_keys(engine)
    if len(songs) < 5:
        raise SystemExit(f"missing songs for benchmark, got={songs}")

    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir) / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    base = {
        "mode": "single",
        "trials": int(args.trials),
        "group_power": int(args.group_power),
        "default_member_point": int(args.default_member_point),
        "sort_by": "+2sigma",
        "seed": int(args.seed),
        "top_n": 5,
        "center_candidates_per_center": 5,
        "shortlist_size": 50,
        "search_pool_size": 80,
    }

    rows: list[dict[str, Any]] = []
    # Compare only preselect (same fast candidate set).
    scenarios = [
        ("pre30", {"disable_fast_all": False, "preselect_all": False, "preselect_top_m": 30, "candidate_strategy": "default"}),
        ("pre_all", {"disable_fast_all": False, "preselect_all": True, "candidate_strategy": "default"}),
        ("axis_t1_pre_all", {"disable_fast_all": False, "preselect_all": True, "candidate_strategy": "axis_t1"}),
    ]

    for color in ("P", "G", "B", "Y", "R"):
        song_key = songs[color]
        run_rows: dict[str, dict[str, Any]] = {}
        for name, extra in scenarios:
            payload = dict(base)
            payload.update(extra)
            payload["song_key"] = song_key
            run_rows[name] = _run_case(engine, payload)

        baseline = run_rows["pre_all"]
        for name in ("pre30", "pre_all", "axis_t1_pre_all"):
            cur = run_rows[name]
            rows.append(
                {
                    "song_color": color,
                    "song_key": song_key,
                    "scenario": name,
                    "elapsed_sec": cur["elapsed_sec"],
                    "candidate_count": cur["candidate_count"],
                    "preselected_count": cur["preselected_count"],
                    "top1_plus2": cur["top1_plus2"],
                    "top1_median": cur["top1_median"],
                    "same_top1_as_pre_all": bool(cur["top1_codes"] == baseline["top1_codes"]),
                    "delta_plus2_vs_pre_all": int(cur["top1_plus2"] - baseline["top1_plus2"]),
                    "top1_codes": cur["top1_codes"],
                }
            )

    json_path = out_dir / "preselect_strategy_benchmark.json"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = [
        f"# preselect / candidate-strategy benchmark ({ts})",
        "",
        f"- trials: `{args.trials}`",
        f"- group_power: `{args.group_power}`",
        f"- default_member_point: `{args.default_member_point}`",
        "",
        "| color | scenario | elapsed(s) | candidates | preselected | +2σ | median | same_top1_as_pre_all | Δ+2σ vs pre_all |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        md_lines.append(
            f"| {r['song_color']} | {r['scenario']} | {r['elapsed_sec']} | {r['candidate_count']} | "
            f"{r['preselected_count']} | {r['top1_plus2']} | {r['top1_median']} | "
            f"{'Y' if r['same_top1_as_pre_all'] else 'N'} | {r['delta_plus2_vs_pre_all']} |"
        )
    md_path = out_dir / "preselect_strategy_benchmark.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(md_path)
    print(json_path)


if __name__ == "__main__":
    main()
