# UOA 队伍优化模拟 - Spec Coding 文档

更新时间: 2026-03-04
适用仓库: `uoa-scoring`

## 1. 文档目标
本文件是 `uoa-scoring` 的技术规格总文档，用于:

- 固定项目边界与口径，避免会话切换后信息丢失。
- 给开发者和 AI 协作工具提供统一的“代码 -> 功能 -> 数据 -> 页面”映射。
- 作为后续改动的核对标准（接口、算分逻辑、UI 结构、数据持久化）。

## 2. 项目定位与边界

### 2.1 项目定位
本项目是 UNI'S ON AIR 的本地 Web 队伍优化模拟器，核心用途:

- 管理账号配置（`group总综合力 + 成员分 + 持有卡池`）。
- 在约束条件下计算单队分布（`/api/evaluate`）。
- 在候选卡池下搜索 TopN 最优队伍（`/api/optimize/jobs` + 轮询）。
- 支持结果内“换卡横向对比”闭环。

### 2.2 明确不做

- 不做抓包/解包流程（该部分在 `uoa-extract`）。
- 不做登录、绕过、密钥提取等高风险内容。
- 不在此仓库存储账号敏感信息。

## 3. 架构总览

### 3.1 技术栈

- 后端: FastAPI (`app/main.py`)
- 引擎: Python 算分引擎 (`app/engine.py`，依赖 `tools/optimize_vs_base_teams.py` + `tools/zawa_score_model.py`)
- 前端: 原生 HTML/CSS/JS (`app/static/index.html`, `app/static/styles.css`, `app/static/app.js`)
- 持久化:
  - 账号: `app/data/account_profiles.json`
  - 图标缓存: `app/data/card_icons/*.png`
  - 浏览器状态: `localStorage`

### 3.2 运行形态

- 单体应用（同进程）:
  - FastAPI 提供 API 与静态资源。
  - 前端通过 `fetch('/api/...')` 调用后端。
- 优化计算采用“后端任务 + 前端轮询”，避免刷新页面直接中断交互状态。

## 4. 目录与代码映射

| 路径 | 角色 | 备注 |
| --- | --- | --- |
| `app/main.py` | API 入口、请求模型、优化任务管理、账号 CRUD | 任务内存保留 24h，最多 120 条 |
| `app/engine.py` | 数据加载、卡面装配、图标解析、算分、优化 | 核心业务逻辑 |
| `app/static/index.html` | 页面骨架与模块结构 | 左筛选 + 右算分/卡列表 + 底部结果 |
| `app/static/app.js` | 前端状态机与交互 | 账号、筛选、算分、优化、换卡对比 |
| `app/static/styles.css` | 样式与布局 | 双栏、弹窗、结果卡、响应式 |
| `app/data/account_profiles.json` | 账号持久化文件 | group/member_points/owned_codes |
| `docs/ui_layout_profile_requirements_20260301.md` | 历史 UI/交互约束 | 本文档会吸收其稳定部分 |
| `docs/strict_zawa_rules_manual_20260227.md` | 历史口径文档 | 算分口径来源之一 |
| `reports/icon_diagnosis_20260301.md` | 图标缺失诊断记录 | 当前有 22 张缺图卡 |

## 5. 数据源与装载流程

### 5.1 数据源

- 卡库主数据: `masters/<latest>`
- 期望值/技能校正工作簿: `UOA大表 新人必看.xlsx`
- 歌曲列表: `catalogs/uniair_songlist.json`
- zawa 模拟主数据: `catalogs/zawa_score_sim_master.json`
- 现役名单: `catalogs/active_members_manual_20260227.json`
- 默认成员分: `catalogs/member_points_manual_20260228.json`
- catalog 资源映射: `catalogs/unison_catalog_*.json`

### 5.2 启动加载（`ScoringEngine._load()`）

1. 定位最新 masters。
2. 读取卡数据与工作簿，构造全 SSR 卡池。
3. 过滤规则: `skill_expected > 2.0`。
4. 合并成员元数据（团体、期别、罗马音、假名）。
5. 构造图标映射:
   - 优先卡包精确图标（`/api/card-icons/{code}` 走 bundle 解析）
   - 再回退 catalog icon CDN
   - 再回退 kosa 缩略图
   - 最终无图则前端占位
