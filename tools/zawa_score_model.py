#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import math
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


ZAWA_MASTER_URL = "https://zawa-oden-smk.github.io/uniair_sim/Score_sim_master.js"
ZAWA_PERCENTILES = (
    (0.0013, "-3sigma"),
    (0.0228, "-2sigma"),
    (0.1587, "-1sigma"),
    (0.5, "median"),
    (0.8413, "+1sigma"),
    (0.9772, "+2sigma"),
    (0.9987, "+3sigma"),
)
COLOR_WORD_TO_CODE = {
    "RED": "R",
    "BLUE": "B",
    "GREEN": "G",
    "YELLOW": "Y",
    "PURPLE": "P",
    "ALL": "ALL",
}


def _http_get_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urlopen(req, timeout=30).read().decode("utf-8", "ignore")


def _normalize_song_name(text: str) -> str:
    t = str(text or "").replace("\u3000", " ").replace("\u00a0", " ")
    t = re.sub(r"\s+", "", t)
    return t.strip()


@dataclass(frozen=True)
class SkillFrame:
    interval: int
    proc_pct: float
    duration: int
    combo_pct: float
    score_pct: float


@dataclass(frozen=True)
class SkillProfile:
    front: SkillFrame
    back: SkillFrame
    use_fleek: bool = False


ZERO_FRAME = SkillFrame(interval=1, proc_pct=0.0, duration=0, combo_pct=0.0, score_pct=0.0)


def _as_int(x: Any, default: int = 0) -> int:
    try:
        return int(str(x).strip())
    except Exception:
        return default


def _as_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(str(x).strip())
    except Exception:
        return default


