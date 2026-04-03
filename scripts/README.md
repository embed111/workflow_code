# Scripts Directory Guide

## 1. Structure
- `scripts/bin/`: 对外命令入口（Python）。
- `scripts/quality/`: 门禁与质量检查脚本（`check-*`）。
- `scripts/dev/`: 启动与开发辅助脚本（PowerShell/兼容静态资源）。
- `scripts/acceptance/`: 验收脚本（保持原职责）。

## 2. Top-Level Policy
- 顶层仅保留稳定入口与兼容过渡 stub：
  - `scripts/workflow_web_server.py`
  - `scripts/workflow_entry_cli.py`
  - `scripts/launch_workflow.ps1`

## 3. Path Mapping
| old path | new path | compatibility |
|---|---|---|
| `scripts/workflow_web_server.py` | `scripts/bin/workflow_web_server.py` | 顶层 stub 转发 |
| `scripts/workflow_entry_cli.py` | `scripts/bin/workflow_entry_cli.py` | 顶层 stub 转发 |
| `scripts/launch_workflow.ps1` | `scripts/dev/launch_workflow.ps1` | 顶层 stub 转发 |
| `scripts/start_workflow_web.ps1` | `scripts/dev/start_workflow_web.ps1` | 直接使用新路径 |
| `scripts/agent_runtime.py` | `scripts/bin/agent_runtime.py` | 使用新路径 |
| `scripts/task_agent_runner.py` | `scripts/bin/task_agent_runner.py` | 使用新路径 |
| `scripts/training_center_runtime.py` | `scripts/bin/training_center_runtime.py` | 使用新路径 |
| `scripts/workflow_history_admin.py` | `scripts/bin/workflow_history_admin.py` | 使用新路径 |
| `scripts/check-module-readme-contract.py` | `scripts/quality/check-module-readme-contract.py` | 使用新路径 |
| `scripts/check-prototype-text.py` | `scripts/quality/check-prototype-text.py` | 使用新路径 |
| `scripts/check_crud_gate.py` | `scripts/quality/check_crud_gate.py` | 使用新路径 |
| `scripts/check_layout_overflow.py` | `scripts/quality/check_layout_overflow.py` | 使用新路径 |
| `scripts/check_workspace_line_budget.py` | `scripts/quality/check_workspace_line_budget.py` | 使用新路径 |
| `scripts/workflow_web_client.js` | `scripts/dev/workflow_web_client.js` | 使用新路径 |

## 4. Common Commands
- `python scripts/workflow_web_server.py --help`
- `python scripts/workflow_entry_cli.py --help`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/launch_workflow.ps1 -OpenBrowser`
- `python scripts/quality/check-module-readme-contract.py --root .`
- `python scripts/quality/check-prototype-text.py --root .`
- `python scripts/quality/check_workspace_line_budget.py --root .`
