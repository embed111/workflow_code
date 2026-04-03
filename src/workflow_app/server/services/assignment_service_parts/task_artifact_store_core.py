from __future__ import annotations

from .work_record_store import sync_assignment_task_bundle as sync_assignment_task_bundle_index


ASSIGNMENT_TASK_RECORD_TYPE = "assignment_task"
ASSIGNMENT_RUN_RECORD_TYPE = "assignment_run"
ASSIGNMENT_AUDIT_RECORD_TYPE = "assignment_audit"
ASSIGNMENT_TASK_SCHEMA_VERSION = 1
ASSIGNMENT_AUDIT_FILE_NAME = "audit.jsonl"
ASSIGNMENT_TASK_FILE_NAME = "task.json"
ASSIGNMENT_TASK_STRUCTURE_FILE_NAME = "TASK_STRUCTURE.md"
ASSIGNMENT_DELIVERY_INFO_FILE_NAME = "DELIVERY_INFO.json"
ASSIGNMENT_DELIVERY_ROOT_DIRNAME = "delivery"
ASSIGNMENT_HISTORICAL_RUN_SUMMARY = "历史运行导入自任务产物目录"
_ASSIGNMENT_REPAIRABLE_SUFFIXES = {".html", ".json", ".jsonl", ".log", ".md", ".txt"}
_ASSIGNMENT_ANY_TASK_PATH_RE = re.compile(
    r"(?P<prefix>(?:[A-Za-z]:)?[^\s\"'`<>#]*?)?[\\/](?P<kind>tasks|workspace[\\/]+assignments)[\\/](?P<ticket>asg-[^\\/\s\"'`<>#]+)(?P<suffix>(?:[\\/][^\s\"'`<>#]+)*(?:#[^\s\"'`<>]+)?)"
)
_ASSIGNMENT_TASKS_ROOT_RE = re.compile(
    r"(?P<prefix>(?:[A-Za-z]:)?[^\s\"'`<>#]*?)?[\\/]tasks(?P<suffix>(?:#[^\s\"'`<>]+)?)"
)
_ASSIGNMENT_ROOT_STRUCTURE_RE = re.compile(
    r"(?P<prefix>(?:[A-Za-z]:)?[^\s\"'`<>#]*?)?[\\/]TASKS_STRUCTURE\.md(?P<suffix>(?:#[^\s\"'`<>]+)?)"
)


def _assignment_artifact_root(root: Path) -> Path:
    artifact_root = resolve_artifact_root_path(root)
    artifact_root, _tasks_root = ensure_artifact_root_dirs(artifact_root)
    return artifact_root


def _assignment_workspace_root(root: Path) -> Path:
    return (_assignment_artifact_root(root) / "tasks").resolve(strict=False)


def _assignment_tasks_root(root: Path) -> Path:
    return _assignment_workspace_root(root)


def _assignment_ticket_workspace_dir(root: Path, ticket_id: str) -> Path:
    return (_assignment_tasks_root(root) / str(ticket_id or "").strip()).resolve(strict=False)


def _assignment_graph_record_path(root: Path, ticket_id: str) -> Path:
    return _assignment_ticket_workspace_dir(root, ticket_id) / ASSIGNMENT_TASK_FILE_NAME


def _assignment_legacy_graph_record_path(root: Path, ticket_id: str) -> Path:
    return _assignment_ticket_workspace_dir(root, ticket_id) / "graph.json"


def _assignment_node_record_path(root: Path, ticket_id: str, node_id: str) -> Path:
    return _assignment_ticket_workspace_dir(root, ticket_id) / "nodes" / (str(node_id or "").strip() + ".json")


def _assignment_run_trace_dir(root: Path, ticket_id: str, run_id: str) -> Path:
    return (_assignment_ticket_workspace_dir(root, ticket_id) / "runs" / str(run_id or "").strip()).resolve(strict=False)


def _assignment_run_file_paths(root: Path, ticket_id: str, run_id: str) -> dict[str, Path]:
    trace_dir = _assignment_run_trace_dir(root, ticket_id, run_id)
    return {
        "trace_dir": trace_dir,
        "meta": trace_dir / "run.json",
        "prompt": trace_dir / "prompt.txt",
        "stdout": trace_dir / "stdout.txt",
        "stderr": trace_dir / "stderr.txt",
        "result": trace_dir / "result.json",
        "result_markdown": trace_dir / "result.md",
        "events": trace_dir / "events.log",
    }


def _assignment_audit_log_path(root: Path, ticket_id: str) -> Path:
    return _assignment_ticket_workspace_dir(root, ticket_id) / "audit" / ASSIGNMENT_AUDIT_FILE_NAME


def _assignment_task_structure_path(root: Path, ticket_id: str) -> Path:
    return _assignment_ticket_workspace_dir(root, ticket_id) / ASSIGNMENT_TASK_STRUCTURE_FILE_NAME


def _assignment_artifacts_root(root: Path, ticket_id: str) -> Path:
    return _assignment_ticket_workspace_dir(root, ticket_id) / "artifacts"


def _normalize_path_segment(raw: Any, fallback: str) -> str:
    text = str(raw or "").strip()
    if not text:
        text = str(fallback or "").strip()
    if not text:
        text = "item"
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text).strip().strip(".")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:96] or "item"


def _artifact_label_text(node: dict[str, Any]) -> str:
    return (
        str(node.get("expected_artifact") or "").strip()
        or str(node.get("node_name") or "").strip()
        or str(node.get("node_id") or "").strip()
        or "artifact"
    )


def _normalize_artifact_extension(raw: Any, fallback: str = ".html") -> str:
    text = str(raw or "").strip()
    if text and not text.startswith("."):
        text = "." + text
    if text and re.fullmatch(r"\.[A-Za-z0-9_-]{1,16}", text):
        return text
    return fallback


def _artifact_file_extension_from_body(raw: Any) -> str:
    text = str(raw or "").lstrip()
    if not text:
        return ".html"
    head = text[:512].lower()
    if head.startswith("<!doctype html") or head.startswith("<html"):
        return ".html"
    return ".html"


