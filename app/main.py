from __future__ import annotations

import os
import json
import hashlib
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .engine import ScoringEngine

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_DATA_DIR = ROOT / "app" / "data"
RUNTIME_DATA_DIR = Path(os.environ.get("UOA_RUNTIME_DATA_DIR", str(DEFAULT_RUNTIME_DATA_DIR))).expanduser().resolve()
STATIC_DIR = ROOT / "app" / "static"
DATA_DIR = RUNTIME_DATA_DIR
PROFILES_FILE = DATA_DIR / "account_profiles.json"
PROFILES_BACKUP_DIR = DATA_DIR / "account_profiles_backups"
PROFILES_BACKUP_KEEP = 20
PROFILES_EXPORT_FORMAT = "uoa_profiles_export"
PROFILES_EXPORT_VERSION = 1

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


class OptimizeJobCanceledError(RuntimeError):
    pass


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
    front_skin_profile: str = "auto"
    front_skin_rate: float = 0.08
    front_skin_axes: list[str] = Field(default_factory=lambda: ["auto"])
    front_skin_vo_rate: Optional[float] = None
    front_skin_da_rate: Optional[float] = None
    front_skin_pe_rate: Optional[float] = None
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
    front_skin_profile: str = "auto"
    front_skin_rate: float = 0.08
    front_skin_axes: list[str] = Field(default_factory=lambda: ["auto"])
    front_skin_vo_rate: Optional[float] = None
    front_skin_da_rate: Optional[float] = None
    front_skin_pe_rate: Optional[float] = None
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


class ProfileUndoRequest(BaseModel):
    backup_file: Optional[str] = None


def _validate_backup_file_name(backup_file: str) -> str:
    bf = str(backup_file or "").strip()
    if not bf:
        raise HTTPException(status_code=400, detail="backup_file is empty")
    if "/" in bf or "\\" in bf:
        raise HTTPException(status_code=400, detail="backup_file is invalid")
    if not (bf.startswith("account_profiles.") and bf.endswith(".json")):
        raise HTTPException(status_code=400, detail="backup_file format is invalid")
    return bf


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
    if PROFILES_FILE.exists():
        try:
            PROFILES_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            current_bytes = PROFILES_FILE.read_bytes()
            should_create_backup = True
            latest_backup = next(iter(_iter_profile_backup_files_desc()), None)
            if latest_backup and latest_backup.exists():
                try:
                    latest_bytes = latest_backup.read_bytes()
                    if _profiles_payload_signature_from_bytes(current_bytes) == _profiles_payload_signature_from_bytes(
                        latest_bytes
                    ):
                        should_create_backup = False
                except Exception:
                    should_create_backup = True

            if should_create_backup:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
                backup_file = PROFILES_BACKUP_DIR / f"account_profiles.{stamp}.json"
                backup_file.write_bytes(current_bytes)
            backups = sorted(PROFILES_BACKUP_DIR.glob("account_profiles.*.json"))
            overflow = len(backups) - PROFILES_BACKUP_KEEP
            if overflow > 0:
                for old in backups[:overflow]:
                    try:
                        old.unlink()
                    except Exception:
                        pass
        except Exception:
            # Backup is best-effort; never block normal save path.
            pass
    PROFILES_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _normalize_profile_entry(raw: dict[str, Any]) -> dict[str, Any]:
    gp = raw.get("group_power", 0)
    try:
        gp_int = max(0, int(gp))
    except Exception:
        gp_int = 0
    return {
        "group_power": gp_int,
        "member_points": _normalize_member_points(raw.get("member_points", {})),
        "owned_codes": _normalize_card_codes(raw.get("owned_codes", [])),
        "exclude_codes": _normalize_card_codes(raw.get("exclude_codes", [])),
        "saved_at": str(raw.get("saved_at") or ""),
    }


