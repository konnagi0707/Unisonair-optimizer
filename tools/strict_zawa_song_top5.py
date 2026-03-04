#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import itertools
import heapq
import math
import re
from pathlib import Path
from typing import Any

import optimize_vs_base_teams as opt
import zawa_score_model as zsm


def _slug(text: str) -> str:
    t = re.sub(r"\s+", "_", str(text or "").strip())
    t = re.sub(r"[^0-9A-Za-z_\-]+", "", t)
    if t:
        return t
    checksum = sum(ord(ch) for ch in str(text or "song"))
    return f"song_{checksum}"


def _parse_exclude(raw: str) -> set[str] | None:
    if not str(raw or "").strip():
        return None
    names = re.split(r"[,\n;|/]+", raw)
    out = {opt._normalize_name(x) for x in names if opt._normalize_name(x)}
    return out or None


def _type_bonus_total(cards: list[opt.Card], song_color: str, rate: float) -> int:
    total = 0
    for c in cards:
        if song_color != "ALL" and c.color != song_color:
            continue
        total += int(math.ceil(c.vo * rate))
        total += int(math.ceil(c.da * rate))
        total += int(math.ceil(c.pe * rate))
    return int(total)


def _parse_axes(raw: str) -> set[str]:
    axes = {x.strip().lower() for x in str(raw or "").split(",") if x.strip()}
    if not axes:
        return set()
    valid = {"vo", "da", "pe"}
    if not axes.issubset(valid):
        raise SystemExit(f"invalid axes: {raw}")
    return axes


def _center_focus_axes(center: opt.Card) -> set[str]:
    rule = center.vs_rule
    mode = (rule.mode if rule else "").strip()
    if mode == "sum_vo":
        return {"vo"}
    if mode == "sum_da":
        return {"da"}
    if mode == "sum_pe":
        return {"pe"}
    if mode == "sum_vo_da":
        return {"vo", "da"}
    if mode == "sum_vo_pe":
        return {"vo", "pe"}
    if mode == "sum_da_pe":
        return {"da", "pe"}
    return {"vo", "da", "pe"}


def _office_bonus_total(cards: list[opt.Card], vo_rate: float, da_rate: float, pe_rate: float) -> int:
    total = 0
    for c in cards:
        total += int(math.ceil(float(c.vo) * float(vo_rate)))
        total += int(math.ceil(float(c.da) * float(da_rate)))
        total += int(math.ceil(float(c.pe) * float(pe_rate)))
    return int(total)


def _skin_bonus_total(
    cards: list[opt.Card],
    *,
    song_color: str,
    rate: float,
    axes: set[str],
    target_color_mode: str,
) -> int:
    if rate <= 0.0 or not axes:
        return 0
    total = 0
    target = (target_color_mode or "song").strip().lower()
    for c in cards:
        if target == "song":
            if song_color != "ALL" and c.color != song_color:
                continue
        elif target == "all":
            pass
        else:
            tc = target.upper()
            if tc != "ALL" and c.color != tc:
                continue
        if "vo" in axes:
            total += int(math.ceil(float(c.vo) * float(rate)))
        if "da" in axes:
            total += int(math.ceil(float(c.da) * float(rate)))
        if "pe" in axes:
            total += int(math.ceil(float(c.pe) * float(rate)))
    return int(total)


def _build_skill_profiles(team: opt.TeamResult, song_color: str) -> list[zsm.SkillProfile]:
    color_mult, member_mult = opt._collect_skill_rate_multipliers(team.cards, team.center)
    profiles: list[zsm.SkillProfile] = []
    for c in team.cards:
        proc_mult = opt._card_skill_proc_multiplier(c, team.center, color_mult, member_mult)
        profiles.append(
            zsm.parse_card_skill_profile(
                skill_desc=c.skill_desc,
                card_color=c.color,
                song_color=song_color,
                proc_multiplier=proc_mult,
            )
        )
    return profiles


def _skill_frame_expected(frame: zsm.SkillFrame) -> tuple[float, float]:
    if frame.interval <= 0 or frame.duration <= 0 or frame.proc_pct <= 0:
        return 0.0, 0.0
    proc = max(0.0, min(0.99, float(frame.proc_pct) / 100.0))
    active_ratio = max(0.0, min(1.0, proc * float(frame.duration) / float(frame.interval)))
    score_ev = float(frame.score_pct) * active_ratio
    combo_ev = float(frame.combo_pct) * active_ratio
    return score_ev, combo_ev