6. 加载歌曲并和 zawa master 对齐 `zawa_index`。
7. 生成 bootstrap 响应缓存（cards/songs/defaults/meta）。

## 6. 页面与模块规范（当前实现）

## 6.1 主布局

- 顶栏: 项目 logo + 标题。
- 主工作区: `workspace-shell` 双栏布局（左:筛选，右:算分+卡列表）。
- 结果区: 独立全宽面板，显示 Top 队伍与明细。

## 6.2 左栏（卡片筛选）

- 基础筛选:
  - 颜色、团体、排序、系列、期望标签。
- 成员筛选:
  - 按团体 -> 期别分组的成员 chip。
  - “毕业成员”作为未分期分组标签。

## 6.3 右栏（算分设置 + 卡列表）

- 账号区:
  - 读取账号 / 新建账号 / 保存账号 / 删除账号。
- 参数区:
  - 模式、歌曲、group、试行回数、排序。
- 优化入口:
  - 前N队伍、候选卡池、一键重置筛选、一键全卡池Top5、最优配队。
- 卡列表区:
  - 搜索、列表范围（全卡池/仅持有）。
  - 每卡支持: 上队、持有、候选（V/S）、必带、成员分手动覆盖。

## 6.4 结果区

- 标题提示: “结果（点击成员可进行横向对比）”。
- Top 队伍卡片展示:
  - 队伍 5 卡信息（可点进换卡对比）
  - 综合力/分布/发动效果/Front 编成
  - 折叠细则（center、scene、成员分明细）

## 6.5 队伍换卡对比弹窗

- 顶部: 当前 5 位卡（可切换正在替换位）。
- 左侧: 颜色/团体/系列/成员筛选。
- 右侧: 搜索 + 候选范围 + 持有筛选 + 候选卡列表。
- 底部: 横向对比结果（替换前后指标差异）。

## 7. API 规格

### 7.1 `GET /api/bootstrap`

返回初始化数据:

- `cards`: 前端卡片渲染模型（含技能 tuple、tag、icon url、成员元信息）
- `songs`: 可计算歌曲列表（含 `zawa_index`）
- `defaults`: 默认参数
- `meta`: 数据版本和图标统计

### 7.2 `POST /api/evaluate`

用途: 计算固定 5 卡队伍。

关键入参:

- `card_codes` 长度固定 5（第 1 张是 center）
- `mode`: `single | color | all`
- `song_key`（single 必填）
- `group_power`
- `member_points` + `default_member_point`
- 衣服/家具/skin/同色加成开关与参数

关键出参:

- `results[].distribution`（min/-3σ/-2σ/-1σ/median/+1σ/+2σ/+3σ/max）
- `front_pre` / `front_post`
- `scene_power.raw/effective/delta`
- `skill_profiles`（single 模式）
- `member_point_breakdown`

### 7.3 `POST /api/optimize`

用途: 同步优化（仍可用，但前端主流程改为 job 模式）。

关键入参:

- `pool_scope`: `all | owned`
- `owned_card_codes`: `pool_scope=owned` 时至少 5 张
- `center_card_codes` / `must_include_codes` / `top_n` / `sort_by`

### 7.4 `POST /api/optimize/jobs`

用途: 创建优化任务，立即返回 `job_id`。

状态流转:

- `queued -> running -> success|error`

### 7.5 `GET /api/optimize/jobs/{job_id}`

用途: 查询任务状态与结果。

### 7.6 账号接口

- `GET /api/profiles`
- `POST /api/profiles`
- `DELETE /api/profiles/{name}`

账号结构:

```json
{
  "group_power": 1810181,
  "member_points": {"小島凪紗": 13870},
  "owned_codes": ["card_15_129_401101"],
  "exclude_codes": [],
  "saved_at": "2026-03-02T01:26:23.605853+00:00"
}
```

注: 目前“排除池”机制处于暂停状态，`exclude_codes` 保留字段兼容。

