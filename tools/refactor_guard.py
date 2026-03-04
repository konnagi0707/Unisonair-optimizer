#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "tools" / "baselines" / "refactor_guard_baseline.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass
class GuardReport:
    errors: list[str]
    warnings: list[str]
    infos: list[str]

    def __init__(self) -> None:
        self.errors = []
        self.warnings = []
        self.infos = []

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def add_info(self, message: str) -> None:
        self.infos.append(message)

    def ok(self) -> bool:
        return not self.errors

    def print(self) -> None:
        print("== UOA Refactor Guard ==")
        for msg in self.infos:
            print(f"[INFO] {msg}")
        for msg in self.warnings:
            print(f"[WARN] {msg}")
        for msg in self.errors:
            print(f"[ERROR] {msg}")
        print(
            f"-- Summary: info={len(self.infos)} warn={len(self.warnings)} "
            f"error={len(self.errors)} status={'PASS' if self.ok() else 'FAIL'}"
        )


def _normalize_for_compare(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _normalize_for_compare(value[k]) for k in sorted(value.keys())}
    if isinstance(value, list):
        return [_normalize_for_compare(x) for x in value]
    if isinstance(value, float):
        return round(float(value), 6)
    return value


def _collect_diffs(
    expected: Any,
    actual: Any,
    path: str = "root",
    out: list[str] | None = None,
) -> list[str]:
    if out is None:
        out = []
    if type(expected) is not type(actual):
        out.append(f"{path}: type mismatch expected={type(expected).__name__} actual={type(actual).__name__}")
        return out

    if isinstance(expected, dict):
        exp_keys = set(expected.keys())
        act_keys = set(actual.keys())
        only_exp = sorted(exp_keys - act_keys)
        only_act = sorted(act_keys - exp_keys)
        if only_exp:
            out.append(f"{path}: missing keys in actual: {only_exp}")
        if only_act:
            out.append(f"{path}: extra keys in actual: {only_act}")
        for key in sorted(exp_keys & act_keys):
            _collect_diffs(expected[key], actual[key], f"{path}.{key}", out)
        return out

    if isinstance(expected, list):
        if len(expected) != len(actual):
            out.append(f"{path}: list length mismatch expected={len(expected)} actual={len(actual)}")
            return out
        for idx, (e, a) in enumerate(zip(expected, actual)):
            _collect_diffs(e, a, f"{path}[{idx}]", out)
        return out

    if expected != actual:
        out.append(f"{path}: expected={expected!r} actual={actual!r}")
    return out


def _pick_song_key(songs: list[dict[str, Any]]) -> str:
    # Prefer a Green song to match our common test path and front-skin defaults.
    for s in songs:
        if str(s.get("color", "")).upper() == "G":
            key = str(s.get("key", "")).strip()
            if key:
                return key
    if songs:
        key = str(songs[0].get("key", "")).strip()
        if key:
            return key
    raise RuntimeError("no valid songs found in bootstrap payload")


def _build_team_codes(cards: list[dict[str, Any]], center_code: str) -> list[str]:
    out = [center_code]
    for c in cards:
        code = str(c.get("code", "")).strip()
        if not code or code == center_code:
            continue
        out.append(code)
        if len(out) == 5:
            break
    if len(out) != 5:
        raise RuntimeError("failed to build 5-card team from bootstrap cards")
    return out


