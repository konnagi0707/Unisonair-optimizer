#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import optimize_vs_base_teams as opt
import strict_zawa_song_top5 as strict
import zawa_score_model as zsm


@dataclass(frozen=True)
class SongSpec:
    color: str
    name: str
    level: int | None


DEFAULT_SONG_SPECS = [
    SongSpec("G", "Dead end", 25),
    SongSpec("P", "雨が降ったって", 24),
    SongSpec("R", "流れ弾", 23),
    SongSpec("Y", "流れ弾", 24),
    SongSpec("B", "東京タワーはどこから見える？", 24),
]

COLOR_LABEL = {
    "R": "红歌",
    "B": "蓝歌",
    "G": "绿歌",
    "Y": "黄歌",
    "P": "紫歌",
    "ALL": "全色歌",
}


def _parse_song_spec(raw: str) -> SongSpec:
    parts = [p.strip() for p in str(raw or "").split("|")]
    if len(parts) < 2:
        raise SystemExit(f"invalid --song spec: {raw} (need COLOR|NAME|LEVEL)")
    color = parts[0].upper()
    name = parts[1]
    level: int | None = None
    if len(parts) >= 3 and parts[2]:
        level = int(parts[2])
    return SongSpec(color=color, name=name, level=level)


def _find_song(songs: list[opt.Song], spec: SongSpec) -> opt.Song:
    name_key = opt._normalize_song_name(spec.name)
    rows = [s for s in songs if s.color == spec.color and opt._normalize_song_name(s.name) == name_key]
    if spec.level is not None:
        rows = [s for s in rows if s.level == spec.level]
    if not rows:
        raise SystemExit(f"Song not found: color={spec.color} name={spec.name} level={spec.level}")
    rows.sort(key=lambda s: (s.level, s.notes, s.seconds, -s.no), reverse=True)
    return rows[0]


def _type_bonus_per_card(c: opt.Card, song_color: str, rate: float) -> tuple[int, int, int]:
    if song_color != "ALL" and c.color != song_color:
        return (0, 0, 0)
    return (
        int(math.ceil(c.vo * rate)),
        int(math.ceil(c.da * rate)),
        int(math.ceil(c.pe * rate)),
    )


def _skill_tuple_text(profile: zsm.SkillProfile) -> str:
    f = profile.front
    return f"{f.interval}-{f.proc_pct:.1f}-{f.duration}-{f.combo_pct:.1f}-{f.score_pct:.1f}"


def _team_seed(seed_base: int, song_no: int, center_code: str) -> int:
    center_seed = sum(ord(ch) for ch in str(center_code))
    return int(seed_base + int(song_no) * 1009 + center_seed)


def _team_detail_rows(team: opt.TeamResult, song: opt.Song, type_bonus_rate: float) -> tuple[list[dict[str, Any]], dict[str, float], set[str]]:
    center = team.center
    rule = center.vs_rule
    agg = {a: 0.0 for a in opt.AXES}
    zero_axes: set[str] = set()
    if rule is not None:
        agg = opt._aggregate_center_bonus(team.cards, center, rule)
        zero_axes = opt._mode_zero_axes(rule.mode)

    color_mult, member_mult = opt._collect_skill_rate_multipliers(team.cards, center)

    rows: list[dict[str, Any]] = []
    for c in team.cards:
        m = max(1.0, color_mult.get(c.color, 1.0), member_mult.get(c.member_name_norm, 1.0))
        profile = zsm.parse_card_skill_profile(
            skill_desc=c.skill_desc,
            card_color=c.color,
            song_color=song.color,
            proc_multiplier=m,
        )

        base = {"vo": float(c.vo), "da": float(c.da), "pe": float(c.pe)}
        pct = {"vo": 0.0, "da": 0.0, "pe": 0.0}

        if rule is not None and c.color in rule.agg_target_types:
            for axis in zero_axes:
                base[axis] = 0.0
            for axis in opt.AXES:
                pct[axis] += float(agg.get(axis, 0.0))

        post = {
            "vo": int(round(base["vo"] * (1.0 + pct["vo"] / 100.0))),
            "da": int(round(base["da"] * (1.0 + pct["da"] / 100.0))),
            "pe": int(round(base["pe"] * (1.0 + pct["pe"] / 100.0))),
        }
        tb_vo, tb_da, tb_pe = _type_bonus_per_card(c, song.color, type_bonus_rate)

        rows.append(
            {
                "member": c.member_name,
                "card": f"{c.member_name}[{c.title}]",
                "title": c.title,
                "color": c.color,
                "skill_desc": c.skill_desc,
                "skill_expected": float(c.skill_expected),
                "skill_mult": float(m),
                "skill_expected_effective": float(c.skill_expected) * float(m),
                "skill_tuple": _skill_tuple_text(profile),
                "raw_vo": int(c.vo),
                "raw_da": int(c.da),
                "raw_pe": int(c.pe),
                "pct_vo": float(pct["vo"]),
                "pct_da": float(pct["da"]),
                "pct_pe": float(pct["pe"]),
                "post_vo": int(post["vo"]),
                "post_da": int(post["da"]),
                "post_pe": int(post["pe"]),
                "scene_power": int(post["vo"] + post["da"] + post["pe"]),
                "tb_vo": int(tb_vo),
                "tb_da": int(tb_da),
                "tb_pe": int(tb_pe),
            }
        )

    return rows, agg, zero_axes


