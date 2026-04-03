from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any


RUNTIME_ENV_VAR = "WORKFLOW_RUNTIME_ENV"
RUNTIME_SOURCE_ROOT_VAR = "WORKFLOW_RUNTIME_SOURCE_ROOT"
RUNTIME_CONTROL_ROOT_VAR = "WORKFLOW_RUNTIME_CONTROL_ROOT"
RUNTIME_MANIFEST_PATH_VAR = "WORKFLOW_RUNTIME_MANIFEST_PATH"
RUNTIME_DEPLOY_ROOT_VAR = "WORKFLOW_RUNTIME_DEPLOY_ROOT"
RUNTIME_VERSION_VAR = "WORKFLOW_RUNTIME_VERSION"
RUNTIME_PID_FILE_VAR = "WORKFLOW_RUNTIME_PID_FILE"
RUNTIME_INSTANCE_FILE_VAR = "WORKFLOW_RUNTIME_INSTANCE_FILE"

PROD_UPGRADE_EXIT_CODE = 73

_RUNTIME_UPGRADE_HIGHLIGHT_CACHE: dict[tuple[str, str], list[str]] = {}
_RUNTIME_UPGRADE_HIGHLIGHT_RULES: tuple[dict[str, Any], ...] = (
    {
        "prefixes": (
            "src/workflow_app/web_client/runtime_upgrade_banner.js",
            "src/workflow_app/server/api/runtime_upgrade.py",
        ),
        "message": "升级切换完成后，成功确认窗会更快出现，不再长时间空等。",
    },
    {
        "prefixes": (
            "src/workflow_app/server/presentation/templates/index_runtime_upgrade_banner.css",
        ),
        "message": "升级弹窗改成更扁平的配色，去掉了明显的渐变、发光和厚重阴影。",
    },
    {
        "prefixes": (
            "src/workflow_app/server/services/runtime_upgrade_service.py",
        ),
        "message": "升级完成后会明确列出本次修复与变化，而不是只给笼统说明。",
    },
    {
        "prefixes": (
            "src/workflow_app/server/services/assignment_service_parts/assignment_core.py",
            "src/workflow_app/server/services/assignment_service_parts/task_artifact_store_core.py",
            "src/workflow_app/server/services/assignment_service_parts/workspace_state_and_metrics.py",
            "src/workflow_app/web_client/assignment_center_state_helpers.js",
            "src/workflow_app/web_client/assignment_center_render_runtime.js",
            "src/workflow_app/server/presentation/templates/index.html",
        ),
        "message": "任务中心已统一交付方式和交付对象，未指定时默认交付给当前 agent。",
    },
    {
        "prefixes": (
            "src/workflow_app/server/services/assignment_service_parts/",
            "src/workflow_app/server/api/assignments.py",
            "src/workflow_app/web_client/assignment_center_",
            "src/workflow_app/server/presentation/templates/index_training_loop_panels.css",
        ),
        "message": "任务产物默认按 HTML 生成，任务详情里可以直接打开查看。",
    },
    {
        "prefixes": (
            "src/workflow_app/server/bootstrap/web_server_runtime_parts/event_persistence_and_flags.py",
            "src/workflow_app/server/bootstrap/web_server_runtime_parts/runtime_paths_and_config.py",
            "scripts/start_workflow_env.ps1",
        ),
        "message": "工作区路径配置与升级启动稳定性有更新，无害断连日志会更安静。",
    },
)
_RUNTIME_UPGRADE_GENERIC_HIGHLIGHTS: tuple[tuple[str, str], ...] = (
    ("src/workflow_app/web_client/", "页面交互和展示体验有更新。"),
    ("src/workflow_app/server/api/", "接口返回和页面联动逻辑有更新。"),
    ("src/workflow_app/server/bootstrap/", "启动流程和运行时配置有更新。"),
    ("src/workflow_app/server/services/", "服务端执行和稳定性逻辑有更新。"),
    ("scripts/", "部署与环境切换脚本有更新。"),
)
_RUNTIME_UPGRADE_TERMINAL_ACTION_STATUSES = {
    "success",
    "failed",
    "rollback_success",
    "rollback_failed",
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _remove_file(path: Path | None) -> None:
    if not isinstance(path, Path):
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except Exception:
        return


def _env_path(name: str) -> Path | None:
    text = str(os.getenv(name) or "").strip()
    if not text:
        return None
    return Path(text).resolve(strict=False)


def _parse_timestamp(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except Exception:
        return None


def _version_rank(value: dict[str, Any]) -> str:
    return str(value.get("version_rank") or value.get("current_version_rank") or value.get("version") or value.get("current_version") or "").strip()


def current_runtime_environment() -> str:
    text = str(os.getenv(RUNTIME_ENV_VAR) or "").strip().lower()
    return text or "source"


def current_runtime_source_root() -> Path | None:
    return _env_path(RUNTIME_SOURCE_ROOT_VAR)


def current_runtime_control_root() -> Path | None:
    env_path = _env_path(RUNTIME_CONTROL_ROOT_VAR)
    if isinstance(env_path, Path):
        return env_path
    deploy_root = _env_path(RUNTIME_DEPLOY_ROOT_VAR)
    if isinstance(deploy_root, Path) and deploy_root.parent.name == ".running":
        return (deploy_root.parent / "control").resolve(strict=False)
    return None


def environment_manifest_path(environment: str) -> Path | None:
    control_root = current_runtime_control_root()
    normalized = str(environment or "").strip().lower()
    if not isinstance(control_root, Path) or not normalized:
        return None
    return (control_root / "envs" / f"{normalized}.json").resolve(strict=False)


def current_runtime_manifest_path() -> Path | None:
    env_path = _env_path(RUNTIME_MANIFEST_PATH_VAR)
    if isinstance(env_path, Path):
        return env_path
    environment = current_runtime_environment()
    return environment_manifest_path(environment)


def read_environment_manifest(environment: str) -> dict[str, Any]:
    path = environment_manifest_path(environment)
    if not isinstance(path, Path):
        return {}
    payload = _read_json(path)
    payload.setdefault("manifest_path", path.as_posix())
    return payload


def current_runtime_manifest() -> dict[str, Any]:
    path = current_runtime_manifest_path()
    if not isinstance(path, Path):
        return {}
    payload = _read_json(path)
    payload.setdefault("manifest_path", path.as_posix())
    return payload


def current_runtime_instance() -> dict[str, Any]:
    path = _env_path(RUNTIME_INSTANCE_FILE_VAR)
    if not isinstance(path, Path):
        return {}
    return _read_json(path)


def prod_candidate_path() -> Path | None:
    control_root = current_runtime_control_root()
    if not isinstance(control_root, Path):
        return None
    return (control_root / "prod-candidate.json").resolve(strict=False)


def prod_last_action_path() -> Path | None:
    control_root = current_runtime_control_root()
    if not isinstance(control_root, Path):
        return None
    return (control_root / "prod-last-action.json").resolve(strict=False)


def prod_upgrade_request_path() -> Path | None:
    control_root = current_runtime_control_root()
    if not isinstance(control_root, Path):
        return None
    return (control_root / "prod-upgrade-request.json").resolve(strict=False)


def _candidate_store_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    payload = dict(candidate or {})
    payload.pop("candidate_record_path", None)
    return payload


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[int, str, str]:
    payload = dict(candidate or {})
    return (
        1 if candidate_is_complete(payload) else 0,
        _version_rank(payload),
        str(payload.get("passed_at") or "").strip(),
    )


def _candidate_from_test_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    payload = dict(manifest or {})
    test_gate_status = str(payload.get("latest_test_gate_status") or "").strip().lower()
    if test_gate_status and test_gate_status != "passed":
        return {}
    version = str(payload.get("latest_candidate_version") or "").strip()
    candidate_app_root = str(payload.get("latest_candidate_path") or "").strip()
    evidence_path = str(payload.get("latest_test_gate_evidence") or "").strip()
    if not version or not candidate_app_root or not evidence_path:
        return {}
    control_root_text = str(payload.get("control_root") or "").strip()
    candidate_meta_path = ""
    if control_root_text:
        candidate_meta_path = (
            Path(control_root_text).resolve(strict=False) / "candidates" / version / "candidate.json"
        ).as_posix()
    result = {
        "version": version,
        "version_rank": str(payload.get("latest_candidate_version") or version).strip(),
        "source_environment": "test",
        "test_batch_id": f"test-gate-{version}",
        "passed_at": str(payload.get("latest_candidate_created_at") or payload.get("updated_at") or "").strip(),
        "evidence_path": evidence_path,
        "candidate_app_root": candidate_app_root,
        "source_root": str(payload.get("source_root") or "").strip(),
        "source_control_root": control_root_text,
        "source_manifest_path": str(payload.get("manifest_path") or "").strip(),
    }
    if candidate_meta_path:
        result["candidate_meta_path"] = candidate_meta_path
    return result


def _sync_prod_candidate_from_test_manifest(
    path: Path | None,
    local_candidate: dict[str, Any],
) -> dict[str, Any]:
    current = dict(local_candidate or {})
    test_candidate = _candidate_from_test_manifest(read_environment_manifest("test"))
    preferred = current
    if _candidate_sort_key(test_candidate) > _candidate_sort_key(current):
        preferred = test_candidate
    if not preferred:
        return {}
    if not isinstance(path, Path):
        return preferred
    preferred.setdefault("candidate_record_path", path.as_posix())
    if _candidate_store_payload(preferred) != _candidate_store_payload(current):
        stored = _candidate_store_payload(preferred)
        _write_json(path, stored)
        stored["candidate_record_path"] = path.as_posix()
        return stored
    current.setdefault("candidate_record_path", path.as_posix())
    return current


def read_prod_candidate() -> dict[str, Any]:
    path = prod_candidate_path()
    if not isinstance(path, Path):
        return {}
    payload = _read_json(path)
    payload.setdefault("candidate_record_path", path.as_posix())
    return _sync_prod_candidate_from_test_manifest(path, payload)


def read_prod_last_action() -> dict[str, Any]:
    path = prod_last_action_path()
    if not isinstance(path, Path):
        return {}
    return _read_json(path)


def _prod_upgrade_request_is_stale(
    request: dict[str, Any],
    *,
    last_action: dict[str, Any],
    current_instance: dict[str, Any],
) -> bool:
    request_candidate = str(request.get("candidate_version") or "").strip()
    if not request_candidate:
        return True

    requested_at = _parse_timestamp(request.get("requested_at"))
    instance_started_at = _parse_timestamp(current_instance.get("started_at"))
    if requested_at is not None and instance_started_at is not None and instance_started_at >= requested_at:
        return True

    action = str(last_action.get("action") or "").strip().lower()
    status = str(last_action.get("status") or "").strip().lower()
    finished_at = _parse_timestamp(last_action.get("finished_at"))
    action_candidate = str(last_action.get("candidate_version") or "").strip()
    if (
        action == "upgrade"
        and status in _RUNTIME_UPGRADE_TERMINAL_ACTION_STATUSES
        and finished_at is not None
        and requested_at is not None
        and finished_at >= requested_at
        and (not action_candidate or action_candidate == request_candidate)
    ):
        return True

    return False


def read_prod_upgrade_request() -> dict[str, Any]:
    path = prod_upgrade_request_path()
    if not isinstance(path, Path):
        return {}
    payload = _read_json(path)
    if not payload:
        return {}
    if _prod_upgrade_request_is_stale(
        payload,
        last_action=read_prod_last_action(),
        current_instance=current_runtime_instance(),
    ):
        _remove_file(path)
        return {}
    return payload


def runtime_snapshot() -> dict[str, Any]:
    manifest = current_runtime_manifest()
    environment = current_runtime_environment()
    current_version = str(os.getenv(RUNTIME_VERSION_VAR) or manifest.get("current_version") or "").strip()
    current_rank = str(manifest.get("current_version_rank") or current_version).strip()
    return {
        "environment": environment,
        "source_root": (current_runtime_source_root() or Path(".")).resolve(strict=False).as_posix()
        if current_runtime_source_root()
        else "",
        "control_root": current_runtime_control_root().as_posix() if current_runtime_control_root() else "",
        "manifest": manifest,
        "manifest_path": str(manifest.get("manifest_path") or ""),
        "current_version": current_version,
        "current_version_rank": current_rank,
        "candidate": read_prod_candidate(),
        "last_action": read_prod_last_action(),
        "upgrade_request": read_prod_upgrade_request(),
    }


def candidate_is_complete(candidate: dict[str, Any]) -> bool:
    evidence_path = str(candidate.get("evidence_path") or "").strip()
    app_root = str(candidate.get("candidate_app_root") or "").strip()
    if not evidence_path or not app_root:
        return False
    return Path(evidence_path).exists() and Path(app_root).exists()


def candidate_is_newer(snapshot: dict[str, Any]) -> bool:
    candidate = dict(snapshot.get("candidate") or {})
    candidate_rank = _version_rank(candidate)
    current_rank = str(snapshot.get("current_version_rank") or "").strip()
    if not candidate_rank or not current_rank:
        return bool(candidate_rank and candidate_is_complete(candidate))
    return candidate_is_complete(candidate) and candidate_rank > current_rank


def current_runtime_deploy_root() -> Path | None:
    env_path = _env_path(RUNTIME_DEPLOY_ROOT_VAR)
    if isinstance(env_path, Path):
        return env_path
    manifest = current_runtime_manifest()
    text = str(manifest.get("deploy_root") or "").strip()
    if not text:
        return None
    return Path(text).resolve(strict=False)


def _runtime_highlight_relpath_allowed(relpath: str) -> bool:
    normalized = str(relpath or "").replace("\\", "/").strip("./")
    if not normalized:
        return False
    if normalized.startswith((".running/", ".test/", ".tmp/", ".codex/", "__pycache__/")):
        return False
    if normalized.endswith((".pyc", ".pyo", ".log", ".db", ".sqlite", ".sqlite3")):
        return False
    if normalized.startswith("src/workflow_app/"):
        return True
    if normalized.startswith("scripts/"):
        return True
    return normalized in {"run_workflow.bat"}


def _runtime_highlight_files(root: Path | None) -> dict[str, Path]:
    if not isinstance(root, Path) or not root.exists():
        return {}
    output: dict[str, Path] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relpath = path.relative_to(root).as_posix()
        if not _runtime_highlight_relpath_allowed(relpath):
            continue
        output[relpath] = path
    return output


def _runtime_upgrade_file_changed(current_path: Path, previous_path: Path) -> bool:
    try:
        current_stat = current_path.stat()
        previous_stat = previous_path.stat()
    except Exception:
        return True
    if current_stat.st_size != previous_stat.st_size:
        return True
    try:
        return current_path.read_bytes() != previous_path.read_bytes()
    except Exception:
        return True


def _runtime_upgrade_changed_relpaths(current_root: Path | None, previous_root: Path | None) -> list[str]:
    if not isinstance(current_root, Path) or not isinstance(previous_root, Path):
        return []
    cache_key = (current_root.as_posix(), previous_root.as_posix())
    cached = _RUNTIME_UPGRADE_HIGHLIGHT_CACHE.get(cache_key)
    if isinstance(cached, list):
        return list(cached)
    current_files = _runtime_highlight_files(current_root)
    previous_files = _runtime_highlight_files(previous_root)
    changed: list[str] = []
    for relpath in sorted(set(current_files.keys()) | set(previous_files.keys())):
        current_path = current_files.get(relpath)
        previous_path = previous_files.get(relpath)
        if current_path is None or previous_path is None:
            changed.append(relpath)
            continue
        if _runtime_upgrade_file_changed(current_path, previous_path):
            changed.append(relpath)
    _RUNTIME_UPGRADE_HIGHLIGHT_CACHE[cache_key] = list(changed)
    return changed


def _runtime_upgrade_match_prefix(relpath: str, prefix: str) -> bool:
    normalized_rel = str(relpath or "").replace("\\", "/").strip()
    normalized_prefix = str(prefix or "").replace("\\", "/").strip()
    if not normalized_rel or not normalized_prefix:
        return False
    if normalized_rel == normalized_prefix:
        return True
    if normalized_prefix.endswith("/"):
        return normalized_rel.startswith(normalized_prefix)
    return normalized_rel.startswith(normalized_prefix)


def _runtime_upgrade_highlights_for_changed_paths(changed_paths: list[str]) -> list[str]:
    if not changed_paths:
        return []
    highlights: list[str] = []
    for rule in _RUNTIME_UPGRADE_HIGHLIGHT_RULES:
        prefixes = rule.get("prefixes") or ()
        if any(
            _runtime_upgrade_match_prefix(relpath, prefix)
            for relpath in changed_paths
            for prefix in prefixes
        ):
            message = str(rule.get("message") or "").strip()
            if message and message not in highlights:
                highlights.append(message)
    if len(highlights) < 3:
        for prefix, message in _RUNTIME_UPGRADE_GENERIC_HIGHLIGHTS:
            if any(_runtime_upgrade_match_prefix(relpath, prefix) for relpath in changed_paths):
                if message not in highlights:
                    highlights.append(message)
            if len(highlights) >= 3:
                break
    if not highlights:
        changed_count = len(changed_paths)
        return [f"本次升级包含 {changed_count} 个已发布文件变更，建议重点留意常用操作路径。"]
    return highlights[:4]


def build_runtime_upgrade_highlights(snapshot: dict[str, Any]) -> list[str]:
    last_action = dict(snapshot.get("last_action") or {})
    if str(last_action.get("status") or "").strip().lower() != "success":
        return []
    current_root = current_runtime_deploy_root()
    manifest = snapshot.get("manifest") if isinstance(snapshot.get("manifest"), dict) else {}
    previous_root_text = str(manifest.get("backup_app_root") or "").strip()
    previous_root = Path(previous_root_text).resolve(strict=False) if previous_root_text else None
    if not isinstance(current_root, Path) or not current_root.exists():
        return []
    changed_paths = _runtime_upgrade_changed_relpaths(current_root, previous_root)
    if changed_paths:
        return _runtime_upgrade_highlights_for_changed_paths(changed_paths)
    previous_version = str(last_action.get("previous_version") or "").strip()
    current_version = str(last_action.get("current_version") or snapshot.get("current_version") or "").strip()
    if previous_version and current_version:
        return [f"正式环境已从 {previous_version} 切换到 {current_version}，本次以稳定性和体验调整为主。"]
    return ["正式环境已切换到新版本，本次包含若干体验与稳定性更新。"]


def build_runtime_upgrade_status(
    snapshot: dict[str, Any],
    *,
    running_task_count: int,
    agent_call_count: int,
) -> dict[str, Any]:
    candidate = dict(snapshot.get("candidate") or {})
    last_action = dict(snapshot.get("last_action") or {})
    request = dict(snapshot.get("upgrade_request") or {})
    environment = str(snapshot.get("environment") or "source")
    is_prod = environment == "prod"
    blocker = ""
    blocker_code = ""
    request_pending = bool(request and str(request.get("candidate_version") or "").strip())
    if running_task_count > 0:
        blocker = "存在运行中任务，暂不可升级"
        blocker_code = "running_tasks_present"
    elif request_pending:
        blocker = "正式升级正在切换中，请等待页面自动重连"
        blocker_code = "upgrade_switching"
    elif is_prod and candidate and not candidate_is_complete(candidate):
        blocker = "升级候选不完整，请先重新生成"
        blocker_code = "candidate_incomplete"
    elif is_prod and not candidate_is_newer(snapshot):
        blocker = "暂无可升级版本"
        blocker_code = "no_candidate"
    return {
        "ok": True,
        "environment": environment,
        "current_version": str(snapshot.get("current_version") or ""),
        "current_version_rank": str(snapshot.get("current_version_rank") or ""),
        "candidate_version": str(candidate.get("version") or ""),
        "candidate_version_rank": _version_rank(candidate),
        "candidate_source_environment": str(candidate.get("source_environment") or ""),
        "candidate_passed_at": str(candidate.get("passed_at") or ""),
        "candidate_evidence_path": str(candidate.get("evidence_path") or ""),
        "candidate_record_path": str(candidate.get("candidate_record_path") or ""),
        "candidate_available": bool(candidate and candidate_is_complete(candidate)),
        "candidate_is_newer": bool(candidate_is_newer(snapshot)),
        "request_pending": request_pending,
        "request_candidate_version": str(request.get("candidate_version") or ""),
        "request_requested_at": str(request.get("requested_at") or ""),
        "running_task_count": max(0, int(running_task_count)),
        "agent_call_count": max(0, int(agent_call_count)),
        "blocking_reason": blocker,
        "blocking_reason_code": blocker_code,
        "can_upgrade": bool(is_prod and not blocker and candidate_is_newer(snapshot)),
        "banner_visible": bool(is_prod and candidate_is_newer(snapshot)),
        "last_action": last_action,
        "upgrade_highlights": build_runtime_upgrade_highlights(snapshot),
    }


def write_prod_upgrade_request(
    snapshot: dict[str, Any],
    *,
    operator: str,
) -> dict[str, Any]:
    path = prod_upgrade_request_path()
    if not isinstance(path, Path):
        raise RuntimeError("runtime control root unavailable")
    candidate = dict(snapshot.get("candidate") or {})
    payload = {
        "environment": "prod",
        "requested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "requested_by": str(operator or "web-user"),
        "current_version": str(snapshot.get("current_version") or ""),
        "candidate_version": str(candidate.get("version") or ""),
        "candidate_evidence_path": str(candidate.get("evidence_path") or ""),
        "candidate_app_root": str(candidate.get("candidate_app_root") or ""),
    }
    _write_json(path, payload)
    return payload


def schedule_runtime_shutdown(
    state: Any,
    *,
    exit_code: int,
    reason: str,
    delay_seconds: float = 0.25,
) -> None:
    setattr(state, "_runtime_shutdown_code", int(exit_code))
    setattr(state, "_runtime_shutdown_reason", str(reason or ""))

    def _shutdown() -> None:
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        try:
            state.stop_event.set()
        except Exception:
            pass
        shutdown_cb = getattr(state, "_runtime_server_shutdown", None)
        if callable(shutdown_cb):
            try:
                shutdown_cb()
            except Exception:
                return

    thread = threading.Thread(target=_shutdown, name="runtime-upgrade-shutdown", daemon=True)
    thread.start()


def requested_shutdown_code(state: Any) -> int:
    try:
        return int(getattr(state, "_runtime_shutdown_code", 0) or 0)
    except Exception:
        return 0


def runtime_process_start(
    *,
    host: str,
    port: int,
) -> None:
    pid_path = _env_path(RUNTIME_PID_FILE_VAR)
    instance_path = _env_path(RUNTIME_INSTANCE_FILE_VAR)
    runtime_env = current_runtime_environment()
    payload = {
        "environment": runtime_env,
        "version": str(os.getenv(RUNTIME_VERSION_VAR) or "").strip(),
        "control_root": str(os.getenv(RUNTIME_CONTROL_ROOT_VAR) or "").strip(),
        "manifest_path": str(os.getenv(RUNTIME_MANIFEST_PATH_VAR) or "").strip(),
        "deploy_root": str(os.getenv(RUNTIME_DEPLOY_ROOT_VAR) or "").strip(),
        "pid": os.getpid(),
        "host": str(host or ""),
        "port": int(port or 0),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "running",
    }
    if isinstance(pid_path, Path):
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
    if isinstance(instance_path, Path):
        _write_json(instance_path, payload)


def runtime_process_stop() -> None:
    pid_path = _env_path(RUNTIME_PID_FILE_VAR)
    instance_path = _env_path(RUNTIME_INSTANCE_FILE_VAR)
    _remove_file(pid_path)
    if isinstance(instance_path, Path):
        current = _read_json(instance_path)
        current["stopped_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        current["status"] = "stopped"
        _write_json(instance_path, current)
