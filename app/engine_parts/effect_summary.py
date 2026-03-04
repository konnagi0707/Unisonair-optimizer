from __future__ import annotations

from typing import Any

import optimize_vs_base_teams as opt


def team_effect_summary(cards: list[Any], center: Any) -> str:
    if not center.vs_rule:
        return center.leader_desc or center.leader_name or ""

    parts: list[str] = []
    agg = opt._aggregate_center_bonus(cards, center, center.vs_rule)
    target_types = "・".join(sorted(center.vs_rule.agg_target_types))
    if agg.get("vo", 0.0) > 0.0:
        parts.append(f"{target_types}タイプのVoが{agg['vo']:.1f}%アップ")
    if agg.get("da", 0.0) > 0.0:
        parts.append(f"{target_types}タイプのDaが{agg['da']:.1f}%アップ")
    if agg.get("pe", 0.0) > 0.0:
        parts.append(f"{target_types}タイプのPeが{agg['pe']:.1f}%アップ")

    zero_axes = opt._mode_zero_axes(center.vs_rule.mode)
    if zero_axes:
        keep = [a for a in ("Vo", "Da", "Pe") if a.lower() not in zero_axes]
        zero = [a for a in ("Vo", "Da", "Pe") if a.lower() in zero_axes]
        parts.append(f"{'・'.join(keep)}のみ合算（{'・'.join(zero)}を0として計算）")

    color_mult, member_mult = opt._collect_skill_rate_multipliers(cards, center)
    for color in ("R", "B", "G", "Y", "P"):
        val = float(color_mult.get(color, 1.0))
        if val > 1.0001:
            parts.append(f"{color}タイプのスキル発動率が{(val - 1.0) * 100.0:.1f}%アップ")

    seen_members: set[str] = set()
    for c in cards:
        key = c.member_name_norm
        if key in seen_members:
            continue
        if not opt._member_rate_applies_to_card(c, center):
            continue
        seen_members.add(key)
        val = float(member_mult.get(key, 1.0))
        if val > 1.0001:
            parts.append(f"{c.member_name}のスキル発動率が{(val - 1.0) * 100.0:.1f}%アップ")

    return " / ".join(parts)