def _profile_version_payload(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_profile_entry(raw)
    return {
        "group_power": int(normalized.get("group_power") or 0),
        "member_points": dict(normalized.get("member_points") or {}),
        "owned_codes": sorted(set(normalized.get("owned_codes") or [])),
        "exclude_codes": sorted(set(normalized.get("exclude_codes") or [])),
    }


def _profile_version_signature(raw: dict[str, Any]) -> str:
    payload = _profile_version_payload(raw)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def _profiles_payload_signature_from_bytes(raw_bytes: bytes) -> str:
    try:
        obj = json.loads(raw_bytes.decode("utf-8"))
    except Exception:
        return hashlib.sha1(raw_bytes).hexdigest()
    if not isinstance(obj, dict):
        return hashlib.sha1(raw_bytes).hexdigest()
    raw_profiles = obj.get("profiles")
    if not isinstance(raw_profiles, dict):
        raw_profiles = {}
    canonical_profiles: dict[str, Any] = {}
    for name, raw in raw_profiles.items():
        key = str(name or "").strip()
        if not key or not isinstance(raw, dict):
            continue
        canonical_profiles[key] = _profile_version_payload(raw)
    canonical = {"profiles": canonical_profiles}
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def _iter_profile_backup_files_desc() -> list[Path]:
    if not PROFILES_BACKUP_DIR.exists():
        return []
    return sorted(
        [
            p
            for p in PROFILES_BACKUP_DIR.glob("account_profiles.*.json")
            if p.is_file()
        ],
        key=lambda p: p.name,
        reverse=True,
    )


def _parse_backup_profiles(path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(obj, dict):
        return {}
    profiles = obj.get("profiles")
    if not isinstance(profiles, dict):
        return {}
    out: dict[str, Any] = {}
    for name, raw in profiles.items():
        pname = str(name or "").strip()
        if not pname:
            continue
        if not isinstance(raw, dict):
            continue
        out[pname] = _normalize_profile_entry(raw)
    return out


def _list_profile_backups(name: str, limit: int = 30) -> list[dict[str, Any]]:
    key = str(name or "").strip()
    if not key:
        return []
    out: list[dict[str, Any]] = []
    seen_versions: set[str] = set()
    for path in _iter_profile_backup_files_desc():
        profiles = _parse_backup_profiles(path)
        snap = profiles.get(key)
        if not snap:
            continue
        version_sig = _profile_version_signature(snap)
        if version_sig in seen_versions:
            continue
        seen_versions.add(version_sig)
        stamp = path.name.removeprefix("account_profiles.").removesuffix(".json")
        out.append(
            {
                "backup_file": path.name,
                "backup_created_at": stamp,
                "profile_saved_at": str(snap.get("saved_at") or ""),
                "group_power": int(snap.get("group_power") or 0),
                "member_point_count": len(snap.get("member_points") or {}),
                "owned_count": len(snap.get("owned_codes") or []),
            }
        )
        if len(out) >= max(1, int(limit)):
            break
    return out


def _restore_profile_from_backup(name: str, backup_file: Optional[str] = None) -> dict[str, Any]:
    key = str(name or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="name is required")

    candidates: list[Path] = []
    if backup_file:
        bf = _validate_backup_file_name(backup_file)
        path = PROFILES_BACKUP_DIR / bf
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="backup file not found")
        candidates = [path]
    else:
        candidates = _iter_profile_backup_files_desc()

    picked_path: Path | None = None
    picked_profile: dict[str, Any] | None = None
    for path in candidates:
        profiles = _parse_backup_profiles(path)
        snap = profiles.get(key)
        if snap:
            picked_path = path
            picked_profile = snap
            break

    if picked_path is None or picked_profile is None:
        raise HTTPException(status_code=404, detail="no backup found for profile")

    data = _load_profiles()
    profiles = data.setdefault("profiles", {})
    restored = {
        "group_power": int(picked_profile.get("group_power") or 0),
        "member_points": _normalize_member_points(picked_profile.get("member_points", {})),
        "owned_codes": _normalize_card_codes(picked_profile.get("owned_codes", [])),
        "exclude_codes": _normalize_card_codes(picked_profile.get("exclude_codes", [])),
        "saved_at": _utcnow_iso(),
    }
    profiles[key] = restored
    _save_profiles(data)
    return {
        "ok": True,
        "name": key,
        "profile": restored,
        "from_backup_file": picked_path.name,
    }


def _extract_import_profiles(req: Any) -> tuple[dict[str, Any], str]:
    if not isinstance(req, dict):
        raise HTTPException(status_code=400, detail="import payload must be a JSON object")

    payload = req
    nested = req.get("data")
    if isinstance(nested, dict):
        payload = nested

    active_profile = str(payload.get("active_profile") or req.get("active_profile") or "").strip()
    imported: dict[str, Any] = {}

    profiles_raw = payload.get("profiles")
    if isinstance(profiles_raw, dict):
        for name, raw in profiles_raw.items():
            key = str(name or "").strip()
            if not key or not isinstance(raw, dict):
                continue
            imported[key] = _normalize_profile_entry(raw)
    else:
        single_name = str(payload.get("name") or req.get("name") or "").strip()
        single_profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else req.get("profile")
        if single_name and isinstance(single_profile, dict):
            imported[single_name] = _normalize_profile_entry(single_profile)
            if not active_profile:
                active_profile = single_name

    if not imported:
        raise HTTPException(status_code=400, detail="no valid profiles found in import payload")
    return imported, active_profile


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


def _get_job_cancel_event(rec: dict[str, Any]) -> threading.Event | None:
    control = rec.get("control")
    if not isinstance(control, dict):
        return None
    cancel_event = control.get("cancel_event")
    if isinstance(cancel_event, threading.Event):
        return cancel_event
    return None


def _check_job_not_canceled(job_id: str) -> None:
    with OPTIMIZE_JOBS_LOCK:
        rec = OPTIMIZE_JOBS.get(job_id)
        if rec is None:
            raise OptimizeJobCanceledError("optimize job not found or expired")
        cancel_event = _get_job_cancel_event(rec)
        canceled = bool(cancel_event and cancel_event.is_set())
        status = str(rec.get("status") or "").lower()
    if canceled or status == "canceled":
        raise OptimizeJobCanceledError("optimize canceled by user")


def _run_optimize_job(job_id: str) -> None:
    with OPTIMIZE_JOBS_LOCK:
        rec = OPTIMIZE_JOBS.get(job_id)
        if not rec:
            return
        payload = dict(rec["payload"])
    payload["_opt_control_hook"] = lambda: _check_job_not_canceled(job_id)
    try:
        _check_job_not_canceled(job_id)
        with OPTIMIZE_JOBS_LOCK:
            rec = OPTIMIZE_JOBS.get(job_id)
            if not rec:
                return
            # May have been canceled after thread launch but before running.
            if str(rec.get("status") or "").lower() == "canceled":
                return
            now_ts = time.time()
            now_iso = _utcnow_iso()
            rec["status"] = "running"
            rec["started_at"] = now_iso
            rec["updated_at"] = now_iso
            rec["updated_ts"] = now_ts
        result = ENGINE.optimize(payload)
    except OptimizeJobCanceledError:
        with OPTIMIZE_JOBS_LOCK:
            rec = OPTIMIZE_JOBS.get(job_id)
            if rec:
                now_ts = time.time()
                now_iso = _utcnow_iso()
                rec["status"] = "canceled"
                rec["error"] = "优化已取消"
                rec["finished_at"] = now_iso
                rec["finished_ts"] = now_ts
                rec["updated_at"] = now_iso
                rec["updated_ts"] = now_ts
                _gc_optimize_jobs_locked()
        return
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
        cancel_event = _get_job_cancel_event(rec)
        if (cancel_event and cancel_event.is_set()) or str(rec.get("status") or "").lower() == "canceled":
            now_ts = time.time()
            now_iso = _utcnow_iso()
            rec["status"] = "canceled"
            rec["error"] = "优化已取消"
            rec["finished_at"] = now_iso
            rec["finished_ts"] = now_ts
            rec["updated_at"] = now_iso
            rec["updated_ts"] = now_ts
            _gc_optimize_jobs_locked()
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
        "control": {
            "cancel_event": threading.Event(),
        },
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


def _cancel_optimize_job(job_id: str) -> dict[str, Any]:
    with OPTIMIZE_JOBS_LOCK:
        rec = OPTIMIZE_JOBS.get(job_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="optimize job not found or expired")
        status = str(rec.get("status") or "").lower()
        if status in {"success", "error", "canceled"}:
            raise HTTPException(status_code=409, detail=f"optimize job already finished: {status}")
        cancel_event = _get_job_cancel_event(rec)
        if cancel_event:
            cancel_event.set()
        now_ts = time.time()
        now_iso = _utcnow_iso()
        rec["status"] = "canceled"
        rec["error"] = "优化已取消"
        rec["finished_at"] = now_iso
        rec["finished_ts"] = now_ts
        rec["updated_at"] = now_iso
        rec["updated_ts"] = now_ts
        return _job_to_response(rec)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True}


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


