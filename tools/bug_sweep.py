#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "app" / "static" / "index.html"
APP_JS = ROOT / "app" / "static" / "app.js"
STYLES_CSS = ROOT / "app" / "static" / "styles.css"
PROFILES_JSON = ROOT / "app" / "data" / "account_profiles.json"


@dataclass
class SweepReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    infos: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.errors

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def add_info(self, message: str) -> None:
        self.infos.append(message)

    def print(self) -> None:
        print("== UOA Bug Sweep ==")
        for msg in self.infos:
            print(f"[INFO] {msg}")
        for msg in self.warnings:
            print(f"[WARN] {msg}")
        for msg in self.errors:
            print(f"[ERROR] {msg}")
        print(
            f"-- Summary: info={len(self.infos)} warn={len(self.warnings)} error={len(self.errors)} "
            f"status={'PASS' if self.ok() else 'FAIL'}"
        )


def http_get_json(base_url: str, path: str, timeout_sec: float = 12.0) -> tuple[int, Any]:
    req = urllib.request.Request(base_url + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read().decode("utf-8")
            return int(resp.status), json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except Exception:
            payload = {"detail": body}
        return int(exc.code), payload


def http_post_json(base_url: str, path: str, payload: dict[str, Any], timeout_sec: float = 12.0) -> tuple[int, Any, float]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base_url + path,
        method="POST",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read().decode("utf-8")
            cost_ms = (time.perf_counter() - started) * 1000.0
            return int(resp.status), json.loads(body), cost_ms
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        cost_ms = (time.perf_counter() - started) * 1000.0
        try:
            payload = json.loads(body)
        except Exception:
            payload = {"detail": body}
        return int(exc.code), payload, cost_ms


def short_detail(obj: Any, limit: int = 260) -> str:
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def check_dom_reference_drift(report: SweepReport) -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")
    ids = set(re.findall(r'id="([^"]+)"', html))
    refs = set(re.findall(r'\$\("([A-Za-z0-9_:\-]+)"\)', js))

    missing = sorted(refs - ids)
    if missing:
        report.add_warning(f"JS references missing in HTML: {', '.join(missing)}")
    else:
        report.add_info("DOM id references: no drift detected")


def check_ui_static_rules(report: SweepReport) -> None:
    js = APP_JS.read_text(encoding="utf-8")
    css = STYLES_CSS.read_text(encoding="utf-8")

    if 'resultHint").textContent = `mode=' in js:
        report.add_warning("resultHint still renders mode/sort/trials metadata text")
    else:
        report.add_info("resultHint metadata text is suppressed")

    if "replace-workspace" in css and "height: clamp(360px, 52vh, 620px);" in css:
        report.add_info("replace-workspace uses fixed viewport height clamp")
    else:
        report.add_warning("replace-workspace missing fixed height clamp; modal may stretch with sparse candidates")

    if "replace-current-strip" in css and "minmax(220px, 1fr)" in css:
        report.add_info("replace-current-strip uses compact minmax(220px, 1fr)")
    else:
        report.add_warning("replace-current-strip may be too wide and wrap awkwardly")


def check_profiles_member_mapping(report: SweepReport, cards: list[dict[str, Any]]) -> None:
    if not PROFILES_JSON.exists():
        report.add_warning("account_profiles.json not found")
        return
    try:
        profiles_data = json.loads(PROFILES_JSON.read_text(encoding="utf-8"))
    except Exception as exc:
        report.add_error(f"account_profiles.json parse failed: {exc}")
        return

    profiles = profiles_data.get("profiles", {})
    if not isinstance(profiles, dict):
        report.add_error("account_profiles.json has invalid 'profiles' field")
        return

    member_name_set = {str(c.get("member_name", "")).strip() for c in cards}
    member_name_set.discard("")
    member_norm_set = {str(c.get("member_name_norm", "")).strip() for c in cards}
    member_norm_set.discard("")

    for pname, profile in sorted(profiles.items()):
        p = profile if isinstance(profile, dict) else {}
        points = p.get("member_points", {})
        if not isinstance(points, dict):
            report.add_warning(f"profile '{pname}' member_points is not an object")
            continue
        missing_exact = [k for k in points.keys() if str(k).strip() not in member_name_set]
        if not missing_exact:
            report.add_info(f"profile '{pname}': member point names all match card members")
            continue
        alias_like = [k for k in missing_exact if str(k).strip() in member_norm_set]
        if alias_like:
            report.add_warning(
                f"profile '{pname}': {len(alias_like)} member names rely on norm-alias mapping (sample: {alias_like[:3]})"
            )
        unmatched = [k for k in missing_exact if str(k).strip() not in member_norm_set]
        if unmatched:
            report.add_warning(
                f"profile '{pname}': {len(unmatched)} member names do not match card data (sample: {unmatched[:3]})"
            )


def check_api(base_url: str, report: SweepReport, timeout_sec: float) -> None:
    status, boot = http_get_json(base_url, "/api/bootstrap", timeout_sec=timeout_sec)
    if status != 200:
        report.add_error(f"GET /api/bootstrap failed: status={status} detail={boot}")
        return
    cards = boot.get("cards") or []
    songs = boot.get("songs") or []
    if not cards or not songs:
        report.add_error(f"bootstrap payload invalid: cards={len(cards)} songs={len(songs)}")
        return
    report.add_info(f"bootstrap loaded: cards={len(cards)} songs={len(songs)}")

    pool_scope = ((boot.get("defaults") or {}).get("optimize") or {}).get("pool_scope")
    if pool_scope != "owned":
        report.add_error(f"defaults.optimize.pool_scope expected 'owned' but got '{pool_scope}'")
    else:
        report.add_info("defaults.optimize.pool_scope = owned")

    first_cards = cards[:5]
    song_key = str(songs[0].get("key") or "")
    eval_payload = {
        "card_codes": [str(c.get("code")) for c in first_cards],
        "song_key": song_key,
        "mode": "single",
        "trials": 500,
        "sort_by": "+2sigma",
        "group_power": 1_800_000,
        "default_member_point": 15000,
        "member_points": {str(c.get("member_name")): 15000 for c in first_cards},
    }
    status, data, cost_ms = http_post_json(base_url, "/api/evaluate", eval_payload, timeout_sec=timeout_sec)
    if status != 200:
        report.add_error(f"POST /api/evaluate failed: status={status} detail={data}")
    else:
        result_count = len(data.get("results") or [])
        if result_count < 1:
            report.add_error("POST /api/evaluate returned empty results")
        else:
            report.add_info(f"/api/evaluate ok: results={result_count} in {cost_ms:.1f}ms")

    opt_payload = {
        "mode": "single",
        "song_key": song_key,
        "trials": 100,
        "sort_by": "+2sigma",
        "group_power": 1_800_000,
        "pool_scope": "owned",
        "owned_card_codes": [],
        "top_n": 5,
    }
    status, data, cost_ms = http_post_json(base_url, "/api/optimize", opt_payload, timeout_sec=timeout_sec)
    if status != 400:
        report.add_error(
            "POST /api/optimize(owned empty) expected 400 "
            f"but got {status}; detail={short_detail(data)}"
        )
    else:
        detail = str(data.get("detail") or "")
        if "owned_card_codes" not in detail:
            report.add_warning(f"owned-empty optimize returned 400 but unexpected detail: {detail}")
        report.add_info(f"/api/optimize owned-empty fast-fail in {cost_ms:.1f}ms")

    # Data freshness check for known song expected by users.
    song_titles = [str(s.get("title") or "").lower() for s in songs]
    has_iwtc = any("i want tomorrow to come" in t for t in song_titles)
    if not has_iwtc:
        report.add_warning("song list does not include 'I want tomorrow to come' (data source may be outdated)")

    check_profiles_member_mapping(report, cards)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run regression-style bug sweep for UOA scoring app.")
    parser.add_argument("--host", default="127.0.0.1", help="API host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="API port (default: 8765)")
    parser.add_argument("--timeout", type=float, default=12.0, help="HTTP timeout seconds (default: 12)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_url = f"http://{args.host}:{args.port}"
    report = SweepReport()

    check_dom_reference_drift(report)
    check_ui_static_rules(report)
    check_api(base_url, report, timeout_sec=float(args.timeout))

    report.print()
    return 0 if report.ok() else 1


if __name__ == "__main__":
    raise SystemExit(main())
