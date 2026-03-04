# AGENTS.md (UOA Intel)

<INSTRUCTIONS>
## Project Goal
This repo is a **personal** workflow to diff UOA updates and export:
- Added cards/events tables (CSV + Markdown + XLSX)
- New card/event/gacha images (Unity3D -> PNG) from either public catalogs or BlueStacks offline cache
- A repeatable runbook so future “update sniffing” is fast and low-friction

## Non-Goals / Safety
- Do not document or perform login, packet capture, privilege bypass, key extraction, DRM circumvention, or any “cracking” steps.
- Prefer data that is already locally downloaded (BlueStacks cache) and/or officially accessible.
- Never store secrets (passwords, tokens) in repo files.

## Git Commit Identity (Hard Rule)
- All commits in this repo MUST use:
  - `user.name = konnagi0707`
  - `user.email = konnagi0707@users.noreply.github.com`
- Never commit with real name or machine-local email.
- Before any commit, verify identity:
  - `git config user.name`
  - `git config user.email`
- If identity is wrong, fix it before commit (repo-local or global config).
- If a wrong-identity commit was already created, rewrite/fix commit history before pushing.

## Output Contract (每次解析一个新文件夹)
For each update analysis, create a new directory:
- `update/<RUN_TS>_masters_<TARGET_MASTERS>/`

Put all per-run artifacts under that directory:
- tables: `cards_*_table.(csv|md|xlsx)`, `events_*_table.(csv|md)`
- gacha banners: `gacha_banners/` (png + png_x4 + OCR summary)
- scene cards: `scene_cards_<photoId>/` (unity3d + png + presence report)

## Canonical Runbook
The canonical “how to run” documentation lives in:
- `docs/spec_coding_uoa_extract.md`

If you change the workflow or add a new tool script, update the spec doc in the same PR/change.

## Storage Policy (disk)
This repo can get very large due to BlueStacks snapshots.
- Keep only the latest `bluestacks/data_live_*.qcow2` (and ideally only the latest `bluestacks/partition_live_*_p1.ext4.raw`)
- Keep final outputs under `update/` (tables + png) so old snapshots can be deleted safely.
</INSTRUCTIONS>