@app.post("/api/optimize/jobs/{job_id}/cancel")
def optimize_cancel_job(job_id: str) -> dict[str, Any]:
    key = str(job_id or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="job_id is required")
    return _cancel_optimize_job(key)


@app.get("/api/profiles")
def get_profiles() -> dict[str, Any]:
    try:
        return _load_profiles()
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"profiles read failed: {exc}") from exc


@app.get("/api/profiles/export")
def export_profiles(name: Optional[str] = None) -> dict[str, Any]:
    try:
        data = _load_profiles()
        raw_profiles = data.get("profiles")
        profiles = raw_profiles if isinstance(raw_profiles, dict) else {}
        picked_name = str(name or "").strip()
        if picked_name:
            if picked_name not in profiles:
                raise HTTPException(status_code=404, detail="profile not found")
            exported_profiles = {picked_name: _normalize_profile_entry(profiles[picked_name])}
        else:
            exported_profiles = {
                str(k): _normalize_profile_entry(v)
                for k, v in profiles.items()
                if str(k or "").strip() and isinstance(v, dict)
            }
        return {
            "format": PROFILES_EXPORT_FORMAT,
            "version": PROFILES_EXPORT_VERSION,
            "exported_at": _utcnow_iso(),
            "profile_count": len(exported_profiles),
            "profiles": exported_profiles,
        }
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"profile export failed: {exc}") from exc


