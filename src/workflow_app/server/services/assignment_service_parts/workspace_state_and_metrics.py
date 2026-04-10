
from .work_record_store import sync_assignment_task_bundle as sync_assignment_task_bundle_index


def _normalize_path_segment(raw: Any, fallback: str) -> str:
    text = str(raw or "").strip()
    if not text:
        text = str(fallback or "").strip()
    if not text:
        text = "item"
    text = re.sub('[<>:"/\\\\|?*\\x00-\\x1f]+', "_", text).strip().strip(".")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:96] or "item"


def _artifact_label_file_name(node: dict[str, Any]) -> str:
    label = (
        str(node.get("expected_artifact") or "").strip()
        or str(node.get("node_name") or "").strip()
        or str(node.get("node_id") or "").strip()
        or "artifact"
    )
    return _normalize_path_segment(label, "artifact") + ".md"


def _node_artifact_file_paths(root: Path, node: dict[str, Any]) -> list[Path]:
    ticket_id = str(node.get("ticket_id") or "").strip()
    node_id = str(node.get("node_id") or "").strip()
    if not ticket_id or not node_id:
        return []
    file_name = _artifact_label_file_name(node)
    base = _assignment_artifact_root(root) / "tasks" / ticket_id / "artifacts" / node_id
    paths = [base / "output" / file_name]
    if str(node.get("delivery_mode") or "").strip().lower() == "specified":
        receiver_name = _normalize_path_segment(
            node.get("delivery_receiver_agent_id") or node.get("delivery_receiver_agent_name") or "receiver",
            "receiver",
        )
        receiver_path = base / "delivery" / receiver_name / file_name
        if receiver_path not in paths:
            paths.append(receiver_path)
    return paths


def _artifact_structure_file_name() -> str:
    return "TASK_STRUCTURE.md"


def _artifact_directory_role(artifact_root: Path, artifact_dir: Path) -> str:
    try:
        relative_parts = artifact_dir.resolve(strict=False).relative_to(artifact_root.resolve(strict=False)).parts
    except Exception:
        relative_parts = artifact_dir.parts
    if "receive" in relative_parts:
        return "receive"
    if "product" in relative_parts:
        return "product"
    return "artifact"


def _effective_delivery_target_agent_id(node: dict[str, Any]) -> str:
    target_agent_id = str(node.get("delivery_target_agent_id") or "").strip()
    if target_agent_id:
        return target_agent_id
    if str(node.get("delivery_mode") or "").strip().lower() == "specified":
        receiver_agent_id = str(node.get("delivery_receiver_agent_id") or "").strip()
        if receiver_agent_id:
            return receiver_agent_id
    return str(node.get("assigned_agent_id") or "").strip()


def _effective_delivery_target_agent_name(node: dict[str, Any]) -> str:
    target_agent_name = str(node.get("delivery_target_agent_name") or "").strip()
    if target_agent_name:
        return target_agent_name
    if str(node.get("delivery_mode") or "").strip().lower() == "specified":
        receiver_agent_name = str(
            node.get("delivery_receiver_agent_name") or node.get("delivery_receiver_agent_id") or ""
        ).strip()
        if receiver_agent_name:
            return receiver_agent_name
    return str(node.get("assigned_agent_name") or node.get("assigned_agent_id") or "").strip()


