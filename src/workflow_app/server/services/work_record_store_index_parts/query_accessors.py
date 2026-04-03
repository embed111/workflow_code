def _ordered_relpaths(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> list[str]:
    rows = conn.execute(sql, params).fetchall()
    out: list[str] = []
    for row in rows:
        relpath = str(row["relpath"] or "").strip()
        if relpath:
            out.append(relpath)
    return out


def _load_json_records_by_relpaths(root: Path, relpaths: list[str]) -> list[dict[str, Any]]:
    base = _store.artifact_root(root)
    rows: list[dict[str, Any]] = []
    for relpath in relpaths:
        payload = _store._load_json_dict(base / relpath)
        if payload:
            rows.append(payload)
    return rows


def list_session_records_from_index(root: Path, *, include_test_data: bool, limit: int) -> list[dict[str, Any]]:
    ensure_sqlite_index(root)
    conn = _connect(root)
    try:
        relpaths = _ordered_relpaths(
            conn,
            """
            SELECT session_relpath AS relpath
            FROM session_index
            WHERE (? = 1 OR is_test_data = 0)
            ORDER BY
                CASE WHEN status='active' THEN 0 ELSE 1 END,
                last_message_at DESC,
                session_id DESC
            LIMIT ?
            """,
            (1 if include_test_data else 0, max(1, min(int(limit), 2000))),
        )
    finally:
        conn.close()
    return _load_json_records_by_relpaths(root, relpaths)


def list_analysis_records_from_index(root: Path) -> list[dict[str, Any]]:
    ensure_sqlite_index(root)
    conn = _connect(root)
    try:
        relpaths = _ordered_relpaths(
            conn,
            "SELECT analysis_relpath AS relpath FROM analysis_index ORDER BY created_at ASC, analysis_id ASC",
            (),
        )
    finally:
        conn.close()
    return _load_json_records_by_relpaths(root, relpaths)


def list_workflow_records_from_index(root: Path) -> list[dict[str, Any]]:
    ensure_sqlite_index(root)
    conn = _connect(root)
    try:
        relpaths = _ordered_relpaths(
            conn,
            "SELECT workflow_relpath AS relpath FROM analysis_index WHERE workflow_relpath <> '' ORDER BY created_at ASC, analysis_id ASC",
            (),
        )
    finally:
        conn.close()
    return _load_json_records_by_relpaths(root, relpaths)


def list_task_run_records_from_index(root: Path, *, session_id: str, limit: int) -> list[dict[str, Any]]:
    ensure_sqlite_index(root)
    conn = _connect(root)
    try:
        relpaths = _ordered_relpaths(
            conn,
            """
            SELECT run_relpath AS relpath
            FROM task_run_index
            WHERE (? = '' OR session_id = ?)
            ORDER BY created_at DESC, task_id DESC
            LIMIT ?
            """,
            (str(session_id or ""), str(session_id or ""), max(1, min(int(limit), 2000))),
        )
    finally:
        conn.close()
    return _load_json_records_by_relpaths(root, relpaths)


def list_policy_patch_task_records_from_index(root: Path, *, limit: int) -> list[dict[str, Any]]:
    ensure_sqlite_index(root)
    conn = _connect(root)
    try:
        relpaths = _ordered_relpaths(
            conn,
            """
            SELECT source_relpath AS relpath
            FROM audit_index
            WHERE audit_type='policy_patch_task'
            ORDER BY created_at DESC, audit_key DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 2000)),),
        )
    finally:
        conn.close()
    return _load_json_records_by_relpaths(root, relpaths)


def list_ingress_request_records_from_index(root: Path, *, limit: int = 0) -> list[dict[str, Any]]:
    ensure_sqlite_index(root)
    conn = _connect(root)
    try:
        sql = """
            SELECT request_id,session_id,route,created_at,event_logged,source_relpath
            FROM ingress_request_index
            ORDER BY created_at ASC, request_id ASC
        """
        params: tuple[Any, ...] = ()
        if int(limit or 0) > 0:
            sql += " LIMIT ?"
            params = (max(1, min(int(limit), 200000)),)
        rows = conn.execute(sql, params).fetchall()
        return [
            {
                "request_id": str(row["request_id"] or ""),
                "session_id": str(row["session_id"] or ""),
                "route": str(row["route"] or ""),
                "created_at": str(row["created_at"] or ""),
                "event_logged": int(row["event_logged"] or 0),
                "source_relpath": str(row["source_relpath"] or ""),
            }
            for row in rows
        ]
    finally:
        conn.close()


def pending_counts_from_index(root: Path, *, include_test_data: bool) -> tuple[int, int]:
    ensure_sqlite_index(root)
    conn = _connect(root)
    try:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN a.status='pending' THEN 1 ELSE 0 END), 0) AS pending_analysis,
                COALESCE(SUM(CASE WHEN a.training_status='pending' THEN 1 ELSE 0 END), 0) AS pending_training
            FROM analysis_index a
            LEFT JOIN session_index s ON s.session_id = a.session_id
            WHERE (? = 1 OR COALESCE(s.is_test_data, 0) = 0)
            """,
            (1 if include_test_data else 0,),
        ).fetchone()
        return (
            int((row or {"pending_analysis": 0})["pending_analysis"] or 0),
            int((row or {"pending_training": 0})["pending_training"] or 0),
        )
    finally:
        conn.close()


def latest_results_from_index(root: Path, *, include_test_data: bool) -> tuple[str, str]:
    ensure_sqlite_index(root)
    conn = _connect(root)
    try:
        latest_analysis = conn.execute(
            """
            SELECT a.analysis_id,a.decision,a.status
            FROM analysis_index a
            LEFT JOIN session_index s ON s.session_id = a.session_id
            WHERE a.decision <> ''
              AND (? = 1 OR COALESCE(s.is_test_data, 0) = 0)
            ORDER BY a.updated_at DESC, a.analysis_id DESC
            LIMIT 1
            """,
            (1 if include_test_data else 0,),
        ).fetchone()
        latest_training = conn.execute(
            """
            SELECT a.training_id,a.training_status
            FROM analysis_index a
            LEFT JOIN session_index s ON s.session_id = a.session_id
            WHERE a.training_id <> ''
              AND (? = 1 OR COALESCE(s.is_test_data, 0) = 0)
            ORDER BY a.updated_at DESC, a.analysis_id DESC
            LIMIT 1
            """,
            (1 if include_test_data else 0,),
        ).fetchone()
    finally:
        conn.close()
    return (
        (
            f"{latest_analysis['analysis_id']}:{latest_analysis['decision']}({latest_analysis['status']})"
            if latest_analysis
            else "none"
        ),
        (
            f"{latest_training['training_id']}:{latest_training['training_status']}"
            if latest_training
            else "none"
        ),
    )


def new_sessions_24h_from_index(
    root: Path,
    *,
    include_test_data: bool,
    since: str,
    routes: tuple[str, ...],
) -> int:
    route_values = tuple(str(item or "").strip() for item in routes if str(item or "").strip())
    if not route_values:
        return 0
    ensure_sqlite_index(root)
    conn = _connect(root)
    try:
        marks = ",".join("?" for _ in route_values)
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT i.session_id) AS session_count
            FROM ingress_request_index i
            LEFT JOIN session_index s ON s.session_id = i.session_id
            WHERE i.event_logged = 1
              AND i.session_id <> ''
              AND i.created_at >= ?
              AND i.route IN ("""
            + marks
            + """)
              AND (? = 1 OR COALESCE(s.is_test_data, 0) = 0)
            """,
            (str(since or ""), *route_values, 1 if include_test_data else 0),
        ).fetchone()
        return int((row or {"session_count": 0})["session_count"] or 0)
    finally:
        conn.close()


def policy_closure_stats_from_index(root: Path) -> dict[str, Any]:
    ensure_sqlite_index(root)
    conn = _connect(root)
    try:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN audit_type='policy_confirmation' THEN 1 ELSE 0 END), 0) AS fallback_triggered,
                COALESCE(SUM(CASE WHEN audit_type='policy_confirmation' AND action='reject' THEN 1 ELSE 0 END), 0) AS rejected_confirmations,
                COALESCE(SUM(CASE WHEN audit_type='policy_confirmation' AND manual_fallback=1 THEN 1 ELSE 0 END), 0) AS manual_fallback_triggered,
                COALESCE(SUM(CASE WHEN audit_type='policy_patch_task' THEN 1 ELSE 0 END), 0) AS patch_task_total,
                COALESCE(SUM(CASE WHEN audit_type='policy_patch_task' AND status='done' THEN 1 ELSE 0 END), 0) AS patch_task_done
            FROM audit_index
            """
        ).fetchone()
        sessions_row = conn.execute("SELECT COUNT(1) AS session_count FROM session_index").fetchone()
    finally:
        conn.close()
    triggered = int((row or {"fallback_triggered": 0})["fallback_triggered"] or 0)
    rejected = int((row or {"rejected_confirmations": 0})["rejected_confirmations"] or 0)
    manual = int((row or {"manual_fallback_triggered": 0})["manual_fallback_triggered"] or 0)
    patch_total = int((row or {"patch_task_total": 0})["patch_task_total"] or 0)
    patch_done = int((row or {"patch_task_done": 0})["patch_task_done"] or 0)
    created_sessions = int((sessions_row or {"session_count": 0})["session_count"] or 0)
    denominator = max(1, created_sessions + rejected)
    return {
        "fallback_triggered": triggered,
        "fallback_trigger_rate_pct": round((triggered / denominator) * 100.0, 2),
        "manual_fallback_triggered": manual,
        "manual_fallback_rate_pct": round((manual / denominator) * 100.0, 2),
        "manual_fallback_usage_alert": bool((manual / denominator) >= 0.3),
        "patch_task_total": patch_total,
        "patch_task_done": patch_done,
        "patch_completion_rate_pct": round((patch_done / max(1, patch_total)) * 100.0, 2) if patch_total else 0.0,
        "created_sessions": created_sessions,
        "rejected_confirmations": rejected,
    }


