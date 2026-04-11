#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.services import developer_workspace_service
    from workflow_app.server.services import release_boundary_service

    verify_root = workspace_root / ".test" / "release-boundary-local-root-sync-policy"
    if verify_root.exists():
        shutil.rmtree(verify_root, ignore_errors=True)
    verify_root.mkdir(parents=True, exist_ok=True)

    workspace_parent = verify_root / "workspace-root"
    pm_root = workspace_parent / "workflow"
    code_root = workspace_parent / "workflow_code"
    developer_root = pm_root / ".repository" / "pm-main"
    developer_root.mkdir(parents=True, exist_ok=True)
    code_root.mkdir(parents=True, exist_ok=True)

    def fake_git(repo: Path, args: list[str]) -> tuple[bool, str]:
        repo_text = repo.resolve(strict=False).as_posix()
        workspace_text = developer_root.resolve(strict=False).as_posix()
        code_root_text = code_root.resolve(strict=False).as_posix()
        key = tuple(args)
        if key == ("status", "--short", "--branch"):
            if repo_text == workspace_text:
                return True, "## main...origin/main [ahead 1]"
            if repo_text == code_root_text:
                return True, "## main...origin/main [ahead 1]"
        if key == ("rev-parse", "--short", "HEAD"):
            if repo_text in {workspace_text, code_root_text}:
                return True, "abc1234"
        if key == ("diff", "--stat", "--", "."):
            if repo_text == workspace_text:
                return True, ""
        if key == ("merge-base", "--is-ancestor", "abc1234", "abc1234"):
            return True, ""
        if key == ("rev-list", "--count", "abc1234..abc1234"):
            return True, "0"
        return False, ""

    boundary_payload = {
        "workspace_root": workspace_parent.as_posix(),
        "pm_root": pm_root.as_posix(),
        "pm_root_exists": True,
        "code_root": code_root.as_posix(),
        "source_repo_path": code_root.as_posix(),
        "code_root_exists": True,
        "code_root_ready": True,
        "code_root_error": "",
        "code_root_is_git_repo": True,
        "artifact_root": (workspace_parent / ".output").as_posix(),
        "development_workspace_root": (pm_root / ".repository").as_posix(),
        "agent_runtime_root": (workspace_parent / ".output" / "agent-runtime").as_posix(),
        "workspace_boundary_ready": True,
        "workspace_root_ready": True,
        "workspace_root_error": "",
        "protected_write_roots": [pm_root.as_posix(), code_root.as_posix()],
    }

    listing_payload = {"workspaces": []}

    with (
        patch.object(developer_workspace_service, "resolve_workspace_boundary", return_value=boundary_payload),
        patch.object(developer_workspace_service, "list_developer_workspaces", return_value=listing_payload),
        patch.object(release_boundary_service, "_run_git_readonly", side_effect=fake_git),
    ):
        snapshot = release_boundary_service.collect_release_boundary_snapshot(
            workspace_root=workspace_parent,
            preferred_developer_id="pm-main",
        )
        prompt_lines = release_boundary_service.format_release_boundary_prompt_lines(snapshot)

    assert snapshot["workspace_head"] == "abc1234", snapshot
    assert snapshot["code_root_head"] == "abc1234", snapshot
    assert snapshot["root_sync_state"] == "clean_synced", snapshot
    assert int(snapshot["ahead_count"] or 0) == 0, snapshot
    assert int(snapshot["behind_count"] or 0) == 0, snapshot
    assert str(snapshot.get("push_block_reason") or "").strip() == "", snapshot
    assert not bool(snapshot.get("release_boundary_mode_required")), snapshot
    assert int(snapshot.get("upstream_ahead_count") or 0) == 1, snapshot
    assert int(snapshot.get("code_root_upstream_ahead_count") or 0) == 1, snapshot

    prompt_text = "\n".join(prompt_lines)
    assert "GitHub / origin 默认只作参考，不作为本轮阻塞" in prompt_text, prompt_text
    assert "当前已相对本机 `../workflow_code` clean_synced" in prompt_text, prompt_text
    assert "workspace=## main...origin/main [ahead 1]" in prompt_text, prompt_text
    assert "code_root=## main...origin/main [ahead 1]" in prompt_text, prompt_text

    print(
        json.dumps(
            {
                "ok": True,
                "workspace_head": snapshot["workspace_head"],
                "code_root_head": snapshot["code_root_head"],
                "root_sync_state": snapshot["root_sync_state"],
                "push_block_reason": snapshot["push_block_reason"],
                "upstream_ahead_count": snapshot["upstream_ahead_count"],
                "code_root_upstream_ahead_count": snapshot["code_root_upstream_ahead_count"],
                "prompt_lines": prompt_lines,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