def _artifact_structure_markdown(
    root: Path,
    *,
    node: dict[str, Any],
    artifact_file: Path,
    delivered_at: str,
    operator: str,
) -> str:
    artifact_root = _assignment_artifact_root(root)
    ticket_id = str(node.get("ticket_id") or "").strip() or "-"
    task_dir = (_assignment_artifact_root(root) / "tasks" / ticket_id).resolve(strict=False)
    task_name = str(node.get("node_name") or node.get("node_id") or "").strip() or "-"
    assigned_agent = str(node.get("assigned_agent_name") or node.get("assigned_agent_id") or "").strip() or "-"
    delivery_target = _effective_delivery_target_agent_name(node) or _effective_delivery_target_agent_id(node) or "-"
    lines = [
        "# 单任务目录结构说明",
        "",
        "该文件由 workflow 自动维护。",
        "任务创建、状态回写或真实执行完成后，系统都会刷新本说明文件。",
        "",
        "## 当前任务",
        f"- 任务产物路径: {artifact_root.as_posix()}",
        f"- 任务目录: {task_dir.as_posix()}",
        f"- ticket_id: {ticket_id}",
        f"- node_id: {str(node.get('node_id') or '').strip() or '-'}",
        f"- 任务名称: {task_name}",
        f"- 执行 agent: {assigned_agent}",
        f"- 交付对象: {delivery_target}",
        f"- 最近产物文件: {artifact_file.name}",
        f"- 最近刷新时间: {str(delivered_at or '').strip() or '-'}",
        f"- 刷新来源: {str(operator or '').strip() or '-'}",
        "",
        "## 目录结构约定",
        "- `<任务产物路径>/tasks/<ticket_id>/task.json`: 任务图头、调度状态与依赖边元数据。",
        "- `<任务产物路径>/tasks/<ticket_id>/nodes/<node_id>.json`: 单任务节点明细。",
        "- `<任务产物路径>/tasks/<ticket_id>/runs/<run_id>/...`: 完整提示词、stdout/stderr、结果与事件链路。",
        "- `<任务产物路径>/tasks/<ticket_id>/artifacts/<node_id>/output/...`: 当前节点自留产物。",
        "- `<任务产物路径>/tasks/<ticket_id>/artifacts/<node_id>/delivery/<receiver_agent_id>/...`: 指定交付对象时的交付副本。",
        f"- `<任务产物路径>/tasks/<ticket_id>/{_artifact_structure_file_name()}`: 单任务目录结构说明。",
        "",
    ]
    return "\n".join(lines).strip() + "\n"


def _artifact_body_looks_html(raw: Any) -> bool:
    head = str(raw or "").lstrip()[:512].lower()
    return head.startswith("<!doctype html") or head.startswith("<html")


