from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .defect_service import (
    DEFECT_PROCESS_ACTION_KIND,
    DEFECT_REVIEW_ACTION_KIND,
    DEFECT_STATUS_DISPUTE,
    DefectCenterError,
    _append_history,
    _defect_manual_task_gate,
    _default_assignee,
    _ensure_defect_tables,
    _json_loads_object,
    _load_report_row,
    _normalize_text,
    _now_text,
    _report_row_to_payload,
    _require_report_id,
    _runtime_version_label,
    _status_text,
    _write_report_update,
    assignment_service,
    connect_db,
    get_defect_detail,
)

DEFECT_ASSIGNMENT_SOURCE_WORKFLOW = "workflow-ui"
DEFECT_ASSIGNMENT_GRAPH_NAME = "任务中心全局主图"
DEFECT_ASSIGNMENT_GRAPH_REQUEST_ID = "workflow-ui-global-graph-v1"
DEFECT_TASK_NAME_BASE_MAX_LEN = 160
_DEFECT_LEGACY_REQUEST_RE = re.compile(r"^defect:(process|review):(dr-[A-Za-z0-9-]+)$")
_DEFECT_STAGE_TITLE_RE = re.compile(r"^(?P<base>.+?)\s*(?:-|/|·|:|：)\s*(?P<stage>.+?)$")
_DEFECT_ASSIGNMENT_REPAIR_SIGNATURES: dict[str, tuple[int, int]] = {}
_DEFECT_ASSIGNMENT_REPAIR_FAST_SIGNATURES: dict[str, tuple[int, int, int]] = {}
_DEFECT_LEGACY_CHAIN_NAME_BASE = "__legacy_defect_chain__"


class _DefectRootCfg:
    def __init__(self, root: Path) -> None:
        self.root = root


