# Services Module Contract

## 1. 模块目标与非目标
- 目标：承接训练中心、发布管理、策略分析、任务编排等业务逻辑。
- 目标：对 API 层暴露稳定函数入口，统一领域规则。
- 非目标：不直接处理 HTTP 协议细节，不直接拼装页面模板。

## 2. 目录职责边界（In/Out）
- In：队列优先级排序、计划去重/相似标记、状态流转、策略解析、会话编排。
- Out：请求参数解析、响应序列化、静态资源加载、低层 DB 连接创建。

## 3. 对外接口（API/Event/函数入口）
- 训练中心：
  - `training_plan_service.py`
  - `training_registry_service.py`
  - `release_management_service.py`
  - `trainer_assignment_service.py`
- 策略与会话：
  - `policy_analysis.py`
  - `agent_discovery_service.py`
  - `policy_fallback_service.py`
  - `session_orchestration.py`

## 4. 允许依赖与禁止依赖
- 允许依赖：`server/infra/*`、`workflow_app/runtime/training_center_runtime.py` 中公共契约函数。
- 禁止依赖：`server/api/*`、`server/presentation/*`（避免反向耦合）。
- 禁止行为：在服务层引入请求对象、响应对象或 HTML 拼接。

## 5. 状态与数据存储（表/文件/缓存）
- 访问表：`agent_registry`、`training_plan`、`training_queue`、`training_run`、`audit_logs` 等。
- 事件与审计：通过运行时日志和 DB 审计表留痕。
- 缓存：仅允许短生命周期内存缓存，不允许跨进程隐式状态。

## 6. 关键回归命令
- `python scripts/quality/check-module-readme-contract.py --root .`
- `python scripts/quality/check-prototype-text.py --root .`
- `python scripts/acceptance/run_acceptance_training_center_uo.py --root . --host 127.0.0.1 --port 8098`
- `python scripts/acceptance/run_acceptance_agent_release_ar.py --root . --host 127.0.0.1 --port 8099`

## 7. 常见变更操作步骤（新增接口/改字段）
- 新增能力：
  1. 优先新增独立 service 文件（领域 + 职责命名）。
  2. 由 API 层调用新函数，不在 API 层复制规则。
  3. 若涉及表字段，先补迁移再补服务读写。
- 改字段：
  1. 先更新服务返回结构与默认值。
  2. 再更新 API 序列化和前端消费。
  3. 跑 UO/AR 验证兼容性。

## 8. 回滚策略
- 规则回滚：回退对应 service 文件，保持函数签名兼容。
- 数据回滚：如新字段引发问题，先停止写入新字段，再回退读取分支。
- 最小回滚验证：手动训练入队、队列查看、人工移除、执行完成审计可查。

## 9. Agent 接管入口（先读文件、执行顺序、最小验证）
- 先读文件：
  1. `training_plan_service.py`
  2. `release_management_service.py`
  3. `policy_analysis.py`
- 执行顺序：
  1. 理解服务函数输入输出契约。
  2. 检查调用链（API -> Service -> Infra）。
  3. 跑 UO/AR 回归。
- 最小验证：
  1. 训练计划入队与优先级排序正确。
  2. 队列移除写入审计。
  3. 策略链路在异常时走 fallback。

