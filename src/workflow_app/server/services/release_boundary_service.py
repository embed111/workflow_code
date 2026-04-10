from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import developer_workspace_service as developer_workspace


DEFAULT_DEVELOPER_ID = "pm-main"
RELEASE_BOUNDARY_REPORT_PATH = "docs/workflow/reports/7x24发布边界收口方案-20260409.md"

_AHEAD_RE = re.compile(r"ahead\s+(\d+)", re.IGNORECASE)
_BEHIND_RE = re.compile(r"behind\s+(\d+)", re.IGNORECASE)
_MAX_PREVIEW_PATHS = 8


def _git_available() -> str:
    return str(shutil.which("git") or "").strip()


def _run_git_readonly(repo: Path, args: list[str]) -> tuple[bool, str]:
    git_bin = _git_available()
    if not git_bin:
        return False, ""
    try:
        proc = subprocess.run(
            [git_bin, "-C", repo.as_posix(), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except Exception:
        return False, ""
    if proc.returncode != 0:
        return False, str(proc.stderr or proc.stdout or "").strip()
    return True, str(proc.stdout or "").strip()


def _select_workspace_path(
    *,
    boundary: dict[str, Any],
    listing: dict[str, Any],
    preferred_developer_id: str,
) -> tuple[str, Path | None]:
    preferred = str(preferred_developer_id or "").strip() or DEFAULT_DEVELOPER_ID
    items = list(listing.get("workspaces") or [])
    for row in items:
        if str(row.get("developer_id") or "").strip() == preferred:
            path_text = str(row.get("workspace_path") or "").strip()
            if path_text:
                return preferred, Path(path_text).resolve(strict=False)
    if items:
        first = dict(items[0] or {})
        path_text = str(first.get("workspace_path") or "").strip()
        if path_text:
            return str(first.get("developer_id") or "").strip() or preferred, Path(path_text).resolve(strict=False)
    dev_root_text = str(boundary.get("development_workspace_root") or "").strip()
    if dev_root_text:
        candidate = (Path(dev_root_text).resolve(strict=False) / preferred).resolve(strict=False)
        if candidate.exists():
            return preferred, candidate
    return preferred, None


def _parse_git_status(status_text: str) -> tuple[str, int, int, int, int, list[str]]:
    lines = [line.rstrip() for line in str(status_text or "").splitlines() if line.strip()]
    branch_status = str(lines[0] or "").strip() if lines else ""
    ahead_match = _AHEAD_RE.search(branch_status)
    behind_match = _BEHIND_RE.search(branch_status)
    ahead_count = int(ahead_match.group(1)) if ahead_match else 0
    behind_count = int(behind_match.group(1)) if behind_match else 0
    dirty_tracked_count = 0
    untracked_count = 0
    changed_paths: list[str] = []
    for raw_line in lines[1:]:
        line = str(raw_line or "")
        if len(line) < 4:
            continue
        status_code = line[:2]
        path_text = line[3:].strip()
        if " -> " in path_text:
            path_text = path_text.split(" -> ", 1)[-1].strip()
        path_text = path_text.strip('"')
        if path_text:
            changed_paths.append(path_text.replace("\\", "/"))
        if status_code == "??":
            untracked_count += 1
        else:
            dirty_tracked_count += 1
    return branch_status, ahead_count, behind_count, dirty_tracked_count, untracked_count, changed_paths


def _release_batch_label(path_text: str) -> str:
    path = str(path_text or "").replace("\\", "/").lstrip("./")
    if path.startswith("scripts/acceptance/"):
        return "gate/acceptance 收口"
    if path.startswith("src/workflow_app/server/"):
        return "backend 真相收口"
    if path.startswith("src/workflow_app/web_client/") or path.startswith(
        "src/workflow_app/server/presentation/templates/"
    ):
        return "frontend UCD 切片"
    if path.startswith("logs/"):
        return "logs/证据确认"
    head = path.split("/", 1)[0].strip()
    if head:
        return f"{head} 杂项确认"
    return "杂项确认"


def _suggest_push_batches(changed_paths: list[str]) -> list[str]:
    order = [
        "gate/acceptance 收口",
        "backend 真相收口",
        "frontend UCD 切片",
        "logs/证据确认",
    ]
    seen: set[str] = set()
    extra: list[str] = []
    for path in changed_paths:
        label = _release_batch_label(path)
        if label in seen:
            continue
        seen.add(label)
        if label not in order:
            extra.append(label)
    ordered = [label for label in order if label in seen]
    ordered.extend(sorted(extra))
    return ordered


def _root_sync_state(
    *,
    branch_status: str,
    ahead_count: int,
    behind_count: int,
    dirty_tracked_count: int,
    untracked_count: int,
) -> str:
    status_line = str(branch_status or "").lower()
    if "diverged" in status_line or behind_count > 0:
        return "diverged_or_unknown"
    if dirty_tracked_count > 0 or untracked_count > 0 or ahead_count > 0:
        if ahead_count > 0 or dirty_tracked_count > 0 or untracked_count > 0:
            return "ahead_dirty" if (dirty_tracked_count > 0 or untracked_count > 0) else "ahead_clean"
    if branch_status:
        return "clean_synced"
    return "diverged_or_unknown"


def collect_release_boundary_snapshot(
    *,
    runtime_root: Path | None = None,
    workspace_root: str | Path | None = None,
    preferred_developer_id: str = DEFAULT_DEVELOPER_ID,
) -> dict[str, Any]:
    boundary = developer_workspace.resolve_workspace_boundary(
        runtime_root=runtime_root,
        workspace_root=workspace_root,
    )
    listing = developer_workspace.list_developer_workspaces(
        runtime_root=runtime_root,
        workspace_root=workspace_root,
    )
    developer_id, workspace_path = _select_workspace_path(
        boundary=boundary,
        listing=listing,
        preferred_developer_id=preferred_developer_id,
    )
    code_root_text = str(boundary.get("code_root") or "").strip()
    code_root = Path(code_root_text).resolve(strict=False) if code_root_text else None
    snapshot: dict[str, Any] = {
        "developer_id": developer_id,
        "workspace_path": workspace_path.as_posix() if isinstance(workspace_path, Path) else "",
        "code_root_path": code_root.as_posix() if isinstance(code_root, Path) else "",
        "workspace_head": "",
        "code_root_head": "",
        "branch_status": "",
        "code_root_branch_status": "",
        "root_sync_state": "diverged_or_unknown",
        "code_root_sync_state": "diverged_or_unknown",
        "ahead_count": 0,
        "behind_count": 0,
        "code_root_ahead_count": 0,
        "code_root_behind_count": 0,
        "dirty_tracked_count": 0,
        "untracked_count": 0,
        "code_root_dirty_tracked_count": 0,
        "code_root_untracked_count": 0,
        "changed_paths": [],
        "changed_paths_preview": "",
        "suggested_push_batches": [],
        "next_push_batch": "待切批",
        "push_block_reason": "workspace_unavailable",
        "git_status_short": "",
        "git_diff_stat": "",
        "release_boundary_mode_required": True,
        "boundary": boundary,
    }
    if not isinstance(workspace_path, Path) or not workspace_path.exists():
        return snapshot
    ok_status, status_text = _run_git_readonly(workspace_path, ["status", "--short", "--branch"])
    ok_workspace_head, workspace_head = _run_git_readonly(workspace_path, ["rev-parse", "--short", "HEAD"])
    ok_code_head, code_head = _run_git_readonly(code_root, ["rev-parse", "--short", "HEAD"]) if isinstance(code_root, Path) else (False, "")
    ok_code_status, code_status_text = (
        _run_git_readonly(code_root, ["status", "--short", "--branch"])
        if isinstance(code_root, Path)
        else (False, "")
    )
    ok_diff, diff_stat = _run_git_readonly(workspace_path, ["diff", "--stat", "--", "."])
    if not ok_status:
        snapshot["push_block_reason"] = "workspace_git_status_unavailable"
        snapshot["git_status_short"] = status_text
        snapshot["workspace_head"] = workspace_head if ok_workspace_head else ""
        snapshot["code_root_head"] = code_head if ok_code_head else ""
        snapshot["code_root_branch_status"] = code_status_text if ok_code_status else ""
        return snapshot
    branch_status, ahead_count, behind_count, dirty_tracked_count, untracked_count, changed_paths = _parse_git_status(
        status_text
    )
    (
        code_root_branch_status,
        code_root_ahead_count,
        code_root_behind_count,
        code_root_dirty_tracked_count,
        code_root_untracked_count,
        _code_root_changed_paths,
    ) = _parse_git_status(code_status_text) if ok_code_status else ("", 0, 0, 0, 0, [])
    suggested_push_batches = _suggest_push_batches(changed_paths)
    root_sync_state = _root_sync_state(
        branch_status=branch_status,
        ahead_count=ahead_count,
        behind_count=behind_count,
        dirty_tracked_count=dirty_tracked_count,
        untracked_count=untracked_count,
    )
    code_root_sync_state = _root_sync_state(
        branch_status=code_root_branch_status,
        ahead_count=code_root_ahead_count,
        behind_count=code_root_behind_count,
        dirty_tracked_count=code_root_dirty_tracked_count,
        untracked_count=code_root_untracked_count,
    )
    push_block_reason = ""
    if root_sync_state == "diverged_or_unknown":
        push_block_reason = "workspace_branch_diverged_or_behind"
    elif dirty_tracked_count > 0 or untracked_count > 0:
        push_block_reason = "workspace_dirty_changes_present"
    elif ahead_count > 0:
        push_block_reason = "unpushed_commits_present"
    next_push_batch = suggested_push_batches[0] if suggested_push_batches else ("待切批" if push_block_reason else "")
    if code_root_sync_state != "clean_synced" and root_sync_state == "clean_synced":
        root_sync_state = "diverged_or_unknown"
        if code_root_behind_count > 0:
            push_block_reason = "code_root_local_repo_behind_origin_main"
            next_push_batch = "先快进 ../workflow_code 本地 main"
        elif code_root_dirty_tracked_count > 0 or code_root_untracked_count > 0:
            push_block_reason = "code_root_dirty_changes_present"
            next_push_batch = "先收口 ../workflow_code 本地改动"
        elif code_root_ahead_count > 0:
            push_block_reason = "code_root_local_repo_ahead_origin_main"
            next_push_batch = "先校准 ../workflow_code 与 origin/main"
        else:
            push_block_reason = "code_root_sync_unknown"
            next_push_batch = "先校准 ../workflow_code 同步状态"
    snapshot.update(
        {
            "workspace_head": workspace_head if ok_workspace_head else "",
            "code_root_head": code_head if ok_code_head else "",
            "branch_status": branch_status,
            "code_root_branch_status": code_root_branch_status,
            "root_sync_state": root_sync_state,
            "code_root_sync_state": code_root_sync_state,
            "ahead_count": ahead_count,
            "behind_count": behind_count,
            "code_root_ahead_count": code_root_ahead_count,
            "code_root_behind_count": code_root_behind_count,
            "dirty_tracked_count": dirty_tracked_count,
            "untracked_count": untracked_count,
            "code_root_dirty_tracked_count": code_root_dirty_tracked_count,
            "code_root_untracked_count": code_root_untracked_count,
            "changed_paths": changed_paths,
            "changed_paths_preview": " | ".join(changed_paths[:_MAX_PREVIEW_PATHS]),
            "suggested_push_batches": suggested_push_batches,
            "next_push_batch": next_push_batch,
            "push_block_reason": push_block_reason,
            "git_status_short": status_text,
            "git_diff_stat": diff_stat if ok_diff else "",
            "release_boundary_mode_required": root_sync_state != "clean_synced",
        }
    )
    return snapshot


def format_release_boundary_prompt_lines(snapshot: dict[str, Any]) -> list[str]:
    payload = snapshot if isinstance(snapshot, dict) else {}
    changed_preview = str(payload.get("changed_paths_preview") or "").strip()
    batches = list(payload.get("suggested_push_batches") or [])
    batch_text = " | ".join(str(item or "").strip() for item in batches if str(item or "").strip())
    root_sync_state = str(payload.get("root_sync_state") or "").strip() or "diverged_or_unknown"
    lines = [
        f"发布边界专项方案：{RELEASE_BOUNDARY_REPORT_PATH}",
        (
            "根仓同步快照："
            f" root_sync_state={root_sync_state}"
            f" ; ahead_count={int(payload.get('ahead_count') or 0)}"
            f" ; dirty_tracked_count={int(payload.get('dirty_tracked_count') or 0)}"
            f" ; untracked_count={int(payload.get('untracked_count') or 0)}"
        ),
        (
            f"当前开发工作区：{str(payload.get('developer_id') or '').strip() or DEFAULT_DEVELOPER_ID}"
            f" ; workspace_head={str(payload.get('workspace_head') or '').strip() or '-'}"
            f" ; code_root_head={str(payload.get('code_root_head') or '').strip() or '-'}"
        ),
        f"branch_status: {str(payload.get('branch_status') or '').strip() or '-'}",
        (
            "代码根仓快照："
            f" code_root_sync_state={str(payload.get('code_root_sync_state') or '').strip() or 'diverged_or_unknown'}"
            f" ; code_root_ahead_count={int(payload.get('code_root_ahead_count') or 0)}"
            f" ; code_root_behind_count={int(payload.get('code_root_behind_count') or 0)}"
            f" ; code_root_dirty_tracked_count={int(payload.get('code_root_dirty_tracked_count') or 0)}"
            f" ; code_root_untracked_count={int(payload.get('code_root_untracked_count') or 0)}"
        ),
        f"code_root_branch_status: {str(payload.get('code_root_branch_status') or '').strip() or '-'}",
        (
            f"next_push_batch: {str(payload.get('next_push_batch') or '').strip() or '待切批'}"
            f" ; push_block_reason: {str(payload.get('push_block_reason') or '').strip() or '-'}"
        ),
    ]
    if root_sync_state == "clean_synced":
        lines.append(
            "发布边界动作: 当前已 clean_synced；若本轮产生代码改动并完成验证，收尾前必须从当前工作区 commit/push 到 `../workflow_code/main`。"
        )
    else:
        lines.append(
            "发布边界动作: 当前未 clean_synced；若这是上轮留下的 dirty/ahead，本轮第一优先级先处理历史批次，未收口前不要继续扩同工作区改动面。"
        )
    if str(payload.get("code_root_sync_state") or "").strip() not in {"", "clean_synced"}:
        lines.append(
            "代码根仓动作: 若命中 `../workflow_code` 本地落后 / 漂移等异常，`workflow(pm)` 在 7x24 中允许优先执行受支持的 non-destructive git sync / workspace bootstrap 收口，不要只记录阻塞。"
        )
    if batch_text:
        lines.append(f"suggested_push_batches: {batch_text}")
    if changed_preview:
        lines.append(f"changed_paths_preview: {changed_preview}")
    return lines
