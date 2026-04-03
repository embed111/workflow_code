from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


_STORE_LOCK = threading.RLock()
_SCHEMA_VERSION = 1
_USER_MESSAGE_ROLES = {"user", "assistant"}
_ROOT_RUNTIME_CONFIG = Path("state") / "runtime-config.json"
_WORKFLOW_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_ARTIFACT_ROOT = (_WORKFLOW_PROJECT_ROOT.parent / ".output").resolve(strict=False)
_ABSOLUTE_RECORD_REF_TOP_LEVELS = {"sessions", "analysis", "runs", "audit", "system"}


def _now_ts() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load_json(path: Path, fallback: Any) -> Any:
    if not path.exists() or not path.is_file():
        return fallback
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return fallback
    return payload


def _load_json_dict(path: Path) -> dict[str, Any]:
    payload = _load_json(path, {})
    return payload if isinstance(payload, dict) else {}


def _load_json_list(path: Path) -> list[Any]:
    payload = _load_json(path, [])
    return payload if isinstance(payload, list) else []


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for attempt in range(10):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt >= 9:
                raise
            time.sleep(0.1)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
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


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex[:6]}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    for attempt in range(10):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt >= 9:
                raise
            time.sleep(0.1)


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


def _parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    text = str(value or "").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except Exception:
        return []
    return payload if isinstance(payload, list) else []


def _parse_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _runtime_config(root: Path) -> dict[str, Any]:
    path = Path(root).resolve(strict=False) / _ROOT_RUNTIME_CONFIG
    payload = _load_json(path, {})
    return payload if isinstance(payload, dict) else {}


def artifact_root(root: Path) -> Path:
    cfg = _runtime_config(root)
    raw = str(cfg.get("task_artifact_root") or cfg.get("artifact_root") or "").strip()
    base = _WORKFLOW_PROJECT_ROOT
    if raw:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = base / candidate
        return candidate.resolve(strict=False)
    return _DEFAULT_ARTIFACT_ROOT


def records_root(root: Path) -> Path:
    return artifact_root(root) / "records"


def work_records_structure_path(root: Path) -> Path:
    return artifact_root(root) / "WORKFLOW_RECORDS_STRUCTURE.md"


def records_index_path(root: Path) -> Path:
    return records_root(root) / "index.json"


def sessions_root(root: Path) -> Path:
    return records_root(root) / "sessions"


def sessions_index_path(root: Path) -> Path:
    return sessions_root(root) / "index.json"


def session_dir(root: Path, session_id: str) -> Path:
    return sessions_root(root) / str(session_id or "").strip()


def session_record_path(root: Path, session_id: str) -> Path:
    return session_dir(root, session_id) / "session.json"


def session_messages_path(root: Path, session_id: str) -> Path:
    return session_dir(root, session_id) / "messages.jsonl"


def analysis_root(root: Path) -> Path:
    return records_root(root) / "analysis"


def analysis_index_path(root: Path) -> Path:
    return analysis_root(root) / "index.json"


def analysis_dir(root: Path, analysis_id: str) -> Path:
    return analysis_root(root) / str(analysis_id or "").strip()


def analysis_record_path(root: Path, analysis_id: str) -> Path:
    return analysis_dir(root, analysis_id) / "analysis.json"


def workflow_record_path(root: Path, analysis_id: str) -> Path:
    return analysis_dir(root, analysis_id) / "workflow.json"


def analysis_runs_root(root: Path, analysis_id: str) -> Path:
    return analysis_dir(root, analysis_id) / "runs"


def analysis_run_record_path(root: Path, analysis_id: str, analysis_run_id: str) -> Path:
    return analysis_runs_root(root, analysis_id) / f"{str(analysis_run_id or '').strip()}.json"


def analysis_workflow_events_path(root: Path, analysis_id: str) -> Path:
    return analysis_dir(root, analysis_id) / "workflow-events.jsonl"


def training_record_path(root: Path, analysis_id: str) -> Path:
    return analysis_dir(root, analysis_id) / "training.json"


def runs_root(root: Path) -> Path:
    return records_root(root) / "runs"


def runs_index_path(root: Path) -> Path:
    return runs_root(root) / "index.json"


def run_dir(root: Path, task_id: str) -> Path:
    return runs_root(root) / str(task_id or "").strip()


def run_record_path(root: Path, task_id: str) -> Path:
    return run_dir(root, task_id) / "run.json"


def run_trace_path(root: Path, task_id: str) -> Path:
    return run_dir(root, task_id) / "trace.json"


def run_stdout_path(root: Path, task_id: str) -> Path:
    return run_dir(root, task_id) / "stdout.txt"


def run_stderr_path(root: Path, task_id: str) -> Path:
    return run_dir(root, task_id) / "stderr.txt"


def run_summary_path(root: Path, task_id: str) -> Path:
    return run_dir(root, task_id) / "summary.md"


def run_events_path(root: Path, task_id: str) -> Path:
    return run_dir(root, task_id) / "events.log"


def audit_root(root: Path) -> Path:
    return records_root(root) / "audit"


def message_delete_audit_path(root: Path) -> Path:
    return audit_root(root) / "message-delete.jsonl"


def policy_confirmation_audit_path(root: Path) -> Path:
    return audit_root(root) / "policy-confirmation.jsonl"


def policy_patch_tasks_root(root: Path) -> Path:
    return audit_root(root) / "policy-patch-tasks"


