from __future__ import annotations

from workflow_app.server.services.codex_failure_contract import (
    build_codex_failure,
    build_retry_action,
    infer_codex_failure_detail_code,
)


def _assignment_active_run_record(root: Path, *, ticket_id: str, node_id: str) -> dict[str, Any]:
    for row in _assignment_load_run_records(root, ticket_id=ticket_id, node_id=node_id):
        if str(row.get("status") or "").strip().lower() in {"starting", "running"}:
            return dict(row)
    return {}


def _assignment_execution_thread_should_daemon(operator: str) -> bool:
    raw = str(os.getenv("WORKFLOW_ASSIGNMENT_EXECUTION_THREAD_DAEMON") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    operator_text = str(operator or "").strip().lower()
    # PM-triggered one-shot dispatches can originate from a short-lived local process.
    # Keep worker threads non-daemon so helper runs are not orphaned when that host exits.
    if operator_text.startswith("pm-"):
        return False
    return True


def _assignment_execution_worker_guarded(
    root: Path,
    *,
    run_id: str,
    ticket_id: str,
    node_id: str,
    workspace_path: Path,
    command: list[str],
    command_summary: str,
    prompt_text: str,
    operator: str = "",
) -> None:
    try:
        _assignment_execution_worker(
            root,
            run_id=run_id,
            ticket_id=ticket_id,
            node_id=node_id,
            workspace_path=workspace_path,
            command=command,
            command_summary=command_summary,
            prompt_text=prompt_text,
        )
    except Exception as exc:
        failed_at = iso_ts(now_local())
        failure_message = f"assignment execution worker bootstrap failed: {exc}"
        traceback_text = traceback.format_exc()
        try:
            files = _assignment_run_file_paths(root, ticket_id, run_id)
            _append_assignment_run_event(
                files["events"],
                event_type="provider_start_failed",
                message=f"Provider 启动前异常: {exc}",
                created_at=failed_at,
                detail={
                    "exception_type": type(exc).__name__,
                    "operator": str(operator or "").strip(),
                },
            )
            _append_assignment_run_text(files["stderr"], traceback_text)
        except Exception:
            pass
        try:
            _finalize_assignment_execution_run(
                root,
                run_id=run_id,
                ticket_id=ticket_id,
                node_id=node_id,
                exit_code=1,
                stdout_text="",
                stderr_text=traceback_text,
                result_payload={},
                failure_message=failure_message,
            )
        except Exception:
            pass


def _assignment_touch_run_latest_event(
    root: Path,
    *,
    ticket_id: str,
    run_id: str,
    latest_event: str,
    latest_event_at: str,
) -> None:
    run_record = _assignment_load_run_record(root, ticket_id=ticket_id, run_id=run_id)
    if not run_record:
        return
    current_status = str(run_record.get("status") or "").strip().lower()
    if current_status not in {"starting", "running"}:
        return
    run_record["latest_event"] = _short_assignment_text(latest_event, 1000) or "执行中"
    run_record["latest_event_at"] = latest_event_at
    run_record["updated_at"] = latest_event_at
    _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record, sync_index=False)


def _assignment_touch_run_heartbeat(
    root: Path,
    *,
    ticket_id: str,
    run_id: str,
    heartbeat_at: str,
) -> None:
    run_record = _assignment_load_run_record(root, ticket_id=ticket_id, run_id=run_id)
    if not run_record:
        return
    current_status = str(run_record.get("status") or "").strip().lower()
    if current_status not in {"starting", "running"}:
        return
    run_record["updated_at"] = heartbeat_at
    if not str(run_record.get("latest_event_at") or "").strip():
        run_record["latest_event_at"] = heartbeat_at
    _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record, sync_index=False)


def _assignment_execution_codex_failure(
    root: Path,
    *,
    ticket_id: str,
    node_id: str,
    run_id: str,
    run_record: dict[str, Any],
    exit_code: int,
    stderr_text: str,
    failure_message: str,
    failed_at: str,
) -> dict[str, Any]:
    fallback_code = f"codex_exec_failed_exit_{int(exit_code or 0)}" if int(exit_code or 0) > 0 else "assignment_execution_failed"
    detail_code = infer_codex_failure_detail_code(
        str(failure_message or stderr_text or "").strip(),
        fallback=fallback_code,
    )
    attempt_count = len(_assignment_load_run_records(root, ticket_id=ticket_id, node_id=node_id))
    trace_refs = {
        "prompt": str(run_record.get("prompt_ref") or "").strip(),
        "stdout": str(run_record.get("stdout_ref") or "").strip(),
        "stderr": str(run_record.get("stderr_ref") or "").strip(),
        "result": str(run_record.get("result_ref") or "").strip(),
    }
    return build_codex_failure(
        feature_key="assignment_node_execution",
        attempt_id=run_id,
        attempt_count=max(1, int(attempt_count or 0)),
        failure_detail_code=detail_code,
        failure_message=str(failure_message or stderr_text or "").strip(),
        retry_action=build_retry_action(
            "rerun_assignment_node",
            payload={
                "ticket_id": str(ticket_id or "").strip(),
                "node_id": str(node_id or "").strip(),
                "run_id": str(run_id or "").strip(),
            },
        ),
        trace_refs=trace_refs,
        failed_at=failed_at,
    )


def _assignment_stdout_events_are_startup_only(stdout_text: str) -> bool:
    lines = [str(line or "").strip() for line in str(stdout_text or "").splitlines() if str(line or "").strip()]
    if not lines:
        return False
    allowed_types = {"thread.started", "turn.started"}
    for line in lines:
        try:
            payload = json.loads(line)
        except Exception:
            return False
        if not isinstance(payload, dict):
            return False
        event_type = str(payload.get("type") or "").strip().lower()
        if event_type not in allowed_types:
            return False
    return True


def _assignment_stdout_event_error_messages(stdout_text: str) -> list[str]:
    messages: list[str] = []
    lines = [str(line or "").strip() for line in str(stdout_text or "").splitlines() if str(line or "").strip()]
    for line in lines:
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        event_type = str(payload.get("type") or "").strip().lower()
        if event_type == "error":
            message_text = str(payload.get("message") or "").strip()
            if message_text:
                messages.append(message_text)
        failed_error = payload.get("error")
        if isinstance(failed_error, dict):
            failed_message = str(failed_error.get("message") or "").strip()
            if failed_message:
                messages.append(failed_message)
    return messages


def _assignment_stream_disconnect_detected(stdout_text: str, stderr_text: str) -> bool:
    candidates = _assignment_stdout_event_error_messages(stdout_text)
    stderr_value = str(stderr_text or "").strip()
    if stderr_value:
        candidates.append(stderr_value)
    for item in candidates:
        lowered = str(item or "").strip().lower()
        if (
            "stream disconnected before completion" in lowered
            or "stream closed before response.completed" in lowered
            or "连接中断" in lowered
        ):
            return True
    return False


def _assignment_should_retry_transient_stream_disconnect_failure(
    *,
    exit_code: int,
    stdout_text: str,
    stderr_text: str,
    observed_payload: dict[str, Any],
    elapsed_seconds: float,
    attempt_number: int,
) -> bool:
    retry_limit = _assignment_transient_startup_retry_limit()
    if retry_limit <= 0 or int(attempt_number or 0) > retry_limit:
        return False
    if int(exit_code or 0) == 0:
        return False
    if bool(observed_payload):
        return False
    if float(elapsed_seconds or 0.0) > float(_assignment_transient_startup_retry_max_seconds()):
        return False
    return _assignment_stream_disconnect_detected(stdout_text, stderr_text)