## 8. 算分原理与公式

### 8.1 单卡卡分口径

- `scene_raw_total = vo + da + pe`
- `scene_card_total = scene_raw_total + scene_skill_per_card`
  - 当前默认 `scene_skill_per_card = 430`

### 8.2 队伍进歌前综合力

- 先算 center 生效后的 scene 值:
  - `team_power_scene = eff_vo + eff_da + eff_pe`
- 再叠加全队固定项:

```text
front_pre = team_power_scene
          + member_point_total
          + costume_total
          + office_total
          + skin_total
          + skill_stat_total
```

其中:

- `member_point_total = Σ 每卡成员分`
- `costume_total = (costume_vo + costume_da + costume_pe) * 5`
- `office_total = Σ floor(card_vo*office_vo) + floor(card_da*office_da) + floor(card_pe*office_pe)（逐卡逐轴下取整）`
- `skin_total = 依据 front_skin_rate + axes + target_color 逐卡逐轴上取整`
- `skill_stat_total = (scene_skill_per_card + costume_skill_per_card) * 5`

### 8.3 进歌后综合力

```text
front_post = front_pre + type_bonus_total
```

- `type_bonus_total` 只给同色卡（或 ALL 曲）按轴 `ceil(card_stat * type_bonus_rate)` 累加。

### 8.4 分布模拟

- 使用 `zawa_score_model.simulate(...)` 做 Monte Carlo。
- 触发率倍率口径:
  - V/S 吸收链统一按 `1 + (m - 1) * scale` 缩放。
  - `S.teller` 队长时，成员名倍率只对 `Véaut` 卡生效；同名普通卡不吃成员名倍率。
  - `Véaut` 队长时，同名普通卡可吃成员名倍率。
- 输出顺序固定:
  - `min -> -3σ -> -2σ -> -1σ -> median -> +1σ -> +2σ -> +3σ -> max`

### 8.5 期望值显示

- 默认取卡面 `skill_expected`。
- 对 V/S 异色降级场景，按 tuple anchor 或比例法推导 `skill_expected_effective_base`。
- 显示区分:
  - 普通如 `3.68%`
  - 特殊 tuple 标签如 `3.68s`

## 9. 优化器工作流

## 9.1 候选池来源

- `pool_scope=owned`: 只用 `owned_card_codes`（至少 5 张，否则直接报错）
- `pool_scope=all`: 使用全卡池
- 两者都可附加 `exclude_card_codes`（当前前端暂停）

## 9.2 约束

- `must_include_codes` 最多 5 张。
- 若 `must_include=5`，必须至少包含 1 张 V/S 队长卡。
- 若 `owned` 模式且队长候选为空，会自动要求持有池里存在 V/S。

## 9.3 搜索策略

- 默认 `candidate_strategy=axis_t1`。
- 全卡池且无硬约束时可能触发 fast-all 预筛。
- 先 objective 快排，再进严格 zawa 重排。
- 支持两阶段试行:
  - fast trials
  - full trials 精算 top 行

## 9.4 缓存

- `ScoringEngine._opt_cache` 内存缓存相同 payload。
- 最大 96 条，超出 FIFO 弹出。

## 10. 账号、状态与持久化

## 10.1 后端账号文件

- 文件: `app/data/account_profiles.json`
- 账号跟随:
  - `group_power`
  - `member_points`
  - `owned_codes`

## 10.2 前端本地状态

- `uoa_scoring_ui_state_v2`: UI 筛选、参数、持有/必带/候选、成员分覆盖。
- `uoa_scoring_result_state_v2`: 最近一次结果（evaluate 或 optimize）。
- `uoa_scoring_optimize_job_id_v1`: 正在执行中的任务 ID。

## 10.3 刷新恢复

- 刷新后会恢复:
  - 筛选与参数
  - 当前账号选择
  - 最近结果
  - 正在进行中的优化轮询

## 11. 图标系统

图标优先级:

1. 精确卡包 icon（`/api/card-icons/{code}` 下载 bundle 并解包缓存）
2. catalog icon CDN
3. kosa thumbnail/image
4. 无图占位