def policy_patch_index_path(root: Path) -> Path:
    return policy_patch_tasks_root(root) / "index.json"


def policy_patch_task_path(root: Path, patch_task_id: str) -> Path:
    return policy_patch_tasks_root(root) / f"{str(patch_task_id or '').strip()}.json"


def system_root(root: Path) -> Path:
    return records_root(root) / "system"


def workflow_events_path(root: Path) -> Path:
    return system_root(root) / "workflow-events.jsonl"


def ingress_requests_path(root: Path) -> Path:
    return system_root(root) / "ingress-requests.json"


def reconcile_runs_path(root: Path) -> Path:
    return system_root(root) / "reconcile-runs.jsonl"


def daily_summary_path(root: Path) -> Path:
    return system_root(root) / "daily-summary.md"


def session_snapshot_path(root: Path) -> Path:
    return system_root(root) / "session-snapshot.md"


def change_log_path(root: Path) -> Path:
    return system_root(root) / "change-log.md"


def failure_cases_path(root: Path) -> Path:
    return system_root(root) / "failure-cases.md"


def web_e2e_path(root: Path) -> Path:
    return system_root(root) / "web-e2e.md"


def system_runs_root(root: Path) -> Path:
    return system_root(root) / "runs"


from . import work_record_store_index as _record_index


def _map_absolute_work_record_ref(root: Path, ref: str) -> str:
    text = str(ref or "").strip()
    if not text:
        return ""
    candidate = Path(text)
    if not candidate.is_absolute():
        return ""
    parts = [part for part in text.replace("\\", "/").split("/") if part]
    for index, part in enumerate(parts):
        lowered = part.lower()
        if lowered == "records" and index + 1 < len(parts):
            next_part = parts[index + 1].lower()
            if next_part in _ABSOLUTE_RECORD_REF_TOP_LEVELS:
                return (artifact_root(root) / Path(*parts[index:])).as_posix()
        if lowered == "workspace" and index + 1 < len(parts):
            next_part = parts[index + 1].lower()
            if next_part == "assignments":
                tail = parts[index + 2 :]
                return (artifact_root(root) / "tasks" / Path(*tail)).as_posix()
    return ""


def normalize_work_record_ref(
    root: Path,
    ref: str,
    *,
    task_id: str = "",
    analysis_id: str = "",
) -> str:
    text = str(ref or "").strip()
    if not text:
        return ""
    normalized = _map_absolute_work_record_ref(root, text) or text.replace("\\", "/")
    artifact_prefix = artifact_root(root).as_posix().rstrip("/")
    normalized = normalized.replace(f"{artifact_prefix}/workspace/assignments/", f"{artifact_prefix}/tasks/")
    normalized = normalized.replace("workspace/assignments/", "tasks/")
    if normalized.rstrip("/") == "logs/runs":
        return (system_root(root) / "runs").as_posix()
    if normalized.rstrip("/") == "logs/events":
        return workflow_events_path(root).as_posix()
    if normalized.startswith("logs/runs/task-") and normalized.endswith(".md"):
        mapped_task_id = task_id or Path(normalized).stem
        return run_summary_path(root, mapped_task_id).as_posix()
    if normalized.startswith("logs/runs/reconcile-") and normalized.endswith(".md"):
        return (system_root(root) / "runs" / Path(normalized).name).as_posix()
    if normalized.startswith("logs/events/"):
        return workflow_events_path(root).as_posix()
    if normalized.startswith("logs/decisions/") and analysis_id:
        return analysis_record_path(root, analysis_id).as_posix()
    if normalized.startswith("logs/summaries/daily-summary.md"):
        return daily_summary_path(root).as_posix()
    if normalized.startswith("logs/summaries/failure-cases.md"):
        return failure_cases_path(root).as_posix()
    if normalized.startswith("state/session-snapshot.md"):
        return session_snapshot_path(root).as_posix()
    if normalized.startswith("state/change-log.md"):
        return change_log_path(root).as_posix()
    return normalized


def write_structure_file(root: Path) -> Path:
    return _record_index.write_structure_file(root)


def rebuild_record_indexes(root: Path) -> None:
    _record_index.rebuild_record_indexes(root)


def _sync_session_index(root: Path, session_id: str) -> None:
    _record_index.sync_session_bundle(root, session_id)


def _sync_analysis_index(root: Path, analysis_id: str) -> None:
    _record_index.sync_analysis_bundle(root, analysis_id)


def _sync_task_run_index(root: Path, task_id: str) -> None:
    _record_index.sync_record_task_run(root, task_id)


def _sync_policy_patch_index(root: Path, patch_task_id: str) -> None:
    _record_index.sync_policy_patch_task(root, patch_task_id)


def sync_assignment_task_bundle(root: Path, ticket_id: str) -> None:
    _record_index.sync_assignment_task_bundle(root, ticket_id)


def ensure_store(root: Path) -> None:
    with _STORE_LOCK:
        for path in (
            sessions_root(root),
            analysis_root(root),
            runs_root(root),
            policy_patch_tasks_root(root),
            system_root(root),
        ):
            path.mkdir(parents=True, exist_ok=True)
        write_structure_file(root)
        _record_index.ensure_sqlite_index(root)
        index_paths = (
            sessions_index_path(root),
            analysis_index_path(root),
            runs_index_path(root),
            policy_patch_index_path(root),
            records_index_path(root),
        )
        if any(not path.exists() for path in index_paths):
            rebuild_record_indexes(root)


