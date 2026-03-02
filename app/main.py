from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .engine import ScoringEngine

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "app" / "static"
DATA_DIR = ROOT / "app" / "data"
PROFILES_FILE = DATA_DIR / "account_profiles.json"

app = FastAPI(title="UOA Team Scoring Lab", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

ENGINE = ScoringEngine()
OPTIMIZE_JOBS: dict[str, dict[str, Any]] = {}
OPTIMIZE_JOBS_LOCK = threading.Lock()
OPTIMIZE_JOB_KEEP_SEC = 24 * 3600
OPTIMIZE_JOB_MAX_COUNT = 120


class EvaluateRequest(BaseModel):
    card_codes: list[str] = Field(..., min_length=5, max_length=5)
    mode: str = "single"  # single | all | color
    song_key: Optional[str] = None
    song_color: Optional[str] = None
    trials: Optional[int] = None
    seed: int = 20260227
    group_power: int = 1_800_000
    default_member_point: int = 0
    member_points: dict[str, int] = Field(default_factory=dict)
    sort_by: str = "+2sigma"

    enable_costume: bool = True
    costume_vo: int = 125
    costume_da: int = 125
    costume_pe: int = 125
    costume_skill_per_card: int = 10

    scene_skill_per_card: int = 430

    enable_office: bool = True
    office_vo: float = 0.17
    office_da: float = 0.17
    office_pe: float = 0.17

    enable_skin: bool = True
    front_skin_rate: float = 0.08
    front_skin_axes: list[str] = Field(default_factory=lambda: ["auto"])
    front_skin_target_color: str = "song"

    enable_type_bonus: bool = True
    type_bonus_rate: float = 0.30

    include_histogram: bool = True
    histogram_bins: int = 120


class OptimizeRequest(BaseModel):
    pool_scope: str = "owned"  # all | owned
    owned_card_codes: list[str] = Field(default_factory=list)
    exclude_card_codes: list[str] = Field(default_factory=list)
    center_card_codes: list[str] = Field(default_factory=list)
    must_include_codes: list[str] = Field(default_factory=list)

    mode: str = "single"  # single only for now
    song_key: Optional[str] = None
    trials: int = 10_000
    seed: int = 20260227
    group_power: int = 1_800_000
    default_member_point: int = 0
    member_points: dict[str, int] = Field(default_factory=dict)
    sort_by: str = "+2sigma"

    top_n: int = 5
    center_candidates_per_center: int = 5
    shortlist_size: int = 50
    search_pool_size: int = 80
    preselect_top_m: int = 30
    preselect_all: bool = False
    disable_fast_all: bool = False
    pre_eval_trials: int = 100
    final_eval_count: int = 0
    candidate_strategy: str = "default"  # default | axis_t1
    opt_min_skill_expected: float = 3.0

    enable_costume: bool = True
    costume_vo: int = 125
    costume_da: int = 125
    costume_pe: int = 125
    costume_skill_per_card: int = 10

    scene_skill_per_card: int = 430

    enable_office: bool = True
    office_vo: float = 0.17
    office_da: float = 0.17
    office_pe: float = 0.17

    enable_skin: bool = True
    front_skin_rate: float = 0.08
    front_skin_axes: list[str] = Field(default_factory=lambda: ["auto"])
    front_skin_target_color: str = "song"

    enable_type_bonus: bool = True
    type_bonus_rate: float = 0.30

    include_histogram: bool = False
    histogram_bins: int = 120


class ProfileSaveRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    group_power: int = Field(default=0, ge=0)
    member_points: dict[str, int] = Field(default_factory=dict)
    owned_codes: list[str] = Field(default_factory=list)
    exclude_codes: list[str] = Field(default_factory=list)


def _normalize_member_points(raw: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for k, v in (raw or {}).items():
        name = str(k or "").strip()
        if not name:
            continue
        try:
            iv = int(v)
        except Exception:
            iv = 0
        out[name] = max(0, iv)
    return out


def _normalize_card_codes(raw: list[Any] | tuple[Any, ...] | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for x in raw:
        code = str(x or "").strip()
        if not code:
            continue
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _load_profiles() -> dict[str, Any]:
    if not PROFILES_FILE.exists():
        return {"profiles": {}}
    try:
        obj = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"profiles": {}}
    if not isinstance(obj, dict):
        return {"profiles": {}}
    profiles = obj.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
    normalized: dict[str, Any] = {}
    for name, p in profiles.items():
        pname = str(name or "").strip()
        if not pname:
            continue
        if not isinstance(p, dict):
            p = {}
        gp = p.get("group_power", 0)
        try:
            gp_int = max(0, int(gp))
        except Exception:
            gp_int = 0
        normalized[pname] = {
            "group_power": gp_int,
            "member_points": _normalize_member_points(p.get("member_points", {})),
            "owned_codes": _normalize_card_codes(p.get("owned_codes", [])),
            "exclude_codes": _normalize_card_codes(p.get("exclude_codes", [])),
            "saved_at": str(p.get("saved_at") or ""),
        }
    return {"profiles": normalized}


def _save_profiles(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gc_optimize_jobs_locked() -> None:
    now_ts = time.time()
    to_remove: list[str] = []
    for job_id, rec in OPTIMIZE_JOBS.items():
        finished_ts = rec.get("finished_ts")
        if finished_ts is None:
            continue
        if now_ts - float(finished_ts) > OPTIMIZE_JOB_KEEP_SEC:
            to_remove.append(job_id)
    for job_id in to_remove:
        OPTIMIZE_JOBS.pop(job_id, None)

    if len(OPTIMIZE_JOBS) <= OPTIMIZE_JOB_MAX_COUNT:
        return
    overflow = len(OPTIMIZE_JOBS) - OPTIMIZE_JOB_MAX_COUNT
    order = sorted(
        OPTIMIZE_JOBS.items(),
        key=lambda x: float(x[1].get("updated_ts", x[1].get("created_ts", 0.0))),
    )
    for job_id, _ in order[:overflow]:
        OPTIMIZE_JOBS.pop(job_id, None)


def _job_to_response(rec: dict[str, Any]) -> dict[str, Any]:
    data = {
        "job_id": rec["job_id"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "started_at": rec.get("started_at"),
        "finished_at": rec.get("finished_at"),
        "error": rec.get("error"),
    }
    if rec["status"] == "success":
        data["result"] = rec.get("result")
    return data


def _run_optimize_job(job_id: str) -> None:
    with OPTIMIZE_JOBS_LOCK:
        rec = OPTIMIZE_JOBS.get(job_id)
        if not rec:
            return
        now_ts = time.time()
        now_iso = _utcnow_iso()
        rec["status"] = "running"
        rec["started_at"] = now_iso
        rec["updated_at"] = now_iso
        rec["updated_ts"] = now_ts
        payload = dict(rec["payload"])
    try:
        result = ENGINE.optimize(payload)
    except ValueError as exc:
        with OPTIMIZE_JOBS_LOCK:
            rec = OPTIMIZE_JOBS.get(job_id)
            if rec:
                now_ts = time.time()
                now_iso = _utcnow_iso()
                rec["status"] = "error"
                rec["error"] = str(exc)
                rec["finished_at"] = now_iso
                rec["finished_ts"] = now_ts
                rec["updated_at"] = now_iso
                rec["updated_ts"] = now_ts
                _gc_optimize_jobs_locked()
        return
    except Exception as exc:
        with OPTIMIZE_JOBS_LOCK:
            rec = OPTIMIZE_JOBS.get(job_id)
            if rec:
                now_ts = time.time()
                now_iso = _utcnow_iso()
                rec["status"] = "error"
                rec["error"] = f"optimize failed: {exc}"
                rec["finished_at"] = now_iso
                rec["finished_ts"] = now_ts
                rec["updated_at"] = now_iso
                rec["updated_ts"] = now_ts
                _gc_optimize_jobs_locked()
        return

    with OPTIMIZE_JOBS_LOCK:
        rec = OPTIMIZE_JOBS.get(job_id)
        if not rec:
            return
        now_ts = time.time()
        now_iso = _utcnow_iso()
        rec["status"] = "success"
        rec["result"] = result
        rec["error"] = None
        rec["finished_at"] = now_iso
        rec["finished_ts"] = now_ts
        rec["updated_at"] = now_iso
        rec["updated_ts"] = now_ts
        _gc_optimize_jobs_locked()


def _create_optimize_job(payload: dict[str, Any]) -> dict[str, Any]:
    job_id = uuid4().hex
    now_ts = time.time()
    now_iso = _utcnow_iso()
    rec: dict[str, Any] = {
        "job_id": job_id,
        "status": "queued",
        "payload": dict(payload),
        "result": None,
        "error": None,
        "created_at": now_iso,
        "updated_at": now_iso,
        "started_at": None,
        "finished_at": None,
        "created_ts": now_ts,
        "updated_ts": now_ts,
        "finished_ts": None,
    }
    with OPTIMIZE_JOBS_LOCK:
        _gc_optimize_jobs_locked()
        OPTIMIZE_JOBS[job_id] = rec
    threading.Thread(target=_run_optimize_job, args=(job_id,), daemon=True).start()
    return _job_to_response(rec)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/bootstrap")
def bootstrap() -> dict[str, Any]:
    try:
        return ENGINE.bootstrap()
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"bootstrap failed: {exc}") from exc


@app.get("/api/card-icons/{card_code}")
def get_card_icon(card_code: str):
    code = str(card_code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="card_code is required")
    try:
        icon_path = ENGINE.get_or_build_card_icon_path(code)
        if icon_path and icon_path.exists():
            return FileResponse(
                icon_path,
                media_type="image/png",
                headers={
                    "Cache-Control": "public, max-age=31536000, immutable",
                },
            )
        fallback = ENGINE.get_card_icon_fallback_url(code)
        if fallback:
            return RedirectResponse(url=fallback, status_code=307)
        raise HTTPException(status_code=404, detail="icon not found")
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"card icon failed: {exc}") from exc


@app.post("/api/evaluate")
def evaluate(req: EvaluateRequest) -> dict[str, Any]:
    try:
        return ENGINE.evaluate(req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"evaluate failed: {exc}") from exc


@app.post("/api/optimize")
def optimize(req: OptimizeRequest) -> dict[str, Any]:
    try:
        return ENGINE.optimize(req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"optimize failed: {exc}") from exc


@app.post("/api/optimize/jobs")
def optimize_create_job(req: OptimizeRequest) -> dict[str, Any]:
    try:
        payload = req.model_dump()
        return _create_optimize_job(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"optimize job create failed: {exc}") from exc


@app.get("/api/optimize/jobs/{job_id}")
def optimize_get_job(job_id: str) -> dict[str, Any]:
    key = str(job_id or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="job_id is required")
    with OPTIMIZE_JOBS_LOCK:
        rec = OPTIMIZE_JOBS.get(key)
        if rec is None:
            raise HTTPException(status_code=404, detail="optimize job not found or expired")
        return _job_to_response(rec)


@app.get("/api/profiles")
def get_profiles() -> dict[str, Any]:
    try:
        return _load_profiles()
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"profiles read failed: {exc}") from exc


@app.post("/api/profiles")
def save_profile(req: ProfileSaveRequest) -> dict[str, Any]:
    try:
        data = _load_profiles()
        profiles = data.setdefault("profiles", {})
        now = datetime.now(timezone.utc).isoformat()
        name = req.name.strip()
        profiles[name] = {
            "group_power": max(0, int(req.group_power)),
            "member_points": _normalize_member_points(req.member_points),
            "owned_codes": _normalize_card_codes(req.owned_codes),
            "exclude_codes": _normalize_card_codes(req.exclude_codes),
            "saved_at": now,
        }
        _save_profiles(data)
        return {"ok": True, "name": name, "profile": profiles[name]}
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"profile save failed: {exc}") from exc


@app.delete("/api/profiles/{name}")
def delete_profile(name: str) -> dict[str, Any]:
    try:
        key = str(name or "").strip()
        if not key:
            raise HTTPException(status_code=400, detail="name is required")
        data = _load_profiles()
        profiles = data.setdefault("profiles", {})
        existed = key in profiles
        if existed:
            profiles.pop(key, None)
            _save_profiles(data)
        return {"ok": existed}
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"profile delete failed: {exc}") from exc