def _song_quick_objective(
    team_cards: list[opt.Card],
    center: opt.Card,
    *,
    song_color: str,
    member_point: int,
    type_bonus_rate: float,
    costume_vo: int,
    costume_da: int,
    costume_pe: int,
    office_vo: float,
    office_da: float,
    office_pe: float,
    front_skin_rate: float,
    front_skin_axes: set[str],
    front_skin_target_color: str,
    scene_skill_per_card: int,
    costume_skill_per_card: int,
    profile_cache: dict[tuple[str, str, float], zsm.SkillProfile],
) -> float:
    eff_vo, eff_da, eff_pe = opt._compute_effective_stats(team_cards, center)
    team_power = int(eff_vo + eff_da + eff_pe)
    n = len(team_cards)
    costume_total = int((costume_vo + costume_da + costume_pe) * n)
    office_total = _office_bonus_total(team_cards, office_vo, office_da, office_pe)
    skin_axes = front_skin_axes or _center_focus_axes(center)
    skin_total = _skin_bonus_total(
        team_cards,
        song_color=song_color,
        rate=front_skin_rate,
        axes=skin_axes,
        target_color_mode=front_skin_target_color,
    )
    skill_total = int((scene_skill_per_card + costume_skill_per_card) * n)
    front_pre = int(team_power + member_point * n + costume_total + office_total + skin_total + skill_total)
    type_bonus = _type_bonus_total(team_cards, song_color, type_bonus_rate)
    front_post = int(front_pre + type_bonus)

    color_mult, member_mult = opt._collect_skill_rate_multipliers(team_cards, center)
    ev_score = 0.0
    ev_combo = 0.0
    for c in team_cards:
        proc_mult = opt._card_skill_proc_multiplier(c, center, color_mult, member_mult)
        pkey = (c.code, song_color, round(float(proc_mult), 4))
        profile = profile_cache.get(pkey)
        if profile is None:
            profile = zsm.parse_card_skill_profile(
                skill_desc=c.skill_desc,
                card_color=c.color,
                song_color=song_color,
                proc_multiplier=proc_mult,
            )
            profile_cache[pkey] = profile

        s1, c1 = _skill_frame_expected(profile.front)
        s2, c2 = _skill_frame_expected(profile.back)
        ev_score += s1 + s2
        ev_combo += c1 + c2

    # Keep scaling consistent with legacy objective so ordering remains stable.
    return float(front_post) * (1.0 + ev_score / 300.0) * (1.0 + ev_combo / 100.0)


def _augment_pool_for_song(
    center: opt.Card,
    all_cards: list[opt.Card],
    base_pool: list[opt.Card],
    *,
    song_color: str,
    target_size: int,
) -> list[opt.Card]:
    pool: list[opt.Card] = list(base_pool)
    seen = {c.code for c in pool}

    key_members = {center.member_name_norm}
    key_members.update(center.leader_skill_rate_member.keys())
    key_members.update(c.member_name_norm for c in base_pool if opt._is_veaut_card(c))

    extras: list[opt.Card] = []

    def _member_sort_key(c: opt.Card) -> tuple[int, int, int, float, int]:
        title_key = str(c.title).lower()
        return (
            1 if (song_color == "ALL" or c.color == song_color) else 0,
            1 if opt._is_veaut_card(c) else 0,
            1 if "s.teller" in title_key else 0,
            float(c.skill_expected),
            int(c.vo) + int(c.da) + int(c.pe),
        )

    for m in key_members:
        member_cards = [
            c
            for c in all_cards
            if c.code != center.code and c.code not in seen and c.member_name_norm == m
        ]
        member_cards.sort(key=_member_sort_key, reverse=True)
        extras.extend(member_cards[:6])

    same_color_cards = [
        c
        for c in all_cards
        if c.code != center.code and c.code not in seen and (song_color == "ALL" or c.color == song_color)
    ]
    same_color_cards.sort(
        key=lambda c: (float(c.skill_expected), int(c.vo) + int(c.da) + int(c.pe)),
        reverse=True,
    )
    extras.extend(same_color_cards[:24])

    for c in extras:
        if c.code in seen:
            continue
        seen.add(c.code)
        pool.append(c)
        if len(pool) >= target_size:
            break

    return pool


