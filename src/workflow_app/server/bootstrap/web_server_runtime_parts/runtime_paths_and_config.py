#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ...runtime.agent_runtime import AgentConfigError, AgentRuntimeError, chat_once, stream_chat
from ...entry.workflow_entry_cli import (
    append_decision_markdown as append_decision_log,
    create_training_id,
    decision_to_status,
    run_trainer_once,
)
from ...history.workflow_history_admin import (
    cleanup_history as admin_cleanup_history,
    delete_session_history,
    delete_training_content,
)
from ...runtime.training_center_runtime import (
    TrainingCenterError,
    bind_runtime as bind_training_center_runtime,
    clone_training_agent_from_current,
    complete_role_creation_session,
    create_role_creation_session,
    delete_role_creation_session,
    create_role_creation_task,
    confirm_training_agent_release_review,
    create_training_plan_and_enqueue,
    discard_agent_pre_release,
    discard_training_agent_release_review,
    dispatch_next_training_queue_item,
    discover_training_trainers,
    enter_training_queue_next_round,
    enter_training_agent_release_review,
    get_role_creation_session_detail,
    get_training_agent_release_review,
    get_training_queue_loop,
    get_training_queue_status_detail,
    execute_training_queue_item,
    get_training_run_detail,
    is_system_or_test_workspace,
    list_role_creation_sessions,
    list_training_agent_releases,
    list_training_agents_overview,
    list_training_queue_items,
    post_role_creation_message,
    retry_role_creation_session_analysis,
    rename_training_queue_item,
    remove_training_queue_item,
    rollback_training_queue_round_increment,
    set_training_agent_avatar,
    submit_manual_release_evaluation,
    submit_training_agent_release_review_manual,
    switch_training_agent_release,
    start_role_creation_session,
    archive_role_creation_task,
    update_role_creation_session_stage,
)

from ..presentation.pages import load_index_page_css, load_index_page_html

