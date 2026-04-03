# Web Client Contract

## 1. 模块目标与非目标
- 目标：承载会话、策略确认、训练中心、设置等前端交互逻辑。
- 目标：保持现有 API 字段兼容，避免大规模前后端契约漂移。
- 非目标：本目录不处理后端路由，不直接操作数据库。

## 2. 当前模块边界（In/Out）
- In：
  - `app_status_and_icon_utils.js`：全局状态辅助、状态映射、图标与 badge 工具。
  - `app_state_and_utils.js`：布局、agent 选择、策略状态缓存、通用运行时工具。
  - `policy_gate_and_cache.js`：策略门禁与缓存处理。
  - `session_policy_card_helpers.js`：策略卡片、约束解析、复制/编辑辅助。
  - `session_and_agent_meta.js`：会话列表、agent 元数据面板与策略弹窗。
  - `policy_gate_and_session_core.js`：策略门禁联动与会话执行核心。
  - `policy_confirm_and_interactions.js`：会话列表/trace/feed 交互。
  - `workflow_queue_selection_core.js`：队列模式、选择、批处理元状态。
  - `workflow_queue_and_batch.js`：队列详情、事件流、批处理执行。
  - `training_center_and_bootstrap.js`：训练中心页与启动阶段绑定逻辑。
  - `app_shell_and_bootstrap.js`：应用壳层、事件绑定与启动收口。
- Out：
  - 后端协议定义、训练编排规则、数据库迁移。

## 3. 组装机制说明
- 运行时组装入口：`src/workflow_app/server/bootstrap/web_server_runtime.py` 的 `load_web_client_asset_text()`。
- 组装规则：读取 `src/workflow_app/web_client/bundle_manifest.json` 显式清单，按清单顺序拼接后通过 `/static/workflow-web-client.js` 提供。
- 兼容策略：若分片不存在，回退读取 `src/workflow_app/workflow_web_client.js`。

## 4. 去序号命名迁移计划
- 目标：从 `00_*.js` 风格迁移到“领域 + 职责”命名，减少原型化序号依赖。
- 当前状态：已完成；`web_client` 目录不再保留 `^\d{2}_.*\\.js$` 命名。
- 迁移步骤：
  1. 拆出跨域工具模块（如 `app_status_and_icon_utils.js`）。
  2. 拆出队列和策略重模块（如 `policy_gate_and_session_core.js`、`workflow_queue_selection_core.js`）。
  3. 用 `bundle_manifest.json` 固定装配顺序并删除旧序号文件。
- 迁移原则：
  1. 单轮只迁移一个域，避免跨域爆炸改动。
  2. 每次迁移后必须保留可回滚点和证据目录。

## 5. 允许依赖与禁止依赖
- 允许依赖：浏览器标准 API、同目录共享工具、后端公开 API。
- 禁止依赖：Node 构建期依赖、后端私有实现细节、硬编码本地绝对路径。

## 6. 关键回归命令
- `python scripts/quality/check-prototype-text.py --root .`
- `python scripts/acceptance/run_acceptance_training_center_uo.py --root . --host 127.0.0.1 --port 8098`
- `python scripts/acceptance/run_acceptance_agent_release_ar.py --root . --host 127.0.0.1 --port 8099`

## 7. 常见变更操作步骤（新增交互/改字段）
- 新增交互：
  1. 放到最接近域职责的文件，避免堆到单一入口。
  2. 如新增状态字段，先在 `app_state_and_utils.js` 定义默认值。
  3. 补最小 UI 验证截图。
- 改 API 字段：
  1. 先做向后兼容读取（`safe(...)`）。
  2. 再统一替换旧字段引用。
  3. 跑 UO/AR。

## 8. 回滚策略
- 前端异常时优先回滚单域文件，不回滚后端协议。
- 若启动失败，先检查组装顺序与语法错误，再回退最近分片改动。
- 回滚后最小验证：主页可打开、会话发送可用、训练中心可加载。

## 9. Agent 接管入口（先读文件、执行顺序、最小验证）
- 先读文件：
  1. `bundle_manifest.json`
  2. `app_state_and_utils.js`
  3. `policy_confirm_and_interactions.js`
  4. `training_center_and_bootstrap.js`
  5. `app_shell_and_bootstrap.js`
- 执行顺序：
  1. 先确认状态字段定义。
  2. 再改域交互逻辑。
  3. 最后改启动组装。
- 最小验证：
  1. 打开首页并确认训练中心入口可见。
  2. 新建会话、发送消息、查看训练队列。
  3. 运行 UO/AR 并核对截图证据。