def _build_team_candidates_songaware(
    center: opt.Card,
    all_cards: list[opt.Card],
    *,
    song_color: str,
    member_point: int,
    type_bonus_rate: float,
    costume_vo: int,
    costume_da: int,
    costume_pe: int,
    office_vo: float,
    office_da: float,
    office_pe: float,
    front_skin_rate: float,
    front_skin_axes: set[str],
    front_skin_target_color: str,
    scene_skill_per_card: int,
    costume_skill_per_card: int,
    shortlist_size: int,
    search_pool_size: int,
    topk: int,
) -> list[opt.TeamResult]:
    ranked, base_pool = opt._build_search_pool(center, all_cards, shortlist_size, search_pool_size)
    if len(base_pool) < 4:
        team = [center] + base_pool[:4]
        return [opt._objective_for_team(team, center)]

    target_pool_size = max(int(search_pool_size) + 12, len(base_pool))
    pool = _augment_pool_for_song(
        center=center,
        all_cards=all_cards,
        base_pool=base_pool,
        song_color=song_color,
        target_size=target_pool_size,
    )

    if len(pool) < 4:
        team = [center] + ranked[:4]
        return [opt._objective_for_team(team, center)]

    # Keep per-center combination count bounded for runtime.
    if len(pool) > 52:
        pool = pool[:52]

    profile_cache: dict[tuple[str, str, float], zsm.SkillProfile] = {}
    best_heap: list[tuple[float, int, list[opt.Card]]] = []
    counter = 0
    want = max(1, int(topk))

    for combo in itertools.combinations(pool, 4):
        team_cards = [center, *combo]
        obj = _song_quick_objective(
            team_cards,
            center,
            song_color=song_color,
            member_point=member_point,
            type_bonus_rate=type_bonus_rate,
            costume_vo=costume_vo,
            costume_da=costume_da,
            costume_pe=costume_pe,
            office_vo=office_vo,
            office_da=office_da,
            office_pe=office_pe,
            front_skin_rate=front_skin_rate,
            front_skin_axes=front_skin_axes,
            front_skin_target_color=front_skin_target_color,
            scene_skill_per_card=scene_skill_per_card,
            costume_skill_per_card=costume_skill_per_card,
            profile_cache=profile_cache,
        )
        counter += 1
        item = (obj, counter, team_cards)
        if len(best_heap) < want:
            heapq.heappush(best_heap, item)
            continue
        if obj > best_heap[0][0]:
            heapq.heapreplace(best_heap, item)

    if not best_heap:
        team = [center] + ranked[:4]
        return [opt._objective_for_team(team, center)]

    best_heap.sort(key=lambda x: x[0], reverse=True)
    out: list[opt.TeamResult] = []
    seen: set[tuple[str, ...]] = set()
    for obj, _idx, team_cards in best_heap:
        key = tuple(sorted(c.code for c in team_cards))
        if key in seen:
            continue
        seen.add(key)
        t = opt._objective_for_team(team_cards, center)
        t.objective = float(obj)
        out.append(t)
        if len(out) >= want:
            break

    if not out:
        team = [center] + ranked[:4]
        out = [opt._objective_for_team(team, center)]
    return out


def _run_song_sim(
    master: dict[str, Any],
    team: opt.TeamResult,
    song: opt.Song,
    *,
    group_power: int,
    member_point: int,
    type_bonus_rate: float,
    costume_vo: int,
    costume_da: int,
    costume_pe: int,
    office_vo: float,
    office_da: float,
    office_pe: float,
    front_skin_rate: float,
    front_skin_axes: set[str],
    front_skin_target_color: str,
    scene_skill_per_card: int,
    costume_skill_per_card: int,
    trials: int,
    seed: int,
    min_trials_floor: int,
) -> dict[str, int]:
    idx = zsm.find_song_index(
        master,
        name=song.name,
        color_code=song.color,
        level=song.level,
        seconds=song.seconds,
        notes=song.notes,
    )
    if idx < 0:
        raise SystemExit(f"Song not found in zawa master: {song.name} ({song.color})")

    n = len(team.cards)
    costume_total = int((costume_vo + costume_da + costume_pe) * n)
    office_total = _office_bonus_total(team.cards, office_vo, office_da, office_pe)
    skin_axes = front_skin_axes or _center_focus_axes(team.center)
    skin_total = _skin_bonus_total(
        team.cards,
        song_color=song.color,
        rate=front_skin_rate,
        axes=skin_axes,
        target_color_mode=front_skin_target_color,
    )
    skill_total = int((scene_skill_per_card + costume_skill_per_card) * n)
    front_pre = int(team.team_power + member_point * n + costume_total + office_total + skin_total + skill_total)
    type_bonus = _type_bonus_total(team.cards, song.color, type_bonus_rate)
    front_post = int(front_pre + type_bonus)
    profiles = _build_skill_profiles(team, song.color)
    sim = zsm.simulate(
        master=master,
        song_index=idx,
        front_power=front_post,
        group_power=group_power,
        skills=profiles,
        trials=trials,
        seed=seed,
        min_trials_floor=min_trials_floor,
    )
    sim["front_pre"] = int(front_pre)
    sim["front_post"] = int(front_post)
    sim["type_bonus"] = int(type_bonus)
    sim["costume_bonus"] = int(costume_total)
    sim["office_bonus"] = int(office_total)
    sim["skin_bonus"] = int(skin_total)
    sim["skill_stat_bonus"] = int(skill_total)
    return sim