def _run_song(
    *,
    master: dict[str, Any],
    song: opt.Song,
    teams: list[opt.TeamResult],
    group_power: int,
    member_point: int,
    type_bonus_rate: float,
    stage1_trials: int,
    stage2_trials: int,
    stage2_topn: int,
    topn: int,
    seed: int,
) -> list[dict[str, Any]]:
    stage1_rows: list[dict[str, Any]] = []
    for t in teams:
        stage1_rows.append(
            strict._team_summary(
                master,
                t,
                [song],
                group_power=group_power,
                member_point=member_point,
                type_bonus_rate=type_bonus_rate,
                trials=stage1_trials,
                seed_base=seed,
            )
        )
    stage1_rows.sort(key=lambda r: strict._rank_tuple(r, "plus2"), reverse=True)
    shortlisted = stage1_rows[: max(topn, stage2_topn)]

    stage2_rows: list[dict[str, Any]] = []
    stage2_seed_base = seed + 7789
    for r in shortlisted:
        stage2_rows.append(
            strict._team_summary(
                master,
                r["team"],
                [song],
                group_power=group_power,
                member_point=member_point,
                type_bonus_rate=type_bonus_rate,
                trials=stage2_trials,
                seed_base=stage2_seed_base,
            )
        )
    stage2_rows.sort(key=lambda r: strict._rank_tuple(r, "plus2"), reverse=True)

    out: list[dict[str, Any]] = []
    for rank, row in enumerate(stage2_rows[:topn], start=1):
        team: opt.TeamResult = row["team"]
        sim = strict._run_song_sim(
            master,
            team,
            song,
            group_power=group_power,
            member_point=member_point,
            type_bonus_rate=type_bonus_rate,
            trials=stage2_trials,
            seed=_team_seed(stage2_seed_base, song.no, team.center.code),
        )
        members, agg, zero_axes = _team_detail_rows(team, song, type_bonus_rate)
        out.append(
            {
                "rank": rank,
                "song": song,
                "team": team,
                "members": members,
                "agg": agg,
                "zero_axes": zero_axes,
                "effects": opt._team_effect_lines(team),
                "sim": sim,
            }
        )
    return out


def _fmt_pct(v: float) -> str:
    return f"{v:.2f}%"


def _fmt_axis(v: float) -> str:
    return f"{v:.1f}%"