def find_analysis_id_for_run(root: Path, analysis_run_id: str) -> str:
    run_id = str(analysis_run_id or "").strip()
    if not run_id:
        return ""
    ensure_sqlite_index(root)
    conn = _connect(root)
    try:
        row = conn.execute(
            "SELECT analysis_id FROM analysis_run_index WHERE analysis_run_id=?",
            (run_id,),
        ).fetchone()
        return str(row["analysis_id"] or "") if row else ""
    finally:
        conn.close()


def find_analysis_id_by_workflow_id(root: Path, workflow_id: str) -> str:
    workflow_id_text = str(workflow_id or "").strip()
    if not workflow_id_text:
        return ""
    ensure_sqlite_index(root)
    conn = _connect(root)
    try:
        row = conn.execute(
            "SELECT analysis_id FROM analysis_index WHERE workflow_id=?",
            (workflow_id_text,),
        ).fetchone()
        return str(row["analysis_id"] or "") if row else ""
    finally:
        conn.close()


def latest_analysis_run_record_from_index(root: Path, analysis_id: str) -> dict[str, Any] | None:
    analysis_id_text = str(analysis_id or "").strip()
    if not analysis_id_text:
        return None
    ensure_sqlite_index(root)
    conn = _connect(root)
    try:
        row = conn.execute(
            """
            SELECT analysis_run_relpath
            FROM analysis_run_index
            WHERE analysis_id=?
            ORDER BY created_at DESC, analysis_run_id DESC
            LIMIT 1
            """,
            (analysis_id_text,),
        ).fetchone()
        relpath = str(row["analysis_run_relpath"] or "") if row else ""
    finally:
        conn.close()
    if not relpath:
        return None
    payload = _store._load_json_dict(_store.artifact_root(root) / relpath)
    return payload or None
