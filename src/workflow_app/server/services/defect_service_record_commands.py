from __future__ import annotations

from pathlib import Path
from typing import Any

from .defect_service_prejudge import prejudge_defect_report
from .defect_service import (
    DEFECT_ALL_STATUSES,
    DEFECT_STATUS_CLOSED,
    DEFECT_STATUS_DISPUTE,
    DEFECT_STATUS_NOT_FORMAL,
    DEFECT_STATUS_RESOLVED,
    DEFECT_STATUS_UNRESOLVED,
    DefectCenterError,
    _append_history,
    _bool_flag,
    _defect_report_id,
    _derive_summary,
    _ensure_defect_tables,
    _formalize_report_if_needed,
    _json_dumps,
    _load_report_row,
    _next_dts_identity,
    _normalize_image_evidence,
    _normalize_reported_at,
    _normalize_task_priority,
    _resolve_task_priority_truth,
    _normalize_text,
    _now_text,
    _report_row_to_payload,
    _require_report_id,
    _runtime_version_label,
    _status_text,
    _write_report_update,
    connect_db,
    get_defect_detail,
)


def create_defect_report(cfg: Any, body: dict[str, Any]) -> dict[str, Any]:
    root = Path(cfg.root)
    _ensure_defect_tables(root)
    report_text = _normalize_text(body.get("report_text") or body.get("reportText"), field="report_text", required=True)
    images = _normalize_image_evidence(body.get("evidence_images") or body.get("evidenceImages") or [])
    summary = _derive_summary(body.get("defect_summary") or body.get("defectSummary"), report_text)
    operator = _normalize_text(body.get("operator") or "web-user", field="operator", required=False, max_len=120) or "web-user"
    report_source = _normalize_text(body.get("report_source") or body.get("reportSource") or "workflow-ui", field="report_source", required=False, max_len=120) or "workflow-ui"
    automation_context = body.get("automation_context") or body.get("automationContext") or {}
    if not isinstance(automation_context, dict):
        automation_context = {}
    is_test_data = _bool_flag(body.get("is_test_data") or body.get("isTestData"))
    now_text = _now_text()
    report_id = _defect_report_id()
    decision = prejudge_defect_report(summary, report_text, images)
    status = DEFECT_STATUS_UNRESOLVED if decision["decision"] == "defect" else DEFECT_STATUS_NOT_FORMAL
    is_formal = decision["decision"] == "defect"
    task_priority, task_priority_source = _resolve_task_priority_truth(
        explicit_value=body.get("task_priority") or body.get("taskPriority"),
        defect_summary=summary,
        report_text=report_text,
        decision=decision,
        status=status,
        strict=True,
    )
    reported_at = _normalize_reported_at(body.get("reported_at") or body.get("reportedAt"), fallback=now_text)
    dts_id = ""
    dts_sequence = 0
    discovered_iteration = ""
    if is_formal:
        conn_for_seq = connect_db(root)
        try:
            dts_sequence, dts_id = _next_dts_identity(conn_for_seq)
        finally:
            conn_for_seq.close()
        discovered_iteration = _runtime_version_label()
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        conn.execute(
            """
            INSERT INTO defect_reports(
                report_id,dts_id,dts_sequence,defect_summary,report_text,evidence_images_json,
                task_priority,reported_at,is_formal,status,discovered_iteration,resolved_version,current_decision_json,
                report_source,automation_context_json,is_test_data,created_at,updated_at
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                report_id,
                dts_id,
                dts_sequence,
                summary,
                report_text,
                _json_dumps(images, "[]"),
                task_priority,
                reported_at,
                1 if is_formal else 0,
                status,
                discovered_iteration,
                "",
                _json_dumps({**decision, "decided_at": now_text}, "{}"),
                report_source,
                _json_dumps(automation_context, "{}"),
                1 if is_test_data else 0,
                now_text,
                now_text,
            ),
        )
        _append_history(
            conn,
            report_id,
            entry_type="submitted",
            actor=operator,
            title="用户提交缺陷记录",
            detail={
                "defect_summary": summary,
                "task_priority": task_priority,
                "task_priority_source": task_priority_source,
                "reported_at": reported_at,
                "report_source": report_source,
                "image_count": len(images),
                "automation_context": automation_context,
            },
            created_at=now_text,
        )
        _append_history(
            conn,
            report_id,
            entry_type="decision",
            actor="workflow agent",
            title=str(decision["title"]),
            detail=dict(decision),
            created_at=now_text,
        )
        conn.commit()
    finally:
        conn.close()
    return get_defect_detail(root, report_id, include_test_data=True)


def append_defect_text(
    cfg: Any,
    report_id: str,
    body: dict[str, Any],
    *,
    include_test_data: bool = True,
) -> dict[str, Any]:
    root = Path(cfg.root)
    _ensure_defect_tables(root)
    report_key = _require_report_id(report_id)
    text = _normalize_text(body.get("text") or body.get("report_text") or body.get("reportText"), field="text", required=True)
    operator = _normalize_text(body.get("operator") or "web-user", field="operator", required=False, max_len=120) or "web-user"
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        _load_report_row(conn, report_key, include_test_data=include_test_data)
        _append_history(
            conn,
            report_key,
            entry_type="supplement_text",
            actor=operator,
            title="补充文字说明",
            detail={"text": text},
        )
        conn.execute("UPDATE defect_reports SET updated_at=? WHERE report_id=?", (_now_text(), report_key))
        conn.commit()
    finally:
        conn.close()
    return get_defect_detail(root, report_key, include_test_data=include_test_data)


def append_defect_images(
    cfg: Any,
    report_id: str,
    body: dict[str, Any],
    *,
    include_test_data: bool = True,
) -> dict[str, Any]:
    root = Path(cfg.root)
    _ensure_defect_tables(root)
    report_key = _require_report_id(report_id)
    images = _normalize_image_evidence(body.get("evidence_images") or body.get("evidenceImages") or [])
    if not images:
        raise DefectCenterError(400, "evidence_images required", "defect_evidence_images_required")
    operator = _normalize_text(body.get("operator") or "web-user", field="operator", required=False, max_len=120) or "web-user"
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        _load_report_row(conn, report_key, include_test_data=include_test_data)
        _append_history(
            conn,
            report_key,
            entry_type="supplement_images",
            actor=operator,
            title="补充图片证据",
            detail={"images": images, "image_count": len(images)},
        )
        conn.execute("UPDATE defect_reports SET updated_at=? WHERE report_id=?", (_now_text(), report_key))
        conn.commit()
    finally:
        conn.close()
    return get_defect_detail(root, report_key, include_test_data=include_test_data)


def mark_defect_dispute(
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
    reason = _normalize_text(body.get("reason") or body.get("review_text") or body.get("reviewText"), field="reason", required=False)
    now_text = _now_text()
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        row = _load_report_row(conn, report_key, include_test_data=include_test_data)
        dts_sequence, dts_id = _next_dts_identity(conn) if not str(row["dts_id"] or "").strip() else (int(row["dts_sequence"] or 0), str(row["dts_id"] or "").strip())
        discovered_iteration = str(row["discovered_iteration"] or "").strip() or _runtime_version_label()
        if not str(row["dts_id"] or "").strip():
            conn.execute("UPDATE defect_reports SET dts_sequence=?, dts_id=? WHERE report_id=?", (dts_sequence, dts_id, report_key))
        current_decision = _report_row_to_payload(row)["current_decision"]
        current_decision.update(
            {
                "decision_source": str(current_decision.get("decision_source") or "user_dispute").strip() or "user_dispute",
                "decision": "dispute",
                "title": "用户已提出分歧",
                "summary": reason or "用户不同意当前结论，已转入复核链路。",
                "disputed_at": now_text,
            }
        )
        _write_report_update(
            conn,
            report_key,
            status=DEFECT_STATUS_DISPUTE,
            discovered_iteration=discovered_iteration,
            current_decision=current_decision,
            updated_at=now_text,
        )
        _append_history(
            conn,
            report_key,
            entry_type="status",
            actor=operator,
            title="当前记录转为有分歧",
            detail={
                "status": DEFECT_STATUS_DISPUTE,
                "status_text": _status_text(DEFECT_STATUS_DISPUTE),
                "reason": reason,
                "dts_id": dts_id,
                "dts_sequence": dts_sequence,
                "discovered_iteration": discovered_iteration,
            },
            created_at=now_text,
        )
        conn.commit()
    finally:
        conn.close()
    return get_defect_detail(root, report_key, include_test_data=include_test_data)


def write_defect_resolved_version(
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
    resolved_version = _normalize_text(
        body.get("resolved_version") or body.get("resolvedVersion") or _runtime_version_label(),
        field="resolved_version",
        required=True,
        max_len=120,
    )
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        _load_report_row(conn, report_key, include_test_data=include_test_data)
        _formalize_report_if_needed(
            conn,
            report_key,
            actor=operator,
            decision_title="已转为正式缺陷",
            decision_summary="已具备版本回写条件。",
        )
        _write_report_update(
            conn,
            report_key,
            status=DEFECT_STATUS_RESOLVED,
            resolved_version=resolved_version,
            updated_at=_now_text(),
        )
        _append_history(
            conn,
            report_key,
            entry_type="resolved_version",
            actor=operator,
            title="写回解决版本",
            detail={"resolved_version": resolved_version},
        )
        conn.commit()
    finally:
        conn.close()
    return get_defect_detail(root, report_key, include_test_data=include_test_data)


def update_defect_status(
    cfg: Any,
    report_id: str,
    body: dict[str, Any],
    *,
    include_test_data: bool = True,
) -> dict[str, Any]:
    root = Path(cfg.root)
    _ensure_defect_tables(root)
    report_key = _require_report_id(report_id)
    status = str(body.get("status") or "").strip().lower()
    if status not in DEFECT_ALL_STATUSES:
        raise DefectCenterError(400, "status invalid", "defect_status_invalid", {"status": status})
    operator = _normalize_text(body.get("operator") or "web-user", field="operator", required=False, max_len=120) or "web-user"
    reason = _normalize_text(body.get("reason") or body.get("comment") or "", field="reason", required=False)
    now_text = _now_text()
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        row = _load_report_row(conn, report_key, include_test_data=include_test_data)
        if status in {DEFECT_STATUS_UNRESOLVED, DEFECT_STATUS_RESOLVED, DEFECT_STATUS_CLOSED} and not bool(row["is_formal"]):
            _formalize_report_if_needed(
                conn,
                report_key,
                actor=operator,
                decision_title="已转为正式缺陷",
                decision_summary=reason or "已进入正式缺陷状态机。",
            )
        if status == DEFECT_STATUS_RESOLVED:
            resolved_version = _normalize_text(
                body.get("resolved_version") or body.get("resolvedVersion") or str(row["resolved_version"] or "").strip() or _runtime_version_label(),
                field="resolved_version",
                required=True,
                max_len=120,
            )
        else:
            resolved_version = None
        _write_report_update(
            conn,
            report_key,
            status=status,
            resolved_version=resolved_version,
            updated_at=now_text,
        )
        _append_history(
            conn,
            report_key,
            entry_type="status",
            actor=operator,
            title="状态更新为" + _status_text(status),
            detail={"status": status, "status_text": _status_text(status), "reason": reason, "resolved_version": resolved_version or ""},
            created_at=now_text,
        )
        conn.commit()
    finally:
        conn.close()
    return get_defect_detail(root, report_key, include_test_data=include_test_data)