def _assignment_should_retry_transient_startup_failure(
    *,
    exit_code: int,
    stdout_text: str,
    stderr_text: str,
    agent_message_count: int,
    observed_payload: dict[str, Any],
    elapsed_seconds: float,
    attempt_number: int,
) -> bool:
    retry_limit = _assignment_transient_startup_retry_limit()
    if retry_limit <= 0 or int(attempt_number or 0) > retry_limit:
        return False
    if int(exit_code or 0) == 0:
        return False
    if int(agent_message_count or 0) > 0 or bool(observed_payload):
        return False
    if float(elapsed_seconds or 0.0) > float(_assignment_transient_startup_retry_max_seconds()):
        return False
    stderr_value = str(stderr_text or "").strip()
    if stderr_value and stderr_value != "^C":
        return False
    stdout_value = str(stdout_text or "").strip()
    if not stdout_value:
        return stderr_value in {"", "^C"}
    return _assignment_stdout_events_are_startup_only(stdout_value)


def _assignment_cancelled_run_final_message(run_record: dict[str, Any]) -> str:
    existing = str(run_record.get("latest_event") or "").strip()
    if not existing:
        return "执行已取消，后台结果不再回写节点状态。"
    if "后台结果不再回写节点状态" in existing:
        return existing
    if existing.endswith("。"):
        return existing[:-1] + "，后台结果不再回写节点状态。"
    return existing + "，后台结果不再回写节点状态。"


def _assignment_cancel_active_runs(
    root: Path,
    *,
    ticket_id: str,
    node_id: str,
    reason: str,
    now_text: str,
) -> list[str]:
    cancelled: list[str] = []
    for run in _assignment_load_run_records(root, ticket_id=ticket_id, node_id=node_id):
        status = str(run.get("status") or "").strip().lower()
        if status not in {"starting", "running"}:
            continue
        run_id = str(run.get("run_id") or "").strip()
        if not run_id:
            continue
        run["status"] = "cancelled"
        run["latest_event"] = reason
        run["latest_event_at"] = now_text
        run["finished_at"] = now_text
        run["updated_at"] = now_text
        _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run)
        _kill_assignment_run_process(run_id, provider_pid=int(run.get("provider_pid") or 0))
        cancelled.append(run_id)
    return cancelled


def _resolve_assignment_artifact_source_paths(
    workspace_path: Path | str,
    artifact_files: list[Any],
) -> list[Path]:
    workspace_text = str(workspace_path or "").strip()
    if not workspace_text:
        return []
    base = Path(workspace_text).resolve(strict=False)
    if not base.exists() or not base.is_dir():
        return []
    resolved_paths: list[Path] = []
    seen: set[str] = set()
    for raw in list(artifact_files or []):
        text = str(raw or "").strip()
        if not text:
            continue
        candidate = Path(text)
        if not candidate.is_absolute():
            candidate = (base / text).resolve(strict=False)
        else:
            candidate = candidate.resolve(strict=False)
        if not path_in_scope(candidate, base):
            continue
        if not candidate.exists() or not candidate.is_file():
            continue
        key = candidate.as_posix().lower()
        if key in seen:
            continue
        seen.add(key)
        resolved_paths.append(candidate)
    return resolved_paths


def _assignment_workspace_memory_daily_path(workspace_path: Path, *, day_key: str, month_key: str) -> Path:
    return (workspace_path / ".codex" / "memory" / month_key / f"{day_key}.md").resolve(strict=False)


def _assignment_workspace_memory_lines(label: str, items: list[str]) -> list[str]:
    if not items:
        return []
    lines = [f"- {label}:"]
    lines.extend(f"  - {item}" for item in items if str(item or "").strip())
    return lines