def _team_summary(
    master: dict[str, Any],
    team: opt.TeamResult,
    songs: list[opt.Song],
    *,
    group_power: int,
    member_point: int,
    type_bonus_rate: float,
    costume_vo: int,
    costume_da: int,
    costume_pe: int,
    office_vo: float,
    office_da: float,
    office_pe: float,
    front_skin_rate: float,
    front_skin_axes: set[str],
    front_skin_target_color: str,
    scene_skill_per_card: int,
    costume_skill_per_card: int,
    trials: int,
    seed_base: int,
    min_trials_floor: int = 1000,
) -> dict[str, Any]:
    per_song: list[dict[str, Any]] = []
    center_seed = sum(ord(ch) for ch in str(team.center.code))
    for s in songs:
        team_seed = int(seed_base + int(s.no) * 1009 + center_seed)
        sim = _run_song_sim(
            master,
            team,
            s,
            group_power=group_power,
            member_point=member_point,
            type_bonus_rate=type_bonus_rate,
            costume_vo=costume_vo,
            costume_da=costume_da,
            costume_pe=costume_pe,
            office_vo=office_vo,
            office_da=office_da,
            office_pe=office_pe,
            front_skin_rate=front_skin_rate,
            front_skin_axes=front_skin_axes,
            front_skin_target_color=front_skin_target_color,
            scene_skill_per_card=scene_skill_per_card,
            costume_skill_per_card=costume_skill_per_card,
            trials=trials,
            seed=team_seed,
            min_trials_floor=min_trials_floor,
        )
        per_song.append(
            {
                "song_name": s.name,
                "song_color": s.color,
                "song_level": s.level,
                "song_notes": s.notes,
                "song_seconds": s.seconds,
                "median": int(sim["median"]),
                "plus1": int(sim["+1sigma"]),
                "minus1": int(sim["-1sigma"]),
                "plus2": int(sim["+2sigma"]),
                "minus2": int(sim["-2sigma"]),
                "plus3": int(sim["+3sigma"]),
                "minus3": int(sim["-3sigma"]),
                "min": int(sim["min"]),
                "max": int(sim["max"]),
                "front_pre": int(sim["front_pre"]),
                "front_post": int(sim["front_post"]),
                "type_bonus": int(sim["type_bonus"]),
                "costume_bonus": int(sim["costume_bonus"]),
                "office_bonus": int(sim["office_bonus"]),
                "skin_bonus": int(sim["skin_bonus"]),
                "skill_stat_bonus": int(sim["skill_stat_bonus"]),
            }
        )

    medians = [r["median"] for r in per_song]
    plus1 = [r["plus1"] for r in per_song]
    minus1 = [r["minus1"] for r in per_song]
    plus2 = [r["plus2"] for r in per_song]
    minus2 = [r["minus2"] for r in per_song]
    plus3 = [r["plus3"] for r in per_song]
    minus3 = [r["minus3"] for r in per_song]
    sigmas = [(r["plus1"] - r["minus1"]) / 2.0 for r in per_song]

    avg_plus1 = int(round(sum(plus1) / float(len(plus1))))
    avg_minus1 = int(round(sum(minus1) / float(len(minus1))))
    avg_plus2 = int(round(sum(plus2) / float(len(plus2))))
    avg_minus2 = int(round(sum(minus2) / float(len(minus2))))
    avg_plus3 = int(round(sum(plus3) / float(len(plus3))))
    avg_minus3 = int(round(sum(minus3) / float(len(minus3))))
    avg_sigma = int(round(sum(sigmas) / float(len(sigmas))))
    avg_sigma_from_q = int(round((avg_plus1 - avg_minus1) / 2.0))

    return {
        "center": team.center,
        "team": team,
        "song_count": len(per_song),
        "avg_median": int(round(sum(medians) / float(len(medians)))),
        "avg_plus1": avg_plus1,
        "avg_minus1": avg_minus1,
        "avg_plus2": avg_plus2,
        "avg_minus2": avg_minus2,
        "avg_plus3": avg_plus3,
        "avg_minus3": avg_minus3,
        "avg_sigma": avg_sigma,
        "avg_sigma_from_q": avg_sigma_from_q,
        "front_pre": int(round(sum(r["front_pre"] for r in per_song) / float(len(per_song)))),
        "front_post": int(round(sum(r["front_post"] for r in per_song) / float(len(per_song)))),
        "type_bonus": int(round(sum(r["type_bonus"] for r in per_song) / float(len(per_song)))),
        "costume_bonus": int(round(sum(r["costume_bonus"] for r in per_song) / float(len(per_song)))),
        "office_bonus": int(round(sum(r["office_bonus"] for r in per_song) / float(len(per_song)))),
        "skin_bonus": int(round(sum(r["skin_bonus"] for r in per_song) / float(len(per_song)))),
        "skill_stat_bonus": int(round(sum(r["skill_stat_bonus"] for r in per_song) / float(len(per_song)))),
        "per_song": per_song,
    }


