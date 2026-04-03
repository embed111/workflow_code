# Acceptance Scripts

- `run_acceptance_workflow_gate.py`: 全链路 workflow 门禁验收脚本。
- `run_acceptance_session_parallel_ac16_ac22.py`: AC16~AC22 会话并发与任务状态验收。
- `run_acceptance_workflow_chain_ac23_ac26.py`: AC23~AC26 训练链路可见性验收。
- `run_acceptance_message_delete_ac28_ac30.py`: AC28~AC30 消息删除与审计验收。
- `run_acceptance_policy_cache_ac31_ac35.py`: AC31~AC35 角色策略缓存门禁验收。
- `run_acceptance_policy_ui_ac36_ac43.py`: AC36~AC43 角色策略详情 UI 门禁验收。
- `run_acceptance_training_center_uo.py`: AC-UO-01~11 训练中心统一入口验收。
- `run_acceptance_role_creation_async_delete.py`: 创建角色异步消息批处理与删除规则定向验收。
- `run_acceptance_agent_release_ar.py`: AC-AR-01~10 agent 发布管理与版本切换验收。
- `run_acceptance_test_data_toggle_td.py`: AC-TD-01~09 测试数据环境策略与开关下线验收。
- `run_acceptance_agent_release_review_ar09_ar15.py`: AC-AR-09~15 + AC-AR-17/19/20 角色发布评审、废弃重评、历史发布报告弹窗与角色画像绑定验收。
- `prune_evidence_keep_gate_only.py`: 验收通过后证据精简脚本（仅保留门禁截图与汇总文件）。

## Prune Evidence

仅在该轮验收全部通过后执行（脚本会自动校验 `ac_*_summary` 结论）。

示例（AR）：

```powershell
python scripts/acceptance/prune_evidence_keep_gate_only.py --evidence-dir .test/evidence/agent-release-ar-20260303-135327 --dry-run
python scripts/acceptance/prune_evidence_keep_gate_only.py --evidence-dir .test/evidence/agent-release-ar-20260303-135327
```

示例（UO）：

```powershell
python scripts/acceptance/prune_evidence_keep_gate_only.py --evidence-dir .test/evidence/training-center-uo-20260303-135546 --dry-run
python scripts/acceptance/prune_evidence_keep_gate_only.py --evidence-dir .test/evidence/training-center-uo-20260303-135546
```