def _artifact_html_escape(raw: Any) -> str:
    return (
        str(raw or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _artifact_text_to_html_document(raw: Any, *, title: str = "任务产物") -> str:
    text = str(raw or "")
    if _artifact_body_looks_html(text):
        return text
    escaped_title = _artifact_html_escape(title or "任务产物")
    escaped_body = _artifact_html_escape(text)
    body_html = (
        "<pre class='artifact-body'>"
        + escaped_body
        + "</pre>"
        if escaped_body
        else "<div class='artifact-empty'>暂无正文</div>"
    )
    return (
        "<!doctype html>\n"
        "<html lang='zh-CN'>\n"
        "<head>\n"
        "  <meta charset='utf-8' />\n"
        "  <meta name='viewport' content='width=device-width, initial-scale=1' />\n"
        f"  <title>{escaped_title}</title>\n"
        "  <style>\n"
        "    :root { color-scheme: light; }\n"
        "    body {\n"
        "      margin: 0;\n"
        "      font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;\n"
        "      background: #f4f7fb;\n"
        "      color: #1f2937;\n"
        "    }\n"
        "    .artifact-shell {\n"
        "      max-width: 960px;\n"
        "      margin: 0 auto;\n"
        "      padding: 24px;\n"
        "    }\n"
        "    .artifact-card {\n"
        "      border: 1px solid #d9e2ec;\n"
        "      border-radius: 16px;\n"
        "      background: #ffffff;\n"
        "      box-shadow: 0 18px 44px rgba(15, 23, 42, 0.08);\n"
        "      overflow: hidden;\n"
        "    }\n"
        "    .artifact-head {\n"
        "      padding: 18px 20px;\n"
        "      border-bottom: 1px solid #e5edf5;\n"
        "      background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);\n"
        "    }\n"
        "    .artifact-title {\n"
        "      margin: 0;\n"
        "      font-size: 20px;\n"
        "      line-height: 1.3;\n"
        "      font-weight: 800;\n"
        "    }\n"
        "    .artifact-content {\n"
        "      padding: 20px;\n"
        "    }\n"
        "    .artifact-body {\n"
        "      margin: 0;\n"
        "      white-space: pre-wrap;\n"
        "      word-break: break-word;\n"
        "      font: 13px/1.65 'Cascadia Mono', 'Consolas', 'SFMono-Regular', monospace;\n"
        "      color: #334155;\n"
        "    }\n"
        "    .artifact-empty {\n"
        "      font-size: 13px;\n"
        "      color: #64748b;\n"
        "    }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        "  <main class='artifact-shell'>\n"
        "    <section class='artifact-card'>\n"
        "      <header class='artifact-head'>\n"
        f"        <h1 class='artifact-title'>{escaped_title}</h1>\n"
        "      </header>\n"
        f"      <div class='artifact-content'>{body_html}</div>\n"
        "    </section>\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def _write_artifact_structure_files(
    root: Path,
    *,
    node: dict[str, Any],
    artifact_file_paths: list[Path],
    delivered_at: str,
    operator: str,
) -> list[str]:
    del artifact_file_paths, delivered_at, operator
    ticket_id = str(node.get("ticket_id") or "").strip()
    if not ticket_id:
        return []
    _assignment_refresh_structure_guides(root, ticket_id)
    return [
        artifact_root_structure_file_path(_assignment_artifact_root(root)).as_posix(),
        (_assignment_artifact_root(root) / "tasks" / ticket_id / _artifact_structure_file_name()).as_posix(),
    ]


def _assignment_ticket_workspace_dir(root: Path, ticket_id: str) -> Path:
    return (_assignment_artifact_root(root) / "tasks" / str(ticket_id or "").strip()).resolve(strict=False)


def _assignment_graph_record_path(root: Path, ticket_id: str) -> Path:
    return _assignment_ticket_workspace_dir(root, ticket_id) / "task.json"


def _assignment_node_record_path(root: Path, ticket_id: str, node_id: str) -> Path:
    return _assignment_ticket_workspace_dir(root, ticket_id) / "nodes" / (str(node_id or "").strip() + ".json")


def _write_assignment_workspace_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _persist_assignment_workspace_graph(
    root: Path,
    *,
    snapshot: dict[str, Any],
    record_state: str = "active",
    extra: dict[str, Any] | None = None,
    sync_index: bool = True,
) -> str:
    graph_row = snapshot.get("graph_row")
    if not graph_row:
        return ""
    graph_overview = _graph_overview_payload(
        graph_row,
        metrics_summary=snapshot.get("metrics_summary") or {},
        scheduler_state_payload=snapshot.get("scheduler") or {},
    )
    ticket_id = str(graph_overview.get("ticket_id") or "").strip()
    if not ticket_id:
        return ""
    path = _assignment_graph_record_path(root, ticket_id)
    payload = {
        "record_type": "assignment_graph",
        "record_state": str(record_state or "active"),
        "artifact_root": str(_assignment_artifact_root(root)),
        "workspace_root": str(_assignment_workspace_root(root)),
        "ticket_id": ticket_id,
        "is_test_data": bool(graph_overview.get("is_test_data")),
        "graph_name": str(graph_overview.get("graph_name") or "").strip(),
        "source_workflow": str(graph_overview.get("source_workflow") or "").strip(),
        "summary": str(graph_overview.get("summary") or "").strip(),
        "scheduler_state": str(graph_overview.get("scheduler_state") or "").strip(),
        "scheduler_state_text": str(graph_overview.get("scheduler_state_text") or "").strip(),
        "metrics_summary": snapshot.get("metrics_summary") or {},
        "created_at": str(graph_overview.get("created_at") or "").strip(),
        "updated_at": str(graph_overview.get("updated_at") or "").strip(),
    }
    if isinstance(extra, dict) and extra:
        payload["extra"] = dict(extra)
    _write_assignment_workspace_json(path, payload)
    if sync_index:
        sync_assignment_task_bundle_index(root, ticket_id)
    return str(path)


def _persist_assignment_workspace_node(
    root: Path,
    *,
    node: dict[str, Any],
    record_state: str = "active",
    audit_id: str = "",
    extra: dict[str, Any] | None = None,
    sync_index: bool = True,
) -> str:
    ticket_id = str(node.get("ticket_id") or "").strip()
    node_id = str(node.get("node_id") or "").strip()
    if not ticket_id or not node_id:
        return ""
    path = _assignment_node_record_path(root, ticket_id, node_id)
    payload = {
        "record_type": "assignment_node",
        "record_state": str(record_state or "active"),
        "artifact_root": str(_assignment_artifact_root(root)),
        "workspace_root": str(_assignment_workspace_root(root)),
        "ticket_id": ticket_id,
        "is_test_data": bool(node.get("is_test_data")),
        "node_id": node_id,
        "node_name": str(node.get("node_name") or "").strip(),
        "assigned_agent_id": str(node.get("assigned_agent_id") or "").strip(),
        "assigned_agent_name": str(node.get("assigned_agent_name") or "").strip(),
        "node_goal": str(node.get("node_goal") or "").strip(),
        "expected_artifact": str(node.get("expected_artifact") or "").strip(),
        "delivery_mode": str(node.get("delivery_mode") or "none").strip().lower() or "none",
        "delivery_mode_text": _delivery_mode_text(node.get("delivery_mode") or "none"),
        "delivery_receiver_agent_id": str(node.get("delivery_receiver_agent_id") or "").strip(),
        "delivery_receiver_agent_name": str(node.get("delivery_receiver_agent_name") or "").strip(),
        "delivery_target_agent_id": _effective_delivery_target_agent_id(node),
        "delivery_target_agent_name": _effective_delivery_target_agent_name(node),
        "artifact_delivery_status": str(node.get("artifact_delivery_status") or "pending").strip().lower() or "pending",
        "artifact_delivery_status_text": _artifact_delivery_status_text(
            node.get("artifact_delivery_status") or "pending"
        ),
        "artifact_delivered_at": str(node.get("artifact_delivered_at") or "").strip(),
        "artifact_paths": list(node.get("artifact_paths") or []),
        "status": str(node.get("status") or "").strip(),
        "status_text": str(node.get("status_text") or _node_status_text(str(node.get("status") or ""))).strip(),
        "priority": int(node.get("priority") or 0),
        "priority_label": assignment_priority_label(node.get("priority")),
        "completed_at": str(node.get("completed_at") or "").strip(),
        "success_reason": str(node.get("success_reason") or "").strip(),
        "result_ref": str(node.get("result_ref") or "").strip(),
        "failure_reason": str(node.get("failure_reason") or "").strip(),
        "created_at": str(node.get("created_at") or "").strip(),
        "updated_at": str(node.get("updated_at") or "").strip(),
        "upstream_node_ids": list(node.get("upstream_node_ids") or []),
        "downstream_node_ids": list(node.get("downstream_node_ids") or []),
        "audit_ref": _db_ref(audit_id) if audit_id else "",
    }
    if isinstance(extra, dict) and extra:
        payload["extra"] = dict(extra)
    _write_assignment_workspace_json(path, payload)
    if sync_index:
        sync_assignment_task_bundle_index(root, ticket_id)
    return str(path)


def _sync_assignment_workspace_snapshot(root: Path, snapshot: dict[str, Any]) -> None:
    ticket_id = str(((snapshot.get("graph_row") or {}) if isinstance(snapshot.get("graph_row"), dict) else {}).get("ticket_id") or "").strip()
    _persist_assignment_workspace_graph(root, snapshot=snapshot, record_state="active", sync_index=False)
    for node in list(snapshot.get("serialized_nodes") or []):
        if isinstance(node, dict):
            _persist_assignment_workspace_node(root, node=node, record_state="active", sync_index=False)
    if ticket_id:
        sync_assignment_task_bundle_index(root, ticket_id)


def _artifact_delivery_markdown(
    node: dict[str, Any],
    *,
    delivered_at: str,
    operator: str,
    artifact_label: str,
    delivery_note: str,
) -> str:
    delivery_target = _effective_delivery_target_agent_name(node) or _effective_delivery_target_agent_id(node) or "-"
    lines = [
        f"# {artifact_label or '任务产物'}",
        "",
        f"- ticket_id: {str(node.get('ticket_id') or '').strip()}",
        f"- node_id: {str(node.get('node_id') or '').strip()}",
        f"- node_name: {str(node.get('node_name') or '').strip()}",
        f"- assigned_agent: {str(node.get('assigned_agent_name') or node.get('assigned_agent_id') or '').strip()}",
        f"- delivery_mode: {_delivery_mode_text(node.get('delivery_mode') or 'none')}",
        f"- delivery_target: {delivery_target}",
        f"- delivered_at: {delivered_at}",
        f"- operator: {operator}",
    ]
    if str(node.get("expected_artifact") or "").strip():
        lines.append(f"- expected_artifact: {str(node.get('expected_artifact') or '').strip()}")
    if delivery_note:
        lines.extend(["", "## 交付说明", "", delivery_note])
    return _artifact_text_to_html_document(
        "\n".join(lines).strip() + "\n",
        title=artifact_label or "任务产物",
    )


def _artifact_paths_preview(paths: list[Any]) -> list[str]:
    preview: list[str] = []
    for raw in paths:
        text = str(raw or "").strip()
        if not text:
            continue
        preview.append(text)
    return preview


def _assignment_run_trace_dir(root: Path, ticket_id: str, run_id: str) -> Path:
    return (_assignment_workspace_root(root) / ticket_id / "runs" / run_id).resolve(strict=False)


def _assignment_run_file_paths(root: Path, ticket_id: str, run_id: str) -> dict[str, Path]:
    trace_dir = _assignment_run_trace_dir(root, ticket_id, run_id)
    return {
        "trace_dir": trace_dir,
        "prompt": trace_dir / "prompt.txt",
        "stdout": trace_dir / "stdout.txt",
        "stderr": trace_dir / "stderr.txt",
        "result": trace_dir / "result.json",
        "result_markdown": trace_dir / "result.md",
        "events": trace_dir / "events.log",
    }


def _write_assignment_run_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text or ""), encoding="utf-8")


