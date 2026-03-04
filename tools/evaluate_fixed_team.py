#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import optimize_vs_base_teams as opt
import zawa_score_model as zsm


AXES = ("vo", "da", "pe")


def _parse_card_codes(raw: str) -> list[str]:
    codes = [x.strip() for x in raw.split(",") if x.strip()]
    if len(codes) != 5:
        raise SystemExit("--cards must contain exactly 5 card codes (first one is center)")
    return codes


def _parse_member_stats(raw: str) -> dict[str, tuple[int, int, int]]:
    """
    Format:
      "森田ひかる:4260,4730,4230;向井純葉:2780,2785,2750"
    """
    out: dict[str, tuple[int, int, int]] = {}
    for chunk in [x.strip() for x in raw.split(";") if x.strip()]:
        if ":" not in chunk:
            raise SystemExit(f"invalid member-stats item: {chunk}")
        name, vals = chunk.split(":", 1)
        nums = [x.strip() for x in vals.split(",") if x.strip()]
        if len(nums) != 3:
            raise SystemExit(f"invalid member-stats values (need vo,da,pe): {chunk}")
        vo, da, pe = (int(nums[0]), int(nums[1]), int(nums[2]))
        out[opt._normalize_name(name)] = (vo, da, pe)
    if not out:
        raise SystemExit("--member-stats is empty")
    return out


def _parse_axes(raw: str) -> set[str]:
    out = {x.strip().lower() for x in raw.split(",") if x.strip()}
    if not out.issubset(set(AXES)):
        raise SystemExit(f"invalid axes: {raw}")
    return out


def _parse_colors(raw: str) -> set[str]:
    out = {x.strip().upper() for x in raw.split(",") if x.strip()}
    valid = {"R", "B", "G", "Y", "P", "ALL"}
    if not out.issubset(valid):
        raise SystemExit(f"invalid colors: {raw}")
    return out