def _fmt_tuple(frame: zsm.SkillFrame) -> str:
    return f"{frame.interval}-{frame.proc_pct:.1f}-{frame.duration}-{frame.combo_pct:.1f}-{frame.score_pct:.1f}"


def _skill_detail_lines(team: opt.TeamResult, song_color: str, type_bonus_rate: float) -> list[str]:
    color_mult, member_mult = opt._collect_skill_rate_multipliers(team.cards, team.center)
    lines: list[str] = []
    for c in team.cards:
        proc_mult = opt._card_skill_proc_multiplier(c, team.center, color_mult, member_mult)
        same_color = (song_color == "ALL") or (c.color == song_color)
        tb_vo = int(math.ceil(c.vo * type_bonus_rate)) if same_color else 0
        tb_da = int(math.ceil(c.da * type_bonus_rate)) if same_color else 0
        tb_pe = int(math.ceil(c.pe * type_bonus_rate)) if same_color else 0
        p = zsm.parse_card_skill_profile(
            skill_desc=c.skill_desc,
            card_color=c.color,
            song_color=song_color,
            proc_multiplier=proc_mult,
        )
        front = _fmt_tuple(p.front)
        back = _fmt_tuple(p.back)
        lines.append(
            f"- {c.member_name}[{c.title}] ({c.color}): expected(base) `{c.skill_expected:.2f}%` | same_color `{same_color}` | 30%bonus `Vo+{tb_vo}/Da+{tb_da}/Pe+{tb_pe}` | rate `{proc_mult:.2f}x` | front `{front}` | back `{back}`"
        )
        lines.append(f"  skill: `{c.skill_desc}`")
    return lines


