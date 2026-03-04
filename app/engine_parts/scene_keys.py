from __future__ import annotations

import re

import optimize_vs_base_teams as opt


def kosa_color_to_short(color: str) -> str:
    c = str(color or "").strip().upper()
    if c == "RED":
        return "R"
    if c == "BLUE":
        return "B"
    if c == "GREEN":
        return "G"
    if c == "YELLOW":
        return "Y"
    if c == "PURPLE":
        return "P"
    if c == "ALL":
        return "ALL"
    return c[:1] if c else ""


def scene_match_key(member_name: str, color: str, vo: int, da: int, pe: int) -> str:
    return f"{opt._normalize_name(member_name)}|{color}|{int(vo)}|{int(da)}|{int(pe)}"


def scene_member_color_key(member_name: str, color: str) -> str:
    return f"{opt._normalize_name(member_name)}|{color}"


def scene_member_key(member_name: str) -> str:
    return opt._normalize_name(member_name)


def norm_scene_title(title: str | None) -> str:
    raw = str(title or "")
    raw = raw.replace("’", "'").replace("‘", "'").replace("　", " ")
    raw = re.sub(r"\s+", "", raw.strip().lower())
    raw = re.sub(r"[\"'`]", "", raw)
    return raw


def scene_title_key(member_name: str, color: str, title: str | None) -> str:
    return f"{opt._normalize_name(member_name)}|{color}|{norm_scene_title(title)}"
