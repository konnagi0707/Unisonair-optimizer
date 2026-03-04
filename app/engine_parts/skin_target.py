from __future__ import annotations

import re
from typing import Any


_COLOR_WORD_TO_CODE = {
    "R": "R",
    "B": "B",
    "G": "G",
    "Y": "Y",
    "P": "P",
    "ALL": "ALL",
    "RED": "R",
    "BLUE": "B",
    "GREEN": "G",
    "YELLOW": "Y",
    "PURPLE": "P",
}


def auto_skin_axes(center: Any) -> set[str]:
    rule = center.vs_rule
    mode = (rule.mode if rule else "").strip()
    if mode == "sum_vo":
        return {"vo", "da"}
    if mode == "sum_da":
        return {"da", "pe"}
    if mode == "sum_pe":
        return {"vo", "pe"}
    if mode == "sum_vo_da":
        return {"vo", "da"}
    if mode == "sum_da_pe":
        return {"da", "pe"}
    if mode == "sum_vo_pe":
        return {"vo", "pe"}
    return {"vo", "da", "pe"}


def auto_skin_candidate_rates(center: Any) -> list[dict[str, float]]:
    def axis_rates(axes: set[str], rate: float) -> dict[str, float]:
        r = max(0.0, float(rate))
        return {
            "vo": r if "vo" in axes else 0.0,
            "da": r if "da" in axes else 0.0,
            "pe": r if "pe" in axes else 0.0,
        }

    rule = center.vs_rule
    mode = (rule.mode if rule else "").strip()
    if mode == "sum_vo":
        return [axis_rates({"vo", "da"}, 0.08), axis_rates({"vo", "pe"}, 0.08)]
    if mode == "sum_da":
        return [axis_rates({"vo", "da"}, 0.08), axis_rates({"da", "pe"}, 0.08)]
    if mode == "sum_pe":
        return [axis_rates({"vo", "pe"}, 0.08), axis_rates({"da", "pe"}, 0.08)]
    if mode == "sum_vo_da":
        return [axis_rates({"vo", "da"}, 0.08)]
    if mode == "sum_da_pe":
        return [axis_rates({"da", "pe"}, 0.08)]
    if mode == "sum_vo_pe":
        return [axis_rates({"vo", "pe"}, 0.08)]
    return [axis_rates({"vo", "da", "pe"}, 0.05)]


def skin_axis_rates_by_profile(profile: str | None, center: Any) -> dict[str, float]:
    def axis_rates(axes: set[str], rate: float) -> dict[str, float]:
        r = max(0.0, float(rate))
        return {
            "vo": r if "vo" in axes else 0.0,
            "da": r if "da" in axes else 0.0,
            "pe": r if "pe" in axes else 0.0,
        }

    p = str(profile or "auto").strip().lower()
    if p in {"off", "none", "disabled"}:
        return {"vo": 0.0, "da": 0.0, "pe": 0.0}

    if p in {"single_vo", "vo", "vo_only", "vo_single"}:
        return axis_rates({"vo"}, 0.09)
    if p in {"single_da", "da", "da_only", "da_single"}:
        return axis_rates({"da"}, 0.09)
    if p in {"single_pe", "pe", "pe_only", "pe_single"}:
        return axis_rates({"pe"}, 0.09)

    if p in {"dual_vo_da", "vo_da", "voda", "vo-da"}:
        return axis_rates({"vo", "da"}, 0.08)
    if p in {"dual_da_pe", "da_pe", "dape", "da-pe"}:
        return axis_rates({"da", "pe"}, 0.08)
    if p in {"dual_vo_pe", "vo_pe", "vope", "vo-pe"}:
        return axis_rates({"vo", "pe"}, 0.08)

    if p in {"triple_all", "vo_da_pe", "all", "triple", "3axis"}:
        return axis_rates({"vo", "da", "pe"}, 0.05)

    return auto_skin_candidate_rates(center)[0]


def normalize_color_code(token: str | None) -> str | None:
    text = str(token or "").strip().upper()
    if not text:
        return None
    return _COLOR_WORD_TO_CODE.get(text)


def color_set_from_target_mode(target_color_mode: str, *, song_color: str) -> set[str] | None:
    mode_raw = str(target_color_mode or "song").strip()
    mode = mode_raw.lower()
    if mode in {"song", ""}:
        sc = normalize_color_code(song_color) or "ALL"
        return None if sc == "ALL" else {sc}
    if mode == "all":
        return None

    tokens = re.split(r"[,+/&|・\s]+", mode_raw)
    colors: set[str] = set()
    for tok in tokens:
        code = normalize_color_code(tok)
        if code == "ALL":
            return None
        if code:
            colors.add(code)
    if colors:
        return colors

    upper = mode_raw.upper()
    for word in re.findall(r"(RED|BLUE|GREEN|YELLOW|PURPLE|ALL)", upper):
        code = normalize_color_code(word)
        if code == "ALL":
            return None
        if code:
            colors.add(code)
    if colors:
        return colors

    sc = normalize_color_code(song_color) or "ALL"
    return None if sc == "ALL" else {sc}


def serialize_color_set(colors: set[str] | None) -> str:
    if colors is None:
        return "all"
    if not colors:
        return "song"
    return ",".join(sorted(colors))


def is_valid_skin_target_mode(raw_mode: str | None) -> bool:
    mode_raw = str(raw_mode or "").strip()
    if not mode_raw:
        return False
    mode = mode_raw.lower()
    if mode in {"song", "all"}:
        return True

    tokens = [tok for tok in re.split(r"[,+/&|・\s]+", mode_raw) if tok.strip()]
    if not tokens:
        return False
    if len(tokens) > 1 and any((normalize_color_code(tok) == "ALL") for tok in tokens):
        return False
    return all(normalize_color_code(tok) is not None for tok in tokens)


def parse_axes(raw: str | list[str] | None) -> set[str]:
    if raw is None:
        return set()
    if isinstance(raw, list):
        vals = [str(x).strip().lower() for x in raw if str(x).strip()]
    else:
        vals = [x.strip().lower() for x in str(raw).split(",") if x.strip()]
    out = set(vals)
    if "auto" in out:
        return {"auto"}
    valid = {"vo", "da", "pe"}
    return {x for x in out if x in valid}


def optional_rate_value(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        out = float(text)
    except Exception:
        return None
    return max(0.0, out)


def auto_skin_candidate_targets(center: Any, cards: list[Any], *, song_color: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(mode: str) -> None:
        key = str(mode).strip().lower()
        if not key or key in seen:
            return
        seen.add(key)
        out.append(str(mode).strip())

    add("song")

    source_types = sorted(
        {
            c
            for c in (center.vs_rule.source_types if center.vs_rule else set())
            if c in {"R", "B", "G", "Y", "P"}
        }
    )
    if source_types:
        if len(source_types) >= 2:
            add(",".join(source_types[:2]))
        for color in source_types:
            add(color)

    team_colors = sorted({c.color for c in cards if c.color in {"R", "B", "G", "Y", "P"}})
    for color in team_colors:
        add(color)
    for i in range(len(team_colors)):
        for j in range(i + 1, len(team_colors)):
            add(f"{team_colors[i]},{team_colors[j]}")

    return out
