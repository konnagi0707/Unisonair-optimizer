# UOA Intel Project Split Guide (2026-02-27)

## Goal
Split the current mixed workspace into two independent projects:

- `uoa-scoring`: score simulation / team optimization
- `uoa-extract`: fetch / unpack / update-diff pipeline

This keeps algorithm iteration and data collection pipelines isolated.

## Recommended Boundaries

### `uoa-scoring` (算分组队)
- Core scripts:
  - `tools/optimize_vs_base_teams.py`
  - `tools/zawa_score_model.py`
  - `tools/strict_zawa_song_top5.py`
  - `tools/strict_zawa_multicolor_top5_detail.py`
  - `tools/evaluate_fixed_team.py`
- Rules/docs:
  - `docs/strict_zawa_rules_manual_20260227.md`
  - `docs/project_split_guide_20260227.md`
- Runtime/data boundary (current):
  - Read-only shared data (symlink): `catalogs/`, `masters/`, `uoa_intel.db`
  - Scoring-local only: `reports/`, `update/`
  - Scoring workbook: `UOA大表 新人必看.xlsx`
  - Not owned by scoring anymore: `apk/`, `bluestacks/`, `downloads/`

### `uoa-extract` (抓取解包)
- Python package:
  - `uoa_intel/`
- Extract/update scripts:
  - `tools/auto_update.py`
  - `tools/bluestacks_manifest.py`
  - `tools/diff_bluestacks_cache.py`
  - `tools/extract_gacha_banners_bluestacks.py`
  - `tools/extract_scene_cards_bluestacks.py`
  - `tools/export_cards_window.py`
  - `tools/export_update_tables.py`
  - `tools/http_proxy_log.py`
  - `tools/ocr_vision.swift`
- Docs:
  - `README.md`
  - `TASKS.md`
  - `docs/spec_coding_uoa_extract.md`
  - `docs/project_split_guide_20260227.md`
- Optional large runtime data:
  - `apk/`
  - `bluestacks/`
  - `downloads/`
  - `catalogs/`
  - `masters/`
  - `uoa_intel.db`

## Split Command
Use:

```bash
bash tools/split_into_two_projects.sh
```

Default mode is dry-run (only prints plan).
`--apply` without extra flags does a lightweight split (code + docs).

Actual split:

```bash
bash tools/split_into_two_projects.sh --apply
```

Include large runtime data (scoring + extract historical assets/reports):

```bash
bash tools/split_into_two_projects.sh --apply --with-data
```

## Output Paths
By default, split target root is parent directory of current repo:

- `<parent>/uoa-scoring`
- `<parent>/uoa-extract`

You can override target root:

```bash
bash tools/split_into_two_projects.sh --apply --target-root "/your/path"
```

## Migration Recommendation
1. First run dry-run to verify file lists.
2. Run `--apply` without `--with-data`.
3. Validate both projects independently.
4. If extract project needs historical runtime cache, rerun with `--with-data`.

## Current Cleanup Status (2026-02-27)
- `uoa-scoring/reports` and `uoa-scoring/update` are local directories (no longer linked to extract).
- Canonical scoring baseline output kept under:
  - `reports/strict_zawa_*_20260227_with_skin_office_costume/`
- Historical fetch/unpack artifacts remain in `uoa-extract/reports` and `uoa-extract/update`.