def _build_summary() -> dict[str, Any]:
    # Important: set env before importing engine module.
    os.environ.setdefault("UOA_DATA_ROOT", str(ROOT / "data"))
    os.environ.setdefault("UOA_RUNTIME_DATA_DIR", str(ROOT / "runtime"))

    from app.engine import ScoringEngine  # noqa: WPS433 (runtime import by design)

    engine = ScoringEngine()
    boot = engine.bootstrap()
    cards = list(boot.get("cards") or [])
    songs = list(boot.get("songs") or [])
    if len(cards) < 5:
        raise RuntimeError("bootstrap cards fewer than 5")
    if not songs:
        raise RuntimeError("bootstrap songs empty")

    vs_centers = [c for c in cards if bool(c.get("is_vs_base"))]
    if not vs_centers:
        raise RuntimeError("no V/S center cards found in bootstrap cards")

    center_code = str(vs_centers[0]["code"])
    song_key = _pick_song_key(songs)
    team_codes = _build_team_codes(cards, center_code=center_code)

    eval_payload = {
        "mode": "single",
        "song_key": song_key,
        "card_codes": team_codes,
        "trials": 1000,
        "seed": 20260227,
        "group_power": 1_800_000,
        "default_member_point": 15000,
        "member_points": {},
        "sort_by": "+2sigma",
        "enable_costume": True,
        "costume_vo": 125,
        "costume_da": 125,
        "costume_pe": 125,
        "costume_skill_per_card": 10,
        "scene_skill_per_card": 430,
        "enable_office": True,
        "office_vo": 0.17,
        "office_da": 0.17,
        "office_pe": 0.17,
        "enable_skin": True,
        "front_skin_profile": "auto",
        "front_skin_rate": 0.08,
        "front_skin_axes": ["auto"],
        "front_skin_target_color": "song",
        "enable_type_bonus": True,
        "type_bonus_rate": 0.30,
        "include_histogram": False,
    }
    eval_out = engine.evaluate(eval_payload)
    eval_row = (eval_out.get("results") or [None])[0]
    if not isinstance(eval_row, dict):
        raise RuntimeError("evaluate returned no result row")

    opt_payload = {
        "mode": "single",
        "song_key": song_key,
        "pool_scope": "all",
        "owned_card_codes": [],
        "exclude_card_codes": [],
        "center_card_codes": [center_code],
        "must_include_codes": [],
        "trials": 1000,
        "seed": 20260227,
        "group_power": 1_800_000,
        "default_member_point": 15000,
        "member_points": {},
        "sort_by": "+2sigma",
        "top_n": 3,
        "center_candidates_per_center": 8,
        "shortlist_size": 32,
        "search_pool_size": 32,
        "preselect_top_m": 30,
        "preselect_all": False,
        "disable_fast_all": True,
        "pre_eval_trials": 100,
        "final_eval_count": 3,
        "candidate_strategy": "axis_t1",
        "opt_min_skill_expected": 3.0,
        "enable_costume": True,
        "costume_vo": 125,
        "costume_da": 125,
        "costume_pe": 125,
        "costume_skill_per_card": 10,
        "scene_skill_per_card": 430,
        "enable_office": True,
        "office_vo": 0.17,
        "office_da": 0.17,
        "office_pe": 0.17,
        "enable_skin": True,
        "front_skin_profile": "auto",
        "front_skin_rate": 0.08,
        "front_skin_axes": ["auto"],
        "front_skin_target_color": "song",
        "enable_type_bonus": True,
        "type_bonus_rate": 0.30,
        "include_histogram": False,
        "histogram_bins": 120,
    }
    opt_out = engine.optimize(opt_payload)
    opt_teams = list(opt_out.get("teams") or [])
    if not opt_teams:
        raise RuntimeError("optimize returned no teams")
    top1 = opt_teams[0]
    top1_result = top1.get("result") or {}

    summary = {
        "meta": {
            "masters_version": str((boot.get("meta") or {}).get("masters_version", "")),
            "card_count": len(cards),
            "song_count": len(songs),
        },
        "scenario": {
            "song_key": song_key,
            "center_code": center_code,
            "eval_team_codes": team_codes,
        },
        "evaluate": {
            "front_pre": int(eval_row.get("front_pre", 0)),
            "front_post": int(eval_row.get("front_post", 0)),
            "sigma": int(eval_row.get("sigma", 0)),
            "dist_p2": int(((eval_row.get("distribution") or {}).get("+2sigma", 0))),
            "scene_effective_total": int((((eval_row.get("scene_power") or {}).get("effective") or {}).get("total", 0))),
            "bonus_member_point_total": int(((eval_row.get("bonuses") or {}).get("member_point_total", 0))),
            "bonus_costume_total": int(((eval_row.get("bonuses") or {}).get("costume_total", 0))),
            "bonus_office_total": int(((eval_row.get("bonuses") or {}).get("office_total", 0))),
            "bonus_skin_total": int(((eval_row.get("bonuses") or {}).get("skin_total", 0))),
            "bonus_type_total": int(((eval_row.get("bonuses") or {}).get("type_bonus_total", 0))),
        },
        "optimize": {
            "candidate_count": int(((opt_out.get("meta") or {}).get("candidate_count", 0))),
            "preselected_count": int(((opt_out.get("meta") or {}).get("preselected_count", 0))),
            "top1_team_codes": [str(x) for x in (top1.get("team_codes") or [])],
            "top1_front_pre": int(top1_result.get("front_pre", 0)),
            "top1_front_post": int(top1_result.get("front_post", 0)),
            "top1_dist_p2": int(((top1_result.get("distribution") or {}).get("+2sigma", 0))),
        },
    }
    return _normalize_for_compare(summary)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="No-regression guard for safe refactor of UOA scoring code.")
    parser.add_argument(
        "--baseline",
        default=str(DEFAULT_BASELINE),
        help=f"Baseline JSON path (default: {DEFAULT_BASELINE})",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Refresh baseline from current runtime output.",
    )
    parser.add_argument(
        "--allow-master-drift",
        action="store_true",
        help="Do not fail when masters_version differs from baseline.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = GuardReport()
    baseline_path = Path(args.baseline).expanduser().resolve()
    current = _build_summary()

    if args.refresh:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            json.dumps(current, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        report.add_info(f"baseline refreshed: {baseline_path}")
        report.print()
        return 0

    if not baseline_path.exists():
        report.add_error(f"baseline file not found: {baseline_path}")
        report.add_info("Run with --refresh first to generate baseline.")
        report.print()
        return 1

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline = _normalize_for_compare(baseline)

    base_ver = str(((baseline.get("meta") or {}).get("masters_version") or "")).strip()
    cur_ver = str(((current.get("meta") or {}).get("masters_version") or "")).strip()
    if base_ver != cur_ver:
        msg = f"masters_version drift: baseline={base_ver} current={cur_ver}"
        if args.allow_master_drift:
            report.add_warning(msg)
        else:
            report.add_error(msg)

    diffs = _collect_diffs(baseline, current)
    if diffs:
        for line in diffs[:40]:
            report.add_error(f"diff: {line}")
        if len(diffs) > 40:
            report.add_error(f"diff: ... truncated, total={len(diffs)}")
    else:
        report.add_info("current output matches baseline snapshot")

    report.print()
    return 0 if report.ok() else 1


if __name__ == "__main__":
    raise SystemExit(main())
