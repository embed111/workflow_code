# Presentation Module Contract

## 1. 模块目标与非目标
- 目标：承载页面模板与展示输出，避免内联模板回流到运行时主模块。
- 目标：提供稳定的页面渲染入口给 API/路由层调用。
- 非目标：不承载业务编排逻辑和数据库访问逻辑。

## 2. 目录职责边界（In/Out）
- In：`pages.py` 页面输出函数，`templates/index.html` 页面模板。
- Out：训练计划调度、发布管理状态机、审计写入。

## 3. 对外接口（API/Event/函数入口）
- 页面入口：`server/presentation/pages.py`。
- 模板资源：`server/presentation/templates/index.html`。

## 4. 允许依赖与禁止依赖
- 允许依赖：标准库、轻量配置读取、静态文本渲染工具。
- 禁止依赖：`server/services/*` 深层业务逻辑、`server/infra/db/*`。
- 禁止行为：在模板层做 SQL 查询与训练队列状态流转。

## 5. 状态与数据存储（表/文件/缓存）
- 模板文件：`templates/index.html`。
- 可使用进程内短生命周期缓存（模板文本缓存），不得持久化业务状态。

## 6. 关键回归命令
- `python scripts/quality/check-module-readme-contract.py --root .`
- `python scripts/quality/check-prototype-text.py --root .`
- `python scripts/acceptance/run_acceptance_training_center_uo.py --root . --host 127.0.0.1 --port 8098`

## 7. 常见变更操作步骤（新增接口/改字段）
- 改页面结构：
  1. 优先更新模板文件。
  2. 若需数据字段，先确认 API 字段已稳定，再做渲染绑定。
  3. 避免在模板层引入复杂逻辑分支。
- 改静态资源装配：
  1. 确认 `bootstrap` 的资源加载函数仍按约定拼接。
  2. 验证 `/static/workflow-web-client.js` 可访问。

## 8. 回滚策略
- 单点回滚：回退模板或 `pages.py` 的单个提交。
- 若页面不可用：优先恢复最近稳定模板，保持 API 不动。
- 回滚后验证：主页可打开，前端脚本成功加载。

## 9. Agent 接管入口（先读文件、执行顺序、最小验证）
- 先读文件：
  1. `server/presentation/pages.py`
  2. `server/presentation/templates/index.html`
  3. `server/bootstrap/web_server_runtime.py`（静态资源加载段）
- 执行顺序：
  1. 验证模板加载路径。
  2. 验证页面首屏渲染。
  3. 验证 UO 页面交互关键截图。
- 最小验证：
  1. 主页 HTTP 200。
  2. `/static/workflow-web-client.js` HTTP 200。
  3. UO 首屏截图可复现。

