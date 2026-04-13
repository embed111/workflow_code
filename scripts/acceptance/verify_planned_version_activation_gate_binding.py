#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


REFERENCE_TEMPLATE = """# PM当前版本计划

## 2. 当前活跃版本
- active_version: `V2`
- active_version_title: `测试中的当前版本`
- active_version_file: `pm/versions/V2/版本计划.md`
- version_history_root: `pm/versions/V2/history/`
"""

ACTIVE_VERSION_TEMPLATE = """# V2 测试中的当前版本

- version: `V2`
- status: `active`
- owner: `workflow(pm)`
- history_root: `pm/versions/V2/history/`

## 1. 版本定位
- 供 activation gate fixture 使用。

## 3. 版本目标
- 保持当前版本具备最小解析字段。

## 4. 具体需求点
| 需求点 | 责任人 | 协作方 | 状态 | 进度评估 | 预计完成 | 超时/AAR | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `V2-R1` 当前版本占位 | `workflow(pm)` | `workflow_devmate` | `in_progress` | `90%` | `2026-04-18` | `未超时` | 当前版本只用于驱动 planned activation gate fixture。 |

## 5. 当前状态快照
1. 最新有效快照截至 `2026-04-13T20:00:00+08:00`：
   1. active 版本仍是 `V2`
   2. 当前最高价值泳道已切到 `功能开发`
   3. 生命周期阶段已切到 `开发实现`
   4. baseline 已对齐为 `prod=20260413-184546`
"""

PLANNED_VERSION_TEMPLATE = """# V3 下一个 planned 版本

- version: `V3`
- status: `planned`
- owner: `workflow(pm)`
- history_root: `pm/versions/V3/history/`

## 1. 版本定位
- 供 activation gate fixture 使用。

## 2. 进入前提
- `V2` 已进入稳定收口。

## 3. 版本目标
- 让下一版 activation gate 能区分 draft 占位和真实 probe binding。

## 4. 具体需求点
| 需求点 | 责任人 | 协作方 | 状态 | 目标 | 依赖 | 验收/Probe | Gate级别 | 完成定义 | 阻塞/备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `V3-R1` 下一版首项能力 | `workflow(pm)` | `workflow_devmate` | `planned` | 把 activation gate 接成真实准入链 | 无 | `{row_probe}` | `activation-gate` | 准入链具备真实 binding 并能被版本看板识别 | fixture |

## 5. 退出门槛
1. 下一版 activation gate 可以给出正确结论。

## 5.1 激活前准入清单
- activation_readiness: `{activation_readiness}`
- upstream_dependencies: `V2-R8`
- required_probes: `verify_planned_version_activation_readiness.py`、`{required_probe}`
- required_evidence_sources: `pm/versions/V2/版本计划.md`
- blocking_items: `{blocking_items}`
- go_no_go_rule: 只有当 draft 占位都被真实 probe binding 替换，且 blocker 清空后，才允许把 `V3` 提升为 active
- waiver_rule: `无`
"""


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_fixture(root: Path, *, ready: bool) -> None:
    _write_text(root / "pm" / "PM当前版本计划.md", REFERENCE_TEMPLATE)
    _write_text(root / "pm" / "versions" / "V2" / "版本计划.md", ACTIVE_VERSION_TEMPLATE)
    _write_text(
        root / "pm" / "versions" / "V3" / "版本计划.md",
        PLANNED_VERSION_TEMPLATE.format(
            activation_readiness="ready" if ready else "warning",
            required_probe=(
                "verify_planned_version_activation_gate_binding.py"
                if ready
                else "draft:v3-activation-gate"
            ),
            blocking_items="无" if ready else "V2-R8 activation gate 尚未落地",
            row_probe=(
                "verify_planned_version_activation_gate_binding.py"
                if ready
                else "draft:v3-r1-activation-gate"
            ),
        ),
    )
    acceptance_root = root / "scripts" / "acceptance"
    _write_text(
        acceptance_root / "verify_planned_version_activation_readiness.py",
        "# fixture probe\n",
    )
    _write_text(
        acceptance_root / "verify_planned_version_activation_gate_binding.py",
        "# fixture activation gate probe\n",
    )


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.services.pm_version_board_service import load_pm_version_board

    with tempfile.TemporaryDirectory(prefix="pm-activation-gate-") as tmp_dir:
        fixture_root = Path(tmp_dir).resolve()

        _write_fixture(fixture_root, ready=False)
        draft_board = load_pm_version_board(fixture_root, runtime_snapshot={})
        draft_activation = dict(draft_board.get("activation_summary") or {})
        draft_row = next(
            (
                item
                for item in list(draft_activation.get("versions") or [])
                if str(item.get("version_id") or "").strip() == "V3"
            ),
            {},
        )
        assert str(draft_activation.get("next_activation_candidate") or "").strip() == "V3", draft_activation
        assert not bool(draft_activation.get("next_activation_ready")), draft_activation
        assert list(draft_activation.get("hard_failures") or []) == ["V3"], draft_activation
        assert not bool(draft_row.get("ok")), draft_row
        assert bool(draft_row.get("schema_ok")), draft_row
        assert "draft:v3-activation-gate" in list(draft_row.get("draft_probe_refs") or []), draft_row
        assert "draft:v3-r1-activation-gate" in list(draft_row.get("draft_probe_refs") or []), draft_row
        assert not bool(draft_row.get("blocking_items_clear")), draft_row

        _write_fixture(fixture_root, ready=True)
        ready_board = load_pm_version_board(fixture_root, runtime_snapshot={})
        ready_activation = dict(ready_board.get("activation_summary") or {})
        ready_row = next(
            (
                item
                for item in list(ready_activation.get("versions") or [])
                if str(item.get("version_id") or "").strip() == "V3"
            ),
            {},
        )
        assert bool(ready_activation.get("next_activation_ready")), ready_activation
        assert not list(ready_activation.get("hard_failures") or []), ready_activation
        assert bool(ready_row.get("ok")), ready_row
        assert bool(ready_row.get("activation_gate_ready")), ready_row
        assert not list(ready_row.get("draft_probe_refs") or []), ready_row
        assert not list(ready_row.get("unbound_probe_refs") or []), ready_row
        assert bool(ready_row.get("blocking_items_clear")), ready_row

    print(
        json.dumps(
            {
                "ok": True,
                "draft_summary": draft_row.get("summary"),
                "ready_summary": ready_row.get("summary"),
                "ready_activation": ready_activation.get("next_activation_ready"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
