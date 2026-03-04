from __future__ import annotations

import copy
import hashlib
import io
import itertools
import json
import math
import os
import re
import sys
import threading
import time
from collections import Counter, OrderedDict
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = Path(os.environ.get("UOA_DATA_ROOT", str(PROJECT_ROOT))).expanduser().resolve()
RUNTIME_DATA_DIR = Path(
    os.environ.get("UOA_RUNTIME_DATA_DIR", str(PROJECT_ROOT / "app" / "data"))
).expanduser().resolve()
TOOLS_DIR = PROJECT_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import optimize_vs_base_teams as opt
import zawa_score_model as zsm
from .engine_parts.effect_summary import team_effect_summary as _team_effect_summary
from .engine_parts.scene_keys import kosa_color_to_short as _kosa_color_to_short
from .engine_parts.scene_keys import norm_scene_title as _norm_scene_title
from .engine_parts.scene_keys import scene_match_key as _scene_match_key
from .engine_parts.scene_keys import scene_member_color_key as _scene_member_color_key
from .engine_parts.scene_keys import scene_member_key as _scene_member_key
from .engine_parts.scene_keys import scene_title_key as _scene_title_key
from .engine_parts.skin_target import auto_skin_candidate_targets as _auto_skin_candidate_targets
from .engine_parts.skin_target import auto_skin_axes as _auto_skin_axes
from .engine_parts.skin_target import auto_skin_candidate_rates as _auto_skin_candidate_rates
from .engine_parts.skin_target import color_set_from_target_mode as _color_set_from_target_mode
from .engine_parts.skin_target import is_valid_skin_target_mode as _is_valid_skin_target_mode
from .engine_parts.skin_target import normalize_color_code as _normalize_color_code
from .engine_parts.skin_target import optional_rate_value as _optional_rate_value
from .engine_parts.skin_target import parse_axes as _parse_axes
from .engine_parts.skin_target import serialize_color_set as _serialize_color_set
from .engine_parts.skin_target import skin_axis_rates_by_profile as _skin_axis_rates_by_profile

AXES = ("vo", "da", "pe")
VALID_COLORS = {"R", "B", "G", "Y", "P", "ALL"}
ACTIVE_MEMBERS_FILE = DATASET_ROOT / "catalogs/active_members_manual_20260227.json"
DEFAULT_MEMBER_POINTS_FILE = DATASET_ROOT / "catalogs" / "member_points_manual_20260228.json"
MIN_SKILL_EXPECTED = 2.0
DEFAULT_CLIENT_ASSETS_VERSION = "20251019155458"
KOSA_SCENE_API = "https://uniair-api.kosa3.com/api/scenes/?page_size=500&page=1"
KOSA_SCENE_CACHE = DATASET_ROOT / "catalogs" / "kosa_scene_thumb_cache.json"
KOSA_SCENE_CACHE_MAX_AGE_SEC = 24 * 3600

DEFAULT_CENTER_CANDIDATES_PER_CENTER = 5
DEFAULT_SHORTLIST_SIZE = 50
DEFAULT_SEARCH_POOL_SIZE = 80
DEFAULT_PRESELECT_TOP_M = 30
FAST_ALL_CENTER_LIMIT = 24
FAST_ALL_PER_CENTER = 4
FAST_ALL_SHORTLIST_SIZE = 30
FAST_ALL_SEARCH_POOL_SIZE = 36
_CATALOG_NAME_RE = re.compile(r"^unison_catalog_(\d{8,})\.json$")
VALID_CANDIDATE_STRATEGIES = {"default", "axis_t1"}
DEFAULT_OPT_MIN_SKILL_EXPECTED = 2.0
DEFAULT_PRE_EVAL_TRIALS = 100
DEFAULT_EXACT_ENUM_CANDIDATE_LIMIT = 0

_CDN_ASSET_BASE_TEMPLATE = "https://cdn-assets.unis-on-air.com/client_assets/{version}/Android/"
ICON_CACHE_DIR = RUNTIME_DATA_DIR / "card_icons"
ICON_FETCH_TIMEOUT_SEC = 20
ICON_CACHE_REV = "20260302b"
OPT_CACHE_MAX_ENTRIES = 96

# Common zawa tuple -> expected% anchors used by players for T1/T2 judgement.
# These are used for display only (not the simulator core), to show downgraded
# same-color/other-color expectations consistently in optimizer output.
TUPLE_EXPECTED_ANCHORS: dict[str, float] = {
    "8-16.0-7-30.0-0.0": 3.68,
    "7-28.0-6-19.0-0.0": 3.68,
    "9-20.0-9-0.0-65.0": 3.61,
    "11-26.0-15-0.0-40.0": 3.49,
    "8-38.0-5-18.0-0.0": 3.45,
    "8-14.0-9-25.0-0.0": 3.40,
    "8-16.0-7-19.0-0.0": 2.33,
    "7-28.0-6-12.0-0.0": 2.32,
    "9-20.0-9-0.0-41.0": 2.28,
    "8-38.0-5-6.0-0.0": 1.15,
}


def _skill_tuple_text(frame: zsm.SkillFrame) -> str:
    return (
        f"{int(frame.interval)}-"
        f"{float(frame.proc_pct):.1f}-"
        f"{int(frame.duration)}-"
        f"{float(frame.combo_pct):.1f}-"
        f"{float(frame.score_pct):.1f}"
    )


def _estimate_skill_expected(
    *,
    skill_expected_card: float,
    frame_effective: zsm.SkillFrame,
    frame_same_color: zsm.SkillFrame,
) -> float:
    # 1) direct tuple anchor
    key = _skill_tuple_text(frame_effective)
    if key in TUPLE_EXPECTED_ANCHORS:
        return float(TUPLE_EXPECTED_ANCHORS[key])

    # 2) ratio fallback by score/comb magnitude under same card.
    eff_power = max(0.0, float(frame_effective.combo_pct) + float(frame_effective.score_pct))
    base_power = max(0.0, float(frame_same_color.combo_pct) + float(frame_same_color.score_pct))
    if base_power > 0.0:
        ratio = eff_power / base_power
        return round(float(skill_expected_card) * ratio, 2)

    # 3) no effect axis (e.g., heal/judge) -> fallback to card expected
    return round(float(skill_expected_card), 2)


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


def _type_bonus_total(cards: list[opt.Card], song_color: str, rate: float) -> int:
    if rate <= 0.0:
        return 0
    total = 0
    for c in cards:
        if song_color != "ALL" and c.color != song_color:
            continue
        total += int(math.ceil(float(c.vo) * rate))
        total += int(math.ceil(float(c.da) * rate))
        total += int(math.ceil(float(c.pe) * rate))
    return int(total)


def _office_bonus_total(cards: list[opt.Card], vo_rate: float, da_rate: float, pe_rate: float) -> int:
    total = 0
    for c in cards:
        # Office bonus follows in-game style down-rounding per axis per card.
        total += int(math.floor(float(c.vo) * vo_rate))
        total += int(math.floor(float(c.da) * da_rate))
        total += int(math.floor(float(c.pe) * pe_rate))
    return int(total)


def _skin_bonus_total(
    cards: list[opt.Card],
    *,
    song_color: str,
    vo_rate: float,
    da_rate: float,
    pe_rate: float,
    target_color_mode: str,
) -> int:
    vo_rate = max(0.0, float(vo_rate))
    da_rate = max(0.0, float(da_rate))
    pe_rate = max(0.0, float(pe_rate))
    if vo_rate <= 0.0 and da_rate <= 0.0 and pe_rate <= 0.0:
        return 0
    target_colors = _color_set_from_target_mode(target_color_mode, song_color=song_color)
    total = 0
    for c in cards:
        if target_colors is not None and c.color not in target_colors:
            continue
        if vo_rate > 0.0:
            total += int(math.ceil(float(c.vo) * vo_rate))
        if da_rate > 0.0:
            total += int(math.ceil(float(c.da) * da_rate))
        if pe_rate > 0.0:
            total += int(math.ceil(float(c.pe) * pe_rate))
    return int(total)


def _resolve_skin_axis_rates(
    payload: dict[str, Any],
    center: opt.Card,
    *,
    cards: list[opt.Card] | None,
    song_color: str,
    skin_target: str,
    enable_skin: bool,
) -> tuple[dict[str, float], str]:
    if not enable_skin:
        return {"vo": 0.0, "da": 0.0, "pe": 0.0}, "song"

    target_mode = str(skin_target or "song").strip() or "song"
    profile_raw = payload.get("front_skin_profile")
    if profile_raw is not None and str(profile_raw).strip():
        profile_key = str(profile_raw).strip().lower()
        if profile_key in {"off", "none", "disabled"}:
            return {"vo": 0.0, "da": 0.0, "pe": 0.0}, target_mode

        if profile_key in {"auto", "default"}:
            axis_candidates = _auto_skin_candidate_rates(center)
            target_candidates = [target_mode]
            if target_mode.lower() in {"song", "auto"}:
                target_candidates = _auto_skin_candidate_targets(center, cards or [], song_color=song_color)

            best_rates = axis_candidates[0]
            best_target = target_candidates[0] if target_candidates else target_mode
            best_total = -1
            for tgt in target_candidates:
                for rates in axis_candidates:
                    total = _skin_bonus_total(
                        cards or [],
                        song_color=song_color,
                        vo_rate=rates["vo"],
                        da_rate=rates["da"],
                        pe_rate=rates["pe"],
                        target_color_mode=tgt,
                    )
                    if total > best_total:
                        best_total = total
                        best_rates = rates
                        best_target = tgt
            return best_rates, best_target

        return _skin_axis_rates_by_profile(profile_raw, center), target_mode

    vo_rate = _optional_rate_value(payload.get("front_skin_vo_rate"))
    da_rate = _optional_rate_value(payload.get("front_skin_da_rate"))
    pe_rate = _optional_rate_value(payload.get("front_skin_pe_rate"))
    if vo_rate is not None or da_rate is not None or pe_rate is not None:
        return (
            {
                "vo": float(vo_rate or 0.0),
                "da": float(da_rate or 0.0),
                "pe": float(pe_rate or 0.0),
            },
            target_mode,
        )

    legacy_rate = _optional_rate_value(payload.get("front_skin_rate"))
    legacy_skin_rate = float(legacy_rate if legacy_rate is not None else 0.08)
    legacy_axes = _parse_axes(payload.get("front_skin_axes", ["auto"]))
    focus_axes = _auto_skin_axes(center) if "auto" in legacy_axes else legacy_axes
    return (
        {
            "vo": legacy_skin_rate if "vo" in focus_axes else 0.0,
            "da": legacy_skin_rate if "da" in focus_axes else 0.0,
            "pe": legacy_skin_rate if "pe" in focus_axes else 0.0,
        },
        target_mode,
    )


def _pick_latest_catalog(catalog_dir: Path) -> Path | None:
    best: tuple[int, Path] | None = None
    for p in catalog_dir.glob("unison_catalog_*.json"):
        m = _CATALOG_NAME_RE.match(p.name)
        if not m:
            continue
        ver = int(m.group(1))
        if best is None or ver > best[0]:
            best = (ver, p)
    return best[1] if best else None