def _assignment_workspace_memory_artifact_refs(workspace_path: Path, artifact_paths: list[str]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for raw in list(artifact_paths or []):
        text = str(raw or "").strip()
        if not text:
            continue
        candidate = Path(text).resolve(strict=False)
        if path_in_scope(candidate, workspace_path):
            try:
                normalized = candidate.relative_to(workspace_path).as_posix()
            except Exception:
                normalized = candidate.as_posix()
        else:
            normalized = candidate.as_posix()
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        refs.append(normalized)
    return refs


def _append_assignment_workspace_memory_round(
    workspace_path_text: str,
    *,
    ticket_id: str,
    node_record: dict[str, Any],
    run_id: str,
    exit_code: int,
    result_ref: str,
    summary_text: str,
    artifact_paths: list[str],
    warnings: list[Any],
    appended_at: str,
) -> dict[str, Any]:
    workspace_text = str(workspace_path_text or "").strip()
    if not workspace_text:
        return {}
    workspace_path = Path(workspace_text).resolve(strict=False)
    if not workspace_path.exists() or not workspace_path.is_dir():
        return {}
    if not _assignment_workspace_uses_codex_memory(workspace_path):
        return {}
    now_dt = now_local()
    month_key = now_dt.strftime("%Y-%m")
    day_key = now_dt.strftime("%Y-%m-%d")
    created_paths = _ensure_assignment_workspace_memory_scaffold(workspace_path)
    daily_path = _assignment_workspace_memory_daily_path(workspace_path, day_key=day_key, month_key=month_key)
    if not daily_path.exists():
        return {}
    run_marker = f"`{str(run_id or '').strip()}`"
    existing = daily_path.read_text(encoding="utf-8")
    if run_marker and run_marker in existing:
        return {
            "ok": True,
            "daily_path": daily_path.as_posix(),
            "created_paths": created_paths,
            "run_id": str(run_id or "").strip(),
            "skipped": "duplicate_run_id",
        }
    node_id = str(node_record.get("node_id") or "").strip()
    node_name = str(node_record.get("node_name") or node_id or "任务执行").strip() or "任务执行"
    assigned_agent = str(node_record.get("assigned_agent_id") or node_record.get("assigned_agent_name") or "").strip()
    status_text = "成功" if str(node_record.get("status") or "").strip().lower() == "succeeded" else "失败"
    topic_text = f"{node_name} {status_text}收尾"
    summary_value = _normalize_text(summary_text, field="result_summary", required=False, max_len=600) or status_text
    warning_items = [
        _normalize_text(item, field="warning", required=False, max_len=200)
        for item in list(warnings or [])
    ]
    warning_items = [item for item in warning_items if item]
    artifact_refs = _assignment_workspace_memory_artifact_refs(workspace_path, artifact_paths)
    actions = [
        f"我刚刚完成了 `{ticket_id} / {node_id}` 的收尾回写，assigned_agent=`{assigned_agent or '-'}`。",
        f"系统替我补记了这轮日记，run_id={run_marker}，避免我漏掉当日日记。",
        f"我这轮的结果：{summary_value}",
    ]
    if created_paths:
        actions.append("系统还顺手补齐了记忆骨架：" + "；".join(created_paths))
    decisions = ["我已经把这轮结果落进日记，后续可以顺着这条记录继续追踪。"]
    if status_text == "成功":
        decisions.append("当前节点已经成功完成，任务图状态也同步回写了。")
    else:
        decisions.append("当前节点执行失败了，后续要按失败摘要继续排障或重跑。")
    validation = [
        f"run_id={run_marker}",
        f"exit_code={int(exit_code or 0)}",
        f"result_ref={str(result_ref or '-').strip() or '-'}",
        f"node_status={str(node_record.get('status') or '').strip() or '-'}",
    ]
    if warning_items:
        validation.append("warnings=" + "；".join(warning_items))
    next_items = [f"如果还要继续，我下一步优先从 ticket `{ticket_id}` / node `{node_id}` 继续查看任务图与运行记录。"]
    lines = [
        f"### {str(appended_at or iso_ts(now_dt)).strip() or iso_ts(now_dt)} | {topic_text}",
        f"- topic: {topic_text}",
        (
            "- context: "
            + f"任务中心把 `{ticket_id} / {node_id}` 派给了 `{assigned_agent or '-'}` 工作区，这轮在执行结束后由系统帮我补记了日记。"
        ),
        *_assignment_workspace_memory_lines("actions", actions),
        *_assignment_workspace_memory_lines("decisions", decisions),
        *_assignment_workspace_memory_lines("validation", validation),
        *_assignment_workspace_memory_lines("artifacts", artifact_refs),
        *_assignment_workspace_memory_lines("next", next_items),
    ]
    daily_path.write_text(existing.rstrip() + "\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "daily_path": daily_path.as_posix(),
        "created_paths": created_paths,
        "run_id": str(run_id or "").strip(),
        "node_id": node_id,
        "status": str(node_record.get("status") or "").strip(),
        "artifact_refs": artifact_refs,
    }


def _assignment_append_workspace_memory_with_audit(
    root: Path,
    *,
    ticket_id: str,
    node_record: dict[str, Any],
    run_id: str,
    workspace_path_text: str,
    exit_code: int,
    result_ref: str,
    summary_text: str,
    artifact_paths: list[str],
    warnings: list[Any],
    appended_at: str,
    target_status: str,
) -> None:
    try:
        memory_detail = _append_assignment_workspace_memory_round(
            workspace_path_text,
            ticket_id=ticket_id,
            node_record=node_record,
            run_id=run_id,
            exit_code=exit_code,
            result_ref=result_ref,
            summary_text=summary_text,
            artifact_paths=artifact_paths,
            warnings=warnings,
            appended_at=appended_at,
        )
        if memory_detail:
            _assignment_write_audit_entry(
                root,
                ticket_id=ticket_id,
                node_id=str(node_record.get("node_id") or "").strip(),
                action="append_workspace_memory",
                operator="assignment-executor",
                reason="appended workspace daily memory after execution finalize",
                target_status=str(target_status or "").strip().lower(),
                detail=memory_detail,
                created_at=appended_at,
            )
    except Exception as exc:
        _assignment_write_audit_entry(
            root,
            ticket_id=ticket_id,
            node_id=str(node_record.get("node_id") or "").strip(),
            action="append_workspace_memory_failed",
            operator="assignment-executor",
            reason=_normalize_text(
                f"append workspace memory failed: {exc}",
                field="failure_reason",
                required=True,
                max_len=400,
            ),
            target_status=str(target_status or "").strip().lower(),
            detail={
                "workspace_path": workspace_path_text,
                "run_id": run_id,
                "error": str(exc),
            },
            created_at=appended_at,
        )


def _copy_assignment_artifact_source_files(
    root: Path,
    *,
    node: dict[str, Any],
    artifact_source_paths: list[Path],
) -> list[str]:
    copied_paths: list[str] = []
    seen: set[str] = set()
    for source_path in list(artifact_source_paths or []):
        if not isinstance(source_path, Path) or not source_path.exists() or not source_path.is_file():
            continue
        target_paths = _node_artifact_file_paths(
            root,
            node,
            file_name=source_path.name,
        )
        for target_path in target_paths:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
            text = target_path.as_posix()
            if text in seen:
                continue
            seen.add(text)
            copied_paths.append(text)
    return copied_paths


def _copy_assignment_delivery_inbox_source_files(
    root: Path,
    *,
    node: dict[str, Any],
    artifact_source_paths: list[Path],
) -> list[str]:
    copied_paths: list[str] = []
    seen: set[str] = set()
    for source_path in list(artifact_source_paths or []):
        if not isinstance(source_path, Path) or not source_path.exists() or not source_path.is_file():
            continue
        target_paths = _node_delivery_inbox_file_paths(
            root,
            node,
            file_name=source_path.name,
        )
        for target_path in target_paths:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
            text = target_path.as_posix()
            if text in seen:
                continue
            seen.add(text)
            copied_paths.append(text)
    return copied_paths


def _write_assignment_delivery_info_file(
    root: Path,
    *,
    node: dict[str, Any],
    delivered_at: str,
    operator: str,
    artifact_label: str,
    delivery_note: str,
    canonical_artifact_paths: list[str],
    delivery_inbox_paths: list[str],
) -> str:
    info_path = _node_delivery_info_path(root, node)
    payload = {
        "record_type": "assignment_delivery_info",
        "schema_version": ASSIGNMENT_TASK_SCHEMA_VERSION,
        "ticket_id": str(node.get("ticket_id") or "").strip(),
        "node_id": str(node.get("node_id") or "").strip(),
        "task_name": str(node.get("node_name") or "").strip(),
        "artifact_label": str(artifact_label or "").strip(),
        "delivery_note": str(delivery_note or "").strip(),
        "delivered_at": str(delivered_at or "").strip(),
        "delivery_mode": str(node.get("delivery_mode") or "none").strip().lower() or "none",
        "delivery_receiver_agent_id": str(node.get("delivery_receiver_agent_id") or "").strip(),
        "delivery_receiver_agent_name": str(node.get("delivery_receiver_agent_name") or "").strip(),
        "delivery_target_agent_id": _node_delivery_target_agent_id(node),
        "delivery_target_agent_name": _node_delivery_target_agent_name(node),
        "delivery_inbox_relative_path": _node_delivery_inbox_relative_path(node),
        "delivery_inbox_relative_paths": _node_delivery_inbox_relative_paths(node, delivery_inbox_paths),
        "delivered_by_agent_id": str(node.get("assigned_agent_id") or "").strip(),
        "delivered_by_agent_name": str(node.get("assigned_agent_name") or node.get("assigned_agent_id") or "").strip(),
        "delivery_recorded_by": str(operator or "").strip(),
        "canonical_artifact_paths": list(canonical_artifact_paths or []),
        "delivery_inbox_paths": list(delivery_inbox_paths or []),
    }
    _assignment_write_json(info_path, payload)
    return info_path.as_posix()


def _cleanup_assignment_artifact_source_files(
    workspace_path: Path | str,
    artifact_source_paths: list[Path],
) -> tuple[list[str], list[str]]:
    workspace_text = str(workspace_path or "").strip()
    if not workspace_text:
        return [], []
    base = Path(workspace_text).resolve(strict=False)
    if not base.exists() or not base.is_dir():
        return [], []
    cleaned_paths: list[str] = []
    cleanup_errors: list[str] = []
    seen: set[str] = set()
    for source_path in list(artifact_source_paths or []):
        if not isinstance(source_path, Path):
            continue
        candidate = source_path.resolve(strict=False)
        candidate_text = candidate.as_posix()
        if candidate_text.lower() in seen:
            continue
        seen.add(candidate_text.lower())
        if not path_in_scope(candidate, base):
            continue
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            candidate.unlink()
            cleaned_paths.append(candidate_text)
        except Exception as exc:
            cleanup_errors.append(f"{candidate_text}: {exc}")
            continue
        parent = candidate.parent
        while parent != base:
            try:
                if not path_in_scope(parent, base):
                    break
                parent.rmdir()
            except OSError:
                break
            except Exception as exc:
                cleanup_errors.append(f"{parent.as_posix()}: {exc}")
                break
            parent = parent.parent
    return cleaned_paths, cleanup_errors


def _deliver_assignment_artifact_locked(
    root: Path,
    *,
    ticket_id: str,
    node_id: str,
    operator_text: str,
    artifact_label: str,
    delivery_note: str,
    artifact_body: str,
    now_text: str,
    artifact_source_paths: list[Path] | None = None,
    source_workspace_path: Path | str = "",
) -> tuple[dict[str, Any], dict[str, Any], list[str], str]:
    snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=True,
        reconcile_running=False,
    )
    task_record = dict(snapshot["graph_row"])
    node_records = [dict(item) for item in list(snapshot["all_nodes"] or [])]
    selected_node = next(
        (
            item
            for item in node_records
            if str(item.get("node_id") or "").strip() == node_id
            and str(item.get("record_state") or "active").strip().lower() != "deleted"
        ),
        {},
    )
    if not selected_node:
        raise AssignmentCenterError(404, "assignment node not found", "assignment_node_not_found")
    artifact_file_paths = _node_artifact_file_paths(root, selected_node)
    artifact_paths: list[str] = []
    delivery_inbox_paths: list[str] = []
    payload = artifact_body or _artifact_delivery_markdown(
        selected_node,
        delivered_at=now_text,
        operator=operator_text,
        artifact_label=artifact_label,
        delivery_note=delivery_note,
    )
    payload = _artifact_text_to_html_document(
        payload,
        title=artifact_label or _artifact_label_text(selected_node),
    )
    copied_source_artifacts = _copy_assignment_artifact_source_files(
        root,
        node=selected_node,
        artifact_source_paths=list(artifact_source_paths or []),
    )
    copied_delivery_inbox_artifacts = _copy_assignment_delivery_inbox_source_files(
        root,
        node=selected_node,
        artifact_source_paths=list(artifact_source_paths or []),
    )
    cleaned_source_paths, cleanup_errors = _cleanup_assignment_artifact_source_files(
        source_workspace_path,
        list(artifact_source_paths or []),
    )
    artifact_paths.extend(copied_source_artifacts)
    delivery_inbox_paths.extend(copied_delivery_inbox_artifacts)
    if not artifact_paths:
        artifact_file_paths = _node_artifact_file_paths(
            root,
            selected_node,
            preferred_extension=_artifact_file_extension_from_body(payload),
        )
        for path in artifact_file_paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")
            artifact_paths.append(path.as_posix())
        for path in _node_delivery_inbox_file_paths(
            root,
            selected_node,
            preferred_extension=_artifact_file_extension_from_body(payload),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")
            delivery_inbox_paths.append(path.as_posix())
    else:
        artifact_file_paths = [Path(item) for item in copied_source_artifacts]
    delivery_info_path = _write_assignment_delivery_info_file(
        root,
        node=selected_node,
        delivered_at=now_text,
        operator=operator_text,
        artifact_label=artifact_label,
        delivery_note=delivery_note,
        canonical_artifact_paths=artifact_paths,
        delivery_inbox_paths=delivery_inbox_paths,
    )
    artifact_structure_paths = _write_artifact_structure_files(
        root,
        node=selected_node,
        artifact_file_paths=artifact_file_paths,
        delivered_at=now_text,
        operator=operator_text,
    )
    for row in node_records:
        if str(row.get("node_id") or "").strip() != node_id:
            continue
        row["artifact_delivery_status"] = "delivered"
        row["artifact_delivery_status_text"] = _artifact_delivery_status_text("delivered")
        row["artifact_delivered_at"] = now_text
        row["artifact_paths"] = artifact_paths
        row["updated_at"] = now_text
        break
    task_record["updated_at"] = now_text
    _assignment_store_snapshot(root, task_record=task_record, node_records=node_records)
    audit_id = _assignment_write_audit_entry(
        root,
        ticket_id=ticket_id,
        node_id=node_id,
        action="deliver_artifact",
        operator=operator_text,
        reason=delivery_note or "deliver assignment artifact",
        target_status="delivered",
        detail={
            "artifact_label": artifact_label,
            "delivery_mode": str(selected_node.get("delivery_mode") or "none").strip().lower(),
            "delivery_receiver_agent_id": str(selected_node.get("delivery_receiver_agent_id") or "").strip(),
            "delivery_target_agent_id": _node_delivery_target_agent_id(selected_node),
            "delivery_target_agent_name": _node_delivery_target_agent_name(selected_node),
            "delivery_inbox_dir": _node_delivery_inbox_dir(root, selected_node).as_posix(),
            "delivery_inbox_relative_path": _node_delivery_inbox_relative_path(selected_node),
            "delivery_inbox_paths": delivery_inbox_paths,
            "delivery_info_path": delivery_info_path,
            "artifact_paths": artifact_paths,
            "artifact_structure_paths": artifact_structure_paths,
            "source_workspace_cleanup": {
                "cleaned_paths": cleaned_source_paths,
                "cleanup_errors": cleanup_errors,
            },
        },
        created_at=now_text,
    )
    updated_snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=True,
        reconcile_running=False,
    )
    updated_node = next(
        (
            item
            for item in list(updated_snapshot["serialized_nodes"] or [])
            if str(item.get("node_id") or "").strip() == node_id
        ),
        {},
    )
    return updated_snapshot["graph_row"], updated_node, artifact_paths, audit_id