def _rank_tuple(row: dict[str, Any], rank_by: str) -> tuple[int, int, int]:
    mode = str(rank_by or "plus2").strip().lower()
    if mode == "median":
        return (int(row["avg_median"]), int(row["avg_plus2"]), int(row["avg_minus2"]))
    if mode == "minus2":
        return (int(row["avg_minus2"]), int(row["avg_median"]), int(row["avg_plus2"]))
    # Default and recommended: compare by +2σ.
    return (int(row["avg_plus2"]), int(row["avg_median"]), int(row["avg_minus2"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Strict zawa sigma rerank: song-based top5 team search")
    parser.add_argument("--masters-dir", type=Path, default=None)
    parser.add_argument("--masters-root", type=Path, default=Path("masters"))
    parser.add_argument("--workbook", type=Path, default=Path("UOA大表 新人必看.xlsx"))
    parser.add_argument("--songlist-json", type=Path, default=Path("catalogs/uniair_songlist.json"))
    parser.add_argument("--refresh-songlist", action="store_true")
    parser.add_argument("--song-color", type=str, required=True, help="R/B/G/Y/P/ALL")
    parser.add_argument("--song-name", type=str, required=True, help="Exact song name in game")
    parser.add_argument("--song-level", type=int, default=None)
    parser.add_argument("--active-members-json", type=Path, default=Path("catalogs/active_members_manual_20260227.json"))
    parser.add_argument("--refresh-active-members", action="store_true")
    parser.add_argument("--no-active-filter", action="store_true")
    parser.add_argument("--exclude-members", type=str, default="")
    parser.add_argument("--v-only", action="store_true", default=True)
    parser.add_argument("--shortlist-size", type=int, default=240)
    parser.add_argument("--search-pool-size", type=int, default=36)
    parser.add_argument("--center-candidates", type=int, default=24, help="Song-aware candidates kept per center")
    parser.add_argument(
        "--min-skill-expected",
        type=float,
        default=2.0,
        help="Filter out cards with expected skill value below threshold (default: 2.0)",
    )
    parser.add_argument("--group-power", type=int, default=1_800_000)
    parser.add_argument("--member-point", type=int, default=15_000)
    parser.add_argument("--type-bonus-rate", type=float, default=0.30)
    parser.add_argument("--costume-vo", type=int, default=125)
    parser.add_argument("--costume-da", type=int, default=125)
    parser.add_argument("--costume-pe", type=int, default=125)
    parser.add_argument("--office-vo-rate", type=float, default=0.17)
    parser.add_argument("--office-da-rate", type=float, default=0.17)
    parser.add_argument("--office-pe-rate", type=float, default=0.17)
    parser.add_argument(
        "--front-skin-axes",
        type=str,
        default="auto",
        help="vo,da,pe combination; 'auto' follows center mode axes",
    )
    parser.add_argument(
        "--front-skin-target-color",
        type=str,
        default="song",
        help="song/all/or fixed color code R/B/G/Y/P",
    )
    parser.add_argument("--front-skin-rate", type=float, default=0.08)
    parser.add_argument("--scene-skill-per-card", type=int, default=430)
    parser.add_argument("--costume-skill-per-card", type=int, default=10)
    parser.add_argument("--zawa-master-json", type=Path, default=Path("catalogs/zawa_score_sim_master.json"))
    parser.add_argument("--zawa-refresh-master", action="store_true")
    parser.add_argument("--stage1-trials", type=int, default=2000)
    parser.add_argument("--stage2-trials", type=int, default=10000)
    parser.add_argument("--stage2-topn", type=int, default=20)
    parser.add_argument("--topn", type=int, default=5)
    parser.add_argument(
        "--rank-by",
        type=str,
        default="plus2",
        choices=["plus2", "median", "minus2"],
        help="Ranking metric for both stages (default: plus2 / +2σ)",
    )
    parser.add_argument(
        "--no-dedupe-team-set",
        action="store_true",
        help="Do not dedupe same 5-card set (default: dedupe on)",
    )
    parser.add_argument("--seed", type=int, default=20260227)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    color = args.song_color.strip().upper()
    if color not in {"R", "B", "G", "Y", "P", "ALL"}:
        raise SystemExit(f"invalid --song-color: {args.song_color}")
    skin_axes_arg = str(args.front_skin_axes or "auto").strip().lower()
    skin_axes = set() if skin_axes_arg == "auto" else _parse_axes(skin_axes_arg)

    masters_dir = args.masters_dir or opt._find_latest_masters(args.masters_root)
    active_name_norms: set[str] | None = None
    if not args.no_active_filter:
        active_name_norms = opt._load_active_members(args.active_members_json, refresh=args.refresh_active_members)
    exclude_name_norms = _parse_exclude(args.exclude_members)

    cards, meta = opt._build_cards(
        masters_dir=masters_dir,
        workbook_path=args.workbook,
        active_name_norms=active_name_norms,
        exclude_name_norms=exclude_name_norms,
    )
    before_skill_filter = len(cards)
    cards = [c for c in cards if float(c.skill_expected) >= float(args.min_skill_expected)]
    skill_filtered_out = before_skill_filter - len(cards)
    centers = [c for c in cards if c.is_vs_base and c.vs_rule is not None]
    if args.v_only:
        centers = [c for c in centers if opt._is_veaut_card(c)]
    if not centers:
        raise SystemExit("No centers after filters")

    songs = opt._load_songlist(args.songlist_json, refresh=args.refresh_songlist)
    target_name = opt._normalize_song_name(args.song_name)
    songs = [
        s
        for s in songs
        if s.color == color and opt._normalize_song_name(s.name) == target_name and (args.song_level is None or s.level == args.song_level)
    ]
    if not songs:
        raise SystemExit(f"Song not found in songlist: name={args.song_name} color={color} level={args.song_level}")

    master = zsm.load_master(args.zawa_master_json, refresh=args.zawa_refresh_master)

    teams: list[opt.TeamResult] = []
    for c in centers:
        teams.extend(
            _build_team_candidates_songaware(
                c,
                cards,
                song_color=color,
                member_point=args.member_point,
                type_bonus_rate=args.type_bonus_rate,
                costume_vo=args.costume_vo,
                costume_da=args.costume_da,
                costume_pe=args.costume_pe,
                office_vo=args.office_vo_rate,
                office_da=args.office_da_rate,
                office_pe=args.office_pe_rate,
                front_skin_rate=args.front_skin_rate,
                front_skin_axes=skin_axes,
                front_skin_target_color=args.front_skin_target_color,
                scene_skill_per_card=args.scene_skill_per_card,
                costume_skill_per_card=args.costume_skill_per_card,
                shortlist_size=args.shortlist_size,
                search_pool_size=args.search_pool_size,
                topk=args.center_candidates,
            )
        )
    deduped_team_count = 0
    if not args.no_dedupe_team_set:
        keep: dict[tuple[str, ...], opt.TeamResult] = {}
        for t in teams:
            key = tuple(sorted(c.code for c in t.cards))
            cur = keep.get(key)
            if cur is None or float(t.objective) > float(cur.objective):
                keep[key] = t
        deduped_team_count = len(teams) - len(keep)
        teams = list(keep.values())

    stage1_rows: list[dict[str, Any]] = []
    for t in teams:
        stage1_rows.append(
            _team_summary(
                master,
                t,
                songs,
                group_power=args.group_power,
                member_point=args.member_point,
                type_bonus_rate=args.type_bonus_rate,
                costume_vo=args.costume_vo,
                costume_da=args.costume_da,
                costume_pe=args.costume_pe,
                office_vo=args.office_vo_rate,
                office_da=args.office_da_rate,
                office_pe=args.office_pe_rate,
                front_skin_rate=args.front_skin_rate,
                front_skin_axes=skin_axes,
                front_skin_target_color=args.front_skin_target_color,
                scene_skill_per_card=args.scene_skill_per_card,
                costume_skill_per_card=args.costume_skill_per_card,
                trials=args.stage1_trials,
                seed_base=args.seed,
                min_trials_floor=1,
            )
        )
    stage1_rows.sort(key=lambda r: _rank_tuple(r, args.rank_by), reverse=True)
    shortlisted = stage1_rows[: max(args.topn, args.stage2_topn)]

    stage2_rows: list[dict[str, Any]] = []
    for r in shortlisted:
        stage2_rows.append(
            _team_summary(
                master,
                r["team"],
                songs,
                group_power=args.group_power,
                member_point=args.member_point,
                type_bonus_rate=args.type_bonus_rate,
                costume_vo=args.costume_vo,
                costume_da=args.costume_da,
                costume_pe=args.costume_pe,
                office_vo=args.office_vo_rate,
                office_da=args.office_da_rate,
                office_pe=args.office_pe_rate,
                front_skin_rate=args.front_skin_rate,
                front_skin_axes=skin_axes,
                front_skin_target_color=args.front_skin_target_color,
                scene_skill_per_card=args.scene_skill_per_card,
                costume_skill_per_card=args.costume_skill_per_card,
                trials=args.stage2_trials,
                seed_base=args.seed + 7789,
                min_trials_floor=1000,
            )
        )
    stage2_rows.sort(key=lambda r: _rank_tuple(r, args.rank_by), reverse=True)
    if not args.no_dedupe_team_set:
        uniq: list[dict[str, Any]] = []
        seen_set: set[tuple[str, ...]] = set()
        for r in stage2_rows:
            key = tuple(sorted(c.code for c in r["team"].cards))
            if key in seen_set:
                continue
            seen_set.add(key)
            uniq.append(r)
        top_rows = uniq[: args.topn]
    else:
        top_rows = stage2_rows[: args.topn]

    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"strict_zawa_top{args.topn}_{color}_{_slug(args.song_name)}.csv"
    md_path = out_dir / f"strict_zawa_top{args.topn}_{color}_{_slug(args.song_name)}.md"

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "rank",
                "center",
                "members",
                "avg_median",
                "avg_plus1sigma",
                "avg_minus1sigma",
                "avg_plus2sigma",
                "avg_minus2sigma",
                "avg_plus3sigma",
                "avg_minus3sigma",
                "avg_sigma",
                "avg_sigma_from_q",
                "front_pre",
                "front_post",
                "type_bonus",
                "costume_bonus",
                "office_bonus",
                "skin_bonus",
                "skill_stat_bonus",
            ]
        )
        for i, r in enumerate(top_rows, start=1):
            team: opt.TeamResult = r["team"]
            w.writerow(
                [
                    i,
                    f"{team.center.member_name}[{team.center.title}]",
                    " | ".join(f"{c.member_name}[{c.title}]" for c in team.cards),
                    r["avg_median"],
                    r["avg_plus1"],
                    r["avg_minus1"],
                    r["avg_plus2"],
                    r["avg_minus2"],
                    r["avg_plus3"],
                    r["avg_minus3"],
                    r["avg_sigma"],
                    r["avg_sigma_from_q"],
                    r["front_pre"],
                    r["front_post"],
                    r["type_bonus"],
                    r["costume_bonus"],
                    r["office_bonus"],
                    r["skin_bonus"],
                    r["skill_stat_bonus"],
                ]
            )

    lines: list[str] = []
    lines.append(f"# Strict zawa Top{args.topn}: {args.song_name} ({color})")
    lines.append("")
    lines.append(f"- generated_at: `{ts}`")
    lines.append(f"- masters_version: `{meta['masters_version']}`")
    lines.append(f"- group_power: `{args.group_power}`")
    lines.append(f"- member_point_each: `{args.member_point}`")
    lines.append(f"- type_bonus_rate: `{args.type_bonus_rate}`")
    lines.append(
        f"- costume_bonus_per_member: `Vo+{args.costume_vo}/Da+{args.costume_da}/Pe+{args.costume_pe}`"
    )
    lines.append(
        f"- office_rate: `Vo {args.office_vo_rate*100:.1f}% / Da {args.office_da_rate*100:.1f}% / Pe {args.office_pe_rate*100:.1f}%`"
    )
    lines.append(
        f"- front_skin: `rate {args.front_skin_rate*100:.1f}% / axes {args.front_skin_axes} / target {args.front_skin_target_color}`"
    )
    lines.append(
        f"- skill_stat_per_member: `scene {args.scene_skill_per_card} + costume {args.costume_skill_per_card}`"
    )
    lines.append(f"- active_filter: `{not args.no_active_filter}`")
    lines.append(f"- excluded_members: `{args.exclude_members or '-'}`")
    lines.append(f"- v_only: `{args.v_only}`")
    lines.append(f"- min_skill_expected: `{args.min_skill_expected}`")
    lines.append(f"- center_candidates_per_center: `{args.center_candidates}`")
    lines.append(f"- cards_filtered_by_skill_expected: `{skill_filtered_out}`")
    lines.append(f"- dedupe_same_5card_set: `{not args.no_dedupe_team_set}`")
    lines.append(f"- deduped_team_count: `{deduped_team_count}`")
    lines.append(f"- stage1_trials: `{args.stage1_trials}`")
    lines.append(f"- stage2_trials: `{args.stage2_trials}`")
    lines.append(f"- rank_by: `{args.rank_by}`")
    lines.append("")

    for i, r in enumerate(top_rows, start=1):
        team: opt.TeamResult = r["team"]
        lines.append(f"## Top{i}: {team.center.member_name}[{team.center.title}]")
        lines.append("")
        lines.append(f"- 队长: `{team.center.member_name}[{team.center.title}]` ({team.center.color})")
        lines.append("- 队员: `" + " / ".join(f"{c.member_name}[{c.title}]" for c in team.supports) + "`")
        lines.append(
            f"- 分数分布(平均): median `{r['avg_median']}` | +1σ `{r['avg_plus1']}` | -1σ `{r['avg_minus1']}` | +2σ `{r['avg_plus2']}` | -2σ `{r['avg_minus2']}` | +3σ `{r['avg_plus3']}` | -3σ `{r['avg_minus3']}` | σ `{r['avg_sigma_from_q']}`"
        )
        lines.append(f"- σ校验: `(+1σ - -1σ) / 2 = ({r['avg_plus1']} - {r['avg_minus1']}) / 2 = {r['avg_sigma_from_q']}`")
        lines.append(f"- 进歌前综合力(模型): `{r['front_pre']}`")
        lines.append(f"- 进歌后综合力(模型): `{r['front_post']}` (type bonus `{r['type_bonus']}`)")
        lines.append(
            f"- 进歌前构成拆分: `scene+center {team.team_power} + member {args.member_point*len(team.cards)} + costume {r['costume_bonus']} + office {r['office_bonus']} + front_skin {r['skin_bonus']} + skill_stat {r['skill_stat_bonus']} = {r['front_pre']}`"
        )
        raw_vo = sum(int(c.vo) for c in team.cards)
        raw_da = sum(int(c.da) for c in team.cards)
        raw_pe = sum(int(c.pe) for c in team.cards)
        lines.append(
            f"- 场景卡合算(不含成员分): `Vo {raw_vo} -> {team.eff_vo} (Δ{team.eff_vo - raw_vo}) | Da {raw_da} -> {team.eff_da} (Δ{team.eff_da - raw_da}) | Pe {raw_pe} -> {team.eff_pe} (Δ{team.eff_pe - raw_pe})`"
        )
        lines.append(f"- Center Skill: `{team.center.leader_name}`")
        if team.center.leader_desc:
            lines.append(f"- Center Skill Desc: `{team.center.leader_desc}`")
        lines.append("- 发动效果摘要: `" + " / ".join(opt._team_effect_lines(team)) + "`")
        lines.append("- 队员技能明细:")
        lines.extend(_skill_detail_lines(team, color, float(args.type_bonus_rate)))
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"masters_version={meta['masters_version']}")
    print(f"all_ssr_count={meta['all_ssr_count']}")
    print(f"cards_after_skill_expected_filter={len(cards)}")
    print(f"cards_filtered_by_skill_expected={skill_filtered_out}")
    print(f"vs_base_centers={len(centers)}")
    print(f"teams_built={len(teams)}")
    print(f"teams_deduped={deduped_team_count}")
    print(f"song_count={len(songs)}")
    print(f"csv={csv_path}")
    print(f"md={md_path}")


if __name__ == "__main__":
    main()