_ASSIGNMENT_RUN_TRACE_FILE_MAX_BYTES = {
    "stdout.txt": 96 * 1024,
    "stderr.txt": 96 * 1024,
    "events.log": 128 * 1024,
}

_ASSIGNMENT_RUN_PREVIEW_CHARS = {
    "prompt.txt": 4000,
    "stdout.txt": 6000,
    "stderr.txt": 6000,
    "result.json": 6000,
    "result.md": 6000,
}


def _assignment_run_trace_file_limit(path: Path) -> int:
    return int(_ASSIGNMENT_RUN_TRACE_FILE_MAX_BYTES.get(str(path.name or "").strip().lower(), 0) or 0)


def _assignment_run_preview_chars(path_text: str) -> int:
    name = Path(str(path_text or "").strip()).name.lower()
    return int(_ASSIGNMENT_RUN_PREVIEW_CHARS.get(name, 0) or 0)


def _assignment_run_preview_text(text: str, limit: int) -> str:
    raw = str(text or "")
    if limit <= 0 or len(raw) <= limit:
        return raw
    omitted = max(0, len(raw) - limit)
    return (
        raw[:limit].rstrip()
        + f"\n\n...[已截断，当前仅展示前 {limit} 个字符；剩余 {omitted} 个字符请按下方引用路径查看原文件]"
    )


