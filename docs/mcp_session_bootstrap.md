# MCP 会话快速引导（uoa-scoring）

用途: 在新会话中用最少 token 快速恢复项目上下文，避免重复全仓库搜索。

## 1. 30 秒加载顺序

1. `docs/spec_coding_uoa_scoring_app.md`
2. `README.md`
3. （按需）专项文档:
   - `docs/refactor_stability_playbook_20260304.md`
   - `docs/ui_layout_profile_requirements_20260301.md`
   - `docs/strict_zawa_rules_manual_20260227.md`
   - `reports/icon_diagnosis_20260301.md`

## 2. 功能定位速查

- API / 后端任务 / 账号 CRUD: `app/main.py`
- 算分与优化口径: `app/engine.py`
- 页面结构: `app/static/index.html`
- 交互状态与按钮逻辑: `app/static/app.js`
- 样式排版: `app/static/styles.css`

## 3. 标准工作流（开发协作）

1. 先在 `spec` 确认口径和边界。
2. 定位功能对应代码入口（见第 2 节）。
3. 修改代码后同步更新:
   - `README.md`（用户可见行为变化）
   - `docs/spec_coding_uoa_scoring_app.md`（接口/口径/结构变化）
4. 给出验证步骤（最少包含本地启动 + 关键流程复测）。

## 4. 最小验证清单

- 启动服务:
  - `python -m uvicorn app.main:app --host 127.0.0.1 --port 8765`
- 重构护栏:
  - `python3 tools/refactor_guard.py`
- 巡检护栏:
  - `python3 tools/bug_sweep.py --host 127.0.0.1 --port 8765`
- 页面主流程:
  - 读取账号 -> 选择歌曲 -> 最优配队
  - 结果点击成员 -> 队伍换卡对比
  - 保存账号后刷新 -> 状态恢复

## 5. 文档更新触发器

- 改 API 字段: 必须改 `spec`
- 改算分公式/口径: 必须改 `spec`
- 改按钮行为/UI 文案: 必须改 `README`（必要时改 `spec`）
- 改数据结构（如 profiles）: 必须改 `README` + `spec`
