# UOA Scoring Web App

本目录提供一个本地 Web App，用来做 UNI'S ON AIR 的手动配队算分：

- 全卡库筛选 + 手动上 5 卡（第 1 张为队长）
- 期望标签快捷按钮筛选（如 `3.68s / 3.68 / 3.61 / 3.49 / 3.40`）
- 手动成员分（支持逐成员覆盖）
- 衣服 / 家具 / front skin 开关与参数
- 单曲或全曲模拟（zawa 逻辑）
- 持有卡池最优配队（单曲）：可设置“队长候选”“必带卡”，输出 TopN
- 优化默认候选池：`全卡池（现役 + T1(>=3.0)，并保留V/S）`，也可切到“仅持有卡池”
- 默认 `strict_no_miss=true`：优化请求会自动启用 `preselect_all=true` 与 `disable_fast_all=true`（严格不漏，但更慢）
- 队长默认策略：未手动指定“队长候选”时，自动在 `Véaut / S.teller` 中心卡里搜索（不枚举其他队长）
- 候选优先策略默认 `axis_t1`（歌曲主色/主轴优先，V卡副色次优先）
- 未知成员分自动回落到 `default_member_point`（默认 `0`），并在优化结果里标记 `default_estimate`
- 一键全卡池Top5默认使用 `trials=1000`（严格口径下更可控）；若手动设到 `3000/10000` 会明显更慢
- 同参数优化请求带内存缓存，重复运行会直接命中 `cache`
- 卡池支持显示“配队界面人头图”（icon）：优先使用 catalog 映射到 CDN 的 icon 资源，缺失时自动回退到颜色占位
- 分布顺序固定：
  `min -> -3sigma -> -2sigma -> -1sigma -> median -> +1sigma -> +2sigma -> +3sigma -> max`

## 启动

在 `uoa-scoring` 根目录执行：

```bash
/Library/Developer/CommandLineTools/usr/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

然后访问：

- http://127.0.0.1:8765

## 数据来源

- 卡库：`masters/<latest>` + `UOA大表 新人必看.xlsx`
- 卡池默认过滤：`catalogs/active_members_manual_20260227.json`（现役名单） + `skill_expected >= 2.0`
- 歌曲：`catalogs/uniair_songlist.json`
- zawa 模拟：`catalogs/zawa_score_sim_master.json`

## 主要接口

- `GET /api/bootstrap`
  - 返回卡池、歌曲、默认参数
- `POST /api/evaluate`
  - 输入队伍与参数，返回分布、综合力拆分、技能明细
- `POST /api/optimize`
  - 输入持有卡池与约束，返回 TopN 配队（严格 zawa 分布重排）
  - 可选高级参数:
    - `preselect_all`: 是否让全部候选都进入 MonteCarlo（最稳妥，但更慢）
    - `disable_fast_all`: 关闭全卡池快筛模式（更稳妥，但更慢）
    - `candidate_strategy`: `default` 或 `axis_t1`（主色/主轴T1优先候选排序）