def _compact_assignment_event_detail(value: Any, *, depth: int = 0) -> Any:
    if isinstance(value, dict):
        items = list(value.items())
        compact: dict[str, Any] = {}
        for index, (key, item) in enumerate(items):
            if index >= 8:
                compact["__truncated__"] = f"... {len(items) - 8} more fields"
                break
            compact[str(key or "").strip()[:80] or f"field_{index + 1}"] = _compact_assignment_event_detail(
                item,
                depth=depth + 1,
            )
        return compact
    if isinstance(value, list):
        compact_items = [_compact_assignment_event_detail(item, depth=depth + 1) for item in value[:6]]
        if len(value) > 6:
            compact_items.append(f"... {len(value) - 6} more items")
        return compact_items
    if isinstance(value, str):
        limit = 120 if depth >= 2 else 240
        return _short_assignment_text(value, limit)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if depth >= 2:
        try:
            return _short_assignment_text(json.dumps(value, ensure_ascii=False), 200)
        except Exception:
            return _short_assignment_text(str(value), 200)
    return _short_assignment_text(str(value), 240)


def _append_assignment_run_raw_text(path: Path, text: str) -> None:
    raw = str(text or "")
    if not raw:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    file_limit = _assignment_run_trace_file_limit(path)
    if file_limit <= 0:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(raw)
        return
    current_size = path.stat().st_size if path.exists() else 0
    if current_size >= file_limit:
        return
    raw_bytes = raw.encode("utf-8")
    notice_text = (
        f"\n[workflow] {path.name} 已达到 {file_limit} 字节上限；后续输出不再继续落盘。"
        "界面默认只展示精简预览，请优先结合最终结果和关键事件排查。\n"
    )
    notice_bytes = notice_text.encode("utf-8")
    with path.open("ab") as handle:
        if current_size + len(raw_bytes) <= file_limit:
            handle.write(raw_bytes)
            return
        remaining = max(0, file_limit - current_size)
        body_budget = max(0, remaining - len(notice_bytes))
        if body_budget > 0:
            truncated_text = raw_bytes[:body_budget].decode("utf-8", errors="ignore")
            if truncated_text:
                handle.write(truncated_text.encode("utf-8"))
        if handle.tell() < file_limit:
            handle.write(notice_bytes[: max(0, file_limit - handle.tell())])


