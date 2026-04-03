# Server Module Contract

## 1. 模块目标与非目标
- 目标：作为后端分层根目录，统一约束 `api/services/infra/presentation/bootstrap` 的职责分工与装配顺序。
- 目标：保证 API 路径、关键字段、错误码语义在重构中持续兼容。
- 非目标：不在本层新增业务功能，不承载具体训练或会话业务实现。

## 2. 目录职责边界（In/Out）
- In：模块分层边界定义、跨层依赖约束、运行/回归入口约束。
- Out：具体路由处理、业务计算、DB 细节、模板渲染细节。

## 3. 对外接口（API/Event/函数入口）
- 入口函数：`workflow_app.workflow_web_server.serve`（兼容门面）。
- 启动装配：`workflow_app.server.bootstrap.web_server_runtime.serve`。
- 路由分发：`workflow_app.server.api.router.dispatch_get` / `dispatch_post`。

## 4. 允许依赖与禁止依赖
- 允许依赖：`server/bootstrap -> server/api -> server/services -> server/infra`，`server/presentation` 由 API 层按需调用。
- 禁止依赖：`services` 反向依赖 `api/presentation`；`infra` 反向依赖 `api/services`；跨层循环依赖。
- 历史业务实现已迁移到语义目录：`workflow_app/runtime`、`workflow_app/entry`、`workflow_app/history`；`src/workflow_app` 根目录仅保留兼容薄门面。

## 5. 状态与数据存储（表/文件/缓存）
- SQLite：`state/workflow.db`（会话、训练计划、训练队列、训练运行、审计等）。
- 事件文件：`logs/events/*.jsonl`。
- 运行/验收证据：`.test/evidence/*`、`.test/runs/*`、`.test/reports/*`。

## 6. 关键回归命令
- `python scripts/quality/check-module-readme-contract.py --root .`
- `python scripts/quality/check-prototype-text.py --root .`
- `python scripts/acceptance/run_acceptance_training_center_uo.py --root . --host 127.0.0.1 --port 8098`
- `python scripts/acceptance/run_acceptance_agent_release_ar.py --root . --host 127.0.0.1 --port 8099`

## 7. 常见变更操作步骤（新增接口/改字段）
- 新增接口：
  1. 在 `server/api/*` 增加路由处理函数。
  2. 在 `server/services/*` 落业务逻辑，不把逻辑回灌到 API 层。
  3. 若涉及存储变更，更新 `server/infra/db/migrations.py` 与读取路径。
- 改字段：
  1. 先更新服务层返回结构。
  2. 再更新 API 序列化。
  3. 最后更新前端读取字段并跑 UO/AR。

## 8. 回滚策略
- 回滚顺序：先恢复对应子模块文件，再恢复路由分发绑定，最后恢复证据脚本。
- 触发条件：UO/AR 任一非 0，或结构门禁脚本失败。
- 最小回滚验证：`/api/healthz`、`/api/training/agents`、`/api/training/queue` 可用。

## 9. Agent 接管入口（先读文件、执行顺序、最小验证）
- 先读文件：
  1. `docs/workflow/需求详情-工程化重构与目录治理.md`
  2. `docs/workflow/详细设计-工程化重构与目录治理.md`
  3. `docs/workflow/ARCHITECTURE_REFACTOR_MAP.md`
  4. `docs/workflow/REFactor_LINE_BUDGET_REPORT.md`
- 执行顺序：
  1. 跑结构门禁脚本。
  2. 跑文本门禁脚本。
  3. 跑 UO + AR 回归。
- 最小验证：
  1. `python -m compileall src/workflow_app`
  2. `python scripts/quality/check-module-readme-contract.py --root .`
  3. `python scripts/quality/check-prototype-text.py --root .`