def _task_ref_id(
    report_id: str,
    ticket_id: str,
    focus_node_id: str,
    action_kind: str,
    external_request_id: str,
) -> str:
    raw = "|".join(
        [
            str(report_id or "").strip(),
            str(ticket_id or "").strip(),
            str(focus_node_id or "").strip(),
            str(action_kind or "").strip(),
            str(external_request_id or "").strip(),
        ]
    )
    return "dtr-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _upsert_task_ref(
    conn,
    report_id: str,
    *,
    ticket_id: str,
    focus_node_id: str,
    action_kind: str,
    title: str,
    external_request_id: str,
    created_at: str,
) -> None:
    rows = conn.execute(
        """
        SELECT ref_id,created_at FROM defect_task_refs
        WHERE report_id=? AND focus_node_id=? AND (external_request_id=? OR COALESCE(external_request_id,'')='')
        ORDER BY updated_at DESC, created_at DESC, ref_id DESC
        """,
        (report_id, focus_node_id, external_request_id),
    ).fetchall()
    if not rows:
        conn.execute(
            """
            INSERT INTO defect_task_refs(
                ref_id,report_id,ticket_id,focus_node_id,action_kind,title,external_request_id,created_at,updated_at
            )
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                _task_ref_id(report_id, ticket_id, focus_node_id, action_kind, external_request_id),
                report_id,
                ticket_id,
                focus_node_id,
                action_kind,
                title,
                external_request_id,
                created_at,
                created_at,
            ),
        )
        return
    keep_row = rows[0]
    conn.execute(
        """
        UPDATE defect_task_refs
        SET ticket_id=?, action_kind=?, title=?, external_request_id=?, updated_at=?
        WHERE ref_id=?
        """,
        (
            ticket_id,
            action_kind,
            title,
            external_request_id,
            created_at,
            str(keep_row["ref_id"] or "").strip(),
        ),
    )
    stale_ref_ids = [str(row["ref_id"] or "").strip() for row in rows[1:] if str(row["ref_id"] or "").strip()]
    if stale_ref_ids:
        placeholders = ",".join("?" for _ in stale_ref_ids)
        conn.execute(
            f"DELETE FROM defect_task_refs WHERE ref_id IN ({placeholders})",
            tuple(stale_ref_ids),
        )


def _ensure_defect_assignment_graph(cfg: Any) -> str:
    created = assignment_service.create_assignment_graph(
        cfg,
        {
            "graph_name": DEFECT_ASSIGNMENT_GRAPH_NAME,
            "source_workflow": DEFECT_ASSIGNMENT_SOURCE_WORKFLOW,
            "summary": "任务中心手动创建（全局主图）",
            "review_mode": "none",
            "external_request_id": DEFECT_ASSIGNMENT_GRAPH_REQUEST_ID,
            "operator": "defect-center",
        },
    )
    ticket_id = str(created.get("ticket_id") or "").strip()
    if not ticket_id:
        raise DefectCenterError(500, "global assignment graph missing", "defect_assignment_graph_missing")
    return ticket_id


def _load_assignment_node_ids(root: Path, ticket_id: str, *, include_test_data: bool) -> set[str]:
    graph = assignment_service.get_assignment_graph(root, ticket_id, include_test_data=include_test_data)
    rows = list(graph.get("node_catalog") or graph.get("nodes") or [])
    return {
        str(item.get("node_id") or "").strip()
        for item in rows
        if str(item.get("node_id") or "").strip()
    }


def _ensure_assignment_node(
    cfg: Any,
    ticket_id: str,
    body: dict[str, Any],
    *,
    known_node_ids: set[str],
    include_test_data: bool,
) -> bool:
    node_id = str(body.get("node_id") or "").strip()
    if not node_id:
        raise DefectCenterError(500, "assignment node_id missing", "defect_assignment_node_missing")
    if node_id in known_node_ids:
        return False
    assignment_service.create_assignment_node(
        cfg,
        ticket_id,
        {
            **body,
            "operator": "defect-center",
        },
        include_test_data=include_test_data,
    )
    known_node_ids.add(node_id)
    return True


def _defect_stage_layout(report_key: str, action_kind: str) -> list[tuple[str, str, str]]:
    if action_kind == DEFECT_PROCESS_ACTION_KIND:
        return [
            (f"{report_key}-analyze", "分析", "分析缺陷"),
            (f"{report_key}-fix", "修复", "修复缺陷"),
            (f"{report_key}-release", "推送到目标版本", "推送到目标版本"),
        ]
    if action_kind == DEFECT_REVIEW_ACTION_KIND:
        return [
            (f"{report_key}-review", "复核", "复核争议"),
        ]
    raise DefectCenterError(400, "defect action_kind invalid", "defect_action_kind_invalid", {"action_kind": action_kind})


def _normalize_defect_task_name_base(value: Any) -> str:
    text = _normalize_text(
        value,
        field="task_name_base",
        required=False,
        max_len=DEFECT_TASK_NAME_BASE_MAX_LEN,
    )
    return " ".join(text.split())


def _default_defect_task_name_base(report: dict[str, Any]) -> str:
    payload = report if isinstance(report, dict) else {}
    display_id = str(payload.get("display_id") or payload.get("dts_id") or payload.get("report_id") or "").strip()
    summary = str(payload.get("defect_summary") or "").strip()
    if display_id and summary:
        if summary.startswith(display_id):
            return _normalize_defect_task_name_base(summary)
        return _normalize_defect_task_name_base(f"{display_id} {summary}")
    if display_id:
        return _normalize_defect_task_name_base(f"{display_id} 缺陷问题")
    return _normalize_defect_task_name_base(summary or "缺陷问题")


def _resolve_requested_task_name_base(body: dict[str, Any], report: dict[str, Any]) -> str:
    raw = (
        body.get("task_name_base")
        or body.get("taskNameBase")
        or body.get("task_name")
        or body.get("taskName")
        or ""
    )
    explicit = _normalize_defect_task_name_base(raw)
    if explicit:
        return explicit
    return _default_defect_task_name_base(report)


def _defect_stage_title(task_name_base: str, stage_name: str, legacy_title: str) -> str:
    if task_name_base == _DEFECT_LEGACY_CHAIN_NAME_BASE:
        return legacy_title
    return f"{task_name_base} - {stage_name}"


def _active_defect_node_title_map(root: Path, ticket_id: str, node_ids: set[str]) -> dict[str, str]:
    if not ticket_id or not node_ids:
        return {}
    node_records = assignment_service._assignment_load_node_records(root, ticket_id, include_deleted=True)
    out: dict[str, str] = {}
    for row in _assignment_active_rows(node_records):
        node_id = str(row.get("node_id") or "").strip()
        if node_id in node_ids:
            title = str(row.get("node_name") or "").strip()
            if title:
                out[node_id] = title
    return out


def _existing_defect_task_name_base(
    report_key: str,
    *,
    action_kind: str,
    title_map: dict[str, str],
) -> str:
    if not title_map:
        return ""
    legacy_only = False
    for node_id, stage_name, legacy_title in _defect_stage_layout(report_key, action_kind):
        title = str(title_map.get(node_id) or "").strip()
        if not title:
            continue
        if title == legacy_title:
            legacy_only = True
            continue
        matched = _DEFECT_STAGE_TITLE_RE.match(title)
        if matched is None:
            continue
        if str(matched.group("stage") or "").strip() != stage_name:
            continue
        base = str(matched.group("base") or "").strip()
        if base:
            return base
    return _DEFECT_LEGACY_CHAIN_NAME_BASE if legacy_only else ""


def _resolved_defect_task_name_base(
    root: Path,
    *,
    ticket_id: str,
    report_key: str,
    action_kind: str,
    requested_base: str,
) -> str:
    existing_title_map = _active_defect_node_title_map(
        root,
        ticket_id,
        {
            node_id
            for node_id, _stage_name, _legacy_title in _defect_stage_layout(report_key, action_kind)
        },
    )
    existing_base = _existing_defect_task_name_base(
        report_key,
        action_kind=action_kind,
        title_map=existing_title_map,
    )
    if existing_base:
        return existing_base
    return requested_base


def _current_defect_ref_specs(
    root: Path,
    *,
    ticket_id: str,
    node_specs: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    node_ids = {
        str(item.get("node_id") or "").strip()
        for item in list(node_specs or [])
        if str(item.get("node_id") or "").strip()
    }
    current_title_map = _active_defect_node_title_map(root, ticket_id, node_ids)
    return [
        (
            str(item.get("node_id") or "").strip(),
            str(current_title_map.get(str(item.get("node_id") or "").strip()) or item.get("node_name") or "").strip(),
        )
        for item in list(node_specs or [])
        if str(item.get("node_id") or "").strip()
    ]


def _public_defect_task_name_base(task_name_base: str) -> str:
    return "" if str(task_name_base or "").strip() == _DEFECT_LEGACY_CHAIN_NAME_BASE else str(task_name_base or "").strip()


def _process_node_specs(report_key: str, assignee: str, priority_label: str, task_name_base: str) -> list[dict[str, Any]]:
    analyze_node_id = f"{report_key}-analyze"
    fix_node_id = f"{report_key}-fix"
    return [
        {
            "node_id": analyze_node_id,
            "node_name": _defect_stage_title(task_name_base, "分析", "分析缺陷"),
            "assigned_agent_id": assignee,
            "node_goal": "分析当前缺陷成因、复现条件和修复范围。",
            "expected_artifact": "分析缺陷报告.html",
            "priority": priority_label,
            "delivery_mode": "specified",
            "delivery_receiver_agent_id": assignee,
            "upstream_node_ids": [],
        },
        {
            "node_id": fix_node_id,
            "node_name": _defect_stage_title(task_name_base, "修复", "修复缺陷"),
            "assigned_agent_id": assignee,
            "node_goal": "完成缺陷修复并输出修复说明。",
            "expected_artifact": "缺陷修复说明.html",
            "priority": priority_label,
            "delivery_mode": "specified",
            "delivery_receiver_agent_id": assignee,
            "upstream_node_ids": [analyze_node_id],
        },
        {
            "node_id": f"{report_key}-release",
            "node_name": _defect_stage_title(task_name_base, "推送到目标版本", "推送到目标版本"),
            "assigned_agent_id": assignee,
            "node_goal": "确认修复进入目标版本并产出发布记录。",
            "expected_artifact": "目标版本发布记录.html",
            "priority": priority_label,
            "delivery_mode": "specified",
            "delivery_receiver_agent_id": assignee,
            "upstream_node_ids": [fix_node_id],
        },
    ]


def _review_node_specs(report_key: str, assignee: str, priority_label: str, task_name_base: str) -> list[dict[str, Any]]:
    return [
        {
            "node_id": f"{report_key}-review",
            "node_name": _defect_stage_title(task_name_base, "复核", "复核争议"),
            "assigned_agent_id": assignee,
            "node_goal": "结合补充证据和当前结论完成复核。",
            "expected_artifact": "复核争议结论.html",
            "priority": priority_label,
            "delivery_mode": "specified",
            "delivery_receiver_agent_id": assignee,
            "upstream_node_ids": [],
        }
    ]


def _defect_action_specs(
    report_key: str,
    *,
    action_kind: str,
    assignee: str,
    priority_label: str,
    task_name_base: str,
) -> tuple[str, list[dict[str, Any]], list[tuple[str, str]]]:
    if action_kind == DEFECT_PROCESS_ACTION_KIND:
        node_specs = _process_node_specs(report_key, assignee, priority_label, task_name_base)
    elif action_kind == DEFECT_REVIEW_ACTION_KIND:
        node_specs = _review_node_specs(report_key, assignee, priority_label, task_name_base)
    else:
        raise DefectCenterError(400, "defect action_kind invalid", "defect_action_kind_invalid", {"action_kind": action_kind})
    return (
        f"defect:{action_kind}:{report_key}",
        node_specs,
        [(str(item.get("node_id") or "").strip(), str(item.get("node_name") or "").strip()) for item in node_specs],
    )


def _assignment_active_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in list(rows or [])
        if str(row.get("record_state") or "active").strip().lower() != "deleted"
    ]


def _assignment_metrics(rows: list[dict[str, Any]]) -> dict[str, int]:
    active_rows = _assignment_active_rows(rows)
    running_nodes = sum(1 for row in active_rows if str(row.get("status") or "").strip().lower() == "running")
    executed_count = sum(
        1
        for row in active_rows
        if str(row.get("status") or "").strip().lower() in {"running", "succeeded", "failed"}
    )
    return {
        "active_nodes": len(active_rows),
        "running_nodes": running_nodes,
        "executed_count": executed_count,
    }


def _defect_assignment_repair_signature(root: Path) -> tuple[int, int]:
    max_mtime_ns = 0
    count = 0
    tasks_root = assignment_service._assignment_tasks_root(root)
    if not tasks_root.exists() or not tasks_root.is_dir():
        return (0, 0)
    for path in tasks_root.iterdir():
        if not path.is_dir():
            continue
        count += 1
        graph_path = assignment_service._assignment_graph_record_path(root, str(path.name or "").strip())
        target = graph_path if graph_path.exists() else path
        try:
            max_mtime_ns = max(max_mtime_ns, int(target.stat().st_mtime_ns))
        except Exception:
            continue
    return (count, max_mtime_ns)


def _defect_assignment_repair_fast_signature(root: Path) -> tuple[int, int, int]:
    root_path = Path(root).resolve(strict=False)
    tasks_root = assignment_service._assignment_tasks_root(root_path)
    workflow_db_path = root_path / "state" / "workflow.db"
    tasks_mtime_ns = 0
    task_dir_count = 0
    if tasks_root.exists() and tasks_root.is_dir():
        try:
            tasks_mtime_ns = int(tasks_root.stat().st_mtime_ns)
        except Exception:
            tasks_mtime_ns = 0
        try:
            task_dir_count = sum(1 for path in tasks_root.iterdir() if path.is_dir())
        except Exception:
            task_dir_count = 0
    db_mtime_ns = 0
    if workflow_db_path.exists():
        try:
            db_mtime_ns = int(workflow_db_path.stat().st_mtime_ns)
        except Exception:
            db_mtime_ns = 0
    return (tasks_mtime_ns, task_dir_count, db_mtime_ns)


def _hydrate_legacy_assignment_tickets(
    root: Path,
    *,
    tickets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in list(tickets or []):
        ticket_id = str(item.get("ticket_id") or "").strip()
        task_record = dict(item.get("task_record") or {})
        if not ticket_id or not task_record:
            continue
        if not task_record:
            continue
        if str(task_record.get("record_state") or "active").strip().lower() == "deleted":
            continue
        node_records = assignment_service._assignment_load_node_records(root, ticket_id, include_deleted=True)
        rows.append(
            {
                "ticket_id": ticket_id,
                "task_record": task_record,
                "node_records": node_records,
                "metrics": _assignment_metrics(node_records),
            }
        )
    rows.sort(
        key=lambda item: (
            str((item.get("task_record") or {}).get("updated_at") or ""),
            str((item.get("task_record") or {}).get("created_at") or ""),
            str(item.get("ticket_id") or ""),
        ),
        reverse=True,
    )
    return rows


def _pick_chain_assignee(
    root: Path,
    *,
    global_ticket_id: str,
    legacy_tickets: list[dict[str, Any]],
    node_specs: list[dict[str, Any]],
) -> str:
    wanted_node_ids = {
        str(item.get("node_id") or "").strip()
        for item in list(node_specs or [])
        if str(item.get("node_id") or "").strip()
    }
    for ticket_id in [str(global_ticket_id or "").strip(), *[str(item.get("ticket_id") or "").strip() for item in legacy_tickets]]:
        if not ticket_id:
            continue
        try:
            node_rows = assignment_service._assignment_load_node_records(root, ticket_id, include_deleted=True)
        except Exception:
            continue
        for row in _assignment_active_rows(node_rows):
            node_id = str(row.get("node_id") or "").strip()
            assignee = str(row.get("assigned_agent_id") or "").strip()
            if assignee and (not wanted_node_ids or node_id in wanted_node_ids):
                return assignee
    return _default_assignee(_DefectRootCfg(root))


def _ensure_assignment_chain(
    root: Path,
    *,
    ticket_id: str,
    node_specs: list[dict[str, Any]],
    now_text: str,
    operator: str,
    reason: str,
    preserve_existing_node_names: bool = False,
) -> dict[str, int | bool]:
    task_record = assignment_service._assignment_load_task_record(root, ticket_id)
    node_records = assignment_service._assignment_load_node_records(root, ticket_id, include_deleted=True)
    node_map = {
        str(item.get("node_id") or "").strip(): item
        for item in list(node_records or [])
        if str(item.get("node_id") or "").strip()
    }
    edges = list(task_record.get("edges") or [])
    edge_keys = {
        (str(edge.get("from_node_id") or "").strip(), str(edge.get("to_node_id") or "").strip())
        for edge in list(edges or [])
        if str(edge.get("record_state") or "active").strip().lower() != "deleted"
    }
    changed = False
    created_node_count = 0
    updated_node_count = 0
    revived_node_count = 0
    added_edge_count = 0
    for spec in list(node_specs or []):
        node_id = str(spec.get("node_id") or "").strip()
        if not node_id:
            continue
        priority_value = assignment_service.normalize_assignment_priority(spec.get("priority"), required=True)
        existing = node_map.get(node_id)
        if existing is None:
            node_records.append(
                assignment_service._assignment_build_node_record(
                    ticket_id=ticket_id,
                    node_id=node_id,
                    node_name=str(spec.get("node_name") or "").strip(),
                    source_schedule_id="",
                    planned_trigger_at="",
                    trigger_instance_id="",
                    trigger_rule_summary="",
                    assigned_agent_id=str(spec.get("assigned_agent_id") or "").strip(),
                    assigned_agent_name=str(spec.get("assigned_agent_id") or "").strip(),
                    node_goal=str(spec.get("node_goal") or "").strip(),
                    expected_artifact=str(spec.get("expected_artifact") or "").strip(),
                    delivery_mode=str(spec.get("delivery_mode") or "none").strip().lower() or "none",
                    delivery_receiver_agent_id=str(spec.get("delivery_receiver_agent_id") or "").strip(),
                    delivery_receiver_agent_name=str(spec.get("delivery_receiver_agent_id") or "").strip(),
                    artifact_delivery_status="pending",
                    artifact_delivered_at="",
                    artifact_paths=[],
                    status="pending",
                    priority=priority_value,
                    completed_at="",
                    success_reason="",
                    result_ref="",
                    failure_reason="",
                    created_at=now_text,
                    updated_at=now_text,
                    upstream_node_ids=[
                        str(item or "").strip()
                        for item in list(spec.get("upstream_node_ids") or [])
                        if str(item or "").strip()
                    ],
                    downstream_node_ids=[],
                )
            )
            node_map[node_id] = node_records[-1]
            created_node_count += 1
            changed = True
            continue
        node_changed = False
        if str(existing.get("record_state") or "active").strip().lower() == "deleted":
            existing["record_state"] = "active"
            existing["delete_meta"] = {}
            if not str(existing.get("status") or "").strip():
                existing["status"] = "pending"
            node_changed = True
            revived_node_count += 1
        for key in (
            "node_name",
            "assigned_agent_id",
            "node_goal",
            "expected_artifact",
            "delivery_mode",
            "delivery_receiver_agent_id",
        ):
            if key == "node_name" and preserve_existing_node_names and str(existing.get("node_name") or "").strip():
                continue
            next_value = str(spec.get(key) or "").strip()
            if str(existing.get(key) or "").strip() != next_value:
                existing[key] = next_value
                node_changed = True
        if str(existing.get("assigned_agent_name") or "").strip() != str(spec.get("assigned_agent_id") or "").strip():
            existing["assigned_agent_name"] = str(spec.get("assigned_agent_id") or "").strip()
            node_changed = True
        if str(existing.get("delivery_receiver_agent_name") or "").strip() != str(spec.get("delivery_receiver_agent_id") or "").strip():
            existing["delivery_receiver_agent_name"] = str(spec.get("delivery_receiver_agent_id") or "").strip()
            node_changed = True
        if int(existing.get("priority") or 0) != int(priority_value):
            existing["priority"] = int(priority_value)
            node_changed = True
        if node_changed:
            existing["updated_at"] = now_text
            updated_node_count += 1
            changed = True
    for spec in list(node_specs or []):
        to_node_id = str(spec.get("node_id") or "").strip()
        for from_node_id in list(spec.get("upstream_node_ids") or []):
            pair = (str(from_node_id or "").strip(), to_node_id)
            if not pair[0] or not pair[1] or pair in edge_keys:
                continue
            edges.append(
                {
                    "from_node_id": pair[0],
                    "to_node_id": pair[1],
                    "edge_kind": "depends_on",
                    "created_at": now_text,
                    "record_state": "active",
                }
            )
            edge_keys.add(pair)
            added_edge_count += 1
            changed = True
    if not changed:
        return {
            "changed": False,
            "created_node_count": 0,
            "updated_node_count": 0,
            "revived_node_count": 0,
            "added_edge_count": 0,
        }
    task_record["edges"] = edges
    task_record["updated_at"] = now_text
    task_record, node_records, _changed = assignment_service._assignment_recompute_task_state(
        root,
        task_record=task_record,
        node_records=node_records,
        reconcile_running=False,
    )
    assignment_service._assignment_store_snapshot(root, task_record=task_record, node_records=node_records)
    assignment_service._assignment_write_audit_entry(
        root,
        ticket_id=ticket_id,
        node_id="",
        action="repair_defect_chain",
        operator=operator,
        reason=reason,
        target_status=str(task_record.get("scheduler_state") or "idle").strip().lower() or "idle",
        detail={
            "created_node_count": created_node_count,
            "updated_node_count": updated_node_count,
            "revived_node_count": revived_node_count,
            "added_edge_count": added_edge_count,
            "node_ids": [str(item.get("node_id") or "").strip() for item in list(node_specs or [])],
        },
        created_at=now_text,
    )
    return {
        "changed": True,
        "created_node_count": created_node_count,
        "updated_node_count": updated_node_count,
        "revived_node_count": revived_node_count,
        "added_edge_count": added_edge_count,
    }


def _mark_assignment_graph_deleted(
    root: Path,
    *,
    ticket_id: str,
    now_text: str,
    reason: str,
    detail: dict[str, Any],
) -> bool:
    task_record = assignment_service._assignment_load_task_record(root, ticket_id)
    if str(task_record.get("record_state") or "active").strip().lower() == "deleted":
        return False
    node_records = assignment_service._assignment_load_node_records(root, ticket_id, include_deleted=True)
    task_record["record_state"] = "deleted"
    task_record["deleted_at"] = now_text
    task_record["deleted_reason"] = reason
    task_record["updated_at"] = now_text
    for node in list(node_records or []):
        if str(node.get("record_state") or "active").strip().lower() == "deleted":
            continue
        node["record_state"] = "deleted"
        node["delete_meta"] = {
            "delete_action": "repair_defect_chain",
            "deleted_at": now_text,
            "delete_reason": reason,
            "repair_detail": detail,
        }
        node["updated_at"] = now_text
    assignment_service._assignment_store_snapshot(root, task_record=task_record, node_records=node_records)
    assignment_service._assignment_write_audit_entry(
        root,
        ticket_id=ticket_id,
        node_id="",
        action="delete_graph",
        operator="defect-system",
        reason=reason,
        target_status="deleted",
        detail=detail,
        created_at=now_text,
    )
    return True


def _repair_defect_action_group(
    root: Path,
    *,
    report_row: Any,
    action_kind: str,
    legacy_tickets: list[dict[str, Any]],
    now_text: str,
) -> dict[str, Any]:
    report = _report_row_to_payload(report_row)
    report_id = str(report.get("report_id") or "").strip()
    if not report_id:
        return {"changed": False}
    global_ticket_id = _ensure_defect_assignment_graph(_DefectRootCfg(root))
    initial_priority = str(report.get("task_priority") or "P1").strip() or "P1"
    task_name_base = _resolved_defect_task_name_base(
        root,
        ticket_id=global_ticket_id,
        report_key=report_id,
        action_kind=action_kind,
        requested_base=_default_defect_task_name_base(report),
    )
    _, node_specs, ref_specs = _defect_action_specs(
        report_id,
        action_kind=action_kind,
        assignee="",
        priority_label=initial_priority,
        task_name_base=task_name_base,
    )
    assignee = _pick_chain_assignee(
        root,
        global_ticket_id=global_ticket_id,
        legacy_tickets=legacy_tickets,
        node_specs=node_specs,
    )
    external_request_id, node_specs, ref_specs = _defect_action_specs(
        report_id,
        action_kind=action_kind,
        assignee=assignee,
        priority_label=initial_priority,
        task_name_base=task_name_base,
    )
    chain_result = _ensure_assignment_chain(
        root,
        ticket_id=global_ticket_id,
        node_specs=node_specs,
        now_text=now_text,
        operator="defect-system",
        reason=f"repair defect {action_kind} chain into global graph",
        preserve_existing_node_names=True,
    )
    ref_specs = _current_defect_ref_specs(root, ticket_id=global_ticket_id, node_specs=node_specs)
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        _load_report_row(conn, report_id, include_test_data=True)
        for focus_node_id, title in ref_specs:
            _upsert_task_ref(
                conn,
                report_id,
                ticket_id=global_ticket_id,
                focus_node_id=focus_node_id,
                action_kind=action_kind,
                title=title,
                external_request_id=external_request_id,
                created_at=now_text,
            )
        deleted_legacy_ticket_ids: list[str] = []
        skipped_running_ticket_ids: list[str] = []
        for legacy in list(legacy_tickets or []):
            ticket_id = str(legacy.get("ticket_id") or "").strip()
            if not ticket_id or ticket_id == global_ticket_id:
                continue
            metrics = dict(legacy.get("metrics") or {})
            if int(metrics.get("running_nodes") or 0) > 0:
                skipped_running_ticket_ids.append(ticket_id)
                continue
            detail = {
                "repair_scope": "defect_assignment_chain",
                "report_id": report_id,
                "action_kind": action_kind,
                "canonical_ticket_id": global_ticket_id,
                "superseded_external_request_id": external_request_id,
                "metrics": metrics,
            }
            if _mark_assignment_graph_deleted(
                root,
                ticket_id=ticket_id,
                now_text=now_text,
                reason="legacy defect graph superseded by global graph",
                detail=detail,
            ):
                deleted_legacy_ticket_ids.append(ticket_id)
        if chain_result["changed"] or deleted_legacy_ticket_ids or skipped_running_ticket_ids:
            _append_history(
                conn,
                report_id,
                entry_type="repair",
                actor="defect-system",
                title="已收口历史任务图到任务中心总图",
                detail={
                    "action_kind": action_kind,
                    "ticket_id": global_ticket_id,
                    "external_request_id": external_request_id,
                    "task_priority": initial_priority,
                    "created_node_count": int(chain_result.get("created_node_count") or 0),
                    "updated_node_count": int(chain_result.get("updated_node_count") or 0),
                    "revived_node_count": int(chain_result.get("revived_node_count") or 0),
                    "added_edge_count": int(chain_result.get("added_edge_count") or 0),
                    "deleted_legacy_ticket_ids": deleted_legacy_ticket_ids,
                    "skipped_running_ticket_ids": skipped_running_ticket_ids,
                },
                created_at=now_text,
            )
        conn.commit()
    finally:
        conn.close()
    return {
        "changed": bool(chain_result.get("changed")) or bool(deleted_legacy_ticket_ids),
        "report_id": report_id,
        "action_kind": action_kind,
        "ticket_id": global_ticket_id,
        "external_request_id": external_request_id,
        "task_priority": initial_priority,
        "created_node_count": int(chain_result.get("created_node_count") or 0),
        "updated_node_count": int(chain_result.get("updated_node_count") or 0),
        "deleted_legacy_ticket_ids": deleted_legacy_ticket_ids,
        "skipped_running_ticket_ids": skipped_running_ticket_ids,
    }


def repair_defect_assignment_state(root: Path) -> dict[str, Any]:
    root_path = Path(root).resolve(strict=False)
    cache_key = root_path.as_posix()
    fast_signature = _defect_assignment_repair_fast_signature(root_path)
    if _DEFECT_ASSIGNMENT_REPAIR_FAST_SIGNATURES.get(cache_key) == fast_signature:
        return {"ok": True, "skipped": True, "repaired_groups": []}
    signature = _defect_assignment_repair_signature(root_path)
    if _DEFECT_ASSIGNMENT_REPAIR_SIGNATURES.get(cache_key) == signature:
        _DEFECT_ASSIGNMENT_REPAIR_FAST_SIGNATURES[cache_key] = fast_signature
        return {"ok": True, "skipped": True, "repaired_groups": []}
    group_keys: set[tuple[str, str]] = set()
    legacy_ticket_map: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for ticket_id in assignment_service._assignment_list_ticket_ids_lightweight(root_path):
        task_record = assignment_service._assignment_load_task_record_lightweight(root_path, ticket_id)
        if not task_record:
            continue
        if str(task_record.get("record_state") or "active").strip().lower() == "deleted":
            continue
        matched = _DEFECT_LEGACY_REQUEST_RE.match(str(task_record.get("external_request_id") or "").strip())
        if matched is None:
            continue
        action_kind, report_id = matched.groups()
        key = (report_id, action_kind)
        group_keys.add(key)
        legacy_ticket_map.setdefault(key, []).append(
            {
                "ticket_id": ticket_id,
                "task_record": dict(task_record),
            }
        )
    conn = connect_db(root_path)
    try:
        ref_rows = conn.execute(
            """
            SELECT DISTINCT report_id,action_kind
            FROM defect_task_refs
            WHERE action_kind IN (?,?)
            """,
            (DEFECT_PROCESS_ACTION_KIND, DEFECT_REVIEW_ACTION_KIND),
        ).fetchall()
        for row in ref_rows:
            report_id = str(row["report_id"] or "").strip()
            action_kind = str(row["action_kind"] or "").strip()
            if report_id and action_kind:
                group_keys.add((report_id, action_kind))
        report_row_map = {
            str(row["report_id"] or "").strip(): row
            for row in conn.execute("SELECT * FROM defect_reports").fetchall()
            if str(row["report_id"] or "").strip()
        }
    finally:
        conn.close()
    repaired_groups: list[dict[str, Any]] = []
    for report_id, action_kind in sorted(group_keys):
        report_row = report_row_map.get(report_id)
        if report_row is None:
            continue
        result = _repair_defect_action_group(
            root_path,
            report_row=report_row,
            action_kind=action_kind,
            legacy_tickets=_hydrate_legacy_assignment_tickets(
                root_path,
                tickets=legacy_ticket_map.get((report_id, action_kind), []),
            ),
            now_text=_now_text(),
        )
        if result.get("changed"):
            repaired_groups.append(result)
    _DEFECT_ASSIGNMENT_REPAIR_SIGNATURES[cache_key] = _defect_assignment_repair_signature(root_path)
    _DEFECT_ASSIGNMENT_REPAIR_FAST_SIGNATURES[cache_key] = _defect_assignment_repair_fast_signature(root_path)
    return {"ok": True, "skipped": False, "repaired_groups": repaired_groups}


def create_defect_process_task(
    cfg: Any,
    report_id: str,
    body: dict[str, Any],
    *,
    include_test_data: bool = True,
) -> dict[str, Any]:
    root = Path(cfg.root)
    _ensure_defect_tables(root)
    report_key = _require_report_id(report_id)
    operator = _normalize_text(body.get("operator") or "web-user", field="operator", required=False, max_len=120) or "web-user"
    auto_queue = str(body.get("auto_queue") or "").strip().lower() in {"1", "true", "yes", "on"}
    assignee = _normalize_text(body.get("assigned_agent_id") or body.get("assignedAgentId") or _default_assignee(cfg), field="assigned_agent_id", required=True, max_len=120)
    now_text = _now_text()
    external_request_id = f"defect:process:{report_key}"
    if not auto_queue:
        gate = _defect_manual_task_gate(root, report_key, include_test_data=include_test_data)
        if not bool(gate.get("allowed")):
            raise DefectCenterError(
                409,
                "defect queue gate blocked manual task creation",
                "defect_queue_gate_blocked",
                gate,
            )
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        row = _load_report_row(conn, report_key, include_test_data=include_test_data)
        if not bool(row["is_formal"]):
            raise DefectCenterError(409, "not a formal defect yet", "defect_process_requires_formal")
        report = _report_row_to_payload(row)
        priority_label = str(report.get("task_priority") or "P1").strip() or "P1"
        requested_task_name_base = _resolve_requested_task_name_base(body, report)
        conn.commit()
    finally:
        conn.close()
    ticket_id = _ensure_defect_assignment_graph(cfg)
    task_name_base = _resolved_defect_task_name_base(
        root,
        ticket_id=ticket_id,
        report_key=report_key,
        action_kind=DEFECT_PROCESS_ACTION_KIND,
        requested_base=requested_task_name_base,
    )
    _external_request_id, node_specs, _ref_specs = _defect_action_specs(
        report_key,
        action_kind=DEFECT_PROCESS_ACTION_KIND,
        assignee=assignee,
        priority_label=priority_label,
        task_name_base=task_name_base,
    )
    chain_result = _ensure_assignment_chain(
        root,
        ticket_id=ticket_id,
        node_specs=node_specs,
        now_text=now_text,
        operator="defect-center",
        reason="ensure defect process chain on global graph",
        preserve_existing_node_names=True,
    )
    created_node_count = int(chain_result.get("created_node_count") or 0)
    ref_specs = _current_defect_ref_specs(root, ticket_id=ticket_id, node_specs=node_specs)
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        _load_report_row(conn, report_key, include_test_data=include_test_data)
        for focus_node_id, title in ref_specs:
            _upsert_task_ref(
                conn,
                report_key,
                ticket_id=ticket_id,
                focus_node_id=focus_node_id,
                action_kind=DEFECT_PROCESS_ACTION_KIND,
                title=title,
                external_request_id=external_request_id,
                created_at=now_text,
            )
        _append_history(
            conn,
            report_key,
            entry_type="task",
            actor=operator,
            title="已在任务中心创建处理任务",
            detail={
                "ticket_id": ticket_id,
                "external_request_id": external_request_id,
                "graph_name": DEFECT_ASSIGNMENT_GRAPH_NAME,
                "assigned_agent_id": assignee,
                "task_priority": priority_label,
                "created_node_count": created_node_count,
                "auto_queue": auto_queue,
                "task_name_base": _public_defect_task_name_base(task_name_base),
            },
            created_at=now_text,
        )
        conn.execute("UPDATE defect_reports SET updated_at=? WHERE report_id=?", (now_text, report_key))
        conn.commit()
    finally:
        conn.close()
    detail = get_defect_detail(root, report_key, include_test_data=include_test_data)
    detail["created_task_ticket_id"] = ticket_id
    detail["external_request_id"] = external_request_id
    detail["task_name_base"] = _public_defect_task_name_base(task_name_base)
    return detail


def create_defect_review_task(
    cfg: Any,
    report_id: str,
    body: dict[str, Any],
    *,
    include_test_data: bool = True,
) -> dict[str, Any]:
    root = Path(cfg.root)
    _ensure_defect_tables(root)
    report_key = _require_report_id(report_id)
    operator = _normalize_text(body.get("operator") or "web-user", field="operator", required=False, max_len=120) or "web-user"
    auto_queue = str(body.get("auto_queue") or "").strip().lower() in {"1", "true", "yes", "on"}
    assignee = _normalize_text(body.get("assigned_agent_id") or body.get("assignedAgentId") or _default_assignee(cfg), field="assigned_agent_id", required=True, max_len=120)
    now_text = _now_text()
    external_request_id = f"defect:review:{report_key}"
    review_node_id = f"{report_key}-review"
    if not auto_queue:
        gate = _defect_manual_task_gate(root, report_key, include_test_data=include_test_data)
        if not bool(gate.get("allowed")):
            raise DefectCenterError(
                409,
                "defect queue gate blocked manual review creation",
                "defect_queue_gate_blocked",
                gate,
            )
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        row = _load_report_row(conn, report_key, include_test_data=include_test_data)
        payload = _report_row_to_payload(row)
        priority_label = str(payload.get("task_priority") or "P1").strip() or "P1"
        requested_task_name_base = _resolve_requested_task_name_base(body, payload)
        if str(row["status"] or "").strip().lower() != DEFECT_STATUS_DISPUTE:
            current_decision = _json_loads_object(row["current_decision_json"])
            current_decision.update(
                {
                    "decision": "dispute",
                    "decision_source": str(current_decision.get("decision_source") or "review_request").strip() or "review_request",
                    "title": "用户已提出分歧",
                    "summary": "已进入复核链路。",
                }
            )
            discovered_iteration = str(row["discovered_iteration"] or "").strip() or _runtime_version_label()
            _write_report_update(
                conn,
                report_key,
                status=DEFECT_STATUS_DISPUTE,
                discovered_iteration=discovered_iteration,
                current_decision=current_decision,
                updated_at=now_text,
            )
        conn.commit()
    finally:
        conn.close()
    ticket_id = _ensure_defect_assignment_graph(cfg)
    task_name_base = _resolved_defect_task_name_base(
        root,
        ticket_id=ticket_id,
        report_key=report_key,
        action_kind=DEFECT_REVIEW_ACTION_KIND,
        requested_base=requested_task_name_base,
    )
    _external_request_id, node_specs, _ref_specs = _defect_action_specs(
        report_key,
        action_kind=DEFECT_REVIEW_ACTION_KIND,
        assignee=assignee,
        priority_label=priority_label,
        task_name_base=task_name_base,
    )
    chain_result = _ensure_assignment_chain(
        root,
        ticket_id=ticket_id,
        node_specs=node_specs,
        now_text=now_text,
        operator="defect-center",
        reason="ensure defect review chain on global graph",
        preserve_existing_node_names=True,
    )
    created_node_count = int(chain_result.get("created_node_count") or 0)
    ref_specs = _current_defect_ref_specs(root, ticket_id=ticket_id, node_specs=node_specs)
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        _load_report_row(conn, report_key, include_test_data=include_test_data)
        _upsert_task_ref(
            conn,
            report_key,
            ticket_id=ticket_id,
            focus_node_id=review_node_id,
            action_kind=DEFECT_REVIEW_ACTION_KIND,
            title=str(ref_specs[0][1] if ref_specs else "").strip() or "复核争议",
            external_request_id=external_request_id,
            created_at=now_text,
        )
        _append_history(
            conn,
            report_key,
            entry_type="task",
            actor=operator,
            title="已在任务中心创建复核任务",
            detail={
                "ticket_id": ticket_id,
                "external_request_id": external_request_id,
                "graph_name": DEFECT_ASSIGNMENT_GRAPH_NAME,
                "assigned_agent_id": assignee,
                "status_text": _status_text(DEFECT_STATUS_DISPUTE),
                "task_priority": priority_label,
                "created_node_count": created_node_count,
                "auto_queue": auto_queue,
                "task_name_base": _public_defect_task_name_base(task_name_base),
            },
            created_at=now_text,
        )
        conn.execute("UPDATE defect_reports SET updated_at=? WHERE report_id=?", (now_text, report_key))
        conn.commit()
    finally:
        conn.close()
    detail = get_defect_detail(root, report_key, include_test_data=include_test_data)
    detail["created_task_ticket_id"] = ticket_id
    detail["external_request_id"] = external_request_id
    detail["task_name_base"] = _public_defect_task_name_base(task_name_base)
    return detail