def _assignment_system_running_state(root: Path, *, include_test_data: bool) -> dict[str, Any]:
    active_run_ids = {
        str(run_id or "").strip()
        for run_id in _active_assignment_run_ids()
        if str(run_id or "").strip()
    }
    if not active_run_ids:
        return {
            "running_agents": set(),
            "running_node_count": 0,
        }
    now_dt = now_local()
    running_agents: set[str] = set()
    running_node_keys: set[tuple[str, str]] = set()
    canonical_workflow_ui_ticket = _assignment_ensure_workflow_ui_global_graph_ticket(root)
    for ticket_id in _assignment_list_ticket_ids_lightweight(root):
        task_record = _assignment_load_task_record_lightweight(root, ticket_id)
        if not task_record:
            continue
        if not _assignment_task_visible(task_record, include_test_data=include_test_data):
            continue
        if _assignment_is_hidden_workflow_ui_graph_ticket(
            root,
            ticket_id,
            ticket_record=task_record,
            canonical_ticket_id=canonical_workflow_ui_ticket,
        ):
            continue
        live_node_ids: set[str] = set()
        for run in _assignment_load_run_records(root, ticket_id=ticket_id):
            status = str(run.get("status") or "").strip().lower()
            if status not in {"starting", "running"}:
                continue
            if not _assignment_run_row_is_live(
                run,
                active_run_ids=active_run_ids,
                now_dt=now_dt,
                grace_seconds=DEFAULT_ASSIGNMENT_STALE_RUN_GRACE_SECONDS,
            ):
                continue
            node_id = str(run.get("node_id") or "").strip()
            if node_id:
                live_node_ids.add(node_id)
                running_node_keys.add((ticket_id, node_id))
        if not live_node_ids:
            continue
        for node_id in live_node_ids:
            node = _assignment_read_json(_assignment_node_record_path(root, ticket_id, node_id))
            agent_id = str(node.get("assigned_agent_id") or "").strip()
            if agent_id:
                running_agents.add(agent_id)
    return {
        "running_agents": running_agents,
        "running_node_count": len(running_node_keys),
    }