@app.post("/api/profiles/import")
def import_profiles(req: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        imported_profiles, active_profile_hint = _extract_import_profiles(req)
        data = _load_profiles()
        profiles = data.setdefault("profiles", {})
        created: list[str] = []
        updated: list[str] = []
        skipped: list[str] = []
        now = _utcnow_iso()

        for name, imported in imported_profiles.items():
            existing = profiles.get(name)
            normalized = _normalize_profile_entry(imported)
            normalized["saved_at"] = str(normalized.get("saved_at") or now)
            if isinstance(existing, dict) and _profile_version_signature(existing) == _profile_version_signature(normalized):
                skipped.append(name)
                continue
            profiles[name] = normalized
            if isinstance(existing, dict):
                updated.append(name)
            else:
                created.append(name)

        if created or updated:
            _save_profiles(data)

        preferred_name = ""
        if active_profile_hint and active_profile_hint in profiles:
            preferred_name = active_profile_hint
        elif created:
            preferred_name = created[0]
        elif updated:
            preferred_name = updated[0]
        elif skipped:
            preferred_name = skipped[0]

        return {
            "ok": True,
            "imported_count": len(created) + len(updated),
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "active_profile": preferred_name,
        }
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"profile import failed: {exc}") from exc


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


@app.get("/api/profiles/{name}/backups")
def list_profile_backups(name: str, limit: int = 30) -> dict[str, Any]:
    key = str(name or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="name is required")
    try:
        backups = _list_profile_backups(key, limit=max(1, min(PROFILES_BACKUP_KEEP, int(limit))))
        return {"name": key, "backups": backups}
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"profile backup list failed: {exc}") from exc


@app.delete("/api/profiles/{name}/backups/{backup_file}")
def delete_profile_backup(name: str, backup_file: str) -> dict[str, Any]:
    key = str(name or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="name is required")
    try:
        bf = _validate_backup_file_name(backup_file)
        path = PROFILES_BACKUP_DIR / bf
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="backup file not found")
        profiles = _parse_backup_profiles(path)
        if key not in profiles:
            raise HTTPException(status_code=404, detail="backup file not found for profile")
        path.unlink(missing_ok=False)
        return {"ok": True, "name": key, "backup_file": bf}
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"profile backup delete failed: {exc}") from exc


@app.post("/api/profiles/{name}/undo")
def undo_profile_save(name: str, req: Optional[ProfileUndoRequest] = None) -> dict[str, Any]:
    key = str(name or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="name is required")
    try:
        backup_file = str(req.backup_file).strip() if req and req.backup_file is not None else None
        return _restore_profile_from_backup(key, backup_file=backup_file)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"profile undo failed: {exc}") from exc


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
