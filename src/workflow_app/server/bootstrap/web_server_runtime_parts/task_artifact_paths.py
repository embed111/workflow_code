from __future__ import annotations


TASK_ARTIFACT_ROOT_CONFIG_KEY = "task_artifact_root"
TASKS_ROOT_DIRNAME = "tasks"
DELIVERY_ROOT_DIRNAME = "delivery"
TASKS_STRUCTURE_FILE_NAME = "TASKS_STRUCTURE.md"


def _runtime_artifact_root_value(runtime_cfg: dict[str, Any]) -> str:
    if not isinstance(runtime_cfg, dict):
        return ""
    preferred = str(runtime_cfg.get(TASK_ARTIFACT_ROOT_CONFIG_KEY) or "").strip()
    if preferred:
        return preferred
    return str(runtime_cfg.get("artifact_root") or "").strip()


def resolve_artifact_root_candidate(raw: Any) -> tuple[Path, str]:
    text = str(raw or "").strip()
    base = WORKFLOW_PROJECT_ROOT
    if not text:
        return DEFAULT_ARTIFACT_ROOT, "default"
    try:
        return normalize_abs_path(text, base=base), "configured"
    except Exception:
        return DEFAULT_ARTIFACT_ROOT, "invalid"


def resolve_artifact_root_path(root: Path) -> Path:
    runtime_cfg = load_runtime_config(root)
    candidate_root, _source = resolve_artifact_root_candidate(_runtime_artifact_root_value(runtime_cfg))
    try:
        return ensure_artifact_root_dirs(candidate_root)[0]
    except Exception:
        return ensure_artifact_root_dirs(DEFAULT_ARTIFACT_ROOT)[0]


def artifact_root_structure_file_path(artifact_root: Path) -> Path:
    return Path(artifact_root).resolve(strict=False) / TASKS_STRUCTURE_FILE_NAME


def assignment_workspace_records_root(artifact_root: Path) -> Path:
    return (Path(artifact_root).resolve(strict=False) / TASKS_ROOT_DIRNAME).resolve(strict=False)


def assignment_delivery_root(artifact_root: Path) -> Path:
    return (Path(artifact_root).resolve(strict=False) / DELIVERY_ROOT_DIRNAME).resolve(strict=False)


def legacy_assignment_workspace_records_root(runtime_root: Path) -> Path:
    return (Path(runtime_root).resolve(strict=False) / "workspace" / "assignments").resolve(strict=False)


def _legacy_artifact_workspace_records_root(artifact_root: Path) -> Path:
    return (Path(artifact_root).resolve(strict=False) / "workspace" / "assignments").resolve(strict=False)


def _artifact_root_structure_markdown(artifact_root: Path, tasks_root: Path) -> str:
    lines = [
        "# 任务产物目录结构说明",
        "",
        "该文件由 workflow 自动维护。",
        "启动程序时，或在设置中修改任务产物路径后，系统都会生成或刷新本说明文件。",
        "",
        "## 当前配置",
        f"- 任务产物路径: {artifact_root.as_posix()}",
        f"- 任务目录根: {tasks_root.as_posix()}",
        f"- 根目录说明文件: {TASKS_STRUCTURE_FILE_NAME}",
        "",
        "## 目录结构约定",
        "- `<任务产物路径>/tasks/<ticket_id>/task.json`: 任务图头、调度状态与依赖边元数据。",
        "- `<任务产物路径>/tasks/<ticket_id>/nodes/<node_id>.json`: 单任务节点明细。",
        "- `<任务产物路径>/tasks/<ticket_id>/runs/<run_id>/...`: 完整提示词、stdout/stderr、结果与事件链路。",
        "- `<任务产物路径>/tasks/<ticket_id>/artifacts/<node_id>/output/...`: 当前节点自留产物。",
        "- `<任务产物路径>/tasks/<ticket_id>/artifacts/<node_id>/delivery/<receiver_agent_id>/...`: 指定交付对象时的交付副本。",
        "- `<任务产物路径>/delivery/<agent_name>/<task_name>/...`: 面向 agent 的顶层交付收件箱投影，系统会在这里写入最终交付件与交付标记。",
        "- `<任务产物路径>/tasks/<ticket_id>/TASK_STRUCTURE.md`: 单任务目录结构说明。",
        "",
        "## 维护规则",
        "- workflow 仅保留运行中的内存调度工作集，不在自身目录持久化任务明文。",
        "- 任务图、任务详情、执行链路与产物都应从本目录动态加载。",
        "- 每次真实执行完成并落盘后，系统会同步刷新根目录与单任务目录说明文件。",
    ]
    return "\n".join(lines).strip() + "\n"