def _parse_song_names(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {opt._normalize_song_name(x) for x in str(raw).split(",") if x.strip()}


def _sum_axis(cards: list[opt.Card], axis: str) -> int:
    return int(sum(int(getattr(c, axis)) for c in cards))


def _scene_skill_total(cards: list[opt.Card], per_card: int) -> int:
    return int(per_card * len(cards))


def _member_axis_totals(
    cards: list[opt.Card], member_stats: dict[str, tuple[int, int, int]]
) -> tuple[dict[str, int], int]:
    axis_totals = {a: 0 for a in AXES}
    member_point_total = 0
    for c in cards:
        vo, da, pe = member_stats.get(c.member_name_norm, (0, 0, 0))
        axis_totals["vo"] += vo
        axis_totals["da"] += da
        axis_totals["pe"] += pe
        member_point_total += vo + da + pe
    return axis_totals, member_point_total


def _skin_axis_bonus(
    cards: list[opt.Card],
    rate: float,
    axes: set[str],
    target_colors: set[str],
) -> dict[str, int]:
    out = {a: 0 for a in AXES}
    for c in cards:
        if "ALL" not in target_colors and c.color not in target_colors:
            continue
        for a in axes:
            out[a] += int(math.ceil(rate * float(getattr(c, a))))
    return out


def _axis_bonus_from_rate(
    cards: list[opt.Card],
    rates: dict[str, float],
    color_match: str | None = None,
) -> dict[str, int]:
    out = {a: 0 for a in AXES}
    for c in cards:
        if color_match and color_match != "ALL" and c.color != color_match:
            continue
        for a in AXES:
            out[a] += int(math.ceil(float(rates[a]) * float(getattr(c, a))))
    return out


def _axis_sum(d: dict[str, int]) -> int:
    return int(d["vo"] + d["da"] + d["pe"])


def _load_cards(
    masters_dir: Path,
    workbook: Path,
) -> dict[str, opt.Card]:
    cards, _meta = opt._build_cards(
        masters_dir=masters_dir,
        workbook_path=workbook,
        active_name_norms=None,
        exclude_name_norms=None,
    )
    return {c.code: c for c in cards}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate one fixed UNI'S ON AIR team in detail.")
    parser.add_argument(
        "--masters-dir",
        type=Path,
        default=None,
        help="masters/<version> directory. Default: latest under ./masters",
    )
    parser.add_argument(
        "--masters-root",
        type=Path,
        default=Path("masters"),
    )
    parser.add_argument(
        "--workbook",
        type=Path,
        default=Path("UOA大表 新人必看.xlsx"),
    )
    parser.add_argument("--cards", type=str, required=True, help="5 card codes, comma separated")
    parser.add_argument(
        "--member-stats",
        type=str,
        required=True,
        help='e.g. "森田ひかる:4260,4730,4230;向井純葉:2780,2785,2750"',
    )
    parser.add_argument("--costume-vo", type=int, default=125)
    parser.add_argument("--costume-da", type=int, default=125)
    parser.add_argument("--costume-pe", type=int, default=125)
    parser.add_argument("--costume-skill", type=int, default=10)
    parser.add_argument("--scene-skill-per-card", type=int, default=430)
    parser.add_argument("--front-skin-rate", type=float, default=0.08)
    parser.add_argument("--front-skin-axes", type=str, default="da,pe")
    parser.add_argument("--front-skin-target-colors", type=str, default="P")
    parser.add_argument("--office-vo", type=float, default=0.17)
    parser.add_argument("--office-da", type=float, default=0.17)
    parser.add_argument("--office-pe", type=float, default=0.17)
    parser.add_argument("--type-bonus-rate", type=float, default=0.30)
    parser.add_argument("--song-bonus-rate", type=float, default=0.0)
    parser.add_argument("--sport-bonus-rate", type=float, default=0.0)
    parser.add_argument("--song-color", type=str, default="P", help="R/B/G/Y/P/ALL")
    parser.add_argument(
        "--songlist-json",
        type=Path,
        default=Path("catalogs/uniair_songlist.json"),
    )
    parser.add_argument(
        "--song-allowlist",
        type=Path,
        default=Path("catalogs/song_top15_chart_scope_20260226.csv"),
    )
    parser.add_argument("--group-power", type=int, default=1_800_000)
    parser.add_argument("--score-front-power", type=int, default=None, help="Override front power for score model")
    parser.add_argument("--score-model", type=str, choices=["legacy", "zawa"], default="zawa")
    parser.add_argument("--song-scale", type=float, default=4.5)
    parser.add_argument(
        "--score-member-point",
        type=int,
        default=None,
        help="Override per-member point used in score scaling. Default: average of given member stats in this fixed team.",
    )
    parser.add_argument("--song-names", type=str, default=None, help="Optional comma-separated song names filter")
    parser.add_argument(
        "--zawa-master-json",
        type=Path,
        default=Path("catalogs/zawa_score_sim_master.json"),
        help="Cached zawa Score_sim master json",
    )
    parser.add_argument("--zawa-refresh-master", action="store_true", help="Refresh zawa score data from source")
    parser.add_argument(
        "--zawa-skill-presets",
        type=str,
        default=None,
        help="5 entries: A-B-C-D-E[/mult][,A2-B2-C2-D2-E2] separated by ';'",
    )
    parser.add_argument("--zawa-trials", type=int, default=10000)
    parser.add_argument("--zawa-seed", type=int, default=20260226)
    parser.add_argument("--out-csv", type=Path, default=None, help="Optional song score csv output path")
    args = parser.parse_args()

    masters_dir = args.masters_dir or opt._find_latest_masters(args.masters_root)
    card_codes = _parse_card_codes(args.cards)
    member_stats = _parse_member_stats(args.member_stats)
    skin_axes = _parse_axes(args.front_skin_axes)
    skin_target_colors = _parse_colors(args.front_skin_target_colors)
    song_color = args.song_color.strip().upper()

    cards_by_code = _load_cards(masters_dir=masters_dir, workbook=args.workbook)
    missing = [c for c in card_codes if c not in cards_by_code]
    if missing:
        raise SystemExit(f"card codes not found: {missing}")

    team_cards = [cards_by_code[c] for c in card_codes]
    center = team_cards[0]
    if not center.vs_rule:
        raise SystemExit(f"center has no parsed V/S rule: {center.code} {center.title}")

    scene_raw = {a: _sum_axis(team_cards, a) for a in AXES}
    eff_vo, eff_da, eff_pe = opt._compute_effective_stats(team_cards, center)
    scene_eff = {"vo": eff_vo, "da": eff_da, "pe": eff_pe}
    center_axis = {a: int(scene_eff[a] - scene_raw[a]) for a in AXES}

    member_axis, member_point_total = _member_axis_totals(team_cards, member_stats)
    costume_axis = {
        "vo": args.costume_vo * len(team_cards),
        "da": args.costume_da * len(team_cards),
        "pe": args.costume_pe * len(team_cards),
    }
    costume_skill_total = int(args.costume_skill * len(team_cards))
    scene_skill_total = _scene_skill_total(team_cards, args.scene_skill_per_card)
    skill_total = scene_skill_total + costume_skill_total

    skin_axis = _skin_axis_bonus(
        cards=team_cards,
        rate=args.front_skin_rate,
        axes=skin_axes,
        target_colors=skin_target_colors,
    )

    base_axis = {
        a: int(member_axis[a] + costume_axis[a] + scene_raw[a] + center_axis[a] + skin_axis[a])
        for a in AXES
    }
    base_total = int(_axis_sum(base_axis) + skill_total)

    office_axis = _axis_bonus_from_rate(
        cards=team_cards,
        rates={"vo": args.office_vo, "da": args.office_da, "pe": args.office_pe},
        color_match=None,
    )
    type_axis = _axis_bonus_from_rate(
        cards=team_cards,
        rates={"vo": args.type_bonus_rate, "da": args.type_bonus_rate, "pe": args.type_bonus_rate},
        color_match=song_color,
    )
    song_axis = _axis_bonus_from_rate(
        cards=team_cards,
        rates={"vo": args.song_bonus_rate, "da": args.song_bonus_rate, "pe": args.song_bonus_rate},
        color_match=song_color,
    )
    sport_axis = _axis_bonus_from_rate(
        cards=team_cards,
        rates={"vo": args.sport_bonus_rate, "da": args.sport_bonus_rate, "pe": args.sport_bonus_rate},
        color_match=song_color,
    )

    front_with_office = int(base_total + _axis_sum(office_axis))
    live_total = int(front_with_office + _axis_sum(type_axis) + _axis_sum(song_axis) + _axis_sum(sport_axis))

    print(f"center={center.member_name}[{center.title}]")
    print("team_cards=" + " | ".join(f"{c.member_name}[{c.title}]" for c in team_cards))
    print(f"scene_raw_vo_da_pe={scene_raw['vo']},{scene_raw['da']},{scene_raw['pe']}")
    print(f"center_delta_vo_da_pe={center_axis['vo']},{center_axis['da']},{center_axis['pe']}")
    print(f"member_vo_da_pe={member_axis['vo']},{member_axis['da']},{member_axis['pe']}")
    print(f"costume_vo_da_pe={costume_axis['vo']},{costume_axis['da']},{costume_axis['pe']}")
    print(f"skin_vo_da_pe={skin_axis['vo']},{skin_axis['da']},{skin_axis['pe']}")
    print(f"scene_skill_total={scene_skill_total}")
    print(f"costume_skill_total={costume_skill_total}")
    print(f"base_axis_vo_da_pe={base_axis['vo']},{base_axis['da']},{base_axis['pe']}")
    print(f"base_total_no_office_type_song={base_total}")
    print(f"office_bonus_total={_axis_sum(office_axis)}")
    print(f"type_bonus_total={_axis_sum(type_axis)}")
    print(f"song_bonus_total={_axis_sum(song_axis)}")
    print(f"sport_bonus_total={_axis_sum(sport_axis)}")
    print(f"front_total_with_office={front_with_office}")
    print(f"live_total_with_type_song={live_total}")
    print(f"score_model={args.score_model}")

    # Song score estimation
    team_result = opt._objective_for_team(team_cards, center)
    songs = opt._load_songlist(args.songlist_json, refresh=False)
    if args.song_allowlist:
        allow = opt._load_song_allowlist(args.song_allowlist)
        songs = opt._filter_songs_by_allowlist(songs, allow)
    name_filter = _parse_song_names(args.song_names)
    if name_filter:
        songs = [s for s in songs if opt._normalize_song_name(s.name) in name_filter]
    songs = [s for s in songs if s.color == song_color or song_color == "ALL"]

    member_point_for_score = args.score_member_point
    if member_point_for_score is None:
        member_point_for_score = int(round(member_point_total / float(len(team_cards))))

    rows: list[dict[str, int | float | str]] = []
    if args.score_model == "legacy":
        for s in songs:
            score_raw, score_m, sigma, s1_low, s1_high, s2_low, s2_high = opt._estimate_song_score(
                team_result,
                s,
                group_power=args.group_power,
                member_point=member_point_for_score,
                song_scale=args.song_scale,
            )
            rows.append(
                {
                    "song_no": s.no,
                    "song_color": s.color,
                    "song_name": s.name,
                    "live": s.live,
                    "notes": s.notes,
                    "seconds": s.seconds,
                    "estimated_score": score_raw,
                    "estimated_score_million": round(score_m, 3),
                    "score_sigma": int(round(sigma)),
                    "score_1sigma_low": s1_low,
                    "score_1sigma_high": s1_high,
                    "score_2sigma_low": s2_low,
                    "score_2sigma_high": s2_high,
                    "score_min": "",
                    "score_max": "",
                }
            )
    else:
        master = zsm.load_master(args.zawa_master_json, refresh=args.zawa_refresh_master)
        front_power_for_score = int(args.score_front_power if args.score_front_power is not None else live_total)
        print(f"score_front_power={front_power_for_score}")
        print(f"score_group_power={int(args.group_power)}")
        fixed_profiles = zsm.parse_skill_presets(args.zawa_skill_presets) if args.zawa_skill_presets else None
        color_mult, member_mult = opt._collect_skill_rate_multipliers(team_cards, center)
        missing_songs: list[str] = []

        for s in songs:
            idx = zsm.find_song_index(
                master,
                name=s.name,
                color_code=s.color,
                level=s.level,
                seconds=s.seconds,
                notes=s.notes,
            )
            if idx < 0:
                missing_songs.append(f"{s.name}({s.color})")
                continue
            if fixed_profiles is not None:
                profiles = fixed_profiles
            else:
                profiles = []
                for c in team_cards:
                    proc_mult = opt._card_skill_proc_multiplier(c, center, color_mult, member_mult)
                    profiles.append(
                        zsm.parse_card_skill_profile(
                            skill_desc=c.skill_desc,
                            card_color=c.color,
                            song_color=s.color,
                            proc_multiplier=proc_mult,
                        )
                    )
            sim = zsm.simulate(
                master=master,
                song_index=idx,
                front_power=front_power_for_score,
                group_power=args.group_power,
                skills=profiles,
                trials=args.zawa_trials,
                seed=(None if args.zawa_seed < 0 else int(args.zawa_seed + int(s.no))),
            )
            zsong = master["songlist"][idx]
            median = int(sim["median"])
            s1_low = int(sim["-1sigma"])
            s1_high = int(sim["+1sigma"])
            s2_low = int(sim["-2sigma"])
            s2_high = int(sim["+2sigma"])
            sigma = int(round((s1_high - s1_low) / 2.0))
            rows.append(
                {
                    "song_no": s.no,
                    "song_color": s.color,
                    "song_name": s.name,
                    "live": s.live,
                    "notes": int(zsong.get("notes") or s.notes),
                    "seconds": int(zsong.get("sec") or s.seconds),
                    "estimated_score": median,
                    "estimated_score_million": round(median / 1_000_000.0, 3),
                    "score_sigma": sigma,
                    "score_1sigma_low": s1_low,
                    "score_1sigma_high": s1_high,
                    "score_2sigma_low": s2_low,
                    "score_2sigma_high": s2_high,
                    "score_min": int(sim["min"]),
                    "score_max": int(sim["max"]),
                }
            )
        if missing_songs:
            print("zawa_song_mapping_missing=" + " | ".join(missing_songs))

    rows.sort(key=lambda r: int(r["estimated_score"]), reverse=True)
    top15 = rows[:15]
    print(f"song_count_after_filter={len(rows)}")
    print("top15_song_scores:")
    for i, r in enumerate(top15, start=1):
        extra = ""
        if r.get("score_min", "") != "":
            extra = f" min={r['score_min']} max={r['score_max']}"
        print(
            f"{i:02d}. {r['song_name']} "
            f"score={r['estimated_score']} "
            f"sigma={r['score_sigma']} "
            f"1sigma=[{r['score_1sigma_low']},{r['score_1sigma_high']}] "
            f"2sigma=[{r['score_2sigma_low']},{r['score_2sigma_high']}]"
            f"{extra}"
        )

    if args.out_csv:
        args.out_csv.parent.mkdir(parents=True, exist_ok=True)
        with args.out_csv.open("w", newline="", encoding="utf-8") as f:
            cols = [
                "song_no",
                "song_color",
                "song_name",
                "live",
                "notes",
                "seconds",
                "estimated_score",
                "estimated_score_million",
                "score_sigma",
                "score_1sigma_low",
                "score_1sigma_high",
                "score_2sigma_low",
                "score_2sigma_high",
                "score_min",
                "score_max",
            ]
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for row in top15:
                w.writerow({k: row.get(k, "") for k in cols})
        print(f"out_csv={args.out_csv}")


if __name__ == "__main__":
    main()