DEFAULT_WORKFLOW_FOCUS = "Workflow web workbench and runtime orchestration"
AB_STATE_FILE = "state/ab-slots.json"
RUNTIME_CONFIG_FILE = "state/runtime-config.json"
DEFAULT_AGENTS_ROOT = Path(os.getenv("WORKFLOW_AGENTS_ROOT") or "C:/work/agents")
AGENT_SEARCH_ROOT_NOT_SET_CODE = "agent_search_root_not_set"
DEFAULT_RUNTIME_ENVIRONMENT = "source"
SHOW_TEST_DATA_SOURCE_ENVIRONMENT_POLICY = "environment_policy"
WORKFLOW_APP_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ARTIFACT_ROOT = (WORKFLOW_PROJECT_ROOT.parent / ".output").resolve(strict=False)
TRAINER_SOURCE_ROOT = (WORKFLOW_PROJECT_ROOT.parent / "trainer").resolve(strict=False)
TRAINING_PRIORITY_LEVELS = ("P0", "P1", "P2", "P3")
TRAINING_PRIORITY_RANK = {name: idx for idx, name in enumerate(TRAINING_PRIORITY_LEVELS)}
MAX_GENERATION_CONCURRENCY = 5
CHAT_INGRESS_ROUTES = ("/api/chat", "/api/chat/stream", "/api/tasks/execute")
AB_FEATURE_ENABLED = str(os.getenv("WORKFLOW_AB_ENABLED") or "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)


TEST_DATA_AUTO_CLEANUP_ENABLED = str(
    os.getenv("WORKFLOW_TESTDATA_AUTO_CLEANUP") or "1"
).strip().lower() in {"1", "true", "yes", "on"}
TEST_DATA_CLEANUP_INTERVAL_S = max(
    3600,
    env_int("WORKFLOW_TESTDATA_CLEANUP_INTERVAL_S", 86400),
)
TEST_DATA_MAX_AGE_HOURS = max(
    1,
    env_int("WORKFLOW_TESTDATA_MAX_AGE_HOURS", 168),
)
ALLOW_MANUAL_POLICY_INPUT_DEFAULT = str(
    os.getenv("WORKFLOW_ALLOW_MANUAL_POLICY_INPUT") or "1"
).strip().lower() in {"1", "true", "yes", "on"}


HTML_PAGE = load_index_page_html()
CSS_PAGE = load_index_page_css()



@dataclass
class AppConfig:
    root: Path
    entry_script: Path
    agent_search_root: Path | None
    agent_search_root_requested_text: str
    show_test_data: bool
    host: str
    port: int
    focus: str
    reconcile_interval_s: int
    allow_manual_policy_input: bool
    runtime_environment: str = DEFAULT_RUNTIME_ENVIRONMENT
    show_test_data_source: str = SHOW_TEST_DATA_SOURCE_ENVIRONMENT_POLICY


@dataclass
class RuntimeState:
    stream_lock: threading.Lock = field(default_factory=threading.Lock)
    active_streams: dict[str, threading.Event] = field(default_factory=dict)
    reconcile_lock: threading.Lock = field(default_factory=threading.Lock)
    session_lock_guard: threading.Lock = field(default_factory=threading.Lock)
    session_locks: dict[str, "SessionLockEntry"] = field(default_factory=dict)
    task_runtime_lock: threading.Lock = field(default_factory=threading.Lock)
    active_tasks: dict[str, "TaskRuntime"] = field(default_factory=dict)
    generation_semaphore: threading.Semaphore = field(
        default_factory=lambda: threading.Semaphore(MAX_GENERATION_CONCURRENCY)
    )
    config_lock: threading.Lock = field(default_factory=threading.Lock)
    workflow_lock: threading.Lock = field(default_factory=threading.Lock)
    analyzing_workflows: set[str] = field(default_factory=set)
    stop_event: threading.Event = field(default_factory=threading.Event)


@dataclass
class TaskRuntime:
    task_id: str
    session_id: str
    agent_name: str
    process: subprocess.Popen[str] | None = None
    interrupted: bool = False
    stop_event: threading.Event = field(default_factory=threading.Event)


class SessionGateError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        message: str,
        code: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.extra = dict(extra or {})


class ConcurrencyLimitError(RuntimeError):
    pass


@dataclass
class SessionLockEntry:
    lock: threading.Lock = field(default_factory=threading.Lock)
    ref_count: int = 0


@dataclass
class GenerationLease:
    session_id: str
    lock: threading.Lock


class WorkflowGateError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        message: str,
        code: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.extra = dict(extra or {})


ANALYSIS_STATE_PENDING = "未分析"
ANALYSIS_STATE_DONE = "已分析"
AGENT_POLICY_ERROR_CODE = "agent_policy_extract_failed"
AGENT_POLICY_CONFIRM_CODE = "agent_policy_confirmation_required"
AGENT_POLICY_CLARITY_BLOCKED_CODE = "agent_policy_clarity_blocked"
AGENT_POLICY_REANALYZE_REQUIRED_CODE = "agent_policy_reanalyze_required"
AGENT_POLICY_OUT_OF_SCOPE_CODE = "target_agents_path_out_of_scope"
MANUAL_POLICY_INPUT_DISABLED_CODE = "manual_policy_input_disabled"
MANUAL_POLICY_INPUT_NOT_ALLOWED_CODE = "manual_policy_input_not_allowed"
POLICY_ALIGNMENT_ALIGNED = "aligned"
POLICY_ALIGNMENT_DEVIATED = "deviated"
POLICY_CLARITY_AUTO_THRESHOLD = 80
POLICY_CLARITY_CONFIRM_THRESHOLD = 60
POLICY_SCORE_MODEL = "v2"
POLICY_EXTRACT_SOURCE = "codex_exec"
POLICY_PROMPT_VERSION = "2026-03-01-codex-exec-v2-evidence"
POLICY_CODEX_TIMEOUT_S = max(
    30,
    env_int("WORKFLOW_POLICY_CODEX_TIMEOUT_S", 180),
)
POLICY_TRACE_DIR = Path(".runtime") / "policy-extract"
POLICY_SCORE_WEIGHTS: dict[str, float] = {
    "completeness": 0.2,
    "executability": 0.2,
    "consistency": 0.2,
    "traceability": 0.15,
    "risk_coverage": 0.15,
    "operability": 0.1,
}
POLICY_SCORE_DIMENSION_META: tuple[tuple[str, str], ...] = (
    ("completeness", "完整性"),
    ("executability", "可执行边界"),
    ("consistency", "一致性"),
    ("traceability", "可追溯性"),
    ("risk_coverage", "风险覆盖度"),
    ("operability", "可操作性"),
)


_WIN_ABS_PATH_PATTERN = re.compile(r"(?i)\b[A-Z]:[\\/][^\s\"'`]+")
_ROOT_ALIAS_PATH_PATTERN = re.compile(r"(?i)\$root(?:[\\/][^\s\"'`]+)?")


def now_local() -> datetime:
    return datetime.now().astimezone()


def iso_ts(ts: datetime) -> str:
    return ts.isoformat(timespec="seconds")


def date_key(ts: datetime) -> str:
    return ts.strftime("%Y%m%d")


def web_asset_path(name: str) -> Path:
    return WORKFLOW_APP_ROOT / name


def web_client_parts_dir() -> Path:
    return WORKFLOW_APP_ROOT / "web_client"


def web_client_bundle_manifest_path() -> Path:
    return web_client_parts_dir() / "bundle_manifest.json"


def load_web_client_bundle_manifest() -> list[str]:
    manifest_path = web_client_bundle_manifest_path()
    if not manifest_path.exists():
        raise FileNotFoundError("web client bundle manifest missing")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"invalid web client bundle manifest: {exc}") from exc
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("web client bundle manifest must be a non-empty array")
    names: list[str] = []
    seen: set[str] = set()
    for raw in payload:
        name = str(raw or "").strip()
        if not name:
            continue
        if "/" in name or "\\" in name:
            raise RuntimeError(f"invalid manifest item path: {name}")
        if not name.lower().endswith(".js"):
            raise RuntimeError(f"manifest item must be .js: {name}")
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    if not names:
        raise RuntimeError("web client bundle manifest has no valid js entries")
    return names


