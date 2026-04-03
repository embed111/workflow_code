# Bootstrap Module Contract

## 1. 模块目标与非目标
- 目标：提供应用启动、运行时配置装配、Web 资源拼装与服务生命周期管理。
- 目标：保持 `workflow_web_server.py` 薄门面策略。
- 非目标：不承载领域业务规则，不新增训练/会话功能。

## 2. 目录职责边界（In/Out）
- In：`web_server_runtime.py` 中的启动参数、HTTPServer 组装、资源加载。
- Out：训练计划调度策略、发布版本判断、策略分析业务计算。

## 3. 对外接口（API/Event/函数入口）
- 启动入口：`web_server_runtime.py` 的 `serve(...)`。
- 资源装配：`load_web_client_asset_text()`（按 `web_client/bundle_manifest.json` 显式清单顺序拼装 `web_client/*.js`）。
- 兼容门面：`workflow_app/workflow_web_server.py` 调用本模块。

## 4. 允许依赖与禁止依赖
- 允许依赖：`server/api/*`、`server/presentation/*`、`server/infra/*`。
- 禁止依赖：直接在 bootstrap 内实现复杂业务算法。
- 禁止行为：把已拆分服务逻辑回流到启动层。

## 5. 状态与数据存储（表/文件/缓存）
- 配置源：环境变量 + runtime config 文件。
- 静态资源：`src/workflow_app/web_client/*.js` 按 manifest 组装成 `/static/workflow-web-client.js`。
- 启动日志：标准输出/错误输出与 `logs/runs` 留痕。

## 6. 关键回归命令
- `python scripts/quality/check-module-readme-contract.py --root .`
- `python scripts/quality/check-prototype-text.py --root .`
- `python scripts/acceptance/run_acceptance_training_center_uo.py --root . --host 127.0.0.1 --port 8098`
- `python scripts/acceptance/run_acceptance_agent_release_ar.py --root . --host 127.0.0.1 --port 8099`

## 7. 常见变更操作步骤（新增接口/改字段）
- 新增后端接口：
  1. 在 API 层实现并注册。
  2. bootstrap 仅更新装配，不写业务逻辑。
  3. 保持门面入口参数兼容。
- 改前端脚本装配：
  1. 确认 `web_client/bundle_manifest.json` 清单顺序与文件存在性。
  2. 验证脚本拼装结果加载正常。

## 8. 回滚策略
- 启动异常：优先回滚 bootstrap 层变更，保持 API/Service 文件不变。
- 资源异常：回滚 `load_web_client_asset_text()` 或 manifest 变更，恢复稳定清单装配。
- 回滚后验证：`/api/healthz`、主页加载、UO/AR 均通过。

## 9. Agent 接管入口（先读文件、执行顺序、最小验证）
- 先读文件：
  1. `src/workflow_app/workflow_web_server.py`
  2. `src/workflow_app/server/bootstrap/web_server_runtime.py`
  3. `src/workflow_app/server/api/router.py`
- 执行顺序：
  1. 确认入口门面只做转发。
  2. 确认启动装配与路由注册顺序。
  3. 跑 `healthz + UO + AR`。
- 最小验证：
  1. `python -m compileall src/workflow_app`
  2. `python scripts/acceptance/run_acceptance_training_center_uo.py --root . --host 127.0.0.1 --port 8098`
  3. `python scripts/acceptance/run_acceptance_agent_release_ar.py --root . --host 127.0.0.1 --port 8099`

