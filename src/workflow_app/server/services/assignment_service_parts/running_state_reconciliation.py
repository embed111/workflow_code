def _parse_assignment_iso_datetime(raw: Any) -> Any:
    text = str(raw or "").strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        from datetime import datetime

        return datetime.fromisoformat(normalized)
    except Exception:
        return None


def _assignment_process_pid_is_live(raw_pid: Any) -> bool:
    try:
        pid = int(raw_pid or 0)
    except Exception:
        return False
    if pid <= 0:
        return False
    if str(os.name or "").lower() == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            process_handle = kernel32.OpenProcess(0x1000, False, pid)
            if not process_handle:
                last_error = int(ctypes.get_last_error() or 0)
                if last_error == 5:
                    return True
                if last_error in {87, 1168}:
                    return False
                raise OSError(last_error, "OpenProcess failed")
            try:
                exit_code = ctypes.c_ulong()
                if kernel32.GetExitCodeProcess(process_handle, ctypes.byref(exit_code)) == 0:
                    last_error = int(ctypes.get_last_error() or 0)
                    if last_error == 5:
                        return True
                    if last_error in {87, 1168}:
                        return False
                    raise OSError(last_error, "GetExitCodeProcess failed")
                return int(exit_code.value) == 259
            finally:
                kernel32.CloseHandle(process_handle)
        except Exception:
            pass
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return False
    except Exception:
        return False


def _assignment_run_row_is_live(
    row: sqlite3.Row | dict[str, Any],
    *,
    active_run_ids: set[str],
    now_dt: Any,
    grace_seconds: int,
) -> bool:
    run_id = str((row["run_id"] if isinstance(row, sqlite3.Row) else row.get("run_id")) or "").strip()
    status = str((row["status"] if isinstance(row, sqlite3.Row) else row.get("status")) or "").strip().lower()
    raw_pid = row["provider_pid"] if isinstance(row, sqlite3.Row) else row.get("provider_pid")
    effective_grace_seconds = max(1, int(grace_seconds))
    if status == "starting":
        effective_grace_seconds = max(effective_grace_seconds, DEFAULT_ASSIGNMENT_PROVIDER_START_GRACE_SECONDS)
    elif not raw_pid:
        # Codex cold start can take far longer than the stale-running default window.
        # Keep a dispatch-created run alive until provider pid or the first real heartbeat lands.
        effective_grace_seconds = max(effective_grace_seconds, DEFAULT_ASSIGNMENT_PROVIDER_START_GRACE_SECONDS)
    if run_id and run_id in active_run_ids:
        return True
    pid_is_live = _assignment_process_pid_is_live(raw_pid)
    if pid_is_live:
        live_process_grace_seconds = max(
            effective_grace_seconds,
            max(1, int(DEFAULT_ASSIGNMENT_EVENT_STREAM_KEEPALIVE_S)) * 3,
        )
        # A live provider pid without an in-process handle is only trusted while the run
        # record still receives fresh timestamps. Once those timestamps age out, treat it
        # as a detached orphan and let stale recovery terminate the provider tree.
        for field in ("latest_event_at", "updated_at", "started_at", "created_at"):
            raw_value = row[field] if isinstance(row, sqlite3.Row) else row.get(field)
            parsed = _parse_assignment_iso_datetime(raw_value)
            if parsed is None:
                continue
            try:
                if getattr(parsed, "tzinfo", None) is None and getattr(now_dt, "tzinfo", None) is not None:
                    parsed = parsed.replace(tzinfo=now_dt.tzinfo)
                age_seconds = abs((now_dt - parsed).total_seconds())
            except Exception:
                continue
            if age_seconds <= live_process_grace_seconds:
                return True
        return False
    for field in ("latest_event_at", "updated_at", "started_at", "created_at"):
        raw_value = row[field] if isinstance(row, sqlite3.Row) else row.get(field)
        parsed = _parse_assignment_iso_datetime(raw_value)
        if parsed is None:
            continue
        try:
            if getattr(parsed, "tzinfo", None) is None and getattr(now_dt, "tzinfo", None) is not None:
                parsed = parsed.replace(tzinfo=now_dt.tzinfo)
            age_seconds = abs((now_dt - parsed).total_seconds())
        except Exception:
            continue
        if age_seconds <= effective_grace_seconds:
            return True
    return False