def _timestamp_assignment_run_log_text(text: str) -> str:
    raw = str(text or "")
    if not raw:
        return ""
    chunks: list[str] = []
    for line in raw.splitlines(keepends=True):
        body = line
        newline = ""
        if line.endswith("\r\n"):
            body = line[:-2]
            newline = "\r\n"
        elif line.endswith("\n") or line.endswith("\r"):
            body = line[:-1]
            newline = line[-1]
        if not body:
            chunks.append(line)
            continue
        chunks.append(f"[{iso_ts(now_local())}] {body}{newline}")
    if not chunks and raw:
        return f"[{iso_ts(now_local())}] {raw}"
    return "".join(chunks)


def _append_assignment_run_text(path: Path, text: str) -> None:
    if not text:
        return
    rendered = _timestamp_assignment_run_log_text(text)
    if not rendered:
        return
    _append_assignment_run_raw_text(path, rendered)


def _write_assignment_run_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_assignment_run_event(path: Path, *, event_type: str, message: str, created_at: str, detail: dict[str, Any] | None = None) -> None:
    payload = {
        "created_at": created_at,
        "event_type": str(event_type or "").strip(),
        "message": _short_assignment_text(str(message or "").rstrip(), 1200),
        "detail": _compact_assignment_event_detail(dict(detail or {})),
    }
    _append_assignment_run_raw_text(path, json.dumps(payload, ensure_ascii=False) + "\n")


def _tail_assignment_run_events(path: Path, *, limit: int = 120) -> list[dict[str, Any]]:
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
                payload = {"created_at": "", "event_type": "raw", "message": text, "detail": {}}
            if isinstance(payload, dict):
                rows.append(payload)
    except Exception:
        return []
    return rows[-max(1, int(limit)) :]


def _read_assignment_run_text(path_text: str, *, preview_chars: int = 0) -> str:
    path = Path(str(path_text or "").strip()).resolve(strict=False)
    if not path.exists() or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return ""
    return _assignment_run_preview_text(text, preview_chars)


def _load_assignment_runs(
    conn: sqlite3.Connection,
    *,
    ticket_id: str,
    node_id: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            run_id,ticket_id,node_id,provider,workspace_path,status,command_summary,
            prompt_ref,stdout_ref,stderr_ref,result_ref,latest_event,latest_event_at,
            exit_code,started_at,finished_at,created_at,updated_at
        FROM assignment_execution_runs
        WHERE ticket_id=? AND node_id=?
        ORDER BY created_at DESC, run_id DESC
        LIMIT ?
        """,
        (ticket_id, node_id, max(1, int(limit))),
    ).fetchall()
    return [_row_dict(row) for row in rows]


def _active_assignment_run_row(conn: sqlite3.Connection, *, ticket_id: str, node_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            run_id,ticket_id,node_id,provider,workspace_path,status,command_summary,
            prompt_ref,stdout_ref,stderr_ref,result_ref,latest_event,latest_event_at,
            exit_code,started_at,finished_at,created_at,updated_at
        FROM assignment_execution_runs
        WHERE ticket_id=? AND node_id=? AND status IN ('starting','running')
        ORDER BY created_at DESC, run_id DESC
        LIMIT 1
        """,
        (ticket_id, node_id),
    ).fetchone()
    return _row_dict(row)