def _write_reports(
    out_dir: Path,
    color_results: dict[str, list[dict[str, Any]]],
    *,
    active_members_json: Path,
    min_skill_expected: float,
    cards_filtered_by_skill_expected: int,
    center_candidates: int,
    group_power: int,
    member_point: int,
    type_bonus_rate: float,
    stage1_trials: int,
    stage2_trials: int,
    seed: int,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "strict_zawa_multicolor_top5_detail.md"
    csv_path = out_dir / "strict_zawa_multicolor_top5_summary.csv"

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "song_color",
                "song_name",
                "song_level",
                "rank",
                "captain",
                "min",
                "minus3sigma",
                "minus2sigma",
                "minus1sigma",
                "median",
                "plus1sigma",
                "plus2sigma",
                "plus3sigma",
                "max",
                "front_pre",
                "front_post",
                "type_bonus",
                "scene_vo",
                "scene_da",
                "scene_pe",
                "scene_power",
            ]
        )
        for color in ("G", "P", "R", "Y", "B"):
            for row in color_results.get(color, []):
                song: opt.Song = row["song"]
                team: opt.TeamResult = row["team"]
                sim = row["sim"]
                members = row["members"]
                scene_vo = sum(int(m["post_vo"]) for m in members)
                scene_da = sum(int(m["post_da"]) for m in members)
                scene_pe = sum(int(m["post_pe"]) for m in members)
                w.writerow(
                    [
                        color,
                        song.name,
                        song.level,
                        row["rank"],
                        f"{team.center.member_name}[{team.center.title}]",
                        int(sim["min"]),
                        int(sim["-3sigma"]),
                        int(sim["-2sigma"]),
                        int(sim["-1sigma"]),
                        int(sim["median"]),
                        int(sim["+1sigma"]),
                        int(sim["+2sigma"]),
                        int(sim["+3sigma"]),
                        int(sim["max"]),
                        int(sim["front_pre"]),
                        int(sim["front_post"]),
                        int(sim["type_bonus"]),
                        scene_vo,
                        scene_da,
                        scene_pe,
                        scene_vo + scene_da + scene_pe,
                    ]
                )

    lines: list[str] = []
    lines.append("# Strict Zawa 五色 Top5（+2σ）")
    lines.append("")
    lines.append("- 排序: `+2σ`")
    lines.append(f"- active_members_json: `{active_members_json}`")
    lines.append(f"- min_skill_expected: `{min_skill_expected}`")
    lines.append(f"- cards_filtered_by_skill_expected: `{cards_filtered_by_skill_expected}`")
    lines.append(f"- center_candidates_per_center: `{center_candidates}`")
    lines.append(f"- group_power: `{group_power}`")
    lines.append(f"- member_point_each: `{member_point}`")
    lines.append(f"- type_bonus_rate: `{type_bonus_rate}`")
    lines.append(f"- stage1_trials: `{stage1_trials}`")
    lines.append(f"- stage2_trials: `{stage2_trials}`")
    lines.append(f"- seed: `{seed}`")
    lines.append("")

    for color in ("G", "P", "R", "Y", "B"):
        rows = color_results.get(color, [])
        if not rows:
            continue
        song: opt.Song = rows[0]["song"]
        lines.append(f"## {COLOR_LABEL.get(color, color)} {song.name} ({color}/Lv.{song.level})")
        lines.append("")
        lines.append("|排名|队长|MIN|-3σ|-2σ|-1σ|中位|+1σ|+2σ|+3σ|MAX|进歌前|进歌后|类型30%|")
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for row in rows:
            sim = row["sim"]
            team: opt.TeamResult = row["team"]
            lines.append(
                "|"
                + "|".join(
                    [
                        str(row["rank"]),
                        f"{team.center.member_name}[{team.center.title}]",
                        str(int(sim["min"])),
                        str(int(sim["-3sigma"])),
                        str(int(sim["-2sigma"])),
                        str(int(sim["-1sigma"])),
                        str(int(sim["median"])),
                        str(int(sim["+1sigma"])),
                        str(int(sim["+2sigma"])),
                        str(int(sim["+3sigma"])),
                        str(int(sim["max"])),
                        str(int(sim["front_pre"])),
                        str(int(sim["front_post"])),
                        str(int(sim["type_bonus"])),
                    ]
                )
                + "|"
            )
        lines.append("")

        for row in rows:
            rank = row["rank"]
            team: opt.TeamResult = row["team"]
            sim = row["sim"]
            members = row["members"]
            agg = row["agg"]
            zero_axes: set[str] = row["zero_axes"]
            effects: list[str] = row["effects"]

            scene_vo = sum(int(m["post_vo"]) for m in members)
            scene_da = sum(int(m["post_da"]) for m in members)
            scene_pe = sum(int(m["post_pe"]) for m in members)

            tb_vo = sum(int(m["tb_vo"]) for m in members)
            tb_da = sum(int(m["tb_da"]) for m in members)
            tb_pe = sum(int(m["tb_pe"]) for m in members)

            lines.append(f"### Top{rank}: {team.center.member_name}[{team.center.title}]")
            lines.append("")
            lines.append("- 队伍: `" + " / ".join(f"{c.member_name}[{c.title}]" for c in team.cards) + "`")
            lines.append("- 发动效果: `" + " / ".join(effects) + "`")
            lines.append(
                f"- Center聚合加成(缩放后): Vo `{_fmt_axis(float(agg.get('vo', 0.0)))}` "
                f"Da `{_fmt_axis(float(agg.get('da', 0.0)))}` Pe `{_fmt_axis(float(agg.get('pe', 0.0)))}`"
            )
            lines.append(f"- 零化轴: `{','.join(sorted(zero_axes)) if zero_axes else '-'}`")
            lines.append(f"- 总Vo/Da/Pe(中心后): `{scene_vo} / {scene_da} / {scene_pe}`")
            lines.append(f"- 30%类型加成Vo/Da/Pe: `{tb_vo} / {tb_da} / {tb_pe}` (仅同色卡吃到)")
            lines.append(
                f"- 进歌前综合力: `{int(sim['front_pre'])} = ({scene_vo}+{scene_da}+{scene_pe}) + {member_point}*5`"
            )
            lines.append(
                f"- 进歌后综合力: `{int(sim['front_post'])} = {int(sim['front_pre'])} + ({tb_vo}+{tb_da}+{tb_pe})`"
            )
            lines.append(
                f"- 分数(严格zawa): `MIN {int(sim['min'])} / -3σ {int(sim['-3sigma'])} / -2σ {int(sim['-2sigma'])} / -1σ {int(sim['-1sigma'])} / "
                f"median {int(sim['median'])} / +1σ {int(sim['+1sigma'])} / +2σ {int(sim['+2sigma'])} / +3σ {int(sim['+3sigma'])} / MAX {int(sim['max'])}`"
            )
            lines.append("")
            lines.append(
                "|成员|卡片全称|色|技能描述|技能期望值|技能up倍率|倍率后期望值(参考)|技能tuple(当前歌色)|"
                "原Vo/Da/Pe|中心后Vo/Da/Pe%|中心后Vo/Da/Pe|个人scene综合力|30%类型加成(Vo/Da/Pe)|"
            )
            lines.append(
                "|---|---|---|---|---:|---:|---:|---|---|---|---|---:|---|"
            )
            for m in members:
                lines.append(
                    "|"
                    + "|".join(
                        [
                            str(m["member"]),
                            f"{m['member']}[{m['title']}]",
                            str(m["color"]),
                            str(m["skill_desc"]).replace("|", "\\|"),
                            _fmt_pct(float(m["skill_expected"])),
                            f"{float(m['skill_mult']):.2f}x",
                            _fmt_pct(float(m["skill_expected_effective"])),
                            str(m["skill_tuple"]),
                            f"{int(m['raw_vo'])}/{int(m['raw_da'])}/{int(m['raw_pe'])}",
                            f"{float(m['pct_vo']):.1f}%/{float(m['pct_da']):.1f}%/{float(m['pct_pe']):.1f}%",
                            f"{int(m['post_vo'])}/{int(m['post_da'])}/{int(m['post_pe'])}",
                            str(int(m["scene_power"])),
                            f"{int(m['tb_vo'])}/{int(m['tb_da'])}/{int(m['tb_pe'])}",
                        ]
                    )
                    + "|"
                )
            lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, csv_path


