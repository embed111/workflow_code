# workflow_app Source

`src/workflow_app` 根目录仅保留薄门面与包元信息，业务实现按语义目录划分：

- `workflow_web_server.py`: Web/API 兼容启动门面（转发到 `server/bootstrap/web_server_runtime.py`）。
- `server/`: 后端分层模块（`api/services/infra/presentation/bootstrap`）。
- `runtime/`: 运行时能力（`agent_runtime.py`、`task_agent_runner.py`、`training_center_runtime.py`）。
- `entry/`: 会话与训练闭环 CLI 模块（`workflow_entry_cli.py` 及其辅助模块）。
- `history/`: 历史数据清理与治理模块（`workflow_history_admin.py`）。
- `web_client/`: 前端分模块源码与 `bundle_manifest.json`。

兼容说明：

- `scripts/*.py` 保留薄入口，导入并转发到 `src/workflow_app` 新模块路径。
- `/static/workflow-web-client.js` 对外路径保持不变，由后端基于 manifest 组装输出。