def _load_cloud_asset_map(catalog_path: Path | None) -> dict[str, dict[str, str | None]]:
    if catalog_path is None or not catalog_path.exists():
        return {}
    obj = json.loads(catalog_path.read_text(encoding="utf-8"))
    items = obj.get("assets_masters", [])
    if not isinstance(items, list):
        return {}

    out: dict[str, dict[str, str | None]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "")
        if not code:
            continue
        cloud = item.get("cloud_storage_path") or item.get("cloudStoragePath")
        if isinstance(cloud, str) and cloud.strip():
            sig = item.get("signature")
            out[code] = {
                "cloud_storage_path": cloud.strip(),
                "signature": sig.strip() if isinstance(sig, str) and sig.strip() else None,
            }
    return out


def _load_merged_cloud_asset_map(catalog_dir: Path) -> dict[str, dict[str, str | None]]:
    # Merge all catalog snapshots (newest first), so older cards missing in the
    # latest catalog can still resolve their exact card bundle path.
    files = []
    for p in catalog_dir.glob("unison_catalog_*.json"):
        m = _CATALOG_NAME_RE.match(p.name)
        if not m:
            continue
        files.append((int(m.group(1)), p))
    files.sort(key=lambda x: x[0], reverse=True)

    out: dict[str, dict[str, str | None]] = {}
    for _, p in files:
        rows = _load_cloud_asset_map(p)
        for code, item in rows.items():
            if code in out:
                continue
            out[code] = item
    return out


def _load_icon_cloud_map(catalog_path: Path | None) -> dict[str, dict[str, str | None]]:
    all_assets = _load_cloud_asset_map(catalog_path)
    return {
        code: item
        for code, item in all_assets.items()
        if code.startswith("textures/cards/scene_card_") and code.endswith("_icon.png.bytes")
    }


def _build_cloud_icon_url(
    *,
    client_assets_version: str,
    cloud_storage_path: str,
    signature: str | None = None,
) -> str:
    base_url = _CDN_ASSET_BASE_TEMPLATE.format(version=client_assets_version)
    encoded_path = quote(PurePosixPath(str(cloud_storage_path)).as_posix(), safe="/._-")
    url = urljoin(base_url, encoded_path)
    # Keep URL unsigned: signed query frequently yields 400 on public CDN.
    # Browser/img loading is much more stable with the plain object URL.
    _ = signature
    return url


def _load_card_icon_codes(masters_dir: Path) -> dict[str, str]:
    card_rows = json.loads((masters_dir / "card_masters.json").read_text(encoding="utf-8")).get("card_masters", [])
    photo_rows = json.loads((masters_dir / "card_photo_masters.json").read_text(encoding="utf-8")).get("card_photo_masters", [])
    if not isinstance(card_rows, list) or not isinstance(photo_rows, list):
        return {}

    photo_file_by_code: dict[str, str] = {}
    for row in photo_rows:
        if not isinstance(row, dict):
            continue
        code = row.get("code")
        file_name = row.get("file_name")
        if isinstance(code, str) and isinstance(file_name, str) and file_name:
            photo_file_by_code[code] = file_name

    out: dict[str, str] = {}
    for row in card_rows:
        if not isinstance(row, dict):
            continue
        card_code = row.get("code")
        photo_code = row.get("card_photo_master_code1")
        if not (isinstance(card_code, str) and isinstance(photo_code, str)):
            continue
        stem = photo_file_by_code.get(photo_code)
        if not stem:
            continue
        out[card_code] = f"textures/cards/{stem}/{stem}_icon.png.bytes"
    return out


def _load_card_scene_bundle_codes(masters_dir: Path) -> dict[str, dict[str, str]]:
    card_rows = json.loads((masters_dir / "card_masters.json").read_text(encoding="utf-8")).get("card_masters", [])
    photo_rows = json.loads((masters_dir / "card_photo_masters.json").read_text(encoding="utf-8")).get("card_photo_masters", [])
    if not isinstance(card_rows, list) or not isinstance(photo_rows, list):
        return {}

    photo_file_by_code: dict[str, str] = {}
    for row in photo_rows:
        if not isinstance(row, dict):
            continue
        code = row.get("code")
        file_name = row.get("file_name")
        if isinstance(code, str) and isinstance(file_name, str) and file_name:
            photo_file_by_code[code] = file_name

    out: dict[str, dict[str, str]] = {}
    for row in card_rows:
        if not isinstance(row, dict):
            continue
        card_code = row.get("code")
        photo_code = row.get("card_photo_master_code1")
        if not (isinstance(card_code, str) and isinstance(photo_code, str)):
            continue
        stem = photo_file_by_code.get(photo_code)
        if not stem:
            continue
        out[card_code] = {
            "photo_stem": stem,
            "asset_code": f"content/cards/{stem}.unity3d",
        }
    return out


def _resolve_client_assets_version() -> str:
    extract_root = PROJECT_ROOT.parent / "uoa-extract"
    if extract_root.exists():
        try:
            if str(extract_root) not in sys.path:
                sys.path.insert(0, str(extract_root))
            from uoa_intel.remote import latest_remote_versions  # type: ignore

            latest = latest_remote_versions()
            if latest and isinstance(latest.client_assets, str) and latest.client_assets.strip():
                return latest.client_assets.strip()
        except Exception:
            pass
    return DEFAULT_CLIENT_ASSETS_VERSION


def _build_series_tags(*, title: str, is_vs_base: bool) -> list[str]:
    title_key = opt._title_key(title)
    tags: list[str] = []
    if is_vs_base:
        tags.append("V/S")
    if "veaut" in title_key:
        tags.append("Véaut")
    if "s.teller" in title_key:
        tags.append("S.teller")

    # Precious pair cards support both a broad bucket and year-split bucket.
    is_precious_pair = bool(re.search(r"precious\s*-\s*pair", title_key))
    is_precious_pair_23 = bool(re.search(r"precious\s*-\s*pair\s*-\s*'?23", title_key))
    if is_precious_pair:
        tags.append("Precious -pair-")
    if is_precious_pair_23:
        tags.append("Precious -pair-'23")

    return tags


def _group_key_from_group_type_code(code: str | None) -> str | None:
    c = str(code or "").strip()
    if c.startswith("group_type_1_"):
        return "sakura"
    if c.startswith("group_type_2_"):
        return "hinata"
    return None


def _group_label_from_key(key: str | None) -> str | None:
    if key == "sakura":
        return "櫻坂46"
    if key == "hinata":
        return "日向坂46"
    return None


_MANUAL_GENERATION_TABLE: dict[str, dict[int, list[str]]] = {
    "sakura": {
        2: ["遠藤光莉", "大園玲", "大沼晶保", "幸阪茉里乃", "武元唯衣", "田村保乃", "藤吉夏鈴", "増本綺良", "松田里奈", "森田ひかる", "守屋麗奈", "山﨑天"],
        3: ["石森璃花", "遠藤理子", "小田倉麗奈", "小島凪紗", "谷口愛季", "中嶋優月", "的野美青", "向井純葉", "村井優", "村山美羽", "山下瞳月"],
        4: ["浅井恋乃未", "稲熊ひな", "勝又春", "佐藤愛桜", "中川智尋", "松本和子", "目黒陽色", "山川宇衣", "山田桃実"],
    },
    "hinata": {
        2: ["金村美玖", "小坂菜緒", "松田好花"],
        3: ["上村ひなの", "髙橋未来虹", "森本茉莉", "山口陽世"],
        4: ["石塚瑶季", "小西夏菜実", "清水理央", "正源司陽子", "竹内希来里", "平尾帆夏", "平岡海月", "藤嶌果歩", "宮地すみれ", "山下葉留花", "渡辺莉奈"],
        5: ["大田美月", "大野愛実", "片山紗希", "蔵盛妃那乃", "坂井新奈", "佐藤優羽", "下田衣珠季", "高井俐香", "鶴崎仁香", "松尾桜"],
    },
}


def _generation_label(gen_no: int | None) -> str | None:
    if not gen_no or gen_no <= 0:
        return None
    return f"{gen_no}期生"


def _load_manual_member_generations() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for group_key, gens in _MANUAL_GENERATION_TABLE.items():
        for gen_no, members in gens.items():
            for idx, name in enumerate(members, start=1):
                out[opt._normalize_name(name)] = {
                    "group_key": group_key,
                    "generation_no": int(gen_no),
                    "generation_label": _generation_label(int(gen_no)),
                    "generation_member_order": int(idx),
                }
    return out


