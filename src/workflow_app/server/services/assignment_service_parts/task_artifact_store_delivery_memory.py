from __future__ import annotations


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