def write_artifact_root_structure_file(artifact_root: Path, tasks_root: Path) -> Path:
    path = artifact_root_structure_file_path(artifact_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _artifact_root_structure_markdown(
            Path(artifact_root).resolve(strict=False),
            Path(tasks_root).resolve(strict=False),
        ),
        encoding="utf-8",
    )
    return path


def ensure_artifact_root_dirs(path: Path) -> tuple[Path, Path]:
    artifact_root = Path(path).resolve(strict=False)
    artifact_root.mkdir(parents=True, exist_ok=True)
    tasks_root = artifact_root / TASKS_ROOT_DIRNAME
    tasks_root.mkdir(parents=True, exist_ok=True)
    assignment_delivery_root(artifact_root).mkdir(parents=True, exist_ok=True)
    write_artifact_root_structure_file(artifact_root, tasks_root)
    return artifact_root, tasks_root


def get_artifact_root_settings(root: Path) -> dict[str, Any]:
    runtime_cfg = load_runtime_config(root)
    requested_root_text = _runtime_artifact_root_value(runtime_cfg)
    artifact_root, source = resolve_artifact_root_candidate(requested_root_text)
    path_validation_status = "ok"
    path_validation_error = ""
    if source == "invalid":
        path_validation_status = "fallback_default"
        path_validation_error = f"task_artifact_root config invalid: {requested_root_text}"
    try:
        artifact_root, tasks_root = ensure_artifact_root_dirs(artifact_root)
    except Exception as exc:
        artifact_root, tasks_root = ensure_artifact_root_dirs(DEFAULT_ARTIFACT_ROOT)
        path_validation_status = "fallback_default"
        path_validation_error = str(exc)
    return {
        "artifact_root": artifact_root.as_posix(),
        "task_artifact_root": artifact_root.as_posix(),
        "delivery_root": assignment_delivery_root(artifact_root).as_posix(),
        "workspace_root": tasks_root.as_posix(),
        "task_records_root": tasks_root.as_posix(),
        "tasks_root": tasks_root.as_posix(),
        "artifact_root_structure_path": artifact_root_structure_file_path(artifact_root).as_posix(),
        "tasks_structure_path": artifact_root_structure_file_path(artifact_root).as_posix(),
        "default_artifact_root": DEFAULT_ARTIFACT_ROOT.as_posix(),
        "default_task_artifact_root": DEFAULT_ARTIFACT_ROOT.as_posix(),
        "requested_artifact_root": requested_root_text,
        "requested_task_artifact_root": requested_root_text,
        "path_validation_status": path_validation_status,
        "path_validation_error": path_validation_error,
        "workspace_ready": True,
    }


def _cleanup_empty_legacy_tree(path: Path) -> None:
    current = Path(path).resolve(strict=False)
    for _ in range(3):
        try:
            if current.exists() and current.is_dir() and not any(current.iterdir()):
                parent = current.parent
                current.rmdir()
                current = parent
                continue
        except Exception:
            return
        return


def migrate_assignment_workspace_records(
    runtime_root: Path,
    artifact_root: Path,
    *,
    previous_artifact_root: Path | None = None,
) -> dict[str, Any]:
    target_root = assignment_workspace_records_root(artifact_root)
    target_root.mkdir(parents=True, exist_ok=True)

    raw_sources: list[Path] = []
    if isinstance(previous_artifact_root, Path):
        raw_sources.append(_legacy_artifact_workspace_records_root(previous_artifact_root))
    raw_sources.append(_legacy_artifact_workspace_records_root(artifact_root))
    raw_sources.append(legacy_assignment_workspace_records_root(runtime_root))

    seen: set[str] = {target_root.as_posix().lower()}
    sources: list[Path] = []
    for source in raw_sources:
        candidate = Path(source).resolve(strict=False)
        key = candidate.as_posix().lower()
        if key in seen:
            continue
        seen.add(key)
        sources.append(candidate)

    result: dict[str, Any] = {
        "target_root": target_root.as_posix(),
        "moved_count": 0,
        "skipped_existing_count": 0,
        "missing_source_count": 0,
        "moved_ticket_ids": [],
        "sources": [],
    }
    moved_ticket_ids: list[str] = []
    source_rows: list[dict[str, Any]] = []

    for source in sources:
        row: dict[str, Any] = {
            "source_root": source.as_posix(),
            "exists": source.exists() and source.is_dir(),
            "moved_ticket_ids": [],
            "skipped_existing_ticket_ids": [],
        }
        if not source.exists() or not source.is_dir():
            result["missing_source_count"] = int(result["missing_source_count"]) + 1
            source_rows.append(row)
            continue
        for ticket_dir in sorted(source.iterdir(), key=lambda item: item.name.lower()):
            if not ticket_dir.is_dir():
                continue
            ticket_id = str(ticket_dir.name or "").strip()
            if not ticket_id:
                continue
            target_dir = target_root / ticket_id
            if target_dir.exists():
                row["skipped_existing_ticket_ids"].append(ticket_id)
                result["skipped_existing_count"] = int(result["skipped_existing_count"]) + 1
                continue
            shutil.move(ticket_dir.as_posix(), target_dir.as_posix())
            row["moved_ticket_ids"].append(ticket_id)
            moved_ticket_ids.append(ticket_id)
            result["moved_count"] = int(result["moved_count"]) + 1
        _cleanup_empty_legacy_tree(source)
        source_rows.append(row)

    result["moved_ticket_ids"] = moved_ticket_ids
    result["sources"] = source_rows
    write_artifact_root_structure_file(
        Path(artifact_root).resolve(strict=False),
        target_root,
    )
    return result


