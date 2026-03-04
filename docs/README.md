# 文档索引（uoa-scoring）

本目录用于存放 `uoa-scoring` 的规范、口径和历史设计文档。

## 推荐阅读顺序

1. `mcp_session_bootstrap.md`
2. `spec_coding_uoa_scoring_app.md`
3. `refactor_stability_playbook_20260304.md`
4. `ui_layout_profile_requirements_20260301.md`
5. `strict_zawa_rules_manual_20260227.md`
6. `project_split_guide_20260227.md`

## GitHub Pages

- 页面源: `app/static/`（由 `deploy/build_pages_site.sh` 构建为 `.pages_site/`）
- 发布工作流: `.github/workflows/pages.yml`

## 文档说明

### `mcp_session_bootstrap.md`
- 新会话最小上下文加载清单。
- 重点解决“重复查找文件导致 token 消耗高”的问题。

### `spec_coding_uoa_scoring_app.md`
- 当前项目的主规格文档（推荐作为 MCP/AI 协作首读文档）。
- 覆盖:
  - 目录与模块映射
  - API 规格
  - 算分公式与优化流程
  - 数据源与持久化
  - UI 模块结构

### `ui_layout_profile_requirements_20260301.md`
- 历史 UI/账号配置交互约束文档。
- 主要用于回溯 UI 变更背景和文案口径。

### `refactor_stability_playbook_20260304.md`
- “不改行为先上护栏”的重构手册。
- 包含 `tools/refactor_guard.py` 基线检查流程与分阶段拆分策略。

### `strict_zawa_rules_manual_20260227.md`
- 严格 zawa 口径说明与成员名单口径。
- 用于验证“为什么这样算”。

### `project_split_guide_20260227.md`
- `uoa-scoring` 与 `uoa-extract` 拆分说明。
- 主要用于仓库边界与职责划分回溯。

## 维护约定

- 修改 API/算分口径/UI 主结构时，必须同步更新:
  - `spec_coding_uoa_scoring_app.md`
- 若只是视觉微调，可仅更新:
  - `ui_layout_profile_requirements_*.md`
- 若调整严格口径或统计规则，必须同步更新:
  - `strict_zawa_rules_manual_*.md`
- 若进行结构重构或模块拆分，必须同步更新:
  - `refactor_stability_playbook_*.md`