def _assignment_run_summary(root: Path, row: dict[str, Any], *, include_content: bool) -> dict[str, Any]:
    run_id = str(row.get("run_id") or "").strip()
    ticket_id = str(row.get("ticket_id") or "").strip()
    node_id = str(row.get("node_id") or "").strip()
    refs = _assignment_run_file_paths(root, ticket_id, run_id) if run_id and ticket_id else {}
    events_path = refs.get("events")
    prompt_ref = str(row.get("prompt_ref") or "").strip()
    stdout_ref = str(row.get("stdout_ref") or "").strip()
    stderr_ref = str(row.get("stderr_ref") or "").strip()
    result_ref = str(row.get("result_ref") or "").strip()
    prompt_text = (
        _read_assignment_run_text(prompt_ref, preview_chars=_assignment_run_preview_chars(prompt_ref)) if include_content else ""
    )
    stdout_text = (
        _read_assignment_run_text(stdout_ref, preview_chars=_assignment_run_preview_chars(stdout_ref)) if include_content else ""
    )
    stderr_text = (
        _read_assignment_run_text(stderr_ref, preview_chars=_assignment_run_preview_chars(stderr_ref)) if include_content else ""
    )
    result_text = (
        _read_assignment_run_text(result_ref, preview_chars=_assignment_run_preview_chars(result_ref)) if include_content else ""
    )
    events = _tail_assignment_run_events(events_path) if isinstance(events_path, Path) else []
    return {
        "run_id": run_id,
        "ticket_id": ticket_id,
        "node_id": node_id,
        "provider": str(row.get("provider") or "").strip(),
        "workspace_path": str(row.get("workspace_path") or "").strip(),
        "status": _normalize_run_status(row.get("status") or "starting"),
        "status_text": _node_status_text("running" if str(row.get("status") or "").strip().lower() == "running" else row.get("status") or ""),
        "command_summary": str(row.get("command_summary") or "").strip(),
        "prompt_ref": prompt_ref,
        "stdout_ref": stdout_ref,
        "stderr_ref": stderr_ref,
        "result_ref": result_ref,
        "latest_event": str(row.get("latest_event") or "").strip(),
        "latest_event_at": str(row.get("latest_event_at") or "").strip(),
        "exit_code": int(row.get("exit_code") or 0),
        "started_at": str(row.get("started_at") or "").strip(),
        "finished_at": str(row.get("finished_at") or "").strip(),
        "created_at": str(row.get("created_at") or "").strip(),
        "updated_at": str(row.get("updated_at") or "").strip(),
        "event_count": len(events),
        "events": events,
        "prompt_text": prompt_text,
        "stdout_text": stdout_text,
        "stderr_text": stderr_text,
        "result_text": result_text,
    }