def _artifact_preview_content_type(path: Path) -> str:
    suffix = str(path.suffix or "").strip().lower()
    if suffix in {".html", ".htm"}:
        return "text/html; charset=utf-8"
    if suffix == ".md":
        return "text/markdown; charset=utf-8"
    if suffix == ".json":
        return "application/json; charset=utf-8"
    if suffix == ".jsonl":
        return "application/x-ndjson; charset=utf-8"
    if suffix == ".csv":
        return "text/csv; charset=utf-8"
    if suffix == ".svg":
        return "image/svg+xml; charset=utf-8"
    if suffix in {".xml"}:
        return "application/xml; charset=utf-8"
    if suffix in {".log", ".text", ".txt"}:
        return "text/plain; charset=utf-8"
    return "text/plain; charset=utf-8"


def _normalize_artifact_file_name(raw: Any, *, fallback: str, default_extension: str = ".html") -> str:
    candidate = Path(str(raw or "").strip().replace("\\", "/")).name.strip().strip(".")
    if not candidate:
        candidate = str(fallback or "").strip()
    suffixes = [part for part in Path(candidate).suffixes if re.fullmatch(r"\.[A-Za-z0-9_-]{1,16}", part)]
    stem_source = candidate[:-sum(len(part) for part in suffixes)] if suffixes else candidate
    stem = _normalize_path_segment(stem_source, fallback)
    suffix = "".join(suffixes) or _normalize_artifact_extension(default_extension)
    return stem + suffix


def _artifact_label_file_name(
    node: dict[str, Any],
    *,
    source_name: str = "",
    preferred_extension: str = ".html",
) -> str:
    label = _artifact_label_text(node)
    return _normalize_artifact_file_name(
        source_name or label,
        fallback=label,
        default_extension=preferred_extension,
    )


def _node_artifact_base_dir(root: Path, node: dict[str, Any]) -> Path:
    return _assignment_artifacts_root(root, str(node.get("ticket_id") or "").strip()) / str(node.get("node_id") or "").strip()


def _node_artifact_output_dir(root: Path, node: dict[str, Any]) -> Path:
    return _node_artifact_base_dir(root, node) / "output"


def _node_artifact_delivery_dir(root: Path, node: dict[str, Any]) -> Path | None:
    if str(node.get("delivery_mode") or "").strip().lower() != "specified":
        return None
    receiver = _normalize_path_segment(
        str(node.get("delivery_receiver_agent_id") or "").strip() or "receiver",
        "receiver",
    )
    return _node_artifact_base_dir(root, node) / "delivery" / receiver


def _node_artifact_file_paths(
    root: Path,
    node: dict[str, Any],
    *,
    file_name: str = "",
    preferred_extension: str = ".html",
) -> list[Path]:
    ticket_id = str(node.get("ticket_id") or "").strip()
    node_id = str(node.get("node_id") or "").strip()
    if not ticket_id or not node_id:
        return []
    target_name = _artifact_label_file_name(
        node,
        source_name=file_name,
        preferred_extension=preferred_extension,
    )
    paths = [_node_artifact_output_dir(root, node) / target_name]
    delivery_dir = _node_artifact_delivery_dir(root, node)
    if isinstance(delivery_dir, Path):
        delivery_path = delivery_dir / target_name
        if delivery_path not in paths:
            paths.append(delivery_path)
    return paths


def _node_delivery_target_agent_id(node: dict[str, Any]) -> str:
    if str(node.get("delivery_mode") or "").strip().lower() == "specified":
        receiver_agent_id = str(node.get("delivery_receiver_agent_id") or "").strip()
        if receiver_agent_id:
            return receiver_agent_id
    return str(node.get("assigned_agent_id") or "").strip()


def _node_delivery_target_agent_name(node: dict[str, Any]) -> str:
    if str(node.get("delivery_mode") or "").strip().lower() == "specified":
        receiver_agent_name = str(
            node.get("delivery_receiver_agent_name") or node.get("delivery_receiver_agent_id") or ""
        ).strip()
        if receiver_agent_name:
            return receiver_agent_name
    return str(node.get("assigned_agent_name") or node.get("assigned_agent_id") or "").strip()


def _node_delivery_target_dir_name(node: dict[str, Any]) -> str:
    return _normalize_path_segment(
        _node_delivery_target_agent_name(node) or _node_delivery_target_agent_id(node) or "agent",
        "agent",
    )


def _node_delivery_task_dir_name(node: dict[str, Any]) -> str:
    return _normalize_path_segment(
        str(node.get("node_name") or "").strip() or str(node.get("node_id") or "").strip() or "task",
        "task",
    )


def _node_delivery_inbox_relative_path(node: dict[str, Any]) -> str:
    return (
        Path(ASSIGNMENT_DELIVERY_ROOT_DIRNAME)
        / _node_delivery_target_dir_name(node)
        / _node_delivery_task_dir_name(node)
    ).as_posix()


def _node_delivery_info_relative_path(node: dict[str, Any]) -> str:
    return (Path(_node_delivery_inbox_relative_path(node)) / ASSIGNMENT_DELIVERY_INFO_FILE_NAME).as_posix()


def _assignment_delivery_root(root: Path) -> Path:
    return (_assignment_artifact_root(root) / ASSIGNMENT_DELIVERY_ROOT_DIRNAME).resolve(strict=False)


def _node_delivery_inbox_dir(root: Path, node: dict[str, Any]) -> Path:
    return (
        _assignment_delivery_root(root)
        / _node_delivery_target_dir_name(node)
        / _node_delivery_task_dir_name(node)
    ).resolve(strict=False)


def _node_delivery_info_path(root: Path, node: dict[str, Any]) -> Path:
    return _node_delivery_inbox_dir(root, node) / ASSIGNMENT_DELIVERY_INFO_FILE_NAME


def _node_delivery_inbox_file_paths(
    root: Path,
    node: dict[str, Any],
    *,
    file_name: str = "",
    preferred_extension: str = ".html",
) -> list[Path]:
    ticket_id = str(node.get("ticket_id") or "").strip()
    node_id = str(node.get("node_id") or "").strip()
    if not ticket_id or not node_id:
        return []
    target_name = _artifact_label_file_name(
        node,
        source_name=file_name,
        preferred_extension=preferred_extension,
    )
    return [_node_delivery_inbox_dir(root, node) / target_name]