def _assignment_dispatch_candidates(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        dict(node)
        for node in list(snapshot.get("nodes") or [])
        if str(node.get("status") or "").strip().lower() == "ready"
    ]
    rows.sort(
        key=lambda item: (
            int(item.get("priority") or 0),
            str(item.get("created_at") or ""),
            str(item.get("node_id") or ""),
        )
    )
    return rows


def _assignment_dispatch_snapshot(
    root: Path,
    *,
    ticket_id: str,
    include_test_data: bool,
    reconcile_running: bool,
) -> dict[str, Any]:
    task_record = _assignment_load_task_record(root, ticket_id)
    if not _assignment_task_visible(task_record, include_test_data=include_test_data):
        raise AssignmentCenterError(
            404,
            "assignment graph not found",
            "assignment_graph_not_found",
            {"ticket_id": ticket_id},
        )
    node_records = _assignment_load_node_records(root, ticket_id, include_deleted=True)
    task_record, node_records, changed = _assignment_recompute_task_state(
        root,
        task_record=task_record,
        node_records=node_records,
        reconcile_running=reconcile_running,
    )
    if changed:
        _assignment_store_snapshot(root, task_record=task_record, node_records=node_records)
    active_nodes = _assignment_active_node_records(node_records)
    settings = get_assignment_concurrency_settings(root)
    system_counts = _assignment_system_running_counts(root, include_test_data=include_test_data)
    scheduler_payload = _assignment_scheduler_payload(
        task_record,
        active_nodes,
        system_limit=int(settings.get("global_concurrency_limit") or DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT),
        settings_updated_at=str(settings.get("updated_at") or ""),
        system_counts=system_counts,
    )
    edges = _assignment_active_edges(task_record, active_nodes)
    node_map_by_id = _node_map(active_nodes)
    upstream_map, downstream_map = _edge_maps(edges)
    return {
        "graph_row": task_record,
        "nodes": active_nodes,
        "all_nodes": node_records,
        "edges": edges,
        "node_map_by_id": node_map_by_id,
        "upstream_map": upstream_map,
        "downstream_map": downstream_map,
        "metrics_summary": _graph_metrics(active_nodes),
        "scheduler": scheduler_payload,
        "serialized_nodes": [],
    }


def _prepare_assignment_execution_run(
    root: Path,
    *,
    ticket_id: str,
    node_id: str,
    now_text: str,
    snapshot_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ensure_assignment_support_tables(root)
    snapshot = dict(snapshot_override or {})
    if not snapshot:
        snapshot = _assignment_snapshot_from_files(
            root,
            ticket_id,
            include_test_data=True,
            reconcile_running=True,
        )
    serialized_node = next(
        (
            node
            for node in list(snapshot.get("serialized_nodes") or [])
            if str(node.get("node_id") or "").strip() == node_id
        ),
        {},
    )
    if not serialized_node:
        target_node = next(
            (
                dict(node)
                for node in list(snapshot.get("nodes") or [])
                if str(node.get("node_id") or "").strip() == node_id
            ),
            {},
        )
        if target_node:
            serialized_node = _serialize_node(
                target_node,
                node_map_by_id=dict(snapshot.get("node_map_by_id") or {}),
                upstream_map=dict(snapshot.get("upstream_map") or {}),
                downstream_map=dict(snapshot.get("downstream_map") or {}),
            )
    if not serialized_node:
        raise AssignmentCenterError(404, "assignment node not found", "assignment_node_not_found", {"node_id": node_id})
    upstream_nodes = [
        snapshot["node_map_by_id"].get(str(item.get("node_id") or "").strip()) or {}
        for item in list(serialized_node.get("upstream_nodes") or [])
    ]
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        workspace_path = _resolve_assignment_workspace_path(
            conn,
            root,
            agent_id=str(serialized_node.get("assigned_agent_id") or "").strip(),
        )
        settings = _assignment_execution_settings_from_conn(conn)
        conn.commit()
    finally:
        conn.close()
    provider = _normalize_execution_provider(settings.get("execution_provider"))
    prompt_text = _build_assignment_execution_prompt(
        graph_row=snapshot["graph_row"],
        node=serialized_node,
        upstream_nodes=upstream_nodes,
        workspace_path=workspace_path,
        delivery_inbox_path=_node_delivery_inbox_dir(root, serialized_node),
    )
    command, command_summary = _build_assignment_execution_command(
        provider=provider,
        codex_command_path=str(settings.get("codex_command_path") or ""),
        command_template=str(settings.get("command_template") or ""),
        workspace_path=workspace_path,
    )
    run_id = assignment_run_id()
    files = _assignment_run_file_paths(root, ticket_id, run_id)
    files["trace_dir"].mkdir(parents=True, exist_ok=True)
    _write_assignment_run_text(files["prompt"], prompt_text)
    _write_assignment_run_text(files["stdout"], "")
    _write_assignment_run_text(files["stderr"], "")
    _write_assignment_run_text(files["events"], "")
    _append_assignment_run_event(
        files["events"],
        event_type="dispatch",
        message="调度器已创建真实执行批次。",
        created_at=now_text,
        detail={"command_summary": command_summary},
    )
    run_record = _assignment_build_run_record(
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        provider=provider,
        workspace_path=workspace_path.as_posix(),
        status="starting",
        command_summary=command_summary,
        prompt_ref=files["prompt"].as_posix(),
        stdout_ref=files["stdout"].as_posix(),
        stderr_ref=files["stderr"].as_posix(),
        result_ref=files["result"].as_posix(),
        latest_event="已创建运行批次，等待 provider 启动。",
        latest_event_at=now_text,
        exit_code=0,
        started_at=now_text,
        finished_at="",
        created_at=now_text,
        updated_at=now_text,
    )
    _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)
    return {
        "run_id": run_id,
        "ticket_id": ticket_id,
        "node_id": node_id,
        "provider": provider,
        "workspace_path": workspace_path,
        "prompt_text": prompt_text,
        "command": command,
        "command_summary": command_summary,
        "files": files,
        "node": serialized_node,
    }


