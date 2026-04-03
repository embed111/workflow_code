# Infra Module Contract

## 1. 模块目标与非目标
- 目标：提供数据库连接、迁移、审计写入、运行时底座能力。
- 目标：为服务层提供稳定、可测试的基础设施抽象。
- 非目标：不承载业务决策逻辑，不直接暴露 HTTP 接口。

## 2. 目录职责边界（In/Out）
- In：`db/connection.py`、`db/migrations.py`、`audit_runtime.py` 及其调用工具。
- Out：训练优先级策略、会话门禁判定、页面渲染逻辑。

## 3. 对外接口（API/Event/函数入口）
- DB 连接：`server/infra/db/connection.py`
- DB 迁移：`server/infra/db/migrations.py`
- 审计桥接：`server/infra/audit_runtime.py`

## 4. 允许依赖与禁止依赖
- 允许依赖：Python 标准库、项目内低层公共工具。
- 禁止依赖：`server/api/*`、`server/presentation/*`。
- 禁止行为：在 infra 层读取浏览器状态或拼接前端响应结构。

## 5. 状态与数据存储（表/文件/缓存）
- SQLite：`state/workflow.db`。
- 运行日志：`logs/events/*.jsonl`、`logs/runs/*.md`。
- Infra 仅维护连接与迁移，不维护业务缓存语义。

## 6. 关键回归命令
- `python scripts/quality/check-module-readme-contract.py --root .`
- `python scripts/quality/check-prototype-text.py --root .`
- `python -m compileall src/workflow_app`
- `python scripts/acceptance/run_acceptance_training_center_uo.py --root . --host 127.0.0.1 --port 8098`

## 7. 常见变更操作步骤（新增接口/改字段）
- 改表结构：
  1. 在 `db/migrations.py` 增加幂等迁移。
  2. 在服务层加读写兼容分支。
  3. 验证旧库升级与新库初始化都通过。
- 改连接参数：
  1. 统一通过连接模块入口修改。
  2. 禁止在服务层散落 `sqlite3.connect`。

## 8. 回滚策略
- 优先回滚迁移触发点，保持旧字段可读。
- 若新字段已写入，先增加兼容读取，再执行代码回退。
- 回滚后验证：服务可启动，`/api/healthz` 和关键查询接口正常。

## 9. Agent 接管入口（先读文件、执行顺序、最小验证）
- 先读文件：
  1. `server/infra/db/connection.py`
  2. `server/infra/db/migrations.py`
  3. `server/infra/audit_runtime.py`
- 执行顺序：
  1. 检查 DB 初始化与迁移是否幂等。
  2. 检查审计记录写入路径。
  3. 运行 UO/AR 验证查询链路。
- 最小验证：
  1. 初始化空目录可自动建库。
  2. 队列操作后可查询审计表。
  3. 事件日志持续落盘。