def set_artifact_root(
    cfg: AppConfig,
    state: RuntimeState,
    requested_root: str,
) -> dict[str, Any]:
    text = str(requested_root or "").strip()
    if not text:
        raise SessionGateError(400, "task_artifact_root required", "task_artifact_root_required")
    try:
        candidate = normalize_abs_path(text, base=WORKFLOW_PROJECT_ROOT)
        artifact_root, tasks_root = ensure_artifact_root_dirs(candidate)
    except Exception as exc:
        raise SessionGateError(
            400,
            f"task_artifact_root invalid: {exc}",
            "task_artifact_root_invalid",
        ) from exc
    previous = resolve_artifact_root_path(cfg.root)
    with state.config_lock:
        try:
            save_runtime_config(
                cfg.root,
                {
                    "artifact_root": artifact_root.as_posix(),
                    TASK_ARTIFACT_ROOT_CONFIG_KEY: artifact_root.as_posix(),
                },
            )
        except Exception as exc:
            raise SessionGateError(
                500,
                f"task_artifact_root save failed: {exc}",
                "task_artifact_root_save_failed",
            ) from exc
    try:
        assignment_workspace_sync = migrate_assignment_workspace_records(
            cfg.root,
            artifact_root,
            previous_artifact_root=previous,
        )
    except Exception as exc:
        raise SessionGateError(
            500,
            f"task_artifact_root assignment sync failed: {exc}",
            "task_artifact_root_assignment_sync_failed",
            {
                "artifact_root": artifact_root.as_posix(),
                "previous_artifact_root": previous.as_posix(),
            },
        ) from exc
    append_change_log(
        cfg.root,
        "task_artifact_root_changed",
        f"from={previous.as_posix()}, to={artifact_root.as_posix()}, tasks_root={tasks_root.as_posix()}",
    )
    if int(assignment_workspace_sync.get("moved_count") or 0) > 0:
        append_change_log(
            cfg.root,
            "legacy_assignment_records_migrated",
            (
                f"target={assignment_workspace_sync.get('target_root')}, "
                f"moved={assignment_workspace_sync.get('moved_count')}, "
                f"skipped_existing={assignment_workspace_sync.get('skipped_existing_count')}"
            ),
        )
    return {
        "ok": True,
        "artifact_root": artifact_root.as_posix(),
        "task_artifact_root": artifact_root.as_posix(),
        "delivery_root": assignment_delivery_root(artifact_root).as_posix(),
        "previous_artifact_root": previous.as_posix(),
        "workspace_root": tasks_root.as_posix(),
        "task_records_root": tasks_root.as_posix(),
        "tasks_root": tasks_root.as_posix(),
        "artifact_root_structure_path": artifact_root_structure_file_path(artifact_root).as_posix(),
        "tasks_structure_path": artifact_root_structure_file_path(artifact_root).as_posix(),
        "path_validation_status": "ok",
        "workspace_ready": True,
        "default_artifact_root": DEFAULT_ARTIFACT_ROOT.as_posix(),
        "default_task_artifact_root": DEFAULT_ARTIFACT_ROOT.as_posix(),
        "assignment_workspace_sync": assignment_workspace_sync,
    }