def load_web_client_asset_text() -> str:
    parts_root = web_client_parts_dir()
    if parts_root.exists() and parts_root.is_dir():
        try:
            manifest_names = load_web_client_bundle_manifest()
            chunks: list[str] = []
            for name in manifest_names:
                part = parts_root / name
                if not part.exists() or not part.is_file():
                    raise FileNotFoundError(f"web client manifest part missing: {name}")
                chunks.append(part.read_text(encoding="utf-8"))
            return "\n".join(chunks)
        except FileNotFoundError:
            pass
    asset = web_asset_path("workflow_web_client.js")
    if not asset.exists():
        raise FileNotFoundError("workflow web client asset missing")
    return asset.read_text(encoding="utf-8")


def relative_to_root(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def runtime_config_file(root: Path) -> Path:
    return root / RUNTIME_CONFIG_FILE


def load_runtime_config(
    root: Path,
    *,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = runtime_config_file(root)
    if isinstance(meta, dict):
        meta.clear()
        meta.update(
            {
                "path": path.as_posix(),
                "exists": bool(path.exists()),
                "status": "missing",
                "error": "",
            }
        )
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        if isinstance(meta, dict):
            meta["status"] = "invalid_json"
            meta["error"] = str(exc)
        return {}
    if not isinstance(payload, dict):
        if isinstance(meta, dict):
            meta["status"] = "invalid_type"
            meta["error"] = "runtime-config payload must be a JSON object"
        return {}
    if isinstance(meta, dict):
        meta["status"] = "ok"
    return payload


def save_runtime_config(root: Path, patch: dict[str, Any]) -> None:
    if not patch:
        return
    path = runtime_config_file(root)
    current = load_runtime_config(root)
    current.update(patch)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _runtime_artifact_root_value(runtime_cfg: dict[str, Any]) -> str:
    if not isinstance(runtime_cfg, dict):
        return ""
    preferred = str(runtime_cfg.get("task_artifact_root") or "").strip()
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
    runtime_cfg_meta: dict[str, Any] = {}
    runtime_cfg = load_runtime_config(root, meta=runtime_cfg_meta)
    runtime_cfg_status = str(runtime_cfg_meta.get("status") or "").strip().lower()
    if runtime_cfg_status and runtime_cfg_status not in {"ok", "missing"}:
        detail = str(runtime_cfg_meta.get("path") or "").strip() or runtime_config_file(root).as_posix()
        error_text = str(runtime_cfg_meta.get("error") or "").strip()
        if error_text:
            detail = f"{detail} ({error_text})"
        print(
            f"web> runtime-config load fallback ({runtime_cfg_status}): {detail}",
            flush=True,
        )
    candidate_root, _source = resolve_artifact_root_candidate(_runtime_artifact_root_value(runtime_cfg))
    try:
        return ensure_artifact_root_dirs(candidate_root)[0]
    except Exception:
        return ensure_artifact_root_dirs(DEFAULT_ARTIFACT_ROOT)[0]


def artifact_root_structure_file_path(artifact_root: Path) -> Path:
    return Path(artifact_root).resolve(strict=False) / "TASKS_STRUCTURE.md"


def assignment_delivery_root(artifact_root: Path) -> Path:
    return (Path(artifact_root).resolve(strict=False) / "delivery").resolve(strict=False)


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
        f"- 根目录说明文件: {artifact_root_structure_file_path(artifact_root).name}",
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
    tasks_root = artifact_root / "tasks"
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


def assignment_workspace_records_root(artifact_root: Path) -> Path:
    return (Path(artifact_root).resolve(strict=False) / "tasks").resolve(strict=False)


def legacy_assignment_workspace_records_root(runtime_root: Path) -> Path:
    return (Path(runtime_root).resolve(strict=False) / "workspace" / "assignments").resolve(strict=False)


def _legacy_artifact_workspace_records_root(artifact_root: Path) -> Path:
    return (Path(artifact_root).resolve(strict=False) / "workspace" / "assignments").resolve(strict=False)


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

    sources: list[Path] = []
    seen_keys = {target_root.as_posix().lower()}
    for source in raw_sources:
        candidate = Path(source).resolve(strict=False)
        key = candidate.as_posix().lower()
        if key in seen_keys:
            continue
        seen_keys.add(key)
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
        try:
            if source.exists() and source.is_dir() and not any(source.iterdir()):
                parent = source.parent
                source.rmdir()
                if parent.exists() and parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
        except Exception:
            pass
        source_rows.append(row)

    result["moved_ticket_ids"] = moved_ticket_ids
    result["sources"] = source_rows
    write_artifact_root_structure_file(
        Path(artifact_root).resolve(strict=False),
        target_root,
    )
    return result


def safe_token(value: str, default: str, max_len: int) -> str:
    text = (value or "").strip()
    if not text:
        text = default
    text = text[:max_len]
    return re.sub(r"[^0-9A-Za-z._:-]", "-", text)


def parse_bool_flag(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on", "y"}:
        return True
    if text in {"0", "false", "no", "off", "n"}:
        return False
    return default


def parse_query_bool(query: dict[str, list[str]], key: str, default: bool = False) -> bool:
    values = query.get(key) or []
    if not values:
        return default
    return parse_bool_flag(values[0], default=default)


def normalize_runtime_environment(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"prod", "production"}:
        return "prod"
    if text in {"dev", "development"}:
        return "dev"
    if text == "test":
        return "test"
    return text or DEFAULT_RUNTIME_ENVIRONMENT


def resolve_show_test_data_policy(
    runtime_cfg: dict[str, Any],
    *,
    environment: str,
) -> tuple[bool, str]:
    env_name = normalize_runtime_environment(environment)
    if env_name == "prod":
        return False, SHOW_TEST_DATA_SOURCE_ENVIRONMENT_POLICY
    if not isinstance(runtime_cfg, dict) or "show_test_data" not in runtime_cfg:
        return False, SHOW_TEST_DATA_SOURCE_ENVIRONMENT_POLICY
    return (
        parse_bool_flag(runtime_cfg.get("show_test_data"), default=False),
        SHOW_TEST_DATA_SOURCE_ENVIRONMENT_POLICY,
    )


def new_session_id() -> str:
    return f"sess-web-{now_local().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def normalize_abs_path(raw: str, *, base: Path) -> Path:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("empty path")
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve(strict=False)


def path_in_scope(path: Path, scope: Path) -> bool:
    try:
        path.relative_to(scope)
        return True
    except ValueError:
        return False


def validate_workspace_root_semantics(workspace_root: Path) -> tuple[bool, str]:
    root = workspace_root.resolve(strict=False)
    if not root.exists() or not root.is_dir():
        return False, "workspace_root_not_directory"
    workflow_dir = root / "workflow"
    if not workflow_dir.exists() or not workflow_dir.is_dir():
        return False, "workspace_root_missing_workflow_subdir"
    return True, ""


def agent_search_root_state(agent_search_root: Path | None) -> tuple[bool, str]:
    if agent_search_root is None:
        return False, AGENT_SEARCH_ROOT_NOT_SET_CODE
    ok, code = validate_workspace_root_semantics(agent_search_root)
    if not ok:
        return False, code or "workspace_root_invalid"
    return True, ""


def agent_search_root_text(agent_search_root: Path | None) -> str:
    if isinstance(agent_search_root, Path):
        return agent_search_root.as_posix()
    return ""


def agent_search_root_block_message(error_code: str) -> str:
    code = str(error_code or "").strip().lower()
    if code == AGENT_SEARCH_ROOT_NOT_SET_CODE:
        return "agent_search_root 未设置，请先在设置页配置有效路径。"
    return f"agent_search_root 无效，请先在设置页修正路径（{code}）。"


def policy_extract_trace_root(root: Path) -> Path:
    return root / POLICY_TRACE_DIR


def clean_target_token(raw: str) -> str:
    return str(raw or "").strip().strip("\"'").rstrip(".,;")


def resolve_root_alias(raw: str, scope: Path) -> str:
    text = clean_target_token(raw)
    if not text:
        return text
    low = text.lower()
    if not low.startswith("$root"):
        return text
    suffix = text[5:]
    if suffix and suffix[0] not in ("/", "\\"):
        return text
    relative = suffix[1:] if suffix else ""
    if not relative:
        return scope.as_posix()
    return (scope / Path(relative)).resolve(strict=False).as_posix()


def collect_write_targets(message: str, explicit_targets: list[str]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for raw in explicit_targets:
        text = clean_target_token(raw)
        if not text or text in seen:
            continue
        values.append(text)
        seen.add(text)
    for match in _WIN_ABS_PATH_PATTERN.findall(message or ""):
        text = clean_target_token(str(match))
        if not text or text in seen:
            continue
        values.append(text)
        seen.add(text)
    for match in _ROOT_ALIAS_PATH_PATTERN.findall(message or ""):
        text = clean_target_token(str(match))
        if not text or text in seen:
            continue
        values.append(text)
        seen.add(text)
    return values


def normalize_write_targets(scope: Path, values: list[str]) -> list[str]:
    out: list[str] = []
    seen_norm: set[str] = set()
    for raw in values:
        resolved = resolve_root_alias(raw, scope)
        path = normalize_abs_path(resolved, base=scope)
        if not path_in_scope(path, scope):
            raise SessionGateError(400, f"path out of root: {raw}", "path_out_of_root")
        norm = path.as_posix()
        if norm in seen_norm:
            continue
        seen_norm.add(norm)
        out.append(norm)
    return out


def connect_db(root: Path) -> sqlite3.Connection:
    from ..infra.db.connection import connect_db as _connect_db

    return _connect_db(root)


def ensure_dirs(root: Path) -> None:
    for rel in [
        "metrics",
        "state",
        "state/slots",
        "docs/workflow",
    ]:
        (root / rel).mkdir(parents=True, exist_ok=True)


def ensure_tables(root: Path) -> None:
    from ..infra.db.migrations import ensure_tables as _ensure_tables

    _ensure_tables(
        root,
        analysis_state_pending=ANALYSIS_STATE_PENDING,
        default_agents_root=DEFAULT_AGENTS_ROOT.resolve(strict=False).as_posix(),
    )


def ensure_metric_files(root: Path) -> None:
    cli = root / "metrics" / "cli-baseline-latency.json"
    wf = root / "metrics" / "workflow-latency-daily.json"
    if not cli.exists():
        cli.write_text(
            json.dumps(
                {
                    "date": now_local().strftime("%Y-%m-%d"),
                    "status": "blocked",
                    "reason": "baseline not measured yet or real agent not configured",
                    "samples": [],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if not wf.exists():
        wf.write_text(
            json.dumps(
                {
                    "date": now_local().strftime("%Y-%m-%d"),
                    "status": "running",
                    "samples": [],
                    "p95_first_token_ms": None,
                    "p95_total_ms": None,
                    "updated_at": iso_ts(now_local()),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def percentile(values: list[int], p: float) -> int | None:
    if not values:
        return None
    vals = sorted(values)
    idx = max(0, min(len(vals) - 1, int(round((len(vals) - 1) * p))))
    return vals[idx]


def append_workflow_latency(root: Path, sample: dict[str, Any]) -> None:
    path = root / "metrics" / "workflow-latency-daily.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    if not data:
        data = {
            "date": now_local().strftime("%Y-%m-%d"),
            "status": "running",
            "samples": [],
        }
    samples = data.get("samples")
    if not isinstance(samples, list):
        samples = []
    samples.append(sample)
    samples = samples[-500:]
    data["samples"] = samples
    ft = [int(s["first_token_ms"]) for s in samples if s.get("first_token_ms") is not None]
    tt = [int(s["total_ms"]) for s in samples if s.get("total_ms") is not None]
    data["p95_first_token_ms"] = percentile(ft, 0.95)
    data["p95_total_ms"] = percentile(tt, 0.95)
    data["updated_at"] = iso_ts(now_local())
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def event_id() -> str:
    ts = now_local()
    return f"evt-{date_key(ts)}-{int(time.time()*1000)}-{uuid.uuid4().hex[:6]}"


def task_id() -> str:
    ts = now_local()
    return f"REQ-{date_key(ts)}-{uuid.uuid4().hex[:6]}"