def _finalize_assignment_execution_run(
    root: Path,
    *,
    run_id: str,
    ticket_id: str,
    node_id: str,
    exit_code: int,
    stdout_text: str,
    stderr_text: str,
    result_payload: dict[str, Any],
    failure_message: str,
) -> None:
    now_text = iso_ts(now_local())
    snapshot = _assignment_snapshot_from_files(
        root,
        ticket_id,
        include_test_data=True,
        reconcile_running=False,
    )
    task_record = dict(snapshot["graph_row"])
    node_records = [dict(item) for item in list(snapshot["all_nodes"] or [])]
    node_record = next(
        (
            item
            for item in node_records
            if str(item.get("node_id") or "").strip() == node_id
            and str(item.get("record_state") or "active").strip().lower() != "deleted"
        ),
        {},
    )
    if not node_record:
        return
    run_record = _assignment_load_run_record(root, ticket_id=ticket_id, run_id=run_id)
    if not run_record:
        return
    result_ref = str(run_record.get("result_ref") or "").strip()
    workspace_path_text = str(run_record.get("workspace_path") or "").strip()
    current_run_status = str(run_record.get("status") or "").strip().lower()
    if current_run_status == "cancelled":
        _kill_assignment_run_process(run_id, provider_pid=run_record.get("provider_pid"))
        run_record["latest_event"] = _assignment_cancelled_run_final_message(run_record)
        run_record["latest_event_at"] = now_text
        run_record["exit_code"] = int(exit_code or 0)
        run_record["finished_at"] = now_text
        run_record["updated_at"] = now_text
        run_record["codex_failure"] = {}
        _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)
        _assignment_append_workspace_memory_with_audit(
            root,
            ticket_id=ticket_id,
            node_record=node_record,
            run_id=run_id,
            workspace_path_text=workspace_path_text,
            exit_code=exit_code,
            result_ref=result_ref,
            summary_text=str(run_record.get("latest_event") or "").strip() or "执行已取消",
            artifact_paths=list(node_record.get("artifact_paths") or []),
            warnings=[],
            appended_at=now_text,
            target_status="cancelled",
        )
        return
    success = int(exit_code or 0) == 0 and not str(failure_message or "").strip()
    upgrade_request_result: dict[str, Any] = {}
    memory_summary_text = ""
    memory_artifact_paths: list[str] = []
    memory_warning_items: list[Any] = []
    if success:
        markdown_text = str(result_payload.get("artifact_markdown") or "").strip()
        artifact_source_paths = _resolve_assignment_artifact_source_paths(
            workspace_path_text,
            list(result_payload.get("artifact_files") or []),
        )
        delivered_graph, delivered_node, artifact_paths, _artifact_audit_id = _deliver_assignment_artifact_locked(
            root,
            ticket_id=ticket_id,
            node_id=node_id,
            operator_text="assignment-executor",
            artifact_label=str(result_payload.get("artifact_label") or "").strip() or "任务产物",
            delivery_note=str(result_payload.get("result_summary") or "").strip(),
            artifact_body=markdown_text,
            now_text=now_text,
            artifact_source_paths=artifact_source_paths,
            source_workspace_path=workspace_path_text,
        )
        task_record = dict(delivered_graph or task_record)
        node_records = _assignment_load_node_records(root, ticket_id, include_deleted=True)
        node_record = next(
            (
                item
                for item in node_records
                if str(item.get("node_id") or "").strip() == node_id
                and str(item.get("record_state") or "active").strip().lower() != "deleted"
            ),
            node_record,
        )
        node_record["status"] = "succeeded"
        node_record["status_text"] = _node_status_text("succeeded")
        node_record["completed_at"] = now_text
        node_record["success_reason"] = str(result_payload.get("result_summary") or "").strip() or "执行完成"
        node_record["result_ref"] = result_ref
        node_record["failure_reason"] = ""
        node_record["updated_at"] = now_text
        node_record["artifact_paths"] = list(delivered_node.get("artifact_paths") or artifact_paths)
        task_record["updated_at"] = now_text
        task_record, node_records, _changed = _assignment_recompute_task_state(
            root,
            task_record=task_record,
            node_records=node_records,
            reconcile_running=False,
        )
        _assignment_store_snapshot(root, task_record=task_record, node_records=node_records)
        _assignment_write_audit_entry(
            root,
            ticket_id=ticket_id,
            node_id=node_id,
            action="execution_succeeded",
            operator="assignment-executor",
            reason=str(result_payload.get("result_summary") or "").strip() or "assignment execution succeeded",
            target_status="succeeded",
            detail={
                "run_id": run_id,
                "result_ref": result_ref,
                "artifact_paths": list(node_record.get("artifact_paths") or []),
            },
            created_at=now_text,
        )
        run_record["status"] = "succeeded"
        run_record["latest_event"] = "执行完成并已自动回写结果。"
        run_record["latest_event_at"] = now_text
        run_record["exit_code"] = int(exit_code or 0)
        run_record["finished_at"] = now_text
        run_record["updated_at"] = now_text
        run_record["codex_failure"] = {}
        _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)
        memory_summary_text = str(result_payload.get("result_summary") or "").strip() or "执行完成"
        memory_artifact_paths = list(node_record.get("artifact_paths") or [])
        memory_warning_items = list(result_payload.get("warnings") or [])
        try:
            schedule_result = _assignment_queue_self_iteration_schedule(
                root,
                task_record=task_record,
                node_record=node_record,
                result_summary=str(result_payload.get("result_summary") or "").strip() or "执行完成",
                success=True,
            )
            if bool(schedule_result.get("queued")):
                _assignment_write_audit_entry(
                    root,
                    ticket_id=ticket_id,
                    node_id=node_id,
                    action="schedule_self_iteration",
                    operator="assignment-executor",
                    reason="queued next self-iteration schedule",
                    target_status="succeeded",
                    detail=schedule_result,
                    created_at=now_text,
                )
        except Exception:
            pass
    else:
        failure_text = _normalize_text(
            failure_message or _short_assignment_text(stderr_text, 500) or "assignment execution failed",
            field="failure_reason",
            required=True,
            max_len=1000,
        )
        node_record["status"] = "failed"
        node_record["status_text"] = _node_status_text("failed")
        node_record["completed_at"] = now_text
        node_record["success_reason"] = ""
        node_record["result_ref"] = ""
        node_record["failure_reason"] = failure_text
        node_record["updated_at"] = now_text
        task_record["updated_at"] = now_text
        task_record, node_records, _changed = _assignment_recompute_task_state(
            root,
            task_record=task_record,
            node_records=node_records,
            reconcile_running=False,
        )
        _assignment_store_snapshot(root, task_record=task_record, node_records=node_records)
        _assignment_write_audit_entry(
            root,
            ticket_id=ticket_id,
            node_id=node_id,
            action="execution_failed",
            operator="assignment-executor",
            reason=failure_text,
            target_status="failed",
            detail={"run_id": run_id, "result_ref": result_ref},
            created_at=now_text,
        )
        run_record["status"] = "failed"
        run_record["latest_event"] = failure_text
        run_record["latest_event_at"] = now_text
        run_record["exit_code"] = int(exit_code or 0)
        run_record["finished_at"] = now_text
        run_record["updated_at"] = now_text
        run_record["codex_failure"] = _assignment_execution_codex_failure(
            root,
            ticket_id=ticket_id,
            node_id=node_id,
            run_id=run_id,
            run_record=run_record,
            exit_code=exit_code,
            stderr_text=stderr_text,
            failure_message=failure_text,
            failed_at=now_text,
        )
        _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)
        memory_summary_text = failure_text
        memory_artifact_paths = list(node_record.get("artifact_paths") or [])
        try:
            schedule_result = _assignment_queue_self_iteration_schedule(
                root,
                task_record=task_record,
                node_record=node_record,
                result_summary=failure_text,
                success=False,
            )
            if bool(schedule_result.get("queued")):
                _assignment_write_audit_entry(
                    root,
                    ticket_id=ticket_id,
                    node_id=node_id,
                    action="schedule_self_iteration",
                    operator="assignment-executor",
                    reason="queued next self-iteration schedule after failure",
                    target_status="failed",
                    detail=schedule_result,
                    created_at=now_text,
                )
        except Exception:
            pass
    _assignment_append_workspace_memory_with_audit(
        root,
        ticket_id=ticket_id,
        node_record=node_record,
        run_id=run_id,
        workspace_path_text=workspace_path_text,
        exit_code=exit_code,
        result_ref=result_ref,
        summary_text=memory_summary_text,
        artifact_paths=memory_artifact_paths,
        warnings=memory_warning_items,
        appended_at=now_text,
        target_status=str(node_record.get("status") or "").strip().lower() or ("succeeded" if success else "failed"),
    )
    try:
        upgrade_request_result = _assignment_maybe_request_prod_upgrade_after_finalize(
            root,
            task_record=task_record,
            node_record=node_record,
        )
        if bool(upgrade_request_result.get("requested")):
            _assignment_write_audit_entry(
                root,
                ticket_id=ticket_id,
                node_id=node_id,
                action="request_prod_upgrade",
                operator="assignment-executor",
                reason="queued prod upgrade after self-iteration finalize",
                target_status=str(node_record.get("status") or "").strip().lower() or "succeeded",
                detail=upgrade_request_result,
                created_at=now_text,
            )
    except Exception:
        upgrade_request_result = {}
    if not bool(upgrade_request_result.get("suppress_dispatch")):
        try:
            dispatch_assignment_next(
                root,
                ticket_id_text=ticket_id,
                operator="assignment-executor",
                include_test_data=True,
            )
        except Exception:
            pass


