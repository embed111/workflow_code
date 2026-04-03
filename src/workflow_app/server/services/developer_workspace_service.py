from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


RUNTIME_CONFIG_FILE = Path("state") / "runtime-config.json"
WORKSPACE_REGISTRY_FILE = Path("state") / "developer-workspaces.json"
PM_ROOT_DIRNAME = "workflow"
CODE_ROOT_DIRNAME = "workflow_code"
DEFAULT_DEVELOPMENT_WORKSPACE_DIRNAME = ".repository"
DEFAULT_AGENT_RUNTIME_DIRNAME = "agent-runtime"


class DeveloperWorkspaceError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        message: str,
        code: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.code = str(code or "").strip()
        self.extra = dict(extra or {})


def _load_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _normalize_abs_path(raw: str, *, base: Path) -> Path:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("empty path")
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve(strict=False)


def _path_in_scope(path: Path, scope: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(scope.resolve(strict=False))
        return True
    except ValueError:
        return False


def _runtime_config(runtime_root: Path | None) -> dict[str, Any]:
    if runtime_root is None:
        return {}
    return _load_json_dict(runtime_root / RUNTIME_CONFIG_FILE)


def _artifact_root(
    *,
    runtime_root: Path | None,
    workspace_root: Path | None,
    runtime_cfg: dict[str, Any],
) -> Path:
    raw = str(runtime_cfg.get("task_artifact_root") or runtime_cfg.get("artifact_root") or "").strip()
    if raw:
        return _normalize_abs_path(raw, base=runtime_root or (workspace_root or Path(".")))
    base_root = (workspace_root or (runtime_root.parent if runtime_root is not None else Path("."))).resolve(strict=False)
    return (base_root / ".output").resolve(strict=False)


def _workspace_root_status(workspace_root: Path | None, pm_root: Path) -> tuple[bool, str]:
    if workspace_root is None:
        return False, "workspace_root_not_set"
    if not workspace_root.exists() or not workspace_root.is_dir():
        return False, "workspace_root_not_directory"
    if not pm_root.exists() or not pm_root.is_dir():
        return False, "workspace_root_missing_workflow_subdir"
    return True, ""


def _code_root_status(code_root: Path) -> tuple[bool, str]:
    if not code_root.exists():
        return False, "code_root_missing"
    if not code_root.is_dir():
        return False, "code_root_not_directory"
    return True, ""


def _git_available() -> str:
    path = shutil.which("git")
    return str(path or "").strip()


def _run_git(
    args: list[str],
    *,
    cwd: Path | None,
    code: str,
    message: str,
) -> subprocess.CompletedProcess[str]:
    git_bin = _git_available()
    if not git_bin:
        raise DeveloperWorkspaceError(409, "git 不可用，无法管理开发工作区。", "git_not_available")
    proc = subprocess.run(
        [git_bin, *args],
        cwd=str(cwd) if isinstance(cwd, Path) else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        detail = str(proc.stderr or proc.stdout or "").strip()
        raise DeveloperWorkspaceError(
            409,
            f"{message}{': ' + detail if detail else ''}",
            code,
            extra={
                "git_args": list(args),
                "cwd": cwd.as_posix() if isinstance(cwd, Path) else "",
                "stderr": str(proc.stderr or "").strip(),
                "stdout": str(proc.stdout or "").strip(),
            },
        )
    return proc


def _git_output(args: list[str], *, cwd: Path | None, code: str, message: str) -> str:
    proc = _run_git(args, cwd=cwd, code=code, message=message)
    return str(proc.stdout or "").strip()


def _git_ref_exists(cwd: Path, ref_name: str) -> bool:
    git_bin = _git_available()
    if not git_bin:
        raise DeveloperWorkspaceError(409, "git 不可用，无法检查分支状态。", "git_not_available")
    proc = subprocess.run(
        [git_bin, "show-ref", "--verify", "--quiet", ref_name],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc.returncode == 0


def _git_repo_ready(code_root: Path) -> tuple[bool, str]:
    git_bin = _git_available()
    if not git_bin:
        return False, "git_not_available"
    proc = subprocess.run(
        [git_bin, "-C", code_root.as_posix(), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0 or str(proc.stdout or "").strip().lower() != "true":
        return False, "code_root_not_git_repo"
    proc_head = subprocess.run(
        [git_bin, "-C", code_root.as_posix(), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc_head.returncode != 0 or not str(proc_head.stdout or "").strip():
        return False, "code_root_head_missing"
    return True, ""


def resolve_workspace_boundary(
    *,
    runtime_root: Path | None = None,
    workspace_root: str | Path | None = None,
    fallback_pm_root: Path | None = None,
) -> dict[str, Any]:
    runtime_root_path = runtime_root.resolve(strict=False) if isinstance(runtime_root, Path) else None
    runtime_cfg = _runtime_config(runtime_root_path)

    resolved_workspace_root: Path | None = None
    if isinstance(workspace_root, Path):
        resolved_workspace_root = workspace_root.resolve(strict=False)
    elif str(workspace_root or "").strip():
        resolved_workspace_root = _normalize_abs_path(str(workspace_root), base=runtime_root_path or Path("."))
    else:
        raw_workspace_root = str(runtime_cfg.get("agent_search_root") or "").strip()
        if raw_workspace_root:
            resolved_workspace_root = _normalize_abs_path(raw_workspace_root, base=runtime_root_path or Path("."))
        elif isinstance(fallback_pm_root, Path):
            resolved_workspace_root = fallback_pm_root.resolve(strict=False).parent

    if isinstance(resolved_workspace_root, Path):
        pm_root = (resolved_workspace_root / PM_ROOT_DIRNAME).resolve(strict=False)
    elif isinstance(fallback_pm_root, Path):
        pm_root = fallback_pm_root.resolve(strict=False)
    else:
        pm_root = Path(PM_ROOT_DIRNAME).resolve(strict=False)
    code_root = (pm_root.parent / CODE_ROOT_DIRNAME).resolve(strict=False)
    artifact_root = _artifact_root(
        runtime_root=runtime_root_path,
        workspace_root=resolved_workspace_root,
        runtime_cfg=runtime_cfg,
    )
    raw_dev_root = str(runtime_cfg.get("development_workspace_root") or "").strip()
    if raw_dev_root:
        development_workspace_root = _normalize_abs_path(raw_dev_root, base=runtime_root_path or artifact_root)
    else:
        development_workspace_root = (pm_root / DEFAULT_DEVELOPMENT_WORKSPACE_DIRNAME).resolve(strict=False)
    raw_agent_runtime_root = str(runtime_cfg.get("agent_runtime_root") or "").strip()
    if raw_agent_runtime_root:
        agent_runtime_root = _normalize_abs_path(raw_agent_runtime_root, base=runtime_root_path or artifact_root)
    else:
        agent_runtime_root = (artifact_root / DEFAULT_AGENT_RUNTIME_DIRNAME).resolve(strict=False)

    workspace_root_ready, workspace_root_error = _workspace_root_status(resolved_workspace_root, pm_root)
    code_root_exists, code_root_path_error = _code_root_status(code_root)
    code_root_git_ready, code_root_git_error = _git_repo_ready(code_root) if code_root_exists else (False, "")
    code_root_ready = bool(code_root_exists and code_root_git_ready)
    code_root_error = code_root_path_error or code_root_git_error

    return {
        "workspace_root": resolved_workspace_root.as_posix() if isinstance(resolved_workspace_root, Path) else "",
        "pm_root": pm_root.as_posix(),
        "pm_root_exists": bool(pm_root.exists() and pm_root.is_dir()),
        "code_root": code_root.as_posix(),
        "source_repo_path": code_root.as_posix(),
        "code_root_exists": bool(code_root.exists() and code_root.is_dir()),
        "code_root_ready": code_root_ready,
        "code_root_error": code_root_error,
        "code_root_is_git_repo": bool(code_root_git_ready),
        "artifact_root": artifact_root.as_posix(),
        "development_workspace_root": development_workspace_root.as_posix(),
        "agent_runtime_root": agent_runtime_root.as_posix(),
        "workspace_boundary_ready": bool(workspace_root_ready and code_root_ready),
        "workspace_root_ready": bool(workspace_root_ready),
        "workspace_root_error": workspace_root_error,
        "protected_write_roots": [pm_root.as_posix(), code_root.as_posix()],
    }


def protected_write_roots(
    *,
    workspace_root: str | Path | None = None,
    runtime_root: Path | None = None,
    fallback_pm_root: Path | None = None,
) -> list[Path]:
    boundary = resolve_workspace_boundary(
        runtime_root=runtime_root,
        workspace_root=workspace_root,
        fallback_pm_root=fallback_pm_root,
    )
    values: list[Path] = []
    for raw in boundary.get("protected_write_roots") or []:
        text = str(raw or "").strip()
        if not text:
            continue
        values.append(Path(text).resolve(strict=False))
    return values


def _registry_path(boundary: dict[str, Any]) -> Path:
    pm_root = Path(str(boundary.get("pm_root") or "")).resolve(strict=False)
    return (pm_root / WORKSPACE_REGISTRY_FILE).resolve(strict=False)


def list_developer_workspaces(
    *,
    runtime_root: Path | None = None,
    workspace_root: str | Path | None = None,
    fallback_pm_root: Path | None = None,
) -> dict[str, Any]:
    boundary = resolve_workspace_boundary(
        runtime_root=runtime_root,
        workspace_root=workspace_root,
        fallback_pm_root=fallback_pm_root,
    )
    registry = _load_json_dict(_registry_path(boundary))
    items = registry.get("items") if isinstance(registry.get("items"), list) else []
    rows: list[dict[str, Any]] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "developer_id": str(row.get("developer_id") or "").strip(),
                "workspace_path": str(row.get("workspace_path") or "").strip(),
                "source_repo_path": str(row.get("source_repo_path") or "").strip(),
                "tracking_branch": str(row.get("tracking_branch") or "").strip(),
                "last_synced_commit": str(row.get("last_synced_commit") or "").strip(),
                "created_at": str(row.get("created_at") or "").strip(),
                "last_used_at": str(row.get("last_used_at") or "").strip(),
                "mode": str(row.get("mode") or "git").strip() or "git",
                "last_operation": str(row.get("last_operation") or "").strip(),
                "remote_url": str(row.get("remote_url") or "").strip(),
                "status": str(row.get("status") or "").strip(),
            }
        )
    rows.sort(key=lambda item: (str(item.get("last_used_at") or ""), str(item.get("developer_id") or "")), reverse=True)
    return {
        "boundary": boundary,
        "workspaces": rows,
        "count": len(rows),
        "registry_path": _registry_path(boundary).as_posix(),
    }


def developer_workspace_response_payload(
    *,
    runtime_root: Path | None = None,
    workspace_root: str | Path | None = None,
    fallback_pm_root: Path | None = None,
) -> dict[str, Any]:
    listing = list_developer_workspaces(
        runtime_root=runtime_root,
        workspace_root=workspace_root,
        fallback_pm_root=fallback_pm_root,
    )
    boundary = listing.get("boundary") if isinstance(listing.get("boundary"), dict) else {}
    return {
        "pm_workspace_path": str(boundary.get("pm_root") or ""),
        "pm_workspace_exists": bool(boundary.get("pm_root_exists")),
        "code_root_path": str(boundary.get("code_root") or ""),
        "source_repo_path": str(boundary.get("source_repo_path") or ""),
        "code_root_exists": bool(boundary.get("code_root_exists")),
        "code_root_ready": bool(boundary.get("code_root_ready")),
        "code_root_error": str(boundary.get("code_root_error") or ""),
        "code_root_is_git_repo": bool(boundary.get("code_root_is_git_repo")),
        "development_workspace_root": str(boundary.get("development_workspace_root") or ""),
        "agent_runtime_root": str(boundary.get("agent_runtime_root") or ""),
        "workspace_boundary_ready": bool(boundary.get("workspace_boundary_ready")),
        "workspace_boundary_error": str(
            boundary.get("code_root_error") or boundary.get("workspace_root_error") or ""
        ),
        "workspace_root": str(boundary.get("workspace_root") or ""),
        "workspace_root_ready": bool(boundary.get("workspace_root_ready")),
        "workspace_root_error": str(boundary.get("workspace_root_error") or ""),
        "developer_workspace_registry_path": str(listing.get("registry_path") or ""),
        "developer_workspace_count": int(listing.get("count") or 0),
        "developer_workspaces": list(listing.get("workspaces") or []),
        "workspace_boundary": boundary,
    }


def _safe_developer_id(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise DeveloperWorkspaceError(400, "developer_id 不能为空。", "developer_id_required")
    normalized = []
    for ch in text:
        if ch.isalnum() or ch in {"-", "_", "."}:
            normalized.append(ch)
        else:
            normalized.append("-")
    safe = "".join(normalized).strip("-._")
    if not safe:
        raise DeveloperWorkspaceError(400, "developer_id 无效。", "developer_id_invalid")
    return safe[:80]


def _default_tracking_branch(developer_id: str) -> str:
    return f"dev/{developer_id}"


def _default_workspace_path(boundary: dict[str, Any], developer_id: str) -> Path:
    root = Path(str(boundary.get("development_workspace_root") or "")).resolve(strict=False)
    return (root / developer_id).resolve(strict=False)


def _resolve_workspace_target(boundary: dict[str, Any], developer_id: str, workspace_path: str) -> Path:
    scope = Path(str(boundary.get("development_workspace_root") or "")).resolve(strict=False)
    scope.mkdir(parents=True, exist_ok=True)
    if str(workspace_path or "").strip():
        candidate = _normalize_abs_path(workspace_path, base=scope)
    else:
        candidate = _default_workspace_path(boundary, developer_id)
    if not _path_in_scope(candidate, scope):
        raise DeveloperWorkspaceError(
            400,
            f"workspace_path 超出开发工作区根路径：{candidate.as_posix()}",
            "workspace_path_out_of_root",
            extra={
                "workspace_path": candidate.as_posix(),
                "development_workspace_root": scope.as_posix(),
            },
        )
    return candidate


def _detect_base_branch(workspace: Path, source_repo: Path) -> str:
    try:
        remote_head = _git_output(
            ["symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=workspace,
            code="origin_head_missing",
            message="无法识别 origin/HEAD",
        )
        if remote_head.startswith("refs/remotes/origin/"):
            return remote_head.split("/", 3)[-1].strip()
    except DeveloperWorkspaceError:
        pass
    branch = _git_output(
        ["rev-parse", "--abbrev-ref", "HEAD"],
        cwd=source_repo,
        code="code_root_head_unavailable",
        message="无法识别代码根仓当前分支",
    ).strip()
    if not branch or branch.upper() == "HEAD":
        raise DeveloperWorkspaceError(409, "代码根仓没有可用基线分支。", "code_root_head_unavailable")
    return branch


def _ensure_origin_remote(workspace: Path, source_repo: Path) -> str:
    source_repo_text = source_repo.as_posix()
    git_bin = _git_available()
    if not git_bin:
        raise DeveloperWorkspaceError(409, "git 不可用，无法配置开发工作区远程。", "git_not_available")
    proc = subprocess.run(
        [git_bin, "remote", "get-url", "origin"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode == 0:
        current = str(proc.stdout or "").strip()
        if current != source_repo_text:
            _run_git(
                ["remote", "set-url", "origin", source_repo_text],
                cwd=workspace,
                code="workspace_remote_update_failed",
                message="更新 origin 远程失败",
            )
        return source_repo_text
    _run_git(
        ["remote", "add", "origin", source_repo_text],
        cwd=workspace,
        code="workspace_remote_add_failed",
        message="创建 origin 远程失败",
    )
    return source_repo_text


def _workspace_is_git_repo(workspace: Path) -> bool:
    git_dir = workspace / ".git"
    if git_dir.exists():
        return True
    git_bin = _git_available()
    if not git_bin or not workspace.exists():
        return False
    proc = subprocess.run(
        [git_bin, "rev-parse", "--is-inside-work-tree"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc.returncode == 0 and str(proc.stdout or "").strip().lower() == "true"


def _workspace_is_clean(workspace: Path) -> bool:
    status_text = _git_output(
        ["status", "--porcelain"],
        cwd=workspace,
        code="workspace_status_failed",
        message="读取开发工作区 Git 状态失败",
    )
    return not bool(status_text.strip())


def _registry_payload_update(
    registry: dict[str, Any],
    *,
    record: dict[str, Any],
    updated_at: str,
) -> dict[str, Any]:
    items = registry.get("items") if isinstance(registry.get("items"), list) else []
    rows = [item for item in items if isinstance(item, dict)]
    next_rows: list[dict[str, Any]] = []
    replaced = False
    for row in rows:
        if str(row.get("developer_id") or "").strip() == str(record.get("developer_id") or "").strip():
            preserved_created_at = str(row.get("created_at") or "").strip()
            next_row = dict(record)
            if preserved_created_at:
                next_row["created_at"] = preserved_created_at
            next_rows.append(next_row)
            replaced = True
        else:
            next_rows.append(dict(row))
    if not replaced:
        next_rows.append(dict(record))
    return {
        "version": 1,
        "updated_at": updated_at,
        "items": next_rows,
    }


def bootstrap_developer_workspace(
    *,
    runtime_root: Path | None = None,
    workspace_root: str | Path | None = None,
    fallback_pm_root: Path | None = None,
    developer_id: str,
    workspace_path: str = "",
    tracking_branch: str = "",
    now_ts: str = "",
) -> dict[str, Any]:
    boundary = resolve_workspace_boundary(
        runtime_root=runtime_root,
        workspace_root=workspace_root,
        fallback_pm_root=fallback_pm_root,
    )
    if not bool(boundary.get("workspace_root_ready")):
        raise DeveloperWorkspaceError(
            409,
            f"PM 工作区边界未就绪：{boundary.get('workspace_root_error')}",
            str(boundary.get("workspace_root_error") or "workspace_root_not_ready"),
            extra={"boundary": boundary},
        )
    if not bool(boundary.get("code_root_ready")):
        raise DeveloperWorkspaceError(
            409,
            f"代码根仓未就绪：{boundary.get('code_root_error')}",
            str(boundary.get("code_root_error") or "code_root_not_ready"),
            extra={"boundary": boundary},
        )

    developer_key = _safe_developer_id(developer_id)
    source_repo = Path(str(boundary.get("source_repo_path") or "")).resolve(strict=False)
    workspace = _resolve_workspace_target(boundary, developer_key, workspace_path)
    target_branch = str(tracking_branch or "").strip() or _default_tracking_branch(developer_key)
    stamp = str(now_ts or "").strip()
    if not stamp:
        from datetime import datetime

        stamp = datetime.now().astimezone().replace(microsecond=0).isoformat()

    operation = "refresh"
    if workspace.exists():
        if not workspace.is_dir():
            raise DeveloperWorkspaceError(
                409,
                f"开发工作区路径不是目录：{workspace.as_posix()}",
                "workspace_path_not_directory",
                extra={"workspace_path": workspace.as_posix()},
            )
        if any(workspace.iterdir()) and not _workspace_is_git_repo(workspace):
            raise DeveloperWorkspaceError(
                409,
                f"开发工作区已存在非 Git 目录，禁止覆盖：{workspace.as_posix()}",
                "workspace_not_git_repo",
                extra={"workspace_path": workspace.as_posix()},
            )
    if not _workspace_is_git_repo(workspace):
        workspace.parent.mkdir(parents=True, exist_ok=True)
        _run_git(
            ["clone", "--origin", "origin", source_repo.as_posix(), workspace.as_posix()],
            cwd=None,
            code="workspace_clone_failed",
            message="初始化开发工作区失败",
        )
        operation = "bootstrap"
    else:
        operation = "refresh"

    remote_url = _ensure_origin_remote(workspace, source_repo)
    if not _workspace_is_clean(workspace):
        raise DeveloperWorkspaceError(
            409,
            f"开发工作区存在未提交改动，禁止自动刷新：{workspace.as_posix()}",
            "workspace_dirty",
            extra={"workspace_path": workspace.as_posix()},
        )
    _run_git(
        ["fetch", "origin", "--prune"],
        cwd=workspace,
        code="workspace_fetch_failed",
        message="同步代码根仓失败",
    )
    base_branch = _detect_base_branch(workspace, source_repo)
    remote_branch_ref = f"refs/remotes/origin/{target_branch}"
    local_branch_ref = f"refs/heads/{target_branch}"
    if _git_ref_exists(workspace, remote_branch_ref):
        _run_git(
            ["checkout", "-B", target_branch, f"origin/{target_branch}"],
            cwd=workspace,
            code="workspace_checkout_failed",
            message="切换开发分支失败",
        )
        _run_git(
            ["pull", "--ff-only", "origin", target_branch],
            cwd=workspace,
            code="workspace_pull_failed",
            message="刷新开发分支失败",
        )
    elif _git_ref_exists(workspace, local_branch_ref):
        _run_git(
            ["checkout", target_branch],
            cwd=workspace,
            code="workspace_checkout_failed",
            message="切换本地开发分支失败",
        )
        _run_git(
            ["merge", "--ff-only", f"origin/{base_branch}"],
            cwd=workspace,
            code="workspace_base_merge_failed",
            message="开发分支无法快进到最新基线，请先提交/推送或手工处理分歧",
        )
    else:
        _run_git(
            ["checkout", "-B", target_branch, f"origin/{base_branch}"],
            cwd=workspace,
            code="workspace_checkout_failed",
            message="创建开发分支失败",
        )

    current_branch = _git_output(
        ["branch", "--show-current"],
        cwd=workspace,
        code="workspace_branch_read_failed",
        message="读取当前开发分支失败",
    ).strip()
    last_synced_commit = _git_output(
        ["rev-parse", "HEAD"],
        cwd=workspace,
        code="workspace_head_missing",
        message="读取最新同步提交失败",
    ).strip()
    remote_lines = [
        line.strip()
        for line in _git_output(
            ["remote", "-v"],
            cwd=workspace,
            code="workspace_remote_read_failed",
            message="读取开发工作区远程失败",
        ).splitlines()
        if line.strip()
    ]

    listing = list_developer_workspaces(
        runtime_root=runtime_root,
        workspace_root=workspace_root,
        fallback_pm_root=fallback_pm_root,
    )
    registry_path = Path(str(listing.get("registry_path") or "")).resolve(strict=False)
    registry = _load_json_dict(registry_path)
    record = {
        "developer_id": developer_key,
        "workspace_path": workspace.as_posix(),
        "source_repo_path": source_repo.as_posix(),
        "tracking_branch": current_branch or target_branch,
        "last_synced_commit": last_synced_commit,
        "created_at": stamp,
        "last_used_at": stamp,
        "mode": "git",
        "last_operation": operation,
        "remote_url": remote_url,
        "status": "ready",
    }
    _write_json(
        registry_path,
        _registry_payload_update(
            registry,
            record=record,
            updated_at=stamp,
        ),
    )

    return {
        "ok": True,
        "operation": operation,
        "developer_id": developer_key,
        "workspace_path": workspace.as_posix(),
        "source_repo_path": source_repo.as_posix(),
        "tracking_branch": current_branch or target_branch,
        "base_branch": base_branch,
        "last_synced_commit": last_synced_commit,
        "remote_url": remote_url,
        "git_remote_lines": remote_lines,
        "current_branch": current_branch or target_branch,
        "registry_path": registry_path.as_posix(),
        "boundary": boundary,
        "record": record,
    }