def _artifact_path_file_names(paths: list[Any]) -> list[str]:
    file_names: list[str] = []
    seen: set[str] = set()
    for raw in list(paths or []):
        text = str(raw or "").strip()
        if not text:
            continue
        file_name = Path(text.replace("\\", "/")).name.strip()
        if not file_name:
            continue
        key = file_name.lower()
        if key in seen:
            continue
        seen.add(key)
        file_names.append(file_name)
    return file_names


def _node_delivery_inbox_relative_paths(
    node: dict[str, Any],
    artifact_paths: list[Any] | None = None,
) -> list[str]:
    base = Path(_node_delivery_inbox_relative_path(node))
    names = _artifact_path_file_names(
        list(artifact_paths if artifact_paths is not None else node.get("artifact_paths") or [])
    )
    return [(base / name).as_posix() for name in names]


def _assignment_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import time as _time
    import uuid as _uuid

    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    last_error: BaseException | None = None
    for attempt in range(6):
        tmp = path.with_name(path.name + "." + _uuid.uuid4().hex + ".tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
        except OSError as exc:
            if int(getattr(exc, "winerror", 0) or 0) != 5:
                raise
            last_error = exc
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
        _time.sleep(0.05 * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"assignment json write failed: {path.as_posix()}")


def _assignment_read_json(path: Path, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return dict(fallback or {})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(fallback or {})
    return payload if isinstance(payload, dict) else dict(fallback or {})


def _assignment_append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _assignment_read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            text = str(line or "").strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except Exception:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    except Exception:
        return []
    return rows


def _assignment_canonical_task_path_text(root: Path, ticket_id: str, suffix: str) -> str:
    base = _assignment_tasks_root(root) / str(ticket_id or "").strip()
    text = str(suffix or "").replace("\\", "/")
    fragment = ""
    if "#" in text:
        text, fragment = text.split("#", 1)
        fragment = "#" + fragment
    text = text.lstrip("/")
    target = (base / text).resolve(strict=False) if text else base.resolve(strict=False)
    return target.as_posix() + fragment


def _assignment_rewrite_legacy_text(root: Path, text: str) -> str:
    raw = str(text or "")
    if not raw:
        return ""

    def replace_path(match: re.Match[str]) -> str:
        return _assignment_canonical_task_path_text(
            root,
            str(match.group("ticket") or "").strip(),
            str(match.group("suffix") or ""),
        )

    def replace_tasks_root(match: re.Match[str]) -> str:
        suffix = str(match.group("suffix") or "")
        fragment = ""
        if suffix.startswith("#"):
            fragment = suffix
        return _assignment_tasks_root(root).resolve(strict=False).as_posix() + fragment

    def replace_root_structure(match: re.Match[str]) -> str:
        suffix = str(match.group("suffix") or "")
        fragment = ""
        if suffix.startswith("#"):
            fragment = suffix
        return artifact_root_structure_file_path(_assignment_artifact_root(root)).as_posix() + fragment

    updated = _ASSIGNMENT_ANY_TASK_PATH_RE.sub(replace_path, raw)
    updated = _ASSIGNMENT_ROOT_STRUCTURE_RE.sub(replace_root_structure, updated)
    updated = _ASSIGNMENT_TASKS_ROOT_RE.sub(replace_tasks_root, updated)
    updated = updated.replace(
        "legacy run imported from workspace/assignments",
        ASSIGNMENT_HISTORICAL_RUN_SUMMARY,
    )
    updated = updated.replace(
        "legacy run imported from historical task workspace",
        ASSIGNMENT_HISTORICAL_RUN_SUMMARY,
    )
    updated = updated.replace("workspace/assignments", "tasks")
    updated = updated.replace("workspace\\assignments", "tasks")
    return updated


def _assignment_repairable_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.name == ASSIGNMENT_TASK_STRUCTURE_FILE_NAME:
        return False
    return path.suffix.lower() in _ASSIGNMENT_REPAIRABLE_SUFFIXES


def _assignment_rewrite_text_file(path: Path, *, transform: Any) -> bool:
    try:
        original = path.read_text(encoding="utf-8")
    except Exception:
        return False
    updated = str(transform(original) or "")
    if updated == original:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def _assignment_task_structure_needs_refresh(root: Path, ticket_id: str) -> bool:
    path = _assignment_task_structure_path(root, ticket_id)
    if not path.exists() or not path.is_file():
        return True
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return True
    return "audit_file:" in text or "audit/audit.jsonl" in text


def _assignment_repair_ticket_files(root: Path, ticket_id: str) -> bool:
    task_dir = _assignment_ticket_workspace_dir(root, ticket_id)
    if not task_dir.exists() or not task_dir.is_dir():
        return False
    metadata_files: list[Path] = []
    graph_path = _assignment_graph_record_path(root, ticket_id)
    if graph_path.exists():
        metadata_files.append(graph_path)
    audit_path = _assignment_audit_log_path(root, ticket_id)
    if audit_path.exists():
        metadata_files.append(audit_path)
    nodes_root = task_dir / "nodes"
    if nodes_root.exists() and nodes_root.is_dir():
        metadata_files.extend(
            path
            for path in sorted(nodes_root.iterdir(), key=lambda item: item.name.lower())
            if path.is_file() and path.suffix.lower() == ".json"
        )
    runs_root = task_dir / "runs"
    if runs_root.exists() and runs_root.is_dir():
        metadata_files.extend(
            run_dir / "run.json"
            for run_dir in sorted(runs_root.iterdir(), key=lambda item: item.name.lower())
            if run_dir.is_dir() and (run_dir / "run.json").exists()
        )
    needs_repair = _assignment_task_structure_needs_refresh(root, ticket_id)
    for path in metadata_files:
        try:
            original = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if _assignment_rewrite_legacy_text(root, original) != original:
            needs_repair = True
            break
    if not needs_repair:
        return False
    changed = False
    for path in sorted(task_dir.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not _assignment_repairable_file(path):
            continue
        changed = _assignment_rewrite_text_file(
            path,
            transform=lambda text: _assignment_rewrite_legacy_text(root, text),
        ) or changed
    if changed or _assignment_task_structure_needs_refresh(root, ticket_id):
        _assignment_refresh_structure_guides(root, ticket_id)
    return changed


def _assignment_copy_or_note(src: Path, dst: Path, *, note_title: str, note_lines: list[str]) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists() and src.is_file():
        shutil.copy2(src, dst)
        return
    payload = [f"# {note_title}", "", *note_lines]
    dst.write_text("\n".join(payload).strip() + "\n", encoding="utf-8")


def _assignment_run_prompt_field(prompt_text: str, field_name: str) -> str:
    text = str(prompt_text or "")
    if not text:
        return ""
    match = re.search(rf"(?im)^-\s*{re.escape(field_name)}\s*:\s*(.+?)\s*$", text)
    if not match:
        return ""
    return str(match.group(1) or "").strip()


def _assignment_tail_event_summary(path: Path) -> tuple[str, str]:
    events = _tail_assignment_run_events(path)
    if not events:
        return "", ""
    latest = events[-1]
    return str(latest.get("message") or "").strip(), str(latest.get("created_at") or "").strip()


def _assignment_run_status_from_node(node: dict[str, Any]) -> str:
    status = str(node.get("status") or "").strip().lower()
    if status == "running":
        return "running"
    if status == "failed":
        return "failed"
    if status == "succeeded":
        return "succeeded"
    return "starting"


def _assignment_build_task_record(
    *,
    ticket_id: str,
    graph_name: str,
    source_workflow: str,
    summary: str,
    review_mode: str,
    global_concurrency_limit: int,
    is_test_data: bool,
    external_request_id: str,
    scheduler_state: str,
    pause_note: str,
    created_at: str,
    updated_at: str,
    edges: list[dict[str, Any]],
    record_state: str = "active",
) -> dict[str, Any]:
    return {
        "record_type": ASSIGNMENT_TASK_RECORD_TYPE,
        "schema_version": ASSIGNMENT_TASK_SCHEMA_VERSION,
        "record_state": str(record_state or "active"),
        "ticket_id": str(ticket_id or "").strip(),
        "graph_name": str(graph_name or "").strip(),
        "source_workflow": str(source_workflow or "").strip(),
        "summary": str(summary or "").strip(),
        "review_mode": str(review_mode or "none").strip() or "none",
        "global_concurrency_limit": int(global_concurrency_limit or DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT),
        "is_test_data": bool(is_test_data),
        "external_request_id": str(external_request_id or "").strip(),
        "scheduler_state": str(scheduler_state or "idle").strip().lower() or "idle",
        "pause_note": str(pause_note or "").strip(),
        "created_at": str(created_at or "").strip(),
        "updated_at": str(updated_at or created_at or "").strip(),
        "deleted_at": "",
        "deleted_reason": "",
        "edges": list(edges or []),
    }


def _assignment_build_node_record(
    *,
    ticket_id: str,
    node_id: str,
    node_name: str,
    source_schedule_id: str,
    planned_trigger_at: str,
    trigger_instance_id: str,
    trigger_rule_summary: str,
    assigned_agent_id: str,
    assigned_agent_name: str,
    node_goal: str,
    expected_artifact: str,
    delivery_mode: str,
    delivery_receiver_agent_id: str,
    delivery_receiver_agent_name: str,
    artifact_delivery_status: str,
    artifact_delivered_at: str,
    artifact_paths: list[str],
    status: str,
    priority: int,
    completed_at: str,
    success_reason: str,
    result_ref: str,
    failure_reason: str,
    created_at: str,
    updated_at: str,
    upstream_node_ids: list[str],
    downstream_node_ids: list[str],
    record_state: str = "active",
    delete_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_delivery_mode = _normalize_delivery_mode(delivery_mode)
    assigned_agent_id_text = str(assigned_agent_id or "").strip()
    assigned_agent_name_text = str(assigned_agent_name or assigned_agent_id or "").strip()
    delivery_receiver_agent_id_text = str(delivery_receiver_agent_id or "").strip()
    delivery_receiver_agent_name_text = str(delivery_receiver_agent_name or "").strip()
    delivery_target_agent_id = (
        delivery_receiver_agent_id_text
        if normalized_delivery_mode == "specified" and delivery_receiver_agent_id_text
        else assigned_agent_id_text
    )
    delivery_target_agent_name = (
        (delivery_receiver_agent_name_text or delivery_receiver_agent_id_text)
        if normalized_delivery_mode == "specified" and (delivery_receiver_agent_name_text or delivery_receiver_agent_id_text)
        else assigned_agent_name_text
    )
    return {
        "record_type": "assignment_node",
        "schema_version": ASSIGNMENT_TASK_SCHEMA_VERSION,
        "record_state": str(record_state or "active"),
        "ticket_id": str(ticket_id or "").strip(),
        "node_id": str(node_id or "").strip(),
        "node_name": str(node_name or "").strip(),
        "source_schedule_id": str(source_schedule_id or "").strip(),
        "planned_trigger_at": str(planned_trigger_at or "").strip(),
        "trigger_instance_id": str(trigger_instance_id or "").strip(),
        "trigger_rule_summary": str(trigger_rule_summary or "").strip(),
        "assigned_agent_id": assigned_agent_id_text,
        "assigned_agent_name": assigned_agent_name_text,
        "node_goal": str(node_goal or "").strip(),
        "expected_artifact": str(expected_artifact or "").strip(),
        "delivery_mode": normalized_delivery_mode,
        "delivery_mode_text": _delivery_mode_text(delivery_mode),
        "delivery_receiver_agent_id": delivery_receiver_agent_id_text,
        "delivery_receiver_agent_name": delivery_receiver_agent_name_text,
        "delivery_target_agent_id": delivery_target_agent_id,
        "delivery_target_agent_name": delivery_target_agent_name,
        "artifact_delivery_status": _normalize_artifact_delivery_status(artifact_delivery_status),
        "artifact_delivery_status_text": _artifact_delivery_status_text(artifact_delivery_status),
        "artifact_delivered_at": str(artifact_delivered_at or "").strip(),
        "artifact_paths": list(artifact_paths or []),
        "status": str(status or "pending").strip().lower() or "pending",
        "status_text": _node_status_text(status or "pending"),
        "priority": int(1 if priority in (None, "") else priority),
        "priority_label": assignment_priority_label(priority),
        "completed_at": str(completed_at or "").strip(),
        "success_reason": str(success_reason or "").strip(),
        "result_ref": str(result_ref or "").strip(),
        "failure_reason": str(failure_reason or "").strip(),
        "created_at": str(created_at or "").strip(),
        "updated_at": str(updated_at or created_at or "").strip(),
        "upstream_node_ids": list(upstream_node_ids or []),
        "downstream_node_ids": list(downstream_node_ids or []),
        "delete_meta": dict(delete_meta or {}),
    }


def _assignment_build_run_record(
    *,
    run_id: str,
    ticket_id: str,
    node_id: str,
    provider: str,
    workspace_path: str,
    status: str,
    command_summary: str,
    prompt_ref: str,
    stdout_ref: str,
    stderr_ref: str,
    result_ref: str,
    latest_event: str,
    latest_event_at: str,
    exit_code: int,
    started_at: str,
    finished_at: str,
    created_at: str,
    updated_at: str,
    provider_pid: Any = 0,
) -> dict[str, Any]:
    return {
        "record_type": ASSIGNMENT_RUN_RECORD_TYPE,
        "schema_version": ASSIGNMENT_TASK_SCHEMA_VERSION,
        "run_id": str(run_id or "").strip(),
        "ticket_id": str(ticket_id or "").strip(),
        "node_id": str(node_id or "").strip(),
        "provider": str(provider or DEFAULT_ASSIGNMENT_EXECUTION_PROVIDER).strip().lower(),
        "workspace_path": str(workspace_path or "").strip(),
        "status": _normalize_run_status(status),
        "command_summary": str(command_summary or "").strip(),
        "prompt_ref": str(prompt_ref or "").strip(),
        "stdout_ref": str(stdout_ref or "").strip(),
        "stderr_ref": str(stderr_ref or "").strip(),
        "result_ref": str(result_ref or "").strip(),
        "latest_event": str(latest_event or "").strip(),
        "latest_event_at": str(latest_event_at or "").strip(),
        "exit_code": int(exit_code or 0),
        "started_at": str(started_at or "").strip(),
        "finished_at": str(finished_at or "").strip(),
        "created_at": str(created_at or "").strip(),
        "updated_at": str(updated_at or created_at or "").strip(),
        "provider_pid": max(0, int(provider_pid or 0)),
    }


def _assignment_audit_ref(root: Path, ticket_id: str, audit_id: str) -> str:
    return _assignment_audit_log_path(root, ticket_id).as_posix() + "#" + str(audit_id or "").strip()


def _assignment_write_audit_entry(
    root: Path,
    *,
    ticket_id: str,
    node_id: str,
    action: str,
    operator: str,
    reason: str,
    target_status: str,
    detail: dict[str, Any] | None,
    created_at: str,
    sync_index: bool = True,
) -> str:
    audit_id = assignment_audit_id()
    payload = {
        "record_type": ASSIGNMENT_AUDIT_RECORD_TYPE,
        "schema_version": ASSIGNMENT_TASK_SCHEMA_VERSION,
        "audit_id": audit_id,
        "ticket_id": str(ticket_id or "").strip(),
        "node_id": str(node_id or "").strip(),
        "action": str(action or "").strip(),
        "operator": _default_assignment_operator(operator),
        "reason": str(reason or "").strip(),
        "target_status": str(target_status or "").strip(),
        "detail": dict(detail or {}),
        "ref": _assignment_audit_ref(root, ticket_id, audit_id),
        "created_at": str(created_at or "").strip(),
    }
    _assignment_append_jsonl(_assignment_audit_log_path(root, ticket_id), payload)
    if sync_index:
        sync_assignment_task_bundle_index(root, ticket_id)
    return audit_id


def _assignment_load_audit_records(
    root: Path,
    *,
    ticket_id: str,
    node_id: str = "",
    limit: int = 12,
) -> list[dict[str, Any]]:
    rows = _assignment_read_jsonl(_assignment_audit_log_path(root, ticket_id))
    lookup = str(node_id or "").strip()
    if lookup:
        rows = [
            row
            for row in rows
            if str(row.get("node_id") or "").strip() in {"", lookup}
        ]
    rows.sort(
        key=lambda item: (
            str(item.get("created_at") or ""),
            str(item.get("audit_id") or ""),
        ),
        reverse=True,
    )
    return rows[: max(1, int(limit))]


def _assignment_load_run_record(root: Path, *, ticket_id: str, run_id: str) -> dict[str, Any]:
    return _assignment_read_json(_assignment_run_file_paths(root, ticket_id, run_id)["meta"])


def _assignment_write_run_record(
    root: Path,
    *,
    ticket_id: str,
    run_record: dict[str, Any],
    sync_index: bool = True,
) -> None:
    run_id = str(run_record.get("run_id") or "").strip()
    if not run_id:
        raise AssignmentCenterError(400, "run_id required", "assignment_run_id_required")
    _assignment_write_json(_assignment_run_file_paths(root, ticket_id, run_id)["meta"], run_record)
    if sync_index:
        sync_assignment_task_bundle_index(root, ticket_id)
    _assignment_publish_runtime_event(
        ticket_id=ticket_id,
        kind="run",
        node_id=str(run_record.get("node_id") or "").strip(),
        run_id=run_id,
        status=str(run_record.get("status") or "").strip().lower(),
        latest_event=str(run_record.get("latest_event") or "").strip(),
        latest_event_at=str(run_record.get("latest_event_at") or run_record.get("updated_at") or "").strip(),
        event_type="run_record_updated",
    )


def _assignment_load_run_records(root: Path, *, ticket_id: str, node_id: str = "") -> list[dict[str, Any]]:
    runs_root = _assignment_ticket_workspace_dir(root, ticket_id) / "runs"
    if not runs_root.exists() or not runs_root.is_dir():
        return []
    lookup = str(node_id or "").strip()
    rows: list[dict[str, Any]] = []
    for run_dir in sorted(runs_root.iterdir(), key=lambda item: item.name.lower()):
        if not run_dir.is_dir():
            continue
        meta = _assignment_read_json(run_dir / "run.json")
        if not meta:
            continue
        if lookup and str(meta.get("node_id") or "").strip() != lookup:
            continue
        rows.append(meta)
    rows.sort(
        key=lambda item: (
            str(item.get("created_at") or ""),
            str(item.get("run_id") or ""),
        ),
        reverse=True,
    )
    return rows


def _assignment_read_legacy_ticket(root: Path, ticket_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    task_dir = _assignment_ticket_workspace_dir(root, ticket_id)
    graph = _assignment_read_json(task_dir / "graph.json")
    if not graph:
        raise AssignmentCenterError(
            404,
            "assignment graph not found",
            "assignment_graph_not_found",
            {"ticket_id": ticket_id},
        )
    nodes_root = task_dir / "nodes"
    nodes: list[dict[str, Any]] = []
    if nodes_root.exists() and nodes_root.is_dir():
        for path in sorted(nodes_root.iterdir(), key=lambda item: item.name.lower()):
            if not path.is_file() or path.suffix.lower() != ".json":
                continue
            payload = _assignment_read_json(path)
            if payload:
                nodes.append(payload)
    return graph, nodes


def _assignment_edges_from_node_records(node_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    edges: list[dict[str, Any]] = []
    active_node_ids = {
        str(item.get("node_id") or "").strip()
        for item in node_records
        if str(item.get("record_state") or "active").strip().lower() != "deleted"
    }
    for node in node_records:
        node_id = str(node.get("node_id") or "").strip()
        if not node_id or node_id not in active_node_ids:
            continue
        for upstream_id in list(node.get("upstream_node_ids") or []):
            from_id = str(upstream_id or "").strip()
            if not from_id or from_id not in active_node_ids:
                continue
            pair = (from_id, node_id)
            if pair in seen:
                continue
            seen.add(pair)
            edges.append(
                {
                    "from_node_id": from_id,
                    "to_node_id": node_id,
                    "edge_kind": "depends_on",
                    "created_at": str(node.get("created_at") or "").strip(),
                    "record_state": "active",
                }
            )
        for downstream_id in list(node.get("downstream_node_ids") or []):
            to_id = str(downstream_id or "").strip()
            if not to_id or to_id not in active_node_ids:
                continue
            pair = (node_id, to_id)
            if pair in seen:
                continue
            seen.add(pair)
            edges.append(
                {
                    "from_node_id": node_id,
                    "to_node_id": to_id,
                    "edge_kind": "depends_on",
                    "created_at": str(node.get("created_at") or "").strip(),
                    "record_state": "active",
                }
            )
    edges.sort(
        key=lambda item: (
            str(item.get("created_at") or ""),
            str(item.get("from_node_id") or ""),
            str(item.get("to_node_id") or ""),
        )
    )
    return edges


def _assignment_normalize_legacy_artifacts(root: Path, node_record: dict[str, Any]) -> list[str]:
    source_paths = [
        Path(str(item or "").strip()).resolve(strict=False)
        for item in list(node_record.get("artifact_paths") or [])
        if str(item or "").strip()
    ]
    target_paths = _node_artifact_file_paths(root, node_record)
    if not target_paths:
        return [item.as_posix() for item in source_paths if item]
    migrated: list[str] = []
    for index, target_path in enumerate(target_paths):
        source_path = source_paths[min(index, len(source_paths) - 1)] if source_paths else Path("")
        _assignment_copy_or_note(
            source_path,
            target_path,
            note_title="迁移说明",
            note_lines=[
                f"- ticket_id: {str(node_record.get('ticket_id') or '').strip()}",
                f"- node_id: {str(node_record.get('node_id') or '').strip()}",
                f"- legacy_path: {source_path.as_posix() if str(source_path) else '-'}",
                "- 旧产物文件不存在，已保留迁移占位说明。",
            ],
        )
        migrated.append(target_path.as_posix())
    return migrated


def _assignment_legacy_run_node_id(prompt_text: str, node_records: list[dict[str, Any]]) -> str:
    prompt_node_id = _assignment_run_prompt_field(prompt_text, "node_id")
    if prompt_node_id:
        return prompt_node_id
    prompt_name = _assignment_run_prompt_field(prompt_text, "task_name")
    if prompt_name:
        for node in node_records:
            if str(node.get("node_name") or "").strip() == prompt_name:
                return str(node.get("node_id") or "").strip()
    return ""


def _assignment_ensure_legacy_run_meta(
    root: Path,
    *,
    ticket_id: str,
    run_dir: Path,
    node_records: list[dict[str, Any]],
) -> dict[str, Any]:
    run_id = str(run_dir.name or "").strip()
    files = _assignment_run_file_paths(root, ticket_id, run_id)
    existing = _assignment_read_json(files["meta"])
    if existing:
        return existing
    prompt_text = _read_assignment_run_text(files["prompt"].as_posix())
    node_id = _assignment_legacy_run_node_id(prompt_text, node_records)
    node = next((item for item in node_records if str(item.get("node_id") or "").strip() == node_id), {})
    latest_event, latest_event_at = _assignment_tail_event_summary(files["events"])
    started_at = str(node.get("created_at") or "").strip()
    finished_at = str(node.get("completed_at") or "").strip()
    run_status = _assignment_run_status_from_node(node)
    if not started_at and files["prompt"].exists():
        started_at = iso_ts(datetime.fromtimestamp(files["prompt"].stat().st_mtime).astimezone())
    if not finished_at and run_status in {"succeeded", "failed"} and files["result"].exists():
        finished_at = iso_ts(datetime.fromtimestamp(files["result"].stat().st_mtime).astimezone())
    run_record = _assignment_build_run_record(
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        provider=DEFAULT_ASSIGNMENT_EXECUTION_PROVIDER,
        workspace_path=_assignment_run_prompt_field(prompt_text, "workspace_path"),
        status=run_status,
        command_summary="legacy run imported from historical task workspace",
        prompt_ref=files["prompt"].as_posix(),
        stdout_ref=files["stdout"].as_posix(),
        stderr_ref=files["stderr"].as_posix(),
        result_ref=files["result"].as_posix(),
        latest_event=latest_event,
        latest_event_at=latest_event_at or finished_at or started_at,
        exit_code=0 if run_status == "succeeded" else 1 if run_status == "failed" else 0,
        started_at=started_at,
        finished_at=finished_at,
        created_at=started_at or iso_ts(now_local()),
        updated_at=finished_at or latest_event_at or started_at or iso_ts(now_local()),
    )
    _assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)
    return run_record


def _assignment_refresh_structure_guides(root: Path, ticket_id: str) -> None:
    artifact_root = _assignment_artifact_root(root)
    tasks_root = _assignment_tasks_root(root)
    write_artifact_root_structure_file(artifact_root, tasks_root)
    task_record = _assignment_read_json(_assignment_graph_record_path(root, ticket_id))
    path = _assignment_task_structure_path(root, ticket_id)
    task_dir = _assignment_ticket_workspace_dir(root, ticket_id)
    node_records: list[dict[str, Any]] = []
    nodes_root = task_dir / "nodes"
    if task_record and nodes_root.exists() and nodes_root.is_dir():
        for node_path in sorted(nodes_root.iterdir(), key=lambda item: item.name.lower()):
            if not node_path.is_file() or node_path.suffix.lower() != ".json":
                continue
            payload = _assignment_read_json(node_path)
            if payload:
                node_records.append(payload)
    run_records: list[dict[str, Any]] = []
    runs_root = task_dir / "runs"
    if task_record and runs_root.exists() and runs_root.is_dir():
        for run_dir in sorted(runs_root.iterdir(), key=lambda item: item.name.lower()):
            if not run_dir.is_dir():
                continue
            payload = _assignment_read_json(run_dir / "run.json")
            if payload:
                run_records.append(payload)
    active_nodes = [
        item for item in node_records if str(item.get("record_state") or "active").strip().lower() != "deleted"
    ]
    deleted_nodes = len(node_records) - len(active_nodes)
    lines = [
        "# 单任务目录结构说明",
        "",
        "该文件由 workflow 自动维护。",
        "",
        "## 当前任务",
        f"- ticket_id: {ticket_id}",
        f"- 任务目录: {task_dir.as_posix()}",
        f"- graph_name: {str(task_record.get('graph_name') or '-').strip() if task_record else '-'}",
        f"- source_workflow: {str(task_record.get('source_workflow') or '-').strip() if task_record else '-'}",
        f"- scheduler_state: {str(task_record.get('scheduler_state') or '-').strip() if task_record else '-'}",
        f"- active_nodes: {len(active_nodes)}",
        f"- deleted_nodes: {deleted_nodes}",
        f"- runs: {len(run_records)}",
        "",
        "## 目录结构约定",
        f"- `{ASSIGNMENT_TASK_FILE_NAME}`: 任务图头、依赖边与调度元数据。",
        "- `nodes/`: 单任务节点明细，逻辑删除节点也在此保留删除标记。",
        "- `runs/<run_id>/`: 完整提示词、stdout/stderr、result 与事件链路。",
        "- `artifacts/<node_id>/output/`: 节点自留产物。",
        "- `artifacts/<node_id>/delivery/<receiver_agent_id>/`: 指定交付对象时的交付副本。",
        f"- `../../{ASSIGNMENT_DELIVERY_ROOT_DIRNAME}/<agent_name>/<task_name>/`: 面向 agent 的顶层交付收件箱投影，目录内同时保留 `{ASSIGNMENT_DELIVERY_INFO_FILE_NAME}`。",
        f"- `{ASSIGNMENT_TASK_STRUCTURE_FILE_NAME}`: 本目录结构说明。",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def _assignment_ensure_ticket_normalized(root: Path, ticket_id: str) -> None:
    task_path = _assignment_graph_record_path(root, ticket_id)
    if task_path.exists():
        _assignment_repair_ticket_files(root, ticket_id)
        return
    legacy_path = _assignment_legacy_graph_record_path(root, ticket_id)
    if not legacy_path.exists():
        return
    graph, legacy_nodes = _assignment_read_legacy_ticket(root, ticket_id)
    created_at = str(graph.get("created_at") or iso_ts(now_local())).strip()
    updated_at = str(graph.get("updated_at") or created_at).strip()
    normalized_nodes: list[dict[str, Any]] = []
    for node in legacy_nodes:
        normalized = _assignment_build_node_record(
            ticket_id=ticket_id,
            node_id=str(node.get("node_id") or "").strip(),
            node_name=str(node.get("node_name") or "").strip(),
            source_schedule_id=str(node.get("source_schedule_id") or "").strip(),
            planned_trigger_at=str(node.get("planned_trigger_at") or "").strip(),
            trigger_instance_id=str(node.get("trigger_instance_id") or "").strip(),
            trigger_rule_summary=str(node.get("trigger_rule_summary") or "").strip(),
            assigned_agent_id=str(node.get("assigned_agent_id") or "").strip(),
            assigned_agent_name=str(node.get("assigned_agent_name") or "").strip(),
            node_goal=str(node.get("node_goal") or "").strip(),
            expected_artifact=str(node.get("expected_artifact") or "").strip(),
            delivery_mode=str(node.get("delivery_mode") or "none").strip().lower() or "none",
            delivery_receiver_agent_id=str(node.get("delivery_receiver_agent_id") or "").strip(),
            delivery_receiver_agent_name=str(node.get("delivery_receiver_agent_name") or "").strip(),
            artifact_delivery_status=str(node.get("artifact_delivery_status") or "pending").strip().lower() or "pending",
            artifact_delivered_at=str(node.get("artifact_delivered_at") or "").strip(),
            artifact_paths=list(node.get("artifact_paths") or []),
            status=str(node.get("status") or "pending").strip().lower() or "pending",
            priority=int(1 if node.get("priority") in (None, "") else node.get("priority")),
            completed_at=str(node.get("completed_at") or "").strip(),
            success_reason=str(node.get("success_reason") or "").strip(),
            result_ref=str(node.get("result_ref") or "").strip(),
            failure_reason=str(node.get("failure_reason") or "").strip(),
            created_at=str(node.get("created_at") or created_at).strip() or created_at,
            updated_at=str(node.get("updated_at") or updated_at).strip() or updated_at,
            upstream_node_ids=[str(item or "").strip() for item in list(node.get("upstream_node_ids") or []) if str(item or "").strip()],
            downstream_node_ids=[str(item or "").strip() for item in list(node.get("downstream_node_ids") or []) if str(item or "").strip()],
            record_state=str(node.get("record_state") or "active").strip().lower() or "active",
            delete_meta=dict(node.get("extra") or {}),
        )
        if list(normalized.get("artifact_paths") or []):
            normalized["artifact_paths"] = _assignment_normalize_legacy_artifacts(root, normalized)
        normalized_nodes.append(normalized)
    edges = _assignment_edges_from_node_records(normalized_nodes)
    task_record = _assignment_build_task_record(
        ticket_id=ticket_id,
        graph_name=str(graph.get("graph_name") or "任务中心主图").strip(),
        source_workflow=str(graph.get("source_workflow") or "workflow-ui").strip(),
        summary=str(graph.get("summary") or "").strip(),
        review_mode=str(graph.get("review_mode") or "none").strip() or "none",
        global_concurrency_limit=int(graph.get("global_concurrency_limit") or DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT),
        is_test_data=bool(graph.get("is_test_data")),
        external_request_id=str(graph.get("external_request_id") or "").strip(),
        scheduler_state=str(graph.get("scheduler_state") or "idle").strip().lower() or "idle",
        pause_note=str(graph.get("pause_note") or "").strip(),
        created_at=created_at,
        updated_at=updated_at,
        edges=edges,
        record_state=str(graph.get("record_state") or "active").strip().lower() or "active",
    )
    _assignment_write_json(task_path, task_record)
    for node_record in normalized_nodes:
        _assignment_write_json(
            _assignment_node_record_path(root, ticket_id, str(node_record.get("node_id") or "").strip()),
            node_record,
        )
    runs_root = _assignment_ticket_workspace_dir(root, ticket_id) / "runs"
    if runs_root.exists() and runs_root.is_dir():
        for run_dir in sorted(runs_root.iterdir(), key=lambda item: item.name.lower()):
            if run_dir.is_dir():
                _assignment_ensure_legacy_run_meta(root, ticket_id=ticket_id, run_dir=run_dir, node_records=normalized_nodes)
    try:
        legacy_path.unlink()
    except Exception:
        pass
    _assignment_repair_ticket_files(root, ticket_id)


def _assignment_load_task_record(root: Path, ticket_id: str) -> dict[str, Any]:
    _assignment_ensure_ticket_normalized(root, ticket_id)
    path = _assignment_graph_record_path(root, ticket_id)
    payload = _assignment_read_json(path)
    if not payload:
        raise AssignmentCenterError(
            404,
            "assignment graph not found",
            "assignment_graph_not_found",
            {"ticket_id": ticket_id},
        )
    return payload


def _assignment_load_node_records(root: Path, ticket_id: str, *, include_deleted: bool = True) -> list[dict[str, Any]]:
    _assignment_ensure_ticket_normalized(root, ticket_id)
    nodes_root = _assignment_ticket_workspace_dir(root, ticket_id) / "nodes"
    if not nodes_root.exists() or not nodes_root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(nodes_root.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file() or path.suffix.lower() != ".json":
            continue
        payload = _assignment_read_json(path)
        if not payload:
            continue
        if not include_deleted and str(payload.get("record_state") or "active").strip().lower() == "deleted":
            continue
        rows.append(payload)
    rows.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("node_id") or "")))
    return rows


def _assignment_write_task_record(root: Path, task_record: dict[str, Any]) -> None:
    ticket_id = str(task_record.get("ticket_id") or "").strip()
    if not ticket_id:
        raise AssignmentCenterError(400, "ticket_id required", "ticket_id_required")
    _assignment_write_json(_assignment_graph_record_path(root, ticket_id), task_record)
    _assignment_refresh_structure_guides(root, ticket_id)


def _assignment_write_node_record(root: Path, node_record: dict[str, Any]) -> None:
    ticket_id = str(node_record.get("ticket_id") or "").strip()
    node_id = str(node_record.get("node_id") or "").strip()
    if not ticket_id or not node_id:
        raise AssignmentCenterError(400, "ticket_id/node_id required", "ticket_or_node_required")
    _assignment_write_json(_assignment_node_record_path(root, ticket_id, node_id), node_record)
    _assignment_refresh_structure_guides(root, ticket_id)


def _assignment_list_ticket_ids(root: Path) -> list[str]:
    tasks_root = _assignment_tasks_root(root)
    tasks_root.mkdir(parents=True, exist_ok=True)
    ticket_ids = [
        str(path.name or "").strip()
        for path in sorted(tasks_root.iterdir(), key=lambda item: item.name.lower())
        if path.is_dir() and str(path.name or "").strip()
    ]
    for ticket_id in ticket_ids:
        _assignment_ensure_ticket_normalized(root, ticket_id)
    return ticket_ids


def _write_artifact_structure_files(
    root: Path,
    *,
    node: dict[str, Any],
    artifact_file_paths: list[Path],
    delivered_at: str,
    operator: str,
) -> list[str]:
    ticket_id = str(node.get("ticket_id") or "").strip()
    if not ticket_id:
        return []
    _assignment_refresh_structure_guides(root, ticket_id)
    return [
        artifact_root_structure_file_path(_assignment_artifact_root(root)).as_posix(),
        _assignment_task_structure_path(root, ticket_id).as_posix(),
    ]