def _assignment_execution_worker(
    root: Path,
    *,
    run_id: str,
    ticket_id: str,
    node_id: str,
    workspace_path: Path,
    command: list[str],
    command_summary: str,
    prompt_text: str,
) -> None:
    files = _assignment_run_file_paths(root, ticket_id, run_id)
    started_at = iso_ts(now_local())
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    agent_messages: list[str] = []
    exit_code = 1
    failure_message = ""
    observed_result_lock = threading.Lock()
    observed_result_payload: dict[str, Any] = {}
    observed_turn_completed_at = 0.0
    forced_result_short_circuit = False
    activity_lock = threading.Lock()
    last_activity_monotonic = 0.0

    def record_observed_result(payload: dict[str, Any]) -> None:
        nonlocal observed_result_payload
        if not isinstance(payload, dict) or not payload:
            return
        with observed_result_lock:
            observed_result_payload = dict(payload)

    def mark_observed_turn_completed() -> None:
        nonlocal observed_turn_completed_at
        with observed_result_lock:
            if observed_result_payload:
                observed_turn_completed_at = time.monotonic()

    def last_observed_result_payload() -> dict[str, Any]:
        with observed_result_lock:
            return dict(observed_result_payload)

    def observed_turn_completed_at_monotonic() -> float:
        with observed_result_lock:
            return float(observed_turn_completed_at or 0.0)

    def mark_activity(activity_monotonic: float | None = None) -> None:
        nonlocal last_activity_monotonic
        stamp = float(activity_monotonic or time.monotonic())
        with activity_lock:
            last_activity_monotonic = stamp

    def last_activity_monotonic_value() -> float:
        with activity_lock:
            return float(last_activity_monotonic or 0.0)

    def read_stream(name: str, pipe: Any, collector: list[str]) -> None:
        if pipe is None:
            return
        try:
            for line in iter(pipe.readline, ""):
                if line == "":
                    break
                mark_activity()
                collector.append(line)
                _append_assignment_run_text(files[name], line)
                message_text = line.rstrip("\n")
                detail: dict[str, Any] = {}
                event_type = name
                if name == "stdout":
                    try:
                        event = json.loads(message_text)
                    except Exception:
                        event = None
                    if isinstance(event, dict):
                        event_type = str(event.get("type") or "stdout_event").strip() or "stdout_event"
                        agent_message_text = _assignment_extract_agent_message_text(event)
                        message_text = agent_message_text or str(event.get("message") or message_text)
                        if message_text and agent_message_text:
                            agent_messages.append(message_text)
                            payload_candidates = _assignment_extract_json_objects(message_text)
                            if payload_candidates:
                                record_observed_result(payload_candidates[-1])
                        if event_type == "turn.completed":
                            mark_observed_turn_completed()
                        detail = event
                created_at = iso_ts(now_local())
                _append_assignment_run_event(
                    files["events"],
                    event_type=event_type,
                    message=message_text or f"{name} 输出",
                    created_at=created_at,
                    detail=detail,
                )
                _assignment_touch_run_latest_event(
                    root,
                    ticket_id=ticket_id,
                    run_id=run_id,
                    latest_event=message_text or f"{name} 输出",
                    latest_event_at=created_at,
                )
        except (OSError, ValueError):
            return

    run_record = _assignment_load_run_record(root, ticket_id=ticket_id, run_id=run_id)
    attempt_number = 0
    while True:
        attempt_number += 1
        exit_code = 1
        failure_message = ""
        forced_result_short_circuit = False
        with observed_result_lock:
            observed_result_payload = {}
            observed_turn_completed_at = 0.0
        attempt_started_at = iso_ts(now_local())
        attempt_started_monotonic = time.monotonic()
        mark_activity(attempt_started_monotonic)
        last_heartbeat_monotonic = attempt_started_monotonic
        attempt_stdout_index = len(stdout_chunks)
        attempt_stderr_index = len(stderr_chunks)
        attempt_agent_message_index = len(agent_messages)
        if run_record:
            run_record["status"] = "running"
            run_record["latest_event"] = "Provider 已启动，执行中。"
            run_record["latest_event_at"] = attempt_started_at
            run_record["updated_at"] = attempt_started_at
            _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record, sync_index=False)
        _append_assignment_run_event(
            files["events"],
            event_type="provider_start",
            message="Provider 已启动。",
            created_at=attempt_started_at,
            detail={
                "command_summary": command_summary,
                "attempt": attempt_number,
            },
        )
        proc: subprocess.Popen[str] | None = None
        try:
            proc = subprocess.Popen(
                command,
                cwd=workspace_path.as_posix(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            if run_record:
                run_record["provider_pid"] = max(0, int(getattr(proc, "pid", 0) or 0))
                run_record["updated_at"] = iso_ts(now_local())
                _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record, sync_index=False)
            _register_assignment_run_process(run_id, proc)
            assert proc.stdin is not None
            proc.stdin.write(prompt_text)
            proc.stdin.write("\n")
            proc.stdin.close()
            t_out = threading.Thread(target=read_stream, args=("stdout", proc.stdout, stdout_chunks), daemon=True)
            t_err = threading.Thread(target=read_stream, args=("stderr", proc.stderr, stderr_chunks), daemon=True)
            t_out.start()
            t_err.start()
            execution_timeout_s = _assignment_execution_activity_timeout_s()
            final_result_grace_s = _assignment_final_result_exit_grace_seconds()
            while True:
                try:
                    exit_code = int(proc.wait(timeout=1) or 0)
                    break
                except subprocess.TimeoutExpired:
                    now_monotonic = time.monotonic()
                    if (now_monotonic - last_heartbeat_monotonic) >= float(DEFAULT_ASSIGNMENT_EVENT_STREAM_KEEPALIVE_S):
                        heartbeat_at = iso_ts(now_local())
                        _assignment_touch_run_heartbeat(
                            root,
                            ticket_id=ticket_id,
                            run_id=run_id,
                            heartbeat_at=heartbeat_at,
                        )
                        last_heartbeat_monotonic = now_monotonic
                    ready_at = observed_turn_completed_at_monotonic()
                    if ready_at > 0 and (now_monotonic - ready_at) >= final_result_grace_s:
                        forced_result_short_circuit = True
                        _append_assignment_run_event(
                            files["events"],
                            event_type="provider_exit_forced",
                            message="已观测到最终结果，provider 超时未退出，执行强制收敛。",
                            created_at=iso_ts(now_local()),
                            detail={"grace_seconds": final_result_grace_s},
                        )
                        _terminate_assignment_process(proc)
                        try:
                            proc.wait(timeout=3)
                        except Exception:
                            pass
                        exit_code = 0
                        break
                    last_activity_at = last_activity_monotonic_value()
                    inactivity_age_s = _assignment_execution_activity_age_seconds(
                        last_activity_monotonic=last_activity_at,
                        now_monotonic=now_monotonic,
                    )
                    if _assignment_execution_activity_timed_out(
                        last_activity_monotonic=last_activity_at,
                        now_monotonic=now_monotonic,
                        timeout_s=execution_timeout_s,
                    ):
                        failure_message = _assignment_execution_timeout_message(execution_timeout_s)
                        _append_assignment_run_event(
                            files["events"],
                            event_type="execution_timeout",
                            message="执行超时，已终止 provider。",
                            created_at=iso_ts(now_local()),
                            detail={
                                "timeout_seconds": execution_timeout_s,
                                "inactivity_seconds": round(inactivity_age_s, 3),
                            },
                        )
                        _terminate_assignment_process(proc)
                        try:
                            proc.wait(timeout=3)
                        except Exception:
                            pass
                        exit_code = 124
                        break
            t_out.join(timeout=2)
            t_err.join(timeout=2)
        except Exception as exc:
            failure_message = f"assignment execution exception: {exc}"
            stderr_chunks.append(failure_message + "\n")
        finally:
            _unregister_assignment_run_process(run_id)
            if proc is not None:
                try:
                    if proc.stdout is not None:
                        proc.stdout.close()
                    if proc.stderr is not None:
                        proc.stderr.close()
                except Exception:
                    pass
        attempt_stdout_text = "".join(stdout_chunks[attempt_stdout_index:])
        attempt_stderr_text = "".join(stderr_chunks[attempt_stderr_index:])
        observed_payload = last_observed_result_payload()
        attempt_elapsed_seconds = time.monotonic() - attempt_started_monotonic
        stream_disconnected = _assignment_stream_disconnect_detected(
            attempt_stdout_text,
            attempt_stderr_text,
        )
        if exit_code != 0 and not failure_message:
            if stream_disconnected:
                failure_message = "Codex 连接中断。"
            else:
                failure_message = (
                    _short_assignment_text(attempt_stderr_text, 500)
                    or f"assignment execution failed with exit={exit_code}"
                )
        current_run_status = str(
            (_assignment_load_run_record(root, ticket_id=ticket_id, run_id=run_id) or {}).get("status") or ""
        ).strip().lower()
        if current_run_status == "cancelled":
            break
        if _assignment_should_retry_transient_stream_disconnect_failure(
            exit_code=exit_code,
            stdout_text=attempt_stdout_text,
            stderr_text=attempt_stderr_text,
            observed_payload=observed_payload,
            elapsed_seconds=attempt_elapsed_seconds,
            attempt_number=attempt_number,
        ):
            _append_assignment_run_event(
                files["events"],
                event_type="provider_retry",
                message="Provider 连接中断，已自动重试。",
                created_at=iso_ts(now_local()),
                detail={
                    "attempt": attempt_number,
                    "next_attempt": attempt_number + 1,
                    "exit_code": int(exit_code or 0),
                    "reason_code": "codex_stream_disconnected",
                },
            )
            _assignment_touch_run_latest_event(
                root,
                ticket_id=ticket_id,
                run_id=run_id,
                latest_event="Provider 连接中断，自动重试中。",
                latest_event_at=iso_ts(now_local()),
            )
            continue
        if _assignment_should_retry_transient_startup_failure(
            exit_code=exit_code,
            stdout_text=attempt_stdout_text,
            stderr_text=attempt_stderr_text,
            agent_message_count=len(agent_messages) - attempt_agent_message_index,
            observed_payload=observed_payload,
            elapsed_seconds=attempt_elapsed_seconds,
            attempt_number=attempt_number,
        ):
            _append_assignment_run_event(
                files["events"],
                event_type="provider_retry",
                message="Provider 启动后瞬时失败，已自动重试。",
                created_at=iso_ts(now_local()),
                detail={
                    "attempt": attempt_number,
                    "next_attempt": attempt_number + 1,
                    "exit_code": int(exit_code or 0),
                    "stderr": _short_assignment_text(attempt_stderr_text, 300),
                },
            )
            _assignment_touch_run_latest_event(
                root,
                ticket_id=ticket_id,
                run_id=run_id,
                latest_event="Provider 启动后瞬时失败，自动重试中。",
                latest_event_at=iso_ts(now_local()),
            )
            continue
        break
    stdout_text = "".join(stdout_chunks)
    stderr_text = "".join(stderr_chunks)
    fallback_text = agent_messages[-1] if agent_messages else stdout_text.strip()
    parsed_candidates: list[dict[str, Any]] = []
    for message in agent_messages:
        parsed_candidates.extend(_assignment_extract_json_objects(message))
    observed_payload = last_observed_result_payload()
    if observed_payload:
        parsed_candidates.append(observed_payload)
    if not parsed_candidates:
        parsed_candidates.extend(_assignment_extract_json_objects(stdout_text))
    result_payload = _normalize_assignment_execution_result(
        parsed_candidates[-1] if parsed_candidates else {},
        fallback_text=fallback_text,
        node={"node_id": node_id},
    )
    if forced_result_short_circuit:
        result_payload["result_summary"] = (
            str(result_payload.get("result_summary") or "").strip()
            or "执行完成，provider 已被强制收敛。"
        )
    if failure_message:
        current_summary = str(result_payload.get("result_summary") or "").strip()
        if not current_summary or current_summary == "执行完成":
            result_payload["result_summary"] = failure_message
    _write_assignment_run_json(files["result"], result_payload)
    _write_assignment_run_text(files["result_markdown"], str(result_payload.get("artifact_markdown") or "").strip())
    final_result_message = str(result_payload.get("result_summary") or "").strip() or "执行结束"
    if failure_message:
        final_result_message = failure_message
    _append_assignment_run_event(
        files["events"],
        event_type="final_result",
        message=final_result_message,
        created_at=iso_ts(now_local()),
        detail={"exit_code": exit_code},
    )
    _finalize_assignment_execution_run(
        root,
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        exit_code=exit_code,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        result_payload=result_payload,
        failure_message=failure_message,
    )