def _live_assignment_run_keys(
    conn: sqlite3.Connection,
    *,
    ticket_id: str = "",
    grace_seconds: int = DEFAULT_ASSIGNMENT_STALE_RUN_GRACE_SECONDS,
) -> set[tuple[str, str]]:
    ticket_filter = safe_token(str(ticket_id or ""), "", 160)
    active_run_ids = {
        str(run_id or "").strip()
        for run_id in _active_assignment_run_ids()
        if str(run_id or "").strip()
    }
    now_dt = now_local()
    rows = conn.execute(
        """
        SELECT run_id,ticket_id,node_id,status,latest_event_at,updated_at,started_at,created_at,provider_pid
        FROM assignment_execution_runs
        WHERE status IN ('starting','running')
          AND (?='' OR ticket_id=?)
        ORDER BY created_at DESC, run_id DESC
        """,
        (ticket_filter, ticket_filter),
    ).fetchall()
    live_keys: set[tuple[str, str]] = set()
    for row in rows:
        if not _assignment_run_row_is_live(
            row,
            active_run_ids=active_run_ids,
            now_dt=now_dt,
            grace_seconds=grace_seconds,
        ):
            continue
        key = (str(row["ticket_id"] or "").strip(), str(row["node_id"] or "").strip())
        if key[0] and key[1]:
            live_keys.add(key)
    return live_keys


def _reconcile_stale_running_nodes(
    conn: sqlite3.Connection,
    *,
    ticket_id: str = "",
    grace_seconds: int = DEFAULT_ASSIGNMENT_STALE_RUN_GRACE_SECONDS,
) -> list[dict[str, Any]]:
    ticket_filter = safe_token(str(ticket_id or ""), "", 160)
    live_keys = _live_assignment_run_keys(
        conn,
        ticket_id=ticket_filter,
        grace_seconds=grace_seconds,
    )
    rows = conn.execute(
        """
        SELECT ticket_id,node_id
        FROM assignment_nodes
        WHERE status='running'
          AND (?='' OR ticket_id=?)
        ORDER BY ticket_id ASC, node_id ASC
        """,
        (ticket_filter, ticket_filter),
    ).fetchall()
    if not rows:
        return []
    now_text = iso_ts(now_local())
    recovered: list[dict[str, Any]] = []
    touched_tickets: set[str] = set()
    for row in rows:
        node_ticket_id = str(row["ticket_id"] or "").strip()
        node_id = str(row["node_id"] or "").strip()
        if not node_ticket_id or not node_id or (node_ticket_id, node_id) in live_keys:
            continue
        run_rows = conn.execute(
            """
            SELECT run_id,provider_pid
            FROM assignment_execution_runs
            WHERE ticket_id=? AND node_id=? AND status IN ('starting','running')
            ORDER BY created_at DESC, run_id DESC
            """,
            (node_ticket_id, node_id),
        ).fetchall()
        cancelled_run_ids = [
            {
                "run_id": str(run_row["run_id"] or "").strip(),
                "provider_pid": int(run_row["provider_pid"] or 0),
            }
            for run_row in run_rows
            if str(run_row["run_id"] or "").strip()
        ]
        if cancelled_run_ids:
            conn.execute(
                """
                UPDATE assignment_execution_runs
                SET status='cancelled',
                    latest_event=?,
                    latest_event_at=?,
                    finished_at=?,
                    updated_at=?
                WHERE ticket_id=? AND node_id=? AND status IN ('starting','running')
                """,
                (
                    "检测到运行态缺失真实执行批次，系统已回收脏 running 状态。",
                    now_text,
                    now_text,
                    now_text,
                    node_ticket_id,
                    node_id,
                ),
            )
            for item in cancelled_run_ids:
                _kill_assignment_run_process(
                    str(item.get("run_id") or "").strip(),
                    provider_pid=int(item.get("provider_pid") or 0),
                )
        conn.execute(
            """
            UPDATE assignment_nodes
            SET status='pending',
                completed_at='',
                success_reason='',
                result_ref='',
                failure_reason='',
                updated_at=?
            WHERE ticket_id=? AND node_id=? AND status='running'
            """,
            (now_text, node_ticket_id, node_id),
        )
        touched_tickets.add(node_ticket_id)
        recovered.append(
            {
                "ticket_id": node_ticket_id,
                "node_id": node_id,
                "cancelled_run_ids": [str(item.get("run_id") or "").strip() for item in cancelled_run_ids],
            }
        )
    if not recovered:
        return []
    for touched_ticket_id in sorted(touched_tickets):
        _recompute_graph_statuses(
            conn,
            touched_ticket_id,
            reconcile_running=False,
        )
    for item in recovered:
        final_row = conn.execute(
            """
            SELECT status
            FROM assignment_nodes
            WHERE ticket_id=? AND node_id=?
            LIMIT 1
            """,
            (str(item["ticket_id"]), str(item["node_id"])),
        ).fetchone()
        target_status = str((final_row or {"status": "pending"})["status"] or "pending").strip().lower()
        _write_assignment_audit(
            conn,
            ticket_id=str(item["ticket_id"]),
            node_id=str(item["node_id"]),
            action="recover_stale_running",
            operator="assignment-system",
            reason="recover stale running node without live execution",
            target_status=target_status,
            detail={
                "cancelled_run_ids": list(item["cancelled_run_ids"]),
                "grace_seconds": int(grace_seconds),
            },
            created_at=now_text,
        )
    return recovered