诊断文档:

- `reports/icon_diagnosis_20260301.md`（当前统计: 1415 卡中 22 张无图）

## 12. 性能与体验约束

- 优化为重计算，`trials` 越大越慢。
- 一键全卡池 Top5 默认建议低试行值。
- 换卡对比候选列表上限 260 行。
- 候选列表采用固定卡片高度，不因结果数量拉伸。

## 13. 已知口径说明

- `Vo/Da/Pe` 展示以“卡面三围”口径为主。
- `卡分` 显示采用 `scene_card_total = vo+da+pe+430`。
- 游戏内个位差异通常来自:
  - 向上取整链路差异
  - Front skin / 家具 / 衣装是否同配置
  - 期望值锚点映射与歌曲色判定差异

## 14. 使用流程（开发/调试）

### 14.1 启动

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

访问: `http://127.0.0.1:8765`

### 14.2 建议调试路径

1. 先用固定 5 卡跑 `evaluate` 验证口径。
2. 再跑 `optimize/jobs` 验证候选约束。
3. 最后在结果内做“换卡对比”确认替换逻辑。

### 14.3 重构稳定性护栏

为了在拆分 `app/engine.py`、`app/static/app.js` 时保持行为不漂移，新增:

- 脚本: `tools/refactor_guard.py`
- 基线: `tools/baselines/refactor_guard_baseline.json`

执行方式:

```bash
# 校验当前实现与基线是否一致
python3 tools/refactor_guard.py

# 仅在确认口径变更后刷新基线
python3 tools/refactor_guard.py --refresh
```

## 15. 文档映射（给后续会话/MCP）

- 总规格（本文件）: `docs/spec_coding_uoa_scoring_app.md`
- 零破坏重构手册: `docs/refactor_stability_playbook_20260304.md`
- UI 历史约束: `docs/ui_layout_profile_requirements_20260301.md`
- 口径历史约束: `docs/strict_zawa_rules_manual_20260227.md`
- 拆仓说明: `docs/project_split_guide_20260227.md`
- 图标诊断: `reports/icon_diagnosis_20260301.md`
- 用户操作手册: `README.md`

## 16. 变更约定

后续任何涉及以下内容的改动，都应同步更新本文件:

- API 入参/出参字段
- 算分公式和加成口径
- 优化约束逻辑
- 页面模块结构与交互入口
- 账号持久化结构

## 17. MCP 会话最小加载规范（降 token 成本）

本节用于减少“新会话重复全仓搜索”的开销。后续会话建议按以下最小集合加载上下文。

### 17.1 必读最小集（按顺序）

1. `docs/mcp_session_bootstrap.md`
2. `docs/spec_coding_uoa_scoring_app.md`
3. `docs/refactor_stability_playbook_20260304.md`
4. `README.md`

仅当涉及专项问题时，再补读:

- UI 细节回溯: `docs/ui_layout_profile_requirements_20260301.md`
- 严格口径回溯: `docs/strict_zawa_rules_manual_20260227.md`
- icon 异常回溯: `reports/icon_diagnosis_20260301.md`

### 17.2 需求到代码入口速查

| 需求方向 | 先看文件 | 备注 |
| --- | --- | --- |
| API 字段/任务轮询/账号接口 | `app/main.py` | 路由和请求模型在此定义 |
| 算分公式/前后综合力/优化口径 | `app/engine.py` | 核心口径唯一入口 |
| 页面结构布局 | `app/static/index.html` | 模块层级和 DOM 锚点 |
| 页面交互行为/状态恢复 | `app/static/app.js` | 本地状态与接口编排 |
| 样式/对齐/响应式 | `app/static/styles.css` | 全部 UI 样式定义 |
| 账号落盘结构 | `app/data/account_profiles.json` | 持久化真实样例 |

### 17.3 不建议默认全量阅读

下列内容不是每次会话都需要:

- `tools/` 下全部脚本
- `masters/` 原始大体量数据
- 历史报告全文

除非用户明确要求或遇到阻塞，否则应按 17.1/17.2 定位后按需读取。
