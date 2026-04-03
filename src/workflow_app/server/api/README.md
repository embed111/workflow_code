# API Module Contract

## 1. 模块目标与非目标
- 目标：负责 HTTP 请求解析、参数校验、路由分发、统一错误响应。
- 目标：保持既有 API 路径与响应字段兼容。
- 非目标：不在 API 层承载复杂业务编排与存储细节。

## 2. 目录职责边界（In/Out）
- In：`config/chat/training/policy/dashboard` 路由注册；legacy 兼容分发；协议转换。
- Out：训练计划排序逻辑、发布状态机、DB SQL 拼接实现。

## 3. 对外接口（API/Event/函数入口）
- 路由入口：`router.py` 中注册与分发。
- 关键接口：
  - `GET /api/healthz`
  - `GET /api/training/agents`
  - `GET /api/training/agents/{agent}/releases`
  - `POST /api/training/plans/manual`
  - `GET /api/training/queue`
  - `POST /api/training/queue/{queue_id}/remove`

## 4. 允许依赖与禁止依赖
- 允许依赖：`server/services/*`、`server/infra/*`、`server/presentation/pages.py`。
- 禁止依赖：反向依赖前端脚本；直接跨层写模板文件；在 API 层新增全局状态缓存。

## 5. 状态与数据存储（表/文件/缓存）
- 不直接定义持久化结构。
- 通过服务层访问：`training_plan`、`training_queue`、`training_run`、`audit_logs` 等表。
- API 层仅可维护短生命周期请求上下文。

## 6. 关键回归命令
- `python scripts/quality/check-module-readme-contract.py --root .`
- `python scripts/quality/check-prototype-text.py --root .`
- `python scripts/acceptance/run_acceptance_training_center_uo.py --root . --host 127.0.0.1 --port 8098`

## 7. 常见变更操作步骤（新增接口/改字段）
- 新增接口：
  1. 在对应域模块新增 handler（优先 `chat/training/policy/dashboard`）。
  2. 在 `router.py` 注册，保持 path 与 method 明确。
  3. 仅在 API 层做入参校验和错误映射。
- 改字段：
  1. 在服务层定义新字段。
  2. API 层做向后兼容转换（必要时保留旧字段）。
  3. 补充验收脚本字段断言。

## 8. 回滚策略
- 单接口回滚：回退对应 handler 与注册项，避免动到其他域路由。
- 聚合回滚：回退 `legacy_task_*_handlers.py` 分拆入口到上一稳定版本。
- 回滚后验证：接口状态码、错误码和关键字段与上轮证据一致。

## 9. Agent 接管入口（先读文件、执行顺序、最小验证）
- 先读文件：
  1. `src/workflow_app/server/api/router.py`
  2. `src/workflow_app/server/api/training.py`
  3. `src/workflow_app/server/api/legacy_task_handlers.py`
- 执行顺序：
  1. 确认路由在 `router.py` 注册。
  2. 确认 handler 调用服务层而非内联业务。
  3. 执行 UO/AR 回归。
- 最小验证：
  1. `curl http://127.0.0.1:8098/api/healthz`
  2. `curl http://127.0.0.1:8098/api/training/agents`
  3. `python scripts/acceptance/run_acceptance_training_center_uo.py --root . --host 127.0.0.1 --port 8098`

