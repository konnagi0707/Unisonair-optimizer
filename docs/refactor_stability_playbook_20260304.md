# 零破坏重构手册（2026-03-04）

适用仓库: `uoa-scoring`

目标: 在不改变现有功能表现的前提下，逐步拆分和清理“大文件/高耦合代码”。

---

## 1. 什么叫“零破坏”

本项目中的“零破坏”定义为以下条件同时满足:

1. API 兼容:
   - 现有接口路径与字段不变（`/api/bootstrap`、`/api/evaluate`、`/api/optimize`、`/api/optimize/jobs`、`/api/profiles*`）。
2. 口径稳定:
   - 固定场景下，`front_pre/front_post`、分布关键分位（例如 `+2sigma`）与基线一致。
3. 交互稳定:
   - 关键用户流程不变（加载账号、修改成员分、优化、换卡对比）。
4. 失败可回滚:
   - 每次变更都可在小粒度内回退，不做跨文件大爆改。

---

## 2. 四层护栏（先护栏，再重构）

### L0: 行为快照护栏（新增）

- 脚本: `tools/refactor_guard.py`
- 基线: `tools/baselines/refactor_guard_baseline.json`
- 作用:
  - 固定一组 `evaluate + optimize` 场景。
  - 比对关键输出字段，防止重构引入隐式行为漂移。

常用命令:

```bash
# 校验当前实现是否与基线一致
python3 tools/refactor_guard.py

# 明确口径变更后，人工确认后刷新基线
python3 tools/refactor_guard.py --refresh
```

注意:

- 默认会检查 `masters_version`，版本漂移会失败（可用 `--allow-master-drift` 放宽）。
- 只有“确认口径本应变化”时才允许刷新基线。

### L1: Bug 巡检护栏（已有）

- 脚本: `tools/bug_sweep.py`
- 覆盖:
  - 基础接口可用性
  - 默认参数检查
  - DOM 引用漂移
  - 账号成员分映射检查

命令:

```bash
python3 tools/bug_sweep.py --host 127.0.0.1 --port 8765
```

### L2: 手工黄金样例

- 维护 2~3 套游戏内可复现队伍（含进歌前综合力、关键 sigma 档）。
- 重构后对照一次，确认“护栏通过 + 人眼对齐”。

### L3: 文档同步

- 任何影响口径/流程的改动，必须同步:
  - `README.md`
  - `docs/README.md`
  - `docs/spec_coding_uoa_scoring_app.md`

---

## 3. 推荐重构节奏（慢速、稳态）

每一轮只做一类变更，且每轮结束必须过 L0+L1:

1. 第 1 轮: 纯搬运拆分（不改逻辑）
   - 例如把 `app/engine.py` 的工具函数迁到新模块。
   - 原入口保留，先做“壳层转发”。
2. 第 2 轮: 消除重复逻辑
   - 只做等价替换，不做功能改造。
3. 第 3 轮: 可观测性增强
   - 增加日志、调试信息、文档注释。
4. 第 4 轮: 小范围行为修正
   - 每次只改一个口径点，并更新基线与文档。

---

## 4. 每次提交前检查清单

1. Git 提交身份正确（硬规则）:
   - `git config user.name` 必须是 `konnagi0707`
   - `git config user.email` 必须是 `konnagi0707@users.noreply.github.com`
2. 启动服务可用。
3. `python3 tools/refactor_guard.py` 通过。
4. `python3 tools/bug_sweep.py --host 127.0.0.1 --port 8765` 通过。
5. 手工验证至少 1 套目标队伍（当前用户常用歌/常用队）。
6. 文档更新完毕（README + docs 索引 + spec）。

---

## 5. 拆分建议（不改对外接口）

### 5.1 后端 (`app/engine.py`)

按职责拆到 `app/engine_parts/`（建议）:

- `bootstrap_loader.py`: 数据加载与 bootstrap 组装
- `evaluate_core.py`: 单队算分链路
- `optimize_core.py`: 候选生成/重排/去重
- `icon_resolver.py`: 图标解析与缓存
- `skin_rules.py`: skin 轴向规则与目标色规则

要求:

- `ScoringEngine` 入口方法名保持不变。
- API 入参/出参结构不变。

### 5.2 前端 (`app/static/app.js`)

按职责拆到 `app/static/modules/`（建议）:

- `state.js`: 全局状态与持久化
- `api.js`: 后端调用
- `render_cards.js`: 卡列表渲染
- `render_results.js`: 结果渲染
- `profile_store.js`: 账号保存/差异摘要
- `optimize_job.js`: 任务轮询与取消

要求:

- 保留现有 DOM id 和接口字段。
- 不一次性改动所有事件绑定。

---

## 6. 失败回退策略

若任一护栏失败:

1. 停止继续重构。
2. 定位到最近一轮最小改动点。
3. 回退该轮改动后重新执行 L0 + L1。
4. 在修复说明中记录:
   - 失败原因
   - 影响范围
   - 新增防护

---

## 7. 当前结论

当前代码属于“可维护但高耦合单体”，适合采用“护栏先行 + 渐进拆分”策略。

不要追求一次性重写。对本项目最稳的路线是:

- 先保证每次改动都可验证、可回退；
- 再逐块拆分，持续降低单文件复杂度。

## 8. 已落地的最小拆分记录

补充: 后续待拆分热点与优先级见 `docs/refactor_backlog_by_size_20260304.md`。

- 2026-03-04（第 1 步）:
  - 新增 `app/engine_parts/skin_target.py`。
  - 从 `app/engine.py` 抽离 skin 目标色解析与候选目标生成的纯函数（无口径变更）。
  - 护栏结果: `refactor_guard` PASS，`bug_sweep` PASS。
- 2026-03-04（第 2 步）:
  - 将 `front_skin_axes/front_skin_rate` 的基础解析函数一并迁入 `app/engine_parts/skin_target.py`：
    - `parse_axes`
    - `optional_rate_value`
  - `app/engine.py` 改为导入调用，算法与参数语义不变（零行为变更）。
- 2026-03-04（第 3 步）:
  - 将 skin 规则映射纯函数迁入 `app/engine_parts/skin_target.py`：
    - `auto_skin_axes`
    - `auto_skin_candidate_rates`
    - `skin_axis_rates_by_profile`
  - `app/engine.py` 仅保留编排逻辑并导入调用（零行为变更）。
- 2026-03-04（第 4 步）:
  - 新增 `app/engine_parts/effect_summary.py`。
  - 将队伍发动效果文案拼装函数迁移为独立纯函数：
    - `team_effect_summary`
  - `app/engine.py` 改为导入调用（零行为变更）。
- 2026-03-04（第 5 步）:
  - 新增 `app/engine_parts/scene_keys.py`。
  - 将 kosa 场景匹配相关纯函数迁移：
    - `kosa_color_to_short`
    - `scene_match_key`
    - `scene_member_color_key`
    - `scene_member_key`
    - `norm_scene_title`
    - `scene_title_key`
  - `app/engine.py` 改为导入调用（零行为变更）。