def main() -> None:
    p = argparse.ArgumentParser(description="Strict zawa multi-color Top5 detailed report (+2sigma)")
    p.add_argument("--masters-dir", type=Path, default=None)
    p.add_argument("--masters-root", type=Path, default=Path("masters"))
    p.add_argument("--workbook", type=Path, default=Path("UOA大表 新人必看.xlsx"))
    p.add_argument("--songlist-json", type=Path, default=Path("catalogs/uniair_songlist.json"))
    p.add_argument("--refresh-songlist", action="store_true")
    p.add_argument(
        "--active-members-json",
        type=Path,
        default=Path("catalogs/active_members_manual_20260227.json"),
    )
    p.add_argument("--group-power", type=int, default=1_809_224)
    p.add_argument("--member-point", type=int, default=15_000)
    p.add_argument("--type-bonus-rate", type=float, default=0.30)
    p.add_argument("--zawa-master-json", type=Path, default=Path("catalogs/zawa_score_sim_master.json"))
    p.add_argument("--zawa-refresh-master", action="store_true")
    p.add_argument("--stage1-trials", type=int, default=2000)
    p.add_argument("--stage2-trials", type=int, default=10000)
    p.add_argument("--stage2-topn", type=int, default=20)
    p.add_argument("--topn", type=int, default=5)
    p.add_argument("--v-only", action="store_true", default=True)
    p.add_argument("--shortlist-size", type=int, default=240)
    p.add_argument("--search-pool-size", type=int, default=42)
    p.add_argument("--center-candidates", type=int, default=6, help="Objective-top candidates kept per center")
    p.add_argument(
        "--min-skill-expected",
        type=float,
        default=2.0,
        help="Filter out cards with expected skill value below threshold (default: 2.0)",
    )
    p.add_argument("--seed", type=int, default=20260227)
    p.add_argument(
        "--song",
        action="append",
        default=[],
        help="COLOR|NAME|LEVEL (repeatable). If omitted, uses fixed 5-color defaults.",
    )
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()

    masters_dir = args.masters_dir or opt._find_latest_masters(args.masters_root)
    active = opt._load_active_members(args.active_members_json, refresh=False)

    cards, meta = opt._build_cards(
        masters_dir=masters_dir,
        workbook_path=args.workbook,
        active_name_norms=active,
        exclude_name_norms=None,
    )
    before_skill_filter = len(cards)
    cards = [c for c in cards if float(c.skill_expected) >= float(args.min_skill_expected)]
    skill_filtered_out = before_skill_filter - len(cards)

    centers = [c for c in cards if c.is_vs_base and c.vs_rule is not None]
    if args.v_only:
        centers = [c for c in centers if opt._is_veaut_card(c)]
    if not centers:
        raise SystemExit("No centers after filters")

    songs_all = opt._load_songlist(args.songlist_json, refresh=args.refresh_songlist)
    specs = [_parse_song_spec(x) for x in args.song] if args.song else list(DEFAULT_SONG_SPECS)
    target_songs = [_find_song(songs_all, s) for s in specs]

    master = zsm.load_master(args.zawa_master_json, refresh=args.zawa_refresh_master)

    teams: list[opt.TeamResult] = []
    for c in centers:
        teams.extend(
            opt._build_team_candidates(
                c,
                cards,
                args.shortlist_size,
                args.search_pool_size,
                args.center_candidates,
            )
        )

    color_results: dict[str, list[dict[str, Any]]] = {}
    for song in target_songs:
        color_results[song.color] = _run_song(
            master=master,
            song=song,
            teams=teams,
            group_power=args.group_power,
            member_point=args.member_point,
            type_bonus_rate=args.type_bonus_rate,
            stage1_trials=args.stage1_trials,
            stage2_trials=args.stage2_trials,
            stage2_topn=args.stage2_topn,
            topn=args.topn,
            seed=args.seed,
        )

    md_path, csv_path = _write_reports(
        args.out_dir,
        color_results,
        active_members_json=args.active_members_json,
        min_skill_expected=float(args.min_skill_expected),
        cards_filtered_by_skill_expected=int(skill_filtered_out),
        center_candidates=int(args.center_candidates),
        group_power=args.group_power,
        member_point=args.member_point,
        type_bonus_rate=args.type_bonus_rate,
        stage1_trials=args.stage1_trials,
        stage2_trials=args.stage2_trials,
        seed=args.seed,
    )

    print(f"masters_version={meta['masters_version']}")
    print(f"all_ssr_count={meta['all_ssr_count']}")
    print(f"cards_after_skill_expected_filter={len(cards)}")
    print(f"cards_filtered_by_skill_expected={skill_filtered_out}")
    print(f"vs_base_centers={len(centers)}")
    print(f"teams_built={len(teams)}")
    print(f"songs={','.join(f'{s.color}:{s.name}(Lv{s.level})' for s in target_songs)}")
    print(f"markdown={md_path}")
    print(f"csv={csv_path}")
    print(f"generated_at={dt.datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