def load_master(path: Path, refresh: bool = False) -> dict[str, Any]:
    if refresh or not path.exists():
        js_code = _http_get_text(ZAWA_MASTER_URL)
        try:
            import quickjs  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise SystemExit(
                "quickjs is required to load zawa score model data. "
                "Install in .venv: .venv/bin/pip install quickjs\n"
                f"details: {exc}"
            )
        ctx = quickjs.Context()
        ctx.eval(js_code)
        raw = ctx.eval("JSON.stringify({songlist:songlist,songdata:songdata,fleekdata:fleekdata})")
        payload = json.loads(raw)
        out = {
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "source": ZAWA_MASTER_URL,
            "songlist": payload.get("songlist", []),
            "songdata": payload.get("songdata", []),
            "fleekdata": payload.get("fleekdata", []),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    for k in ("songlist", "songdata", "fleekdata"):
        if k not in data or not isinstance(data[k], list):
            raise SystemExit(f"Invalid zawa master json (missing {k}): {path}")
    return data


def find_song_index(
    master: dict[str, Any],
    *,
    name: str,
    color_code: str | None = None,
    level: int | None = None,
    seconds: int | None = None,
    notes: int | None = None,
) -> int:
    target_name = _normalize_song_name(name)
    target_color = (color_code or "").strip().upper()
    candidates: list[int] = []
    for idx, row in enumerate(master["songlist"]):
        row_name = _normalize_song_name(row.get("song", ""))
        if row_name != target_name:
            continue
        row_color = COLOR_WORD_TO_CODE.get(str(row.get("color", "")).upper(), "ALL")
        if target_color and target_color != "ALL" and row_color != target_color:
            continue
        candidates.append(idx)
    if not candidates:
        return -1

    def _rank(i: int) -> tuple[int, int, int]:
        row = master["songlist"][i]
        score = 0
        if level is not None and _as_int(row.get("lv")) == int(level):
            score += 10
        if seconds is not None and _as_int(row.get("sec")) == int(seconds):
            score += 5
        if notes is not None and _as_int(row.get("notes")) == int(notes):
            score += 3
        return (score, _as_int(row.get("lv")), -i)

    candidates.sort(key=_rank, reverse=True)
    return candidates[0]


def parse_skill_presets(raw: str) -> list[SkillProfile]:
    items = [x.strip() for x in str(raw or "").split(";") if x.strip()]
    if len(items) != 5:
        raise SystemExit("--zawa-skill-presets must contain exactly 5 entries separated by ';'")
    out: list[SkillProfile] = []
    for item in items:
        use_fleek = False
        token = item
        if token.lower().endswith(":fleek"):
            token = token[:-6].strip()
            use_fleek = True
        mult = 1.0
        if "/" in token:
            token, m = token.rsplit("/", 1)
            mult = _as_float(m.replace("倍", "").strip(), 1.0)
        pair = [x.strip() for x in token.split(",") if x.strip()]
        front = _parse_skill_tuple(pair[0], mult=mult)
        back = _parse_skill_tuple(pair[1], mult=mult) if len(pair) >= 2 else ZERO_FRAME
        out.append(SkillProfile(front=front, back=back, use_fleek=use_fleek))
    return out


def _parse_skill_tuple(raw: str, *, mult: float) -> SkillFrame:
    nums = [x.strip() for x in raw.split("-") if x.strip()]
    if len(nums) != 5:
        raise SystemExit(f"invalid skill tuple: {raw} (need A-B-C-D-E)")
    a, b, c, d, e = (_as_float(nums[i]) for i in range(5))
    return SkillFrame(
        interval=max(1, int(round(a))),
        proc_pct=max(0.0, min(99.0, float(b) * float(mult))),
        duration=max(0, int(round(c))),
        combo_pct=max(0.0, float(d)),
        score_pct=max(0.0, float(e)),
    )


def parse_card_skill_profile(
    *,
    skill_desc: str,
    card_color: str,
    song_color: str,
    proc_multiplier: float,
) -> SkillProfile:
    desc = str(skill_desc or "")
    m = re.search(r"(\d+)秒おきに([0-9]+(?:\.[0-9]+)?)%の確率で(\d+)秒間", desc)
    if not m:
        return SkillProfile(front=ZERO_FRAME, back=ZERO_FRAME, use_fleek=False)
    a = int(m.group(1))
    b = float(m.group(2))
    c = int(m.group(3))

    # We keep two intermediate values by textual axis first:
    #   - score_like: values described as "スコア..."
    #   - combo_like: values described as "コンボボーナス..."
    # Then map to zawa tuple ordering at the end.
    #
    # NOTE:
    # zawa's preset tuples (kitaichi) behave as if score-like values are stored
    # in D and combo-like values are stored in E. This is intentionally preserved
    # here to match zawa simulator outputs.
    score_like = 0.0
    combo_like = 0.0

    m_combo = re.search(r"コンボボーナス(?:が[^0-9%]*)?([0-9]+(?:\.[0-9]+)?)%アップ", desc)
    if m_combo:
        combo_like = float(m_combo.group(1))
    m_score = re.search(
        r"(?:PERFECT(?:とGREAT)?\s*の)?\s*スコア(?:が[^0-9%]*)?([0-9]+(?:\.[0-9]+)?)%アップ",
        desc,
    )
    if m_score:
        score_like = float(m_score.group(1))

    # zawa default assumption for evolved V/S skills:
    # even when text is the non-bond variant in masters, evaluate with max-bond base.
    if (
        a == 8
        and int(round(b)) == 16
        and c == 7
        and "スコア" in desc
        and "同タイプ楽曲のときに効果+11%アップ" in desc
    ):
        score_like = max(score_like, 19.0)
    if (
        a == 9
        and int(round(b)) == 20
        and c == 9
        and "コンボボーナス" in desc
        and "同タイプ楽曲のときに効果+24%アップ" in desc
    ):
        combo_like = max(combo_like, 41.0)
    if (
        a == 7
        and int(round(b)) == 28
        and c == 6
        and "スコア" in desc
        and "同タイプ楽曲のときに効果+7%アップ" in desc
    ):
        score_like = max(score_like, 12.0)

    # Parse conditional "+X%アップ" segments conservatively.
    # Example:
    #   "...コンボボーナス24%アップ、同タイプ楽曲のときに効果+24%アップ"
    # For other-color songs, this conditional +24 must NOT apply.
    for m_plus in re.finditer(r"([^。]{0,80})\+([0-9]+(?:\.[0-9]+)?)%アップ", desc):
        scope = str(m_plus.group(1) or "")
        v = float(m_plus.group(2))
        same = song_color != "ALL" and card_color == song_color
        other = song_color == "ALL" or card_color != song_color

        if ("同タイプ" in scope) or ("同色" in scope):
            apply = same
        elif ("他タイプ" in scope) or ("他色" in scope):
            apply = other
        else:
            # Unqualified +X effects apply in all colors.
            apply = True

        if not apply:
            continue

        # Axis inference: if base clause is pure score/combo, add to that axis.
        if score_like > 0.0 and combo_like <= 0.0:
            score_like += v
        elif combo_like > 0.0 and score_like <= 0.0:
            combo_like += v
        else:
            score_like += v
            combo_like += v

    # zawa tuple compatibility mapping:
    #   D (combo_pct in simulator core) <= score-like textual bonuses
    #   E (score_pct in simulator core) <= combo-like textual bonuses
    combo = score_like
    score = combo_like

    frame = SkillFrame(
        interval=max(1, int(a)),
        proc_pct=max(0.0, min(99.0, b * max(0.0, float(proc_multiplier)))),
        duration=max(0, int(c)),
        combo_pct=max(0.0, combo),
        score_pct=max(0.0, score),
    )
    return SkillProfile(front=frame, back=ZERO_FRAME, use_fleek=("Fleek" in desc))


def simulate(
    *,
    master: dict[str, Any],
    song_index: int,
    front_power: int,
    group_power: int,
    skills: list[SkillProfile],
    trials: int = 10000,
    seed: int | None = None,
    min_trials_floor: int = 1000,
    return_histogram: bool = False,
    histogram_bins: int = 120,
) -> dict[str, Any]:
    if song_index < 0 or song_index >= len(master["songlist"]):
        raise SystemExit(f"invalid song index: {song_index}")
    if len(skills) != 5:
        raise SystemExit("skills must contain exactly 5 profiles")

    song = master["songlist"][song_index]
    songdata = master["songdata"][song_index]
    fleekdata = master["fleekdata"][song_index]

    notes = _as_int(song.get("notes"))
    simlength = _as_int(song.get("sec"))
    song_lv = _as_int(song.get("lv"))
    fs_note = _as_int(song.get("FS"))
    ff_note = _as_int(song.get("FF"))
    if notes <= 0 or simlength <= 0:
        raise SystemExit(f"invalid song metadata for score sim: {song}")
    if len(songdata) < notes or len(fleekdata) < notes:
        raise SystemExit(f"invalid note timing arrays for song index {song_index}")

    base_note = []
    for i in range(1, notes + 1):
        m = 1.2 if fs_note <= i <= ff_note else 1.0
        base_note.append(m)
    base_score = int(round((0.25 * song_lv + 5.0) * (front_power + 0.08 * group_power) / float(notes)))

    frames: list[tuple[SkillFrame, bool]] = []
    for p in skills:
        frames.append((p.front, p.use_fleek))
        frames.append((p.back, p.use_fleek))

    note_sec_main = [max(1, min(simlength, _as_int(x, 1))) for x in songdata[:notes]]
    note_sec_fleek = [max(1, min(simlength, _as_int(x, 1))) for x in fleekdata[:notes]]

    def _score_without_skill() -> int:
        s = 0
        for i in range(1, notes + 1):
            s += int(math.ceil(base_score * base_note[i - 1] * (1.0 + i / float(notes))))
        return s

    n_frames = len(frames)
    intervals = [max(1, int(fr.interval)) for fr, _ in frames]
    durations = [max(0, int(fr.duration)) for fr, _ in frames]
    combo_pcts = [float(fr.combo_pct) for fr, _ in frames]
    score_pcts = [float(fr.score_pct) for fr, _ in frames]
    proc_thresholds = [float(fr.proc_pct) * 100.0 for fr, _ in frames]
    use_fleek_flags = [bool(use_fleek) for _fr, use_fleek in frames]

    note_progress = [(i / float(notes)) for i in range(1, notes + 1)]

    def _roll_hit(rng: random.Random | None, *, force_success: bool, threshold: float) -> bool:
        if force_success:
            return threshold > 0.0
        assert rng is not None
        return rng.randint(1, 10000) <= threshold

    def _run_once(rng: random.Random | None, *, force_success: bool) -> int:
        status = [False] * n_frames
        counter = [1] * n_frames

        # Per-second accumulated bonuses (0-index unused to keep direct sec indexing).
        main_score = [0.0] * (simlength + 1)
        main_combo = [0.0] * (simlength + 1)
        fleek_score = [0.0] * (simlength + 1)
        fleek_combo = [0.0] * (simlength + 1)

        for j in range(n_frames):
            status[j] = _roll_hit(
                rng,
                force_success=force_success,
                threshold=proc_thresholds[j],
            )
            counter[j] = 1

        # sec=1 is always inactive in zawa logic.
        for sec in range(2, simlength + 1):
            for j in range(n_frames):
                a = intervals[j]
                c = durations[j]
                st = status[j]
                cnt = counter[j]
                if (not st) and cnt < a:
                    cnt += 1
                elif st and cnt < a + c:
                    cnt += 1
                else:
                    st = _roll_hit(
                        rng,
                        force_success=force_success,
                        threshold=proc_thresholds[j],
                    )
                    cnt = 1
                status[j] = st
                counter[j] = cnt

                if st and cnt > a:
                    if use_fleek_flags[j]:
                        fleek_score[sec] += score_pcts[j]
                        fleek_combo[sec] += combo_pcts[j]
                    else:
                        main_score[sec] += score_pcts[j]
                        main_combo[sec] += combo_pcts[j]

        total = 0
        for i in range(notes):
            sec_main = note_sec_main[i]
            sec_fleek = note_sec_fleek[i]
            score_bonus = (main_score[sec_main] + fleek_score[sec_fleek]) / 100.0
            combo_bonus = (main_combo[sec_main] + fleek_combo[sec_fleek]) / 100.0
            val = int(
                math.ceil(
                    base_score
                    * base_note[i]
                    * (1.0 + note_progress[i] * (1.0 + score_bonus))
                    * (1.0 + combo_bonus)
                )
            )
            total += val
        return total

    rng = random.Random(seed)
    sims: list[int] = []
    n_trials = max(int(min_trials_floor), int(trials))
    for _ in range(n_trials):
        sims.append(_run_once(rng, force_success=False))
    sims.sort()

    def _q(p: float) -> int:
        for idx, v in enumerate(sims):
            if (idx + 1) / float(n_trials + 1) > p:
                return int(v)
        return int(sims[-1])

    out = {
        "min": int(_score_without_skill()),
        "max": int(_run_once(None, force_success=True)),
    }
    for p, key in ZAWA_PERCENTILES:
        out[key] = _q(p)

    if return_histogram:
        lo = int(sims[0])
        hi = int(sims[-1])
        bins = max(10, min(400, int(histogram_bins)))
        if hi <= lo:
            hist = [{"x0": lo, "x1": hi, "x": lo, "count": int(n_trials), "p": 1.0}]
        else:
            width = max(1, int(math.ceil((hi - lo + 1) / float(bins))))
            n = int(math.ceil((hi - lo + 1) / float(width)))
            counts = [0 for _ in range(n)]
            for v in sims:
                idx = min((int(v) - lo) // width, n - 1)
                counts[idx] += 1
            hist = []
            for i, c in enumerate(counts):
                if c <= 0:
                    continue
                x0 = lo + i * width
                x1 = min(hi, x0 + width - 1)
                xc = (x0 + x1) // 2
                hist.append(
                    {
                        "x0": int(x0),
                        "x1": int(x1),
                        "x": int(xc),
                        "count": int(c),
                        "p": float(c) / float(n_trials),
                    }
                )
        out["mean"] = int(round(sum(sims) / float(n_trials)))
        out["histogram"] = hist
    return out