def _load_edges(conn: sqlite3.Connection, ticket_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT edge_id,from_node_id,to_node_id,edge_kind,created_at
        FROM assignment_edges
        WHERE ticket_id=?
        ORDER BY created_at ASC, edge_id ASC
        """,
        (ticket_id,),
    ).fetchall()
    return [
        {
            "edge_id": int(row["edge_id"] or 0),
            "from_node_id": str(row["from_node_id"] or "").strip(),
            "to_node_id": str(row["to_node_id"] or "").strip(),
            "edge_kind": str(row["edge_kind"] or "depends_on").strip() or "depends_on",
            "created_at": str(row["created_at"] or "").strip(),
        }
        for row in rows
    ]


def _edge_maps(edges: list[dict[str, Any]]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    upstream_map: dict[str, list[str]] = {}
    downstream_map: dict[str, list[str]] = {}
    for edge in edges:
        from_id = str(edge.get("from_node_id") or "").strip()
        to_id = str(edge.get("to_node_id") or "").strip()
        if not from_id or not to_id:
            continue
        upstream_map.setdefault(to_id, []).append(from_id)
        downstream_map.setdefault(from_id, []).append(to_id)
    return upstream_map, downstream_map


def _load_nodes(conn: sqlite3.Connection, ticket_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            n.node_id,n.ticket_id,n.node_name,n.assigned_agent_id,
            COALESCE(a.agent_name,n.assigned_agent_id) AS assigned_agent_name,
            n.node_goal,n.expected_artifact,n.delivery_mode,n.delivery_receiver_agent_id,
            COALESCE(r.agent_name,n.delivery_receiver_agent_id) AS delivery_receiver_agent_name,
            n.artifact_delivery_status,n.artifact_delivered_at,n.artifact_paths_json,
            n.status,n.priority,n.completed_at,
            n.success_reason,n.result_ref,n.failure_reason,n.created_at,n.updated_at
        FROM assignment_nodes n
        LEFT JOIN agent_registry a ON a.agent_id=n.assigned_agent_id
        LEFT JOIN agent_registry r ON r.agent_id=n.delivery_receiver_agent_id
        WHERE n.ticket_id=?
        ORDER BY n.created_at ASC, n.rowid ASC, n.node_id ASC
        """,
        (ticket_id,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "node_id": str(row["node_id"] or "").strip(),
                "ticket_id": str(row["ticket_id"] or "").strip(),
                "node_name": str(row["node_name"] or "").strip(),
                "assigned_agent_id": str(row["assigned_agent_id"] or "").strip(),
                "assigned_agent_name": str(row["assigned_agent_name"] or "").strip(),
                "node_goal": str(row["node_goal"] or "").strip(),
                "expected_artifact": str(row["expected_artifact"] or "").strip(),
                "delivery_mode": _normalize_delivery_mode(row["delivery_mode"] or "none"),
                "delivery_mode_text": _delivery_mode_text(row["delivery_mode"] or "none"),
                "delivery_receiver_agent_id": str(row["delivery_receiver_agent_id"] or "").strip(),
                "delivery_receiver_agent_name": str(row["delivery_receiver_agent_name"] or "").strip(),
                "delivery_target_agent_id": "",
                "delivery_target_agent_name": "",
                "artifact_delivery_status": _normalize_artifact_delivery_status(
                    row["artifact_delivery_status"] or "pending"
                ),
                "artifact_delivery_status_text": _artifact_delivery_status_text(
                    row["artifact_delivery_status"] or "pending"
                ),
                "artifact_delivered_at": str(row["artifact_delivered_at"] or "").strip(),
                "artifact_paths": list(_safe_json_list(row["artifact_paths_json"] or "[]")),
                "status": str(row["status"] or "").strip().lower(),
                "priority": int(row["priority"] or 0),
                "completed_at": str(row["completed_at"] or "").strip(),
                "success_reason": str(row["success_reason"] or "").strip(),
                "result_ref": str(row["result_ref"] or "").strip(),
                "failure_reason": str(row["failure_reason"] or "").strip(),
                "created_at": str(row["created_at"] or "").strip(),
                "updated_at": str(row["updated_at"] or "").strip(),
            }
        )
        out[-1]["delivery_target_agent_id"] = _effective_delivery_target_agent_id(out[-1])
        out[-1]["delivery_target_agent_name"] = _effective_delivery_target_agent_name(out[-1])
    return out


def get_assignment_runtime_metrics(root: Path, *, include_test_data: bool = True) -> dict[str, int]:
    active_run_ids = {
        str(run_id or "").strip()
        for run_id in _active_assignment_run_ids()
        if str(run_id or "").strip()
    }
    if not active_run_ids:
        return _get_assignment_runtime_metrics_from_node_files(
            root,
            include_test_data=include_test_data,
        )
    try:
        file_metrics = _get_assignment_runtime_metrics_from_files(
            root,
            active_run_ids=active_run_ids,
            include_test_data=include_test_data,
        )
        if int(file_metrics.get("running_task_count") or 0) > 0:
            return file_metrics
        return _get_assignment_runtime_metrics_from_node_files(
            root,
            include_test_data=include_test_data,
        )
    except Exception:
        return _get_assignment_runtime_metrics_from_node_files(
            root,
            include_test_data=include_test_data,
        )
