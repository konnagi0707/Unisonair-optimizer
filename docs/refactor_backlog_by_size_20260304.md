# 重构待办清单（按体量与风险排序）

更新时间: 2026-03-04  
目标: 在“零行为变更”前提下，继续降低超长函数与高耦合文件风险。

## 1. 现状快照

核心文件行数（当前）:

- `app/static/app.js`: 4739 行
- `app/static/styles.css`: 3737 行
- `app/engine.py`: 2311 行
- `app/main.py`: 950 行

## 2. 超长函数热点

### 2.1 后端

`app/engine.py`:

- `_load_kosa_scene_map`：1414 行（最高风险热点）
- `_normalize_icon_image`：88 行
- `_resolve_skin_axis_rates`：73 行
- `_load_kosa_scene_rows`：62 行
- `_extract_best_icon_image_from_bundle_bytes`：61 行

`app/main.py`:

- `_run_optimize_job`：94 行
- `import_profiles`：51 行
- `_restore_profile_from_backup`：47 行
- `_save_profiles`：39 行

### 2.2 前端

`app/static/app.js`:

- `bindEvents`：337 行
- `renderOptimize`：283 行
- `renderTeamReplaceModal`：253 行
- `renderCardList`：196 行
- `applyPersistedUiState`：188 行
- `resumePendingOptimizeJobIfAny`：157 行

## 3. 已确认的稳定点

- 签名检测默认开启（`disable_signature_check=false`）。
- 使用账号 `琴原美名`（owned 14）实测:
  - 开启/关闭签名检测均无重复签名队伍（Top10 唯一）。
  - 当前该池子下 `skipped_same_center_permutations=0`，说明本次候选未出现可去重排列。
  - 耗时差很小（约 26.3s vs 26.1s，统计噪声级）。

结论: 默认应保持开启；关闭仅用于诊断与性能对照。

## 4. 下一轮建议（稳态顺序）

按“低风险 -> 中风险 -> 高风险”执行，每步都跑:

- `python3 tools/refactor_guard.py`
- `python3 tools/bug_sweep.py --host 127.0.0.1 --port 8765`
- S.teller/Véaut 定向倍率断言

### 第 A 组（低风险，优先）

1. `app/main.py` 任务管理拆分  
   拆到 `app/main_parts/optimize_jobs.py`:
   - `_create_optimize_job`
   - `_run_optimize_job`
   - `_cancel_optimize_job`
   - `_job_to_response`

2. `app/main.py` 账号导入导出拆分  
   拆到 `app/main_parts/profiles_io.py`:
   - `_load_profiles` / `_save_profiles`
   - `_extract_import_profiles`
   - `_restore_profile_from_backup`

### 第 B 组（中风险）

3. `app/static/app.js` 渲染拆分  
   拆到 `app/static/modules/render_optimize.js`:
   - `renderOptimize`
   - `applyOptimizeResult`
   - 相关 `bindOptimizeResult*`

4. `app/static/app.js` 换卡弹窗拆分  
   拆到 `app/static/modules/replace_modal.js`:
   - `renderTeamReplaceModal`
   - `renderTeamReplaceComparison`
   - `renderTeamReplaceMemberPicker`

### 第 C 组（高风险，最后）

5. `app/engine.py::_load_kosa_scene_map` 解耦  
   建议按“纯子阶段”拆到 `app/engine_parts/kosa_scene_loader.py`:
   - 阶段1: 读源与索引构建
   - 阶段2: 候选匹配与优先级选择
   - 阶段3: scene_map 汇总与统计输出

注意: 该函数体量极大且耦合多，必须“一次只拆一个阶段”。

## 5. 执行约束（必须）

- 不改 API 字段与默认行为。
- 不改 UI DOM id 与已有交互语义。
- 每步仅做“搬运 + 导入替换”，不混入功能修复。
- 文档同步更新:
  - `docs/spec_coding_uoa_scoring_app.md`
  - `docs/refactor_stability_playbook_20260304.md`