def _load_active_member_groups(active_members_file: Path) -> dict[str, str]:
    if not active_members_file.exists():
        return {}
    try:
        obj = json.loads(active_members_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    members_obj = obj.get("members", {}) if isinstance(obj, dict) else {}
    if not isinstance(members_obj, dict):
        return {}
    out: dict[str, str] = {}
    for name in members_obj.get("sakurazaka46", []) or []:
        out[opt._normalize_name(str(name))] = "sakura"
    for name in members_obj.get("hinatazaka46", []) or []:
        out[opt._normalize_name(str(name))] = "hinata"
    return out


def _load_default_member_points(path: Path) -> tuple[dict[str, int], dict[str, int]]:
    if not path.exists():
        return {}, {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}
    if isinstance(obj, dict):
        rows = obj.get("member_points") if isinstance(obj.get("member_points"), dict) else obj
    else:
        rows = {}

    raw: dict[str, int] = {}
    norm: dict[str, int] = {}
    if isinstance(rows, dict):
        for k, v in rows.items():
            name = str(k or "").strip()
            if not name:
                continue
            try:
                pts = max(0, int(v))
            except Exception:
                continue
            raw[name] = pts
            norm[opt._normalize_name(name)] = pts
    return norm, raw


def _load_card_character_map(masters_dir: Path) -> dict[str, dict[str, str]]:
    rows = json.loads((masters_dir / "card_masters.json").read_text(encoding="utf-8")).get("card_masters", [])
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip()
        if not code:
            continue
        out[code] = {
            "character_master_code": str(row.get("character_master_code") or "").strip(),
            "group_type_master_code": str(row.get("group_type_master_code") or "").strip(),
        }
    return out


def _load_character_meta_map(masters_dir: Path) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    rows = json.loads((masters_dir / "character_masters.json").read_text(encoding="utf-8")).get("character_masters", [])
    if not isinstance(rows, list):
        return {}, {}
    by_code: dict[str, dict[str, str]] = {}
    by_name_norm: dict[str, dict[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip()
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        info = {
            "name_roman": str(row.get("name_roman") or "").strip(),
            "name_kana": str(row.get("name_kana") or "").strip(),
            "group_type_master_code": str(row.get("group_type_master_code") or "").strip(),
        }
        if code:
            by_code[code] = info
        by_name_norm[opt._normalize_name(name)] = info
    return by_code, by_name_norm


def _load_kosa_scene_rows() -> list[dict[str, Any]]:
    use_cache = False
    if KOSA_SCENE_CACHE.exists():
        try:
            age = time.time() - KOSA_SCENE_CACHE.stat().st_mtime
            use_cache = age <= KOSA_SCENE_CACHE_MAX_AGE_SEC
        except Exception:
            use_cache = False

    if use_cache:
        try:
            obj = json.loads(KOSA_SCENE_CACHE.read_text(encoding="utf-8"))
            rows = obj.get("results", [])
            if isinstance(rows, list) and rows:
                return rows
        except Exception:
            pass

    rows: list[dict[str, Any]] = []
    next_url = KOSA_SCENE_API
    try:
        while next_url and len(rows) < 20_000:
            req = Request(next_url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            page_rows = payload.get("results", [])
            if isinstance(page_rows, list):
                rows.extend([x for x in page_rows if isinstance(x, dict)])
            next_url = str(payload.get("next") or "").strip()
            if next_url.startswith("http://"):
                next_url = "https://" + next_url[len("http://") :]
            if not next_url:
                break
    except Exception:
        if KOSA_SCENE_CACHE.exists():
            try:
                obj = json.loads(KOSA_SCENE_CACHE.read_text(encoding="utf-8"))
                cached_rows = obj.get("results", [])
                if isinstance(cached_rows, list):
                    return [x for x in cached_rows if isinstance(x, dict)]
            except Exception:
                return []
        return []

    if rows:
        try:
            KOSA_SCENE_CACHE.write_text(
                json.dumps(
                    {
                        "fetched_at": int(time.time()),
                        "count": len(rows),
                        "results": rows,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass
    return rows


def _prefer_scene_candidate(new_item: dict[str, Any], old_item: dict[str, Any] | None) -> bool:
    if old_item is None:
        return True
    new_thumb = bool(new_item.get("thumbnail_url"))
    old_thumb = bool(old_item.get("thumbnail_url"))
    if new_thumb and not old_thumb:
        return True
    if old_thumb and not new_thumb:
        return False
    return float(new_item.get("evaluation_value") or 0.0) > float(old_item.get("evaluation_value") or 0.0)


def _pick_member_color_candidate(cands: list[dict[str, Any]], expected_value: float) -> dict[str, Any] | None:
    if not cands:
        return None

    def _to_float(v: Any) -> float | None:
        try:
            if v is None:
                return None
            return float(v)
        except Exception:
            return None

    target = float(expected_value)
    ranked: list[tuple[tuple[float, float, float], dict[str, Any]]] = []
    for cand in cands:
        if not isinstance(cand, dict):
            continue
        if not (cand.get("thumbnail_url") or cand.get("image_url")):
            continue
        ev = _to_float(cand.get("skill_expected_value"))
        has_ev_penalty = 0.0 if ev is not None else 1.0
        ev_delta = abs(float(ev) - target) if ev is not None else 999.0
        eval_rank = -float(cand.get("evaluation_value") or 0.0)
        ranked.append(((has_ev_penalty, ev_delta, eval_rank), cand))
    if not ranked:
        return None
    ranked.sort(key=lambda x: x[0])
    return ranked[0][1]


def _download_asset_bytes(
    *,
    client_assets_version: str,
    cloud_storage_path: str,
    timeout: int = ICON_FETCH_TIMEOUT_SEC,
) -> bytes | None:
    url = _build_cloud_icon_url(
        client_assets_version=client_assets_version,
        cloud_storage_path=cloud_storage_path,
        signature=None,
    )
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception:
        return None


def _download_url_bytes(url: str, timeout: int = ICON_FETCH_TIMEOUT_SEC) -> bytes | None:
    target = str(url or "").strip()
    if not target:
        return None
    try:
        parts = urlsplit(target)
        path = quote(parts.path or "", safe="/%:@")
        query = quote(parts.query or "", safe="=&%:@,;+")
        target = urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))
    except Exception:
        pass
    req = Request(target, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception:
        return None


def _normalize_icon_image(img: Any):
    try:
        rgba = img.convert("RGBA")
    except Exception:
        return img
    w, h = rgba.size
    if w <= 0 or h <= 0:
        return rgba

    alpha = rgba.split()[-1]
    try:
        alpha_mask = alpha.point(lambda a: 255 if int(a) > 8 else 0)
        bbox = alpha_mask.getbbox()
    except Exception:
        bbox = alpha.getbbox()
    left, top, right, bottom = 0, 0, w, h
    if bbox:
        left = max(left, int(bbox[0]))
        top = max(top, int(bbox[1]))
        right = min(right, int(bbox[2]))
        bottom = min(bottom, int(bbox[3]))

    # Trim almost-uniform outer canvas (transparent/near-solid borders) to reduce
    # visible white edges before fitting back into a square icon.
    px = rgba.load()
    edge_pixels: list[tuple[int, int, int, int]] = []
    for x in range(w):
        edge_pixels.append(px[x, 0])
        edge_pixels.append(px[x, h - 1])
    for y in range(h):
        edge_pixels.append(px[0, y])
        edge_pixels.append(px[w - 1, y])
    bg = Counter(edge_pixels).most_common(1)[0][0] if edge_pixels else (255, 255, 255, 0)

    def _is_bg(p: tuple[int, int, int, int], tol: int = 14) -> bool:
        return (
            abs(int(p[0]) - int(bg[0])) <= tol
            and abs(int(p[1]) - int(bg[1])) <= tol
            and abs(int(p[2]) - int(bg[2])) <= tol
            and abs(int(p[3]) - int(bg[3])) <= tol
        )

    max_trim_x = max(0, int(w * 0.22))
    max_trim_y = max(0, int(h * 0.22))
    trim_l = trim_r = trim_t = trim_b = 0

    while top < bottom - 1 and trim_t < max_trim_y:
        row = [px[x, top] for x in range(left, right)]
        if row and (sum(1 for p in row if _is_bg(p)) / len(row)) >= 0.985:
            top += 1
            trim_t += 1
            continue
        break
    while bottom - 1 > top and trim_b < max_trim_y:
        row = [px[x, bottom - 1] for x in range(left, right)]
        if row and (sum(1 for p in row if _is_bg(p)) / len(row)) >= 0.985:
            bottom -= 1
            trim_b += 1
            continue
        break
    while left < right - 1 and trim_l < max_trim_x:
        col = [px[left, y] for y in range(top, bottom)]
        if col and (sum(1 for p in col if _is_bg(p)) / len(col)) >= 0.985:
            left += 1
            trim_l += 1
            continue
        break
    while right - 1 > left and trim_r < max_trim_x:
        col = [px[right - 1, y] for y in range(top, bottom)]
        if col and (sum(1 for p in col if _is_bg(p)) / len(col)) >= 0.985:
            right -= 1
            trim_r += 1
            continue
        break

    crop_w = max(1, right - left)
    crop_h = max(1, bottom - top)
    if crop_w < 16 or crop_h < 16:
        return rgba
    if (crop_w * crop_h) < int(w * h * 0.55):
        return rgba

    cropped = rgba.crop((left, top, right, bottom))
    if crop_w == w and crop_h == h:
        return cropped
    return cropped.resize((w, h))


def _save_png_icon_from_bytes(data: bytes, out_path: Path) -> bool:
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return False
    try:
        with Image.open(io.BytesIO(data)) as im:
            normalized = _normalize_icon_image(im)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            normalized.save(out_path, format="PNG")
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception:
        return False


def _extract_best_icon_image_from_bundle_bytes(data: bytes, out_path: Path) -> bool:
    try:
        import UnityPy  # type: ignore
    except Exception:
        return False
    try:
        env = UnityPy.load(data)
    except Exception:
        return False
    best_img = None
    best_score: tuple[int, int, int, int] | None = None
    for obj in env.objects:
        tname = obj.type.name
        if tname not in ("Texture2D", "Sprite"):
            continue
        try:
            o = obj.read()
            img = getattr(o, "image", None)
            if img is None:
                continue
            w, h = img.size
            w = int(w)
            h = int(h)
            if w <= 0 or h <= 0:
                continue
            lo, hi = (w, h) if w <= h else (h, w)
            ratio = float(hi) / float(lo)
            # Prefer small/medium square icon-like textures first.
            if ratio <= 1.08 and 96 <= lo <= 512:
                rank = 4
            elif ratio <= 1.18 and 96 <= lo <= 512:
                rank = 3
            elif ratio <= 1.08 and 64 <= lo <= 768:
                rank = 2
            elif ratio <= 1.35:
                rank = 1
            else:
                rank = 0

            # Keep tie-break deterministic:
            # 1) higher rank, 2) larger short edge, 3) closer to square,
            # 4) larger area.
            score = (
                rank,
                lo,
                -abs(w - h),
                w * h,
            )
            if best_score is None or score > best_score:
                best_score = score
                best_img = img
        except Exception:
            continue
    if best_img is None:
        return False
    best_img = _normalize_icon_image(best_img)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    best_img.save(out_path)
    return True


def _load_kosa_scene_map() -> dict[str, dict[str, dict[str, Any]]]:
    rows = _load_kosa_scene_rows()
    out_stats: dict[str, dict[str, Any]] = {}
    out_title: dict[str, dict[str, Any]] = {}
    out_member_color: dict[str, dict[str, Any]] = {}
    out_member_color_rows: dict[str, list[dict[str, Any]]] = {}
    out_member: dict[str, dict[str, Any]] = {}
    out_member_rows: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        member = row.get("member") if isinstance(row.get("member"), dict) else {}
        member_name = str(member.get("name") or "").strip()
        color = _kosa_color_to_short(str(row.get("color") or ""))
        try:
            vo = int(row.get("vo") or 0)
            da = int(row.get("da") or 0)
            pe = int(row.get("pe") or 0)
        except Exception:
            continue
        if not member_name or not color:
            continue
        key_stats = _scene_match_key(member_name, color, vo, da, pe)
        skill_obj = row.get("skill") if isinstance(row.get("skill"), dict) else {}
        center_obj = row.get("center_skill") if isinstance(row.get("center_skill"), dict) else {}
        scene_obj = row.get("scene_type") if isinstance(row.get("scene_type"), dict) else {}

        eval_raw = row.get("evaluation_value")
        try:
            eval_value = float(eval_raw)
        except Exception:
            eval_value = 0.0

        cand = {
            "thumbnail_url": str(row.get("thumbnail_url") or "").strip() or None,
            "image_url": str(row.get("image_url") or "").strip() or None,
            "evaluation_value": eval_value,
            "tier_rank": str(row.get("tier_rank") or "").strip() or None,
            "skill_expected_value": skill_obj.get("expected_value"),
            "center_skill_title": str(center_obj.get("title") or "").strip() or None,
            "skill_title": str(skill_obj.get("title") or "").strip() or None,
            "scene_type_title": str(scene_obj.get("title") or "").strip() or None,
            "alternative_title": str(row.get("alternative_title") or "").strip() or None,
        }
        if _prefer_scene_candidate(cand, out_stats.get(key_stats)):
            out_stats[key_stats] = cand

        title_keys = [
            _scene_title_key(member_name, color, cand.get("scene_type_title")),
            _scene_title_key(member_name, color, cand.get("alternative_title")),
        ]
        for key_title in title_keys:
            if key_title.endswith("|"):
                continue
            if _prefer_scene_candidate(cand, out_title.get(key_title)):
                out_title[key_title] = cand

        key_member_color = _scene_member_color_key(member_name, color)
        if _prefer_scene_candidate(cand, out_member_color.get(key_member_color)):
            out_member_color[key_member_color] = cand
        out_member_color_rows.setdefault(key_member_color, []).append(cand)

        key_member = _scene_member_key(member_name)
        if _prefer_scene_candidate(cand, out_member.get(key_member)):
            out_member[key_member] = cand
        out_member_rows.setdefault(key_member, []).append(cand)

    return {
        "by_stats": out_stats,
        "by_title": out_title,
        "by_member_color": out_member_color,
        "by_member_color_rows": out_member_color_rows,
        "by_member": out_member,
        "by_member_rows": out_member_rows,
    }


class ScoringEngine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ready = False
        self._cards: list[opt.Card] = []
        self._cards_by_code: dict[str, opt.Card] = {}
        self._card_payloads: list[dict[str, Any]] = []
        self._card_payload_by_code: dict[str, dict[str, Any]] = {}
        self._card_icon_bundle_assets: dict[str, dict[str, str]] = {}
        self._card_icon_fallback_url: dict[str, str] = {}
        self._songs: list[dict[str, Any]] = []
        self._songs_by_key: dict[str, dict[str, Any]] = {}
        self._zawa_master: dict[str, Any] = {}
        self._default_member_points_norm: dict[str, int] = {}
        self._default_member_points_ui: dict[str, int] = {}
        self._meta: dict[str, Any] = {}
        self._opt_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._opt_cache_lock = threading.Lock()
        self._icon_cache_dir = ICON_CACHE_DIR
        self._icon_lock_guard = threading.Lock()
        self._icon_locks: dict[str, threading.Lock] = {}

    def ensure_loaded(self) -> None:
        with self._lock:
            if self._ready:
                return
            self._load()
            self._ready = True

    def _get_icon_lock(self, key: str) -> threading.Lock:
        with self._icon_lock_guard:
            lock = self._icon_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._icon_locks[key] = lock
            return lock

    def get_card_icon_fallback_url(self, card_code: str) -> str | None:
        self.ensure_loaded()
        code = str(card_code or "").strip()
        if not code:
            return None
        fallback = str(self._card_icon_fallback_url.get(code) or "").strip()
        return fallback or None

    def get_or_build_card_icon_path(self, card_code: str) -> Path | None:
        self.ensure_loaded()
        code = str(card_code or "").strip()
        if not code:
            return None
        bundle = self._card_icon_bundle_assets.get(code)
        if bundle:
            photo_stem = str(bundle.get("photo_stem") or "").strip()
            cloud_path = str(bundle.get("cloud_storage_path") or "").strip()
            if photo_stem and cloud_path:
                out_path = self._icon_cache_dir / f"{photo_stem}.{ICON_CACHE_REV}.png"
                if out_path.exists() and out_path.stat().st_size > 0:
                    return out_path
                lock = self._get_icon_lock(photo_stem)
                with lock:
                    if out_path.exists() and out_path.stat().st_size > 0:
                        return out_path
                    data = _download_asset_bytes(
                        client_assets_version=str(self._meta.get("icons", {}).get("client_assets_version") or DEFAULT_CLIENT_ASSETS_VERSION),
                        cloud_storage_path=cloud_path,
                        timeout=ICON_FETCH_TIMEOUT_SEC,
                    )
                    if data and _extract_best_icon_image_from_bundle_bytes(data, out_path):
                        return out_path

        # Fallback icons (kosa URLs) are also cached locally so UI doesn't need
        # to re-fetch remote image every time a modal/result block rerenders.
        fallback = str(self._card_icon_fallback_url.get(code) or "").strip()
        if not fallback:
            return None
        fallback_key = hashlib.sha1(fallback.encode("utf-8")).hexdigest()[:10]
        fallback_out = self._icon_cache_dir / f"{code}.fallback.{fallback_key}.{ICON_CACHE_REV}.png"
        if fallback_out.exists() and fallback_out.stat().st_size > 0:
            return fallback_out

        lock = self._get_icon_lock(f"{code}.fallback.{fallback_key}")
        with lock:
            if fallback_out.exists() and fallback_out.stat().st_size > 0:
                return fallback_out
            data = _download_url_bytes(fallback, timeout=ICON_FETCH_TIMEOUT_SEC)
            if not data:
                return None
            if _save_png_icon_from_bytes(data, fallback_out):
                return fallback_out
            return None

    def _load(self) -> None:
        masters_dir = opt._find_latest_masters(DATASET_ROOT / "masters")
        workbook = DATASET_ROOT / "UOA大表 新人必看.xlsx"
        # Full pool should include all SSR cards in masters (MV/碟卡等),
        # then filter only by expected tag threshold.
        active_name_norms = None
        cards, card_meta = opt._build_cards(
            masters_dir=masters_dir,
            workbook_path=workbook,
            active_name_norms=active_name_norms,
            exclude_name_norms=None,
        )
        cards = [c for c in cards if float(c.skill_expected) > MIN_SKILL_EXPECTED]
        self._cards = cards
        self._cards_by_code = {c.code: c for c in cards}
        default_points_norm, default_points_raw = _load_default_member_points(DEFAULT_MEMBER_POINTS_FILE)
        self._default_member_points_norm = default_points_norm
        member_display_by_norm: dict[str, str] = {}
        for c in cards:
            if c.member_name_norm and c.member_name_norm not in member_display_by_norm:
                member_display_by_norm[c.member_name_norm] = c.member_name
        points_ui: dict[str, int] = {}
        for name_norm, pts in default_points_norm.items():
            display_name = member_display_by_norm.get(name_norm)
            if display_name:
                points_ui[display_name] = int(pts)
        for raw_name, pts in default_points_raw.items():
            name_norm = opt._normalize_name(raw_name)
            display_name = member_display_by_norm.get(name_norm, raw_name)
            points_ui[display_name] = int(pts)
        self._default_member_points_ui = points_ui
        card_icon_code_map = _load_card_icon_codes(masters_dir)
        card_scene_bundle_codes = _load_card_scene_bundle_codes(masters_dir)
        card_character_map = _load_card_character_map(masters_dir)
        char_meta_by_code, char_meta_by_name = _load_character_meta_map(masters_dir)
        active_member_groups = _load_active_member_groups(ACTIVE_MEMBERS_FILE)
        manual_member_generations = _load_manual_member_generations()
        catalog_dir = DATASET_ROOT / "catalogs"
        catalog_path = _pick_latest_catalog(catalog_dir)
        cloud_assets_latest = _load_cloud_asset_map(catalog_path)
        cloud_assets_merged = _load_merged_cloud_asset_map(catalog_dir)
        icon_cloud_map = {
            code: item
            for code, item in cloud_assets_merged.items()
            if code.startswith("textures/cards/scene_card_") and code.endswith("_icon.png.bytes")
        }
        card_bundle_assets: dict[str, dict[str, str]] = {}
        for card_code, bundle in card_scene_bundle_codes.items():
            asset_code = str(bundle.get("asset_code") or "").strip()
            if not asset_code:
                continue
            cloud_item = cloud_assets_latest.get(asset_code) or cloud_assets_merged.get(asset_code) or {}
            cloud_path = str(cloud_item.get("cloud_storage_path") or "").strip()
            if not cloud_path:
                continue
            card_bundle_assets[card_code] = {
                "photo_stem": str(bundle.get("photo_stem") or "").strip(),
                "asset_code": asset_code,
                "cloud_storage_path": cloud_path,
            }
        kosa_scene_maps = _load_kosa_scene_map()
        kosa_by_stats = kosa_scene_maps.get("by_stats", {})
        kosa_by_title = kosa_scene_maps.get("by_title", {})
        client_assets_version = _resolve_client_assets_version()

        self._zawa_master = zsm.load_master(DATASET_ROOT / "catalogs/zawa_score_sim_master.json", refresh=False)

        songs_raw = opt._load_songlist(DATASET_ROOT / "catalogs/uniair_songlist.json", refresh=False)
        song_payloads: list[dict[str, Any]] = []
        songs_by_key: dict[str, dict[str, Any]] = {}
        for s in songs_raw:
            zawa_idx = zsm.find_song_index(
                self._zawa_master,
                name=s.name,
                color_code=s.color,
                level=s.level,
                seconds=s.seconds,
                notes=s.notes,
            )
            key = f"{s.no}:{s.color}:{opt._normalize_song_name(s.name)}"
            row = {
                "key": key,
                "no": int(s.no),
                "color": s.color,
                "name": s.name,
                "live": s.live,
                "level": int(s.level),
                "notes": int(s.notes),
                "seconds": int(s.seconds),
                "psylli": float(s.psylli),
                "zawa_index": int(zawa_idx),
                "zawa_available": bool(zawa_idx >= 0),
            }
            song_payloads.append(row)
            songs_by_key[key] = row
        # Keep song ordering aligned with zawa's songlist order (zawa_index starts at 0).
        song_payloads.sort(
            key=lambda x: (
                0 if x["zawa_available"] else 1,
                int(x["zawa_index"]) if x["zawa_available"] else 10**9,
                int(x["no"]),
                x["color"],
                x["name"],
                int(x["level"]),
            )
        )
        self._songs = song_payloads
        self._songs_by_key = songs_by_key

        card_payloads: list[dict[str, Any]] = []
        icon_fallback_by_code: dict[str, str] = {}
        for c in cards:
            name_norm = opt._normalize_name(c.member_name)
            card_ch_meta = card_character_map.get(c.code, {})
            char_code = card_ch_meta.get("character_master_code") or ""
            char_meta = char_meta_by_code.get(char_code) or char_meta_by_name.get(name_norm) or {}
            member_name_roman = str(char_meta.get("name_roman") or "").strip() or None
            member_name_kana = str(char_meta.get("name_kana") or "").strip() or None

            group_type_code = (
                str(card_ch_meta.get("group_type_master_code") or "").strip()
                or str(char_meta.get("group_type_master_code") or "").strip()
            )
            manual_gen = manual_member_generations.get(name_norm, {})
            member_group_key = (
                manual_gen.get("group_key")
                or _group_key_from_group_type_code(group_type_code)
                or active_member_groups.get(name_norm)
            )
            member_generation_no = int(manual_gen.get("generation_no") or 0) or None
            member_generation_label = manual_gen.get("generation_label")
            member_generation_member_order = int(manual_gen.get("generation_member_order") or 0)
            member_group_label = _group_label_from_key(member_group_key)
            member_group_generation_key = (
                f"{member_group_key}|{member_generation_no}" if member_group_key and member_generation_no else None
            )

            center_mode = c.vs_rule.mode if c.vs_rule else None
            base_profile = zsm.parse_card_skill_profile(
                skill_desc=c.skill_desc,
                card_color=c.color,
                song_color=c.color,
                proc_multiplier=1.0,
            )
            skill_front_tuple = _skill_tuple_text(base_profile.front)
            skill_bucket = f"{float(c.skill_expected):.2f}"
            if abs(float(c.skill_expected) - 3.68) < 0.01 and "-30.0-" in skill_front_tuple:
                skill_bucket = "3.68s"
            icon_code = card_icon_code_map.get(c.code)
            scene_key = _scene_match_key(c.member_name, c.color, c.vo, c.da, c.pe)
            scene_title_key = _scene_title_key(c.member_name, c.color, c.title)
            bundle_info = card_bundle_assets.get(c.code) or {}
            has_bundle_icon = bool(bundle_info)
            icon_url = f"/api/card-icons/{quote(str(c.code), safe='')}" if has_bundle_icon else None
            icon_source = "card_bundle_exact" if has_bundle_icon else None
            icon_catalog_url = None
            if icon_code:
                cloud_item = icon_cloud_map.get(icon_code) or {}
                cloud_path = str(cloud_item.get("cloud_storage_path") or "").strip()
                if cloud_path:
                    icon_catalog_url = _build_cloud_icon_url(
                        client_assets_version=client_assets_version,
                        cloud_storage_path=cloud_path,
                        signature=cloud_item.get("signature"),
                    )
            fallback_source = None
            kosa_info = kosa_by_stats.get(scene_key) or kosa_by_title.get(scene_title_key) or {}
            if scene_key in kosa_by_stats:
                fallback_source = None if has_bundle_icon else "kosa_thumb_stats"
            elif scene_title_key in kosa_by_title:
                fallback_source = None if has_bundle_icon else "kosa_thumb_title"
            kosa_thumb = kosa_info.get("thumbnail_url") if isinstance(kosa_info, dict) else None
            kosa_image = kosa_info.get("image_url") if isinstance(kosa_info, dict) else None
            fallback_url = str(kosa_thumb or kosa_image or "").strip() or None
            if fallback_url:
                if scene_key in kosa_by_stats:
                    fallback_source = "kosa_thumb_stats" if kosa_thumb else "kosa_image_stats"
                elif scene_title_key in kosa_by_title:
                    fallback_source = "kosa_thumb_title" if kosa_thumb else "kosa_image_title"
                icon_fallback_by_code[str(c.code)] = fallback_url
            if not icon_url and fallback_url:
                icon_url = f"/api/card-icons/{quote(str(c.code), safe='')}"
                icon_source = fallback_source

            card_payloads.append(
                {
                    "code": c.code,
                    "member_name": c.member_name,
                    "member_name_norm": c.member_name_norm,
                    "member_name_roman": member_name_roman,
                    "member_name_kana": member_name_kana,
                    "member_group_key": member_group_key,
                    "member_group_label": member_group_label,
                    "member_generation_no": member_generation_no,
                    "member_generation_label": member_generation_label,
                    "member_generation_member_order": member_generation_member_order,
                    "member_group_generation_key": member_group_generation_key,
                    "title": c.title,
                    "color": c.color,
                    "vo": int(c.vo),
                    "da": int(c.da),
                    "pe": int(c.pe),
                    "power": int(c.vo + c.da + c.pe),
                    "skill_expected": float(c.skill_expected),
                    "skill_bucket": skill_bucket,
                    "skill_front_tuple": skill_front_tuple,
                    "skill_desc": c.skill_desc,
                    "leader_name": c.leader_name,
                    "leader_desc": c.leader_desc,
                    "is_vs_base": bool(c.is_vs_base and c.vs_rule is not None),
                    "center_mode": center_mode,
                    "icon_code": icon_code,
                    "icon_exact_bundle": has_bundle_icon,
                    "icon_url": icon_url,
                    "icon_url_source": icon_source,
                    "icon_catalog_url": icon_catalog_url,
                    "icon_fallback_url": fallback_url,
                    "kosa_thumbnail_url": kosa_thumb,
                    "kosa_evaluation_value": kosa_info.get("evaluation_value") if isinstance(kosa_info, dict) else None,
                    "kosa_tier_rank": kosa_info.get("tier_rank") if isinstance(kosa_info, dict) else None,
                    "kosa_scene_type_title": kosa_info.get("scene_type_title") if isinstance(kosa_info, dict) else None,
                    "kosa_skill_expected_value": kosa_info.get("skill_expected_value") if isinstance(kosa_info, dict) else None,
                    "has_icon": bool(icon_url),
                    "tags": _build_series_tags(title=c.title, is_vs_base=bool(c.is_vs_base and c.vs_rule is not None)),
                }
            )
        card_payloads.sort(
            key=lambda x: (
                x["member_name"],
                x["color"],
                -float(x["skill_expected"]),
                -int(x["power"]),
                x["title"],
            )
        )
        self._card_payloads = card_payloads
        self._card_payload_by_code = {str(x["code"]): x for x in card_payloads}
        self._card_icon_bundle_assets = card_bundle_assets
        self._card_icon_fallback_url = icon_fallback_by_code

        self._meta = {
            "masters_version": masters_dir.name,
            "card_count": len(cards),
            "song_count": len(song_payloads),
            "card_meta": card_meta,
            "filters": {
                "active_members_file": str(ACTIVE_MEMBERS_FILE),
                "active_members_only": bool(card_meta.get("active_filter_enabled", False)),
                "min_skill_expected": MIN_SKILL_EXPECTED,
                "center_candidates": "Véaut/S.teller only",
            },
            "icons": {
                "catalog_file": (catalog_path.name if catalog_path else None),
                "client_assets_version": client_assets_version,
                "mapped_icons": sum(1 for c in card_payloads if c.get("has_icon")),
                "exact_bundle_icons": sum(1 for c in card_payloads if c.get("icon_exact_bundle")),
                "fallback_icons": sum(
                    1
                    for c in card_payloads
                    if str(c.get("icon_url_source", "")).startswith("kosa_")
                ),
                "catalog_cloud_icons": sum(1 for c in card_payloads if c.get("icon_catalog_url")),
                "bundle_assets_resolved": len(card_bundle_assets),
                "fallback_urls_resolved": len(icon_fallback_by_code),
                "no_icon_cards": sum(1 for c in card_payloads if not c.get("has_icon")),
                "kosa_thumb_stats": sum(1 for c in card_payloads if c.get("icon_url_source") == "kosa_thumb_stats"),
                "kosa_thumb_title": sum(1 for c in card_payloads if c.get("icon_url_source") == "kosa_thumb_title"),
                "kosa_image_stats": sum(1 for c in card_payloads if c.get("icon_url_source") == "kosa_image_stats"),
                "kosa_image_title": sum(1 for c in card_payloads if c.get("icon_url_source") == "kosa_image_title"),
                "kosa_member_color": sum(1 for c in card_payloads if c.get("icon_url_source") == "kosa_member_color"),
                "kosa_member_only": sum(1 for c in card_payloads if c.get("icon_url_source") == "kosa_member_only"),
            },
        }

    def bootstrap(self) -> dict[str, Any]:
        self.ensure_loaded()
        return {
            "meta": self._meta,
            "cards": self._card_payloads,
            "songs": self._songs,
            "defaults": {
                "group_power": 1_800_000,
                "default_member_point": 0,
                "member_points": self._default_member_points_ui,
                "trials_single": 10_000,
                "trials_all": 2_000,
                "seed": 20260227,
                "type_bonus_rate": 0.30,
                "enable_type_bonus": True,
                "costume": {"enabled": True, "vo": 125, "da": 125, "pe": 125, "skill": 10},
                "office": {"enabled": True, "vo": 0.17, "da": 0.17, "pe": 0.17},
                "front_skin": {
                    "enabled": True,
                    "profile": "auto",
                    "rate": 0.08,
                    "axes": ["auto"],
                    "target_color": "song",
                },
                "scene_skill_per_card": 430,
                "optimize": {
                    "top_n": 5,
                    "pool_scope": "owned",
                    "trials_recommended_all": 1000,
                    "strict_no_miss": True,
                    "pre_eval_trials": DEFAULT_PRE_EVAL_TRIALS,
                    "final_eval_count": 5,
                    "candidate_strategy": "axis_t1",
                    "opt_min_skill_expected": DEFAULT_OPT_MIN_SKILL_EXPECTED,
                },
            },
        }

    def _normalize_member_points(self, payload: dict[str, Any]) -> dict[str, int]:
        raw_member_points = payload.get("member_points", {}) or {}
        member_points_norm: dict[str, int] = {}
        if isinstance(raw_member_points, dict):
            for k, v in raw_member_points.items():
                try:
                    member_points_norm[opt._normalize_name(str(k))] = max(0, int(v))
                except Exception:
                    continue
        return member_points_norm

    def _member_point_sources(
        self,
        cards: list[opt.Card],
        member_points_norm: dict[str, int],
        default_member_point: int,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        rows: list[dict[str, Any]] = []
        defaults: list[str] = []
        seen: set[str] = set()
        for c in cards:
            if c.member_name_norm in seen:
                continue
            seen.add(c.member_name_norm)
            if c.member_name_norm in member_points_norm:
                points = int(member_points_norm[c.member_name_norm])
                source = "manual"
            else:
                points = int(default_member_point)
                source = "default_estimate"
                defaults.append(c.member_name)
            rows.append(
                {
                    "member_name": c.member_name,
                    "member_name_norm": c.member_name_norm,
                    "points": points,
                    "source": source,
                }
            )
        return rows, defaults

    def _rank_centers_fast(
        self,
        centers: list[opt.Card],
        pool_cards: list[opt.Card],
        *,
        candidate_strategy: str = "default",
        song_color: str = "ALL",
    ) -> list[opt.Card]:
        # Quick center ranking for all-pool mode. This avoids full combinational search
        # on weak centers and keeps one-click optimize responsive.
        scored: list[tuple[float, opt.Card]] = []
        for center in centers:
            supports = opt._support_shortlist(
                center,
                pool_cards,
                shortlist_size=12,
                candidate_strategy=candidate_strategy,
                song_color=song_color,
            )
            if len(supports) < 4:
                continue
            team = [center, *supports[:4]]
            obj = float(opt._objective_value(team, center))
            scored.append((obj, center))
        if not scored:
            return centers
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored]

    def optimize(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_loaded()
        t0 = time.perf_counter()
        control_hook = payload.get("_opt_control_hook")

        def _control_tick() -> None:
            if callable(control_hook):
                control_hook()

        cache_payload = {
            k: v
            for k, v in payload.items()
            if not str(k).startswith("_opt_")
        }
        cache_key = json.dumps(cache_payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        cached: dict[str, Any] | None = None
        with self._opt_cache_lock:
            cached = self._opt_cache.get(cache_key)
            if cached is not None:
                self._opt_cache.move_to_end(cache_key)
        if cached is not None:
            out = copy.deepcopy(cached)
            out.setdefault("meta", {})["cache_hit"] = True
            return out

        _control_tick()

        mode = str(payload.get("mode", "single")).strip().lower()
        if mode != "single":
            raise ValueError("optimize currently supports mode=single only")

        song_key = str(payload.get("song_key", "")).strip()
        if not song_key:
            raise ValueError("song_key is required for optimize")
        song_obj = self._songs_by_key.get(song_key)
        if song_obj is None:
            raise ValueError(f"unknown song_key: {song_key}")
        song_color = str(song_obj.get("color", "ALL")).upper()

        owned_codes = [str(x).strip() for x in payload.get("owned_card_codes", []) if str(x).strip()]
        owned_codes = list(dict.fromkeys(owned_codes))
        unknown_owned = [x for x in owned_codes if x not in self._cards_by_code]
        if unknown_owned:
            raise ValueError(f"unknown owned card codes: {unknown_owned[:8]}")

        raw_pool_scope = str(payload.get("pool_scope", "") or "").strip().lower()
        if raw_pool_scope in {"all", "owned"}:
            pool_scope = raw_pool_scope
        else:
            # Backward compatibility: old clients may omit pool_scope.
            pool_scope = "owned" if owned_codes else "all"

        if pool_scope == "owned":
            if len(owned_codes) < 5:
                raise ValueError("owned_card_codes must contain at least 5 unique cards")
            pool_cards = [self._cards_by_code[x] for x in owned_codes]
        else:
            pool_cards = list(self._cards)
        pool_set = {c.code for c in pool_cards}
        exclude_codes = [str(x).strip() for x in payload.get("exclude_card_codes", []) if str(x).strip()]
        exclude_codes = list(dict.fromkeys(exclude_codes))
        exclude_set = {x for x in exclude_codes if x in self._cards_by_code}
        if exclude_set:
            pool_cards = [c for c in pool_cards if c.code not in exclude_set]
            pool_set = {c.code for c in pool_cards}
        if len(pool_cards) < 5:
            raise ValueError("current pool has fewer than 5 cards after exclusions")

        center_codes_raw = [str(x).strip() for x in payload.get("center_card_codes", []) if str(x).strip()]
        center_codes_raw = list(dict.fromkeys(center_codes_raw))
        if center_codes_raw:
            not_in_pool = [x for x in center_codes_raw if x not in pool_set]
            if not_in_pool:
                raise ValueError(f"center_card_codes not in current pool: {not_in_pool[:8]}")
            center_cards = [self._cards_by_code[x] for x in center_codes_raw]
            non_vs = [c.code for c in center_cards if not (c.is_vs_base and c.vs_rule is not None)]
            if non_vs:
                raise ValueError(f"center_card_codes must be V/S center cards: {non_vs[:8]}")
        else:
            center_cards = [c for c in pool_cards if c.is_vs_base and c.vs_rule is not None]
        if not center_cards:
            raise ValueError("no center candidates found. Select at least one V/S center card in current pool.")

        must_include_codes = [str(x).strip() for x in payload.get("must_include_codes", []) if str(x).strip()]
        must_include_codes = list(dict.fromkeys(must_include_codes))
        if len(must_include_codes) > 5:
            raise ValueError("must_include_codes cannot exceed 5 cards")
        for code in must_include_codes:
            if code not in pool_set:
                raise ValueError(f"must_include code not in current pool: {code}")
        must_include_set = set(must_include_codes)
        center_code_set = {c.code for c in center_cards}
        if len(must_include_set) == 5 and not (must_include_set & center_code_set):
            raise ValueError(
                "must_include=5 requires at least one V/S center card inside must_include_codes"
            )
        candidate_strategy = str(payload.get("candidate_strategy", "default") or "default").strip().lower()
        if candidate_strategy not in VALID_CANDIDATE_STRATEGIES:
            candidate_strategy = "default"
        opt_min_skill_expected = float(payload.get("opt_min_skill_expected", DEFAULT_OPT_MIN_SKILL_EXPECTED))
        if opt_min_skill_expected < 0.0:
            opt_min_skill_expected = 0.0

        # Optimizer pool defaults to T1+ for better quality/stability.
        # Keep V/S cards and explicit constraints even if below threshold.
        must_keep_codes = set(must_include_codes) | set(center_codes_raw)
        filtered_pool_cards: list[opt.Card] = []
        for c in pool_cards:
            if c.code in must_keep_codes:
                filtered_pool_cards.append(c)
                continue
            if c.is_vs_base and c.vs_rule is not None:
                filtered_pool_cards.append(c)
                continue
            if float(c.skill_expected) >= opt_min_skill_expected:
                filtered_pool_cards.append(c)
        if len(filtered_pool_cards) >= 5:
            pool_cards = filtered_pool_cards
            pool_set = {c.code for c in pool_cards}

        # axis_t1 strategy: center candidates prioritize song-color-compatible V/S rules.
        if candidate_strategy == "axis_t1" and song_color in {"R", "B", "G", "Y", "P"}:
            song_color_centers = [
                c
                for c in center_cards
                if c.vs_rule is not None and song_color in set(c.vs_rule.agg_target_types)
            ]
            if song_color_centers:
                center_cards = song_color_centers

        top_n = max(1, min(30, int(payload.get("top_n", 5))))
        user_fixed_centers = bool(center_codes_raw)
        constrained_must_mode = bool(must_include_set)
        disable_fast_all = bool(payload.get("disable_fast_all", False))
        # Fast-all pruning is useful for broad search, but it can miss valid best
        # teams under hard must-include constraints.
        fast_all_mode = (pool_scope == "all" and not user_fixed_centers and not constrained_must_mode and not disable_fast_all)

        if fast_all_mode:
            ranked_centers = self._rank_centers_fast(
                center_cards,
                pool_cards,
                candidate_strategy=candidate_strategy,
                song_color=song_color,
            )
            center_cards = ranked_centers[:FAST_ALL_CENTER_LIMIT]
            # When user pins must-include cards, always keep those V/S cards as
            # eligible centers even in fast-all truncation mode.
            if must_include_set:
                keep_codes = {c.code for c in center_cards}
                for code in must_include_codes:
                    c = self._cards_by_code.get(code)
                    if c is None:
                        continue
                    if not (c.is_vs_base and c.vs_rule is not None):
                        continue
                    if c.code in keep_codes:
                        continue
                    center_cards.append(c)
                    keep_codes.add(c.code)
            per_center = max(FAST_ALL_PER_CENTER, int(payload.get("center_candidates_per_center", FAST_ALL_PER_CENTER)))
            shortlist_size = max(FAST_ALL_SHORTLIST_SIZE, int(payload.get("shortlist_size", FAST_ALL_SHORTLIST_SIZE)))
            search_pool_size = max(FAST_ALL_SEARCH_POOL_SIZE, int(payload.get("search_pool_size", FAST_ALL_SEARCH_POOL_SIZE)))
            preselect_top_m = max(top_n + 4, 9)
        else:
            per_center = max(1, int(payload.get("center_candidates_per_center", DEFAULT_CENTER_CANDIDATES_PER_CENTER)))
            shortlist_size = max(8, int(payload.get("shortlist_size", DEFAULT_SHORTLIST_SIZE)))
            search_pool_size = max(8, int(payload.get("search_pool_size", DEFAULT_SEARCH_POOL_SIZE)))
            preselect_top_m = max(top_n, int(payload.get("preselect_top_m", DEFAULT_PRESELECT_TOP_M)))

        exact_enum_limit = max(0, int(payload.get("exact_enum_candidate_limit", DEFAULT_EXACT_ENUM_CANDIDATE_LIMIT)))
        force_exact_enum = bool(payload.get("force_exact_enum", False))
        # Benchmark switch: disable signature dedupe (center + sorted(4 supports)).
        # Default remains False; normal behavior unchanged.
        disable_signature_check = bool(payload.get("disable_signature_check", False))

        def _estimate_exact_candidate_count() -> int:
            total = 0
            n_pool = len(pool_cards)
            if n_pool < 5:
                return 0
            for center in center_cards:
                fixed_support_codes = [code for code in must_include_codes if code != center.code]
                if len(fixed_support_codes) > 4:
                    continue
                need = 4 - len(fixed_support_codes)
                if need < 0:
                    continue
                avail = n_pool - 1 - len(fixed_support_codes)
                if avail < need:
                    continue
                total += int(math.comb(avail, need))
            return int(total)

        estimated_exact_candidates = _estimate_exact_candidate_count()
        exact_small_pool_mode = bool(
            force_exact_enum
            or (
                exact_enum_limit > 0
                and estimated_exact_candidates > 0
                and estimated_exact_candidates <= exact_enum_limit
            )
        )

        candidates_map: dict[tuple[str, ...], dict[str, Any]] = {}
        skipped_same_center_permutations = 0
        candidate_seq = 0

        def _upsert_candidate(cards: list[opt.Card], center: opt.Card) -> None:
            nonlocal skipped_same_center_permutations, candidate_seq
            # Keep leader role in candidate identity.
            # Same 5 cards with different center (V/S swap) can yield very different
            # effective stats/skill-rate chains, so they must be evaluated separately.
            if disable_signature_check:
                support_codes = tuple(c.code for c in cards if c.code != center.code)
                key = tuple([center.code, *support_codes, f"seq:{candidate_seq}"])
                candidate_seq += 1
            else:
                support_codes = tuple(sorted(c.code for c in cards if c.code != center.code))
                key = tuple([center.code, *support_codes])
                # Center fixed + same 4 supports means equivalent team for scoring.
                # Skip immediately to avoid re-evaluating position permutations.
                if key in candidates_map:
                    skipped_same_center_permutations += 1
                    return
            objective = float(opt._objective_value(cards, center))
            candidates_map[key] = {
                "objective": objective,
                "center_code": center.code,
                "team_codes": [center.code, *list(support_codes)],
                "team_power_scene": int(sum(opt._compute_effective_stats(cards, center))),
            }

        def _enumerate_must_candidates(center: opt.Card) -> None:
            # Exact expansion for tightly constrained runs:
            # when must-include count is 4/5, remaining free slots are at most 1,
            # so we can enumerate without heuristic pruning.
            fixed_support_codes = [code for code in must_include_codes if code != center.code]
            if len(fixed_support_codes) > 4:
                return
            fixed_supports = [self._cards_by_code[code] for code in fixed_support_codes]
            need = 4 - len(fixed_supports)
            if need < 0:
                return
            if need == 0:
                _upsert_candidate([center, *fixed_supports], center)
                return
            if need == 1:
                used_codes = {center.code, *fixed_support_codes}
                for extra in pool_cards:
                    if extra.code in used_codes:
                        continue
                    _upsert_candidate([center, *fixed_supports, extra], center)
                return

        t_build_start = time.perf_counter()
        exact_must_mode = bool(must_include_set and len(must_include_set) >= 4)
        for center in center_cards:
            _control_tick()
            if exact_small_pool_mode:
                fixed_support_codes = [code for code in must_include_codes if code != center.code]
                if len(fixed_support_codes) > 4:
                    continue
                fixed_supports = [self._cards_by_code[code] for code in fixed_support_codes]
                need = 4 - len(fixed_supports)
                if need < 0:
                    continue
                if need == 0:
                    _upsert_candidate([center, *fixed_supports], center)
                    continue
                used_codes = {center.code, *fixed_support_codes}
                free_pool = [c for c in pool_cards if c.code not in used_codes]
                for extras in itertools.combinations(free_pool, need):
                    _control_tick()
                    _upsert_candidate([center, *fixed_supports, *list(extras)], center)
                continue

            if exact_must_mode:
                _enumerate_must_candidates(center)
                continue

            team_candidates = opt._build_team_candidates(
                center=center,
                all_cards=pool_cards,
                shortlist_size=shortlist_size,
                search_pool_size=search_pool_size,
                topk=per_center,
                candidate_strategy=candidate_strategy,
                song_color=song_color,
            )
            for tr in team_candidates:
                cards = [tr.center, *tr.supports]
                code_set = {c.code for c in cards}
                if must_include_set and not must_include_set.issubset(code_set):
                    continue
                _upsert_candidate(cards, center)

            # Hard-seed at least one must-include-valid team for this center.
            # This prevents false "no candidate" when constrained combos are pruned by topk.
            if must_include_set:
                fixed_support_codes = [code for code in must_include_codes if code != center.code]
                if len(fixed_support_codes) <= 4:
                    used_codes = {center.code, *fixed_support_codes}
                    supports: list[opt.Card] = [self._cards_by_code[code] for code in fixed_support_codes]
                    need = 4 - len(supports)
                    if need > 0:
                        # Broaden shortlist for constrained fill-in.
                        broaden = max(search_pool_size * 2, 120)
                        seeded_pool = opt._support_shortlist(
                            center,
                            pool_cards,
                            shortlist_size=broaden,
                            candidate_strategy=candidate_strategy,
                            song_color=song_color,
                        )
                        for c in seeded_pool:
                            if c.code in used_codes:
                                continue
                            supports.append(c)
                            used_codes.add(c.code)
                            if len(supports) >= 4:
                                break
                    if len(supports) == 4:
                        seeded_cards = [center, *supports]
                        if must_include_set.issubset({c.code for c in seeded_cards}):
                            _upsert_candidate(seeded_cards, center)

        if not candidates_map:
            raise ValueError("no candidate teams matched current constraints")
        t_build_end = time.perf_counter()

        if exact_small_pool_mode:
            preselect_top_m = len(candidates_map)
        elif bool(payload.get("preselect_all", False)):
            preselect_top_m = len(candidates_map)
        elif constrained_must_mode:
            # Keep a wider preselection under hard constraints to avoid dropping
            # high-tail (+2σ/+3σ) teams during objective pre-rank.
            preselect_top_m = max(preselect_top_m, min(len(candidates_map), max(top_n * 16, 80)))
        preselect_top_m = max(top_n, min(len(candidates_map), int(preselect_top_m)))
        pre_candidates = sorted(candidates_map.values(), key=lambda x: float(x["objective"]), reverse=True)[:preselect_top_m]
        sort_key = str(payload.get("sort_by", "+2sigma")).strip()
        if sort_key not in {"median", "+1sigma", "+2sigma", "+3sigma"}:
            sort_key = "+2sigma"

        default_member_point = max(0, int(payload.get("default_member_point", 0)))
        member_points_norm = self._normalize_member_points(payload)
        pre_eval_trials = max(0, int(payload.get("pre_eval_trials", DEFAULT_PRE_EVAL_TRIALS)))
        final_eval_count = max(0, int(payload.get("final_eval_count", 0)))

        eval_payload_base = {
            "mode": "single",
            "song_key": song_key,
            "trials": int(payload.get("trials", 10_000)),
            "seed": int(payload.get("seed", 20260227)),
            "group_power": int(payload.get("group_power", 1_800_000)),
            "default_member_point": default_member_point,
            "member_points": payload.get("member_points", {}) or {},
            "sort_by": sort_key,
            "enable_costume": bool(payload.get("enable_costume", True)),
            "costume_vo": int(payload.get("costume_vo", 125)),
            "costume_da": int(payload.get("costume_da", 125)),
            "costume_pe": int(payload.get("costume_pe", 125)),
            "costume_skill_per_card": int(payload.get("costume_skill_per_card", 10)),
            "scene_skill_per_card": int(payload.get("scene_skill_per_card", 430)),
            "enable_office": bool(payload.get("enable_office", True)),
            "office_vo": float(payload.get("office_vo", 0.17)),
            "office_da": float(payload.get("office_da", 0.17)),
            "office_pe": float(payload.get("office_pe", 0.17)),
            "enable_skin": bool(payload.get("enable_skin", True)),
            "front_skin_profile": str(payload.get("front_skin_profile", "auto")),
            "front_skin_rate": float(payload.get("front_skin_rate", 0.08)),
            "front_skin_axes": payload.get("front_skin_axes", ["auto"]),
            "front_skin_vo_rate": payload.get("front_skin_vo_rate"),
            "front_skin_da_rate": payload.get("front_skin_da_rate"),
            "front_skin_pe_rate": payload.get("front_skin_pe_rate"),
            "front_skin_target_color": str(payload.get("front_skin_target_color", "song")),
            "enable_type_bonus": bool(payload.get("enable_type_bonus", True)),
            "type_bonus_rate": float(payload.get("type_bonus_rate", 0.30)),
            "include_histogram": bool(payload.get("include_histogram", False)),
            "histogram_bins": int(payload.get("histogram_bins", 120)),
        }

        trials_full = max(100, min(50_000, int(eval_payload_base["trials"])))
        if len(pre_candidates) <= top_n or pre_eval_trials <= 0:
            trials_fast = trials_full
        else:
            trials_fast = min(trials_full, max(20, pre_eval_trials))

        def _evaluate_row(rank_idx: int, candidate: dict[str, Any], trials_use: int) -> dict[str, Any] | None:
            eval_payload = dict(eval_payload_base)
            eval_payload["trials"] = trials_use
            eval_payload["card_codes"] = candidate["team_codes"]
            evaluated = self.evaluate(eval_payload)
            if not evaluated.get("results"):
                return None
            single = evaluated["results"][0]
            team_cards = [self._cards_by_code[x] for x in candidate["team_codes"]]
            point_sources, default_members = self._member_point_sources(
                team_cards,
                member_points_norm=member_points_norm,
                default_member_point=default_member_point,
            )
            return {
                "pre_rank": rank_idx,
                "objective": float(candidate["objective"]),
                "team_codes": list(candidate["team_codes"]),
                "team": evaluated["team"],
                "result": single,
                "member_point_sources": point_sources,
                "used_default_member_points": default_members,
            }

        teams: list[dict[str, Any]] = []
        t_eval_start = time.perf_counter()
        for rank_idx, candidate in enumerate(pre_candidates, start=1):
            _control_tick()
            row = _evaluate_row(rank_idx, candidate, trials_fast)
            if row is not None:
                teams.append(row)

        # In all-pool fast mode, do a second precise pass only for top rows.
        refined_count_actual = 0
        if trials_fast < trials_full and teams:
            teams.sort(
                key=lambda x: (
                    int(x["result"]["distribution"].get(sort_key, 0)),
                    int(x["result"]["distribution"].get("median", 0)),
                    float(x["objective"]),
                ),
                reverse=True,
            )
            if final_eval_count > 0:
                requested_refine = final_eval_count
            elif exact_small_pool_mode:
                requested_refine = max(top_n * 8, 80)
            else:
                requested_refine = top_n
            refine_count = min(len(teams), max(top_n, requested_refine))
            refined_count_actual = int(refine_count)
            refined: list[dict[str, Any]] = []
            for row in teams[:refine_count]:
                _control_tick()
                candidate = {
                    "objective": row["objective"],
                    "team_codes": row["team_codes"],
                }
                rerun = _evaluate_row(int(row["pre_rank"]), candidate, trials_full)
                if rerun is not None:
                    refined.append(rerun)
            if refined:
                teams = refined
        t_eval_end = time.perf_counter()

        if not teams:
            raise ValueError("optimization produced no evaluated teams")

        teams.sort(
            key=lambda x: (
                int(x["result"]["distribution"].get(sort_key, 0)),
                int(x["result"]["distribution"].get("median", 0)),
                float(x["objective"]),
            ),
            reverse=True,
        )
        # Hard guard at output stage:
        # for the same center, identical 4-support set is equivalent and should
        # never occupy multiple Top slots.
        output_dedup_skipped = 0
        if disable_signature_check:
            teams = teams[:top_n]
        else:
            unique_teams: list[dict[str, Any]] = []
            seen_output_keys: set[tuple[str, ...]] = set()
            for row in teams:
                team_codes = [str(x).strip() for x in row.get("team_codes", []) if str(x).strip()]
                center_code = str(
                    ((row.get("team") or {}).get("center") or {}).get("code")
                    or (team_codes[0] if team_codes else "")
                ).strip()
                if center_code:
                    supports = tuple(sorted(code for code in team_codes if code != center_code))
                    key = (center_code, *supports)
                else:
                    key = tuple(team_codes)
                if key in seen_output_keys:
                    output_dedup_skipped += 1
                    continue
                seen_output_keys.add(key)
                unique_teams.append(row)
            teams = unique_teams[:top_n]

        out = {
            "meta": {
                "mode": "single",
                "song_key": song_key,
                "sort_by": sort_key,
                "group_power": int(eval_payload_base["group_power"]),
                "trials": int(trials_full),
                "top_n": top_n,
                "candidate_count": len(candidates_map),
                "preselected_count": len(pre_candidates),
                "pool_card_count": len(pool_cards),
                "pool_scope": pool_scope,
                "excluded_count": len(exclude_set),
                "center_candidate_count": len(center_cards),
                "must_include_count": len(must_include_codes),
                "opt_min_skill_expected": opt_min_skill_expected,
                "internal_search_config": {
                    "center_candidates_per_center": per_center,
                    "shortlist_size": shortlist_size,
                    "search_pool_size": search_pool_size,
                    "preselect_top_m": preselect_top_m,
                    "fast_all_mode": fast_all_mode,
                    "disable_fast_all": disable_fast_all,
                    "candidate_strategy": candidate_strategy,
                    "preselect_all": bool(payload.get("preselect_all", False)),
                    "preselect_all_effective": bool(exact_small_pool_mode or payload.get("preselect_all", False)),
                    "must_include_seeded": bool(must_include_set),
                    "skipped_same_center_permutations": skipped_same_center_permutations,
                    "output_dedup_skipped": output_dedup_skipped,
                    "disable_signature_check": disable_signature_check,
                    "exact_small_pool_mode": exact_small_pool_mode,
                    "force_exact_enum": force_exact_enum,
                    "exact_enum_candidate_limit": exact_enum_limit,
                    "estimated_exact_candidates": estimated_exact_candidates,
                    "trials_fast": trials_fast,
                    "trials_full": trials_full,
                    "pre_eval_trials": pre_eval_trials,
                    "final_eval_count": final_eval_count if final_eval_count > 0 else top_n,
                    "refined_count_actual": refined_count_actual,
                },
                "distribution_order": ["min", "-3sigma", "-2sigma", "-1sigma", "median", "+1sigma", "+2sigma", "+3sigma", "max"],
                "unknown_member_point_policy": "use request member_points first, then default_member_point and mark source=default_estimate",
                "cache_hit": False,
                "timing_sec": {
                    "build_candidates": round(t_build_end - t_build_start, 3),
                    "evaluate_candidates": round(t_eval_end - t_eval_start, 3),
                    "total": round(time.perf_counter() - t0, 3),
                },
            },
            "teams": teams,
        }
        # Thread-safe LRU cache for repeated optimize requests from UI.
        with self._opt_cache_lock:
            self._opt_cache[cache_key] = copy.deepcopy(out)
            self._opt_cache.move_to_end(cache_key)
            while len(self._opt_cache) > OPT_CACHE_MAX_ENTRIES:
                self._opt_cache.popitem(last=False)
        return out

    def evaluate(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_loaded()

        card_codes = [str(x).strip() for x in payload.get("card_codes", []) if str(x).strip()]
        if len(card_codes) != 5:
            raise ValueError("card_codes must contain exactly 5 cards (first one is center)")
        if len(set(card_codes)) != 5:
            raise ValueError("card_codes must not contain duplicates")

        missing = [x for x in card_codes if x not in self._cards_by_code]
        if missing:
            raise ValueError(f"unknown card codes: {missing}")

        cards = [self._cards_by_code[x] for x in card_codes]
        center = cards[0]

        mode = str(payload.get("mode", "single")).strip().lower()
        if mode not in {"single", "all", "color"}:
            mode = "single"

        trials_default = 10_000 if mode == "single" else 2_000
        trials = int(payload.get("trials", trials_default))
        trials = max(100, min(50_000, trials))

        seed = int(payload.get("seed", 20260227))
        group_power = int(payload.get("group_power", 1_800_000))
        group_power = max(1, group_power)

        default_member_point = int(payload.get("default_member_point", 0))
        default_member_point = max(0, default_member_point)
        raw_member_points = payload.get("member_points", {}) or {}
        member_points_norm: dict[str, int] = {}
        if isinstance(raw_member_points, dict):
            for k, v in raw_member_points.items():
                try:
                    member_points_norm[opt._normalize_name(str(k))] = max(0, int(v))
                except Exception:
                    continue

        enable_costume = bool(payload.get("enable_costume", True))
        costume_vo = int(payload.get("costume_vo", 125)) if enable_costume else 0
        costume_da = int(payload.get("costume_da", 125)) if enable_costume else 0
        costume_pe = int(payload.get("costume_pe", 125)) if enable_costume else 0
        costume_skill = int(payload.get("costume_skill_per_card", 10)) if enable_costume else 0

        scene_skill = int(payload.get("scene_skill_per_card", 430))
        scene_skill = max(0, scene_skill)
        costume_skill = max(0, costume_skill)

        enable_office = bool(payload.get("enable_office", True))
        office_vo = float(payload.get("office_vo", 0.17)) if enable_office else 0.0
        office_da = float(payload.get("office_da", 0.17)) if enable_office else 0.0
        office_pe = float(payload.get("office_pe", 0.17)) if enable_office else 0.0

        enable_skin = bool(payload.get("enable_skin", True))
        skin_target = str(payload.get("front_skin_target_color", "song")).strip() if enable_skin else "song"
        if enable_skin and not _is_valid_skin_target_mode(skin_target):
            skin_target = "song"

        enable_type_bonus = bool(payload.get("enable_type_bonus", True))
        type_bonus_rate = float(payload.get("type_bonus_rate", 0.30)) if enable_type_bonus else 0.0

        include_histogram = bool(payload.get("include_histogram", mode == "single"))
        histogram_bins = int(payload.get("histogram_bins", 120))
        histogram_bins = max(20, min(400, histogram_bins))

        songs = self._select_songs(payload, mode)
        if not songs:
            raise ValueError("no songs matched current selection")

        member_point_total = 0
        member_point_detail: dict[str, int] = {}
        member_point_breakdown: list[dict[str, Any]] = []
        for c in cards:
            key = c.member_name_norm
            points = int(member_points_norm.get(key, default_member_point))
            points = max(0, points)
            member_point_total += points
            member_point_detail[c.member_name] = points
            scene_raw_total = int(c.vo + c.da + c.pe)
            scene_card_total = int(scene_raw_total + scene_skill)
            member_point_breakdown.append(
                {
                    "code": c.code,
                    "member_name": c.member_name,
                    "title": c.title,
                    "color": c.color,
                    "vo": int(c.vo),
                    "da": int(c.da),
                    "pe": int(c.pe),
                    "scene_raw_total": scene_raw_total,
                    "scene_card_total": scene_card_total,
                    "member_point": points,
                    "scene_plus_member": int(scene_card_total + points),
                }
            )

        scene_raw_vo = int(sum(c.vo for c in cards))
        scene_raw_da = int(sum(c.da for c in cards))
        scene_raw_pe = int(sum(c.pe for c in cards))
        eff_vo, eff_da, eff_pe = opt._compute_effective_stats(cards, center)
        team_power_scene = int(eff_vo + eff_da + eff_pe)
        scene_delta = {
            "vo": int(eff_vo - scene_raw_vo),
            "da": int(eff_da - scene_raw_da),
            "pe": int(eff_pe - scene_raw_pe),
        }

        costume_total = int((costume_vo + costume_da + costume_pe) * len(cards))
        office_total = _office_bonus_total(cards, office_vo, office_da, office_pe)
        skill_total = int((scene_skill + costume_skill) * len(cards))

        color_mult, member_mult = opt._collect_skill_rate_multipliers(cards, center)

        results: list[dict[str, Any]] = []
        for idx, song in enumerate(songs):
            skin_rates, skin_target_resolved = _resolve_skin_axis_rates(
                payload,
                center,
                cards=cards,
                song_color=str(song["color"]),
                skin_target=skin_target,
                enable_skin=enable_skin,
            )
            skin_total = _skin_bonus_total(
                cards,
                song_color=str(song["color"]),
                vo_rate=skin_rates["vo"],
                da_rate=skin_rates["da"],
                pe_rate=skin_rates["pe"],
                target_color_mode=skin_target_resolved,
            )
            front_pre = int(team_power_scene + member_point_total + costume_total + office_total + skin_total + skill_total)
            type_bonus = _type_bonus_total(cards, str(song["color"]), type_bonus_rate)
            front_post = int(front_pre + type_bonus)

            skill_profiles: list[zsm.SkillProfile] = []
            skill_rows: list[dict[str, Any]] = []
            for c in cards:
                proc_mult = opt._card_skill_proc_multiplier(c, center, color_mult, member_mult)
                same_color_song = bool(song["color"] == "ALL" or c.color == song["color"])
                profile = zsm.parse_card_skill_profile(
                    skill_desc=c.skill_desc,
                    card_color=c.color,
                    song_color=str(song["color"]),
                    proc_multiplier=proc_mult,
                )
                profile_base = zsm.parse_card_skill_profile(
                    skill_desc=c.skill_desc,
                    card_color=c.color,
                    song_color=str(song["color"]),
                    proc_multiplier=1.0,
                )
                profile_same_color = zsm.parse_card_skill_profile(
                    skill_desc=c.skill_desc,
                    card_color=c.color,
                    song_color=str(c.color),
                    proc_multiplier=1.0,
                )
                effective_expected_base = _estimate_skill_expected(
                    skill_expected_card=float(c.skill_expected),
                    frame_effective=profile_base.front,
                    frame_same_color=profile_same_color.front,
                )
                if c.is_vs_base:
                    if str(song["color"]) == "ALL":
                        tuple_scope = "S.teller/Véaut他色(ALL曲)"
                    elif same_color_song:
                        tuple_scope = "S.teller/Véaut同色"
                    else:
                        tuple_scope = "S.teller/Véaut他色"
                else:
                    if str(song["color"]) == "ALL":
                        tuple_scope = "ALL曲"
                    elif same_color_song:
                        tuple_scope = "同色"
                    else:
                        tuple_scope = "他色"
                skill_profiles.append(profile)
                skill_rows.append(
                    {
                        "code": c.code,
                        "member_name": c.member_name,
                        "title": c.title,
                        "color": c.color,
                        "same_color_song": same_color_song,
                        "tuple_scope": tuple_scope,
                        "is_vs_base": bool(c.is_vs_base),
                        "skill_expected_base": float(c.skill_expected),
                        "skill_expected_effective_base": float(effective_expected_base),
                        "skill_expected_effective": round(float(effective_expected_base) * float(proc_mult), 2),
                        "proc_multiplier": round(proc_mult, 4),
                        "front_tuple_base": _skill_tuple_text(profile_base.front),
                        "back_tuple_base": _skill_tuple_text(profile_base.back),
                        "front_tuple": _skill_tuple_text(profile.front),
                        "back_tuple": _skill_tuple_text(profile.back),
                        "skill_desc": c.skill_desc,
                    }
                )

            sim = zsm.simulate(
                master=self._zawa_master,
                song_index=int(song["zawa_index"]),
                front_power=front_post,
                group_power=group_power,
                skills=skill_profiles,
                trials=trials,
                seed=(None if seed < 0 else int(seed + idx + int(song["no"]))),
                return_histogram=bool(include_histogram and mode == "single"),
                histogram_bins=histogram_bins,
            )

            minus1 = int(sim["-1sigma"])
            plus1 = int(sim["+1sigma"])
            sigma = int(round((plus1 - minus1) / 2.0))
            row = {
                "song": song,
                "distribution": {
                    "min": int(sim["min"]),
                    "-3sigma": int(sim["-3sigma"]),
                    "-2sigma": int(sim["-2sigma"]),
                    "-1sigma": minus1,
                    "median": int(sim["median"]),
                    "+1sigma": plus1,
                    "+2sigma": int(sim["+2sigma"]),
                    "+3sigma": int(sim["+3sigma"]),
                    "max": int(sim["max"]),
                },
                "mean": int(sim.get("mean", sim["median"])),
                "sigma": sigma,
                "front_pre": front_pre,
                "front_post": front_post,
                "bonuses": {
                    "member_point_total": member_point_total,
                    "costume_total": costume_total,
                    "office_total": office_total,
                    "skin_total": skin_total,
                    "skin_vo_rate": round(float(skin_rates.get("vo", 0.0)), 4),
                    "skin_da_rate": round(float(skin_rates.get("da", 0.0)), 4),
                    "skin_pe_rate": round(float(skin_rates.get("pe", 0.0)), 4),
                    "skin_target_mode": skin_target_resolved,
                    "skin_target_colors": _serialize_color_set(
                        _color_set_from_target_mode(skin_target_resolved, song_color=str(song["color"]))
                    ),
                    "type_bonus_total": type_bonus,
                    "skill_stat_total": skill_total,
                },
                "scene_power": {
                    "raw": {"vo": scene_raw_vo, "da": scene_raw_da, "pe": scene_raw_pe, "total": scene_raw_vo + scene_raw_da + scene_raw_pe},
                    "effective": {"vo": eff_vo, "da": eff_da, "pe": eff_pe, "total": team_power_scene},
                    "delta": scene_delta,
                },
                "skill_profiles": skill_rows if mode == "single" else [],
                "member_point_breakdown": member_point_breakdown,
                "effect_summary": _team_effect_summary(cards, center),
                "center_skill": {"name": center.leader_name, "desc": center.leader_desc},
                "histogram": sim.get("histogram", []),
            }
            results.append(row)

        sort_key = str(payload.get("sort_by", "+2sigma")).strip()
        if sort_key not in {"median", "+1sigma", "+2sigma", "+3sigma"}:
            sort_key = "+2sigma"
        results.sort(key=lambda x: int(x["distribution"].get(sort_key, x["distribution"]["median"])), reverse=True)

        return {
            "meta": {
                "mode": mode,
                "trials": trials,
                "group_power": group_power,
                "default_member_point": default_member_point,
                "member_points": member_point_detail,
                "sort_by": sort_key,
                "distribution_order": ["min", "-3sigma", "-2sigma", "-1sigma", "median", "+1sigma", "+2sigma", "+3sigma", "max"],
            },
            "team": {
                "center": {
                    "code": center.code,
                    "member_name": center.member_name,
                    "title": center.title,
                    "color": center.color,
                    "icon_url": self._card_payload_by_code.get(center.code, {}).get("icon_url"),
                },
                "cards": [
                    {
                        "code": c.code,
                        "member_name": c.member_name,
                        "title": c.title,
                        "color": c.color,
                        "vo": int(c.vo),
                        "da": int(c.da),
                        "pe": int(c.pe),
                        "icon_url": self._card_payload_by_code.get(c.code, {}).get("icon_url"),
                    }
                    for c in cards
                ],
            },
            "results": results,
        }

    def _select_songs(self, payload: dict[str, Any], mode: str) -> list[dict[str, Any]]:
        songs = [s for s in self._songs if bool(s["zawa_available"])]
        if mode == "single":
            key = str(payload.get("song_key", "")).strip()
            if key and key in self._songs_by_key and bool(self._songs_by_key[key]["zawa_available"]):
                return [self._songs_by_key[key]]
            raise ValueError("song_key is required for single mode")
        if mode == "color":
            color = str(payload.get("song_color", "ALL")).strip().upper()
            if color not in VALID_COLORS:
                color = "ALL"
            if color == "ALL":
                return songs
            return [s for s in songs if s["color"] == color]
        return songs
