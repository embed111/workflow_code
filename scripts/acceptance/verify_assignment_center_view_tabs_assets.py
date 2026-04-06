#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
WEB_CLIENT_ROOT = SRC_ROOT / "workflow_app" / "web_client"


def assert_contains(path: Path, needle: str) -> None:
    text = path.read_text(encoding="utf-8")
    if needle not in text:
        raise AssertionError(f"{path.as_posix()} missing: {needle}")


def main() -> int:
    repo_root = REPO_ROOT
    template_path = repo_root / "src" / "workflow_app" / "server" / "presentation" / "templates" / "index.html"
    css_path = repo_root / "src" / "workflow_app" / "server" / "presentation" / "templates" / "index_training_loop_panels.css"
    events_path = repo_root / "src" / "workflow_app" / "web_client" / "assignment_center_events.js"
    state_helpers_path = repo_root / "src" / "workflow_app" / "web_client" / "assignment_center_state_helpers.js"

    assert_contains(template_path, "assignmentWorkboardTabBtn")
    assert_contains(template_path, "assignmentGraphTabBtn")
    assert_contains(template_path, "assignmentWorkboardSection")
    assert_contains(template_path, "assignmentGraphSection")
    assert_contains(css_path, ".assignment-view-tabs")
    assert_contains(css_path, ".assignment-workboard-panel")
    assert_contains(events_path, "data-assignment-primary-view")
    assert_contains(state_helpers_path, "setAssignmentPrimaryView")

    manifest = json.loads((WEB_CLIENT_ROOT / "bundle_manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, list) or not manifest:
        raise AssertionError("bundle manifest invalid")
    bundle_text = "\n\n".join(
        (WEB_CLIENT_ROOT / str(name)).read_text(encoding="utf-8")
        for name in manifest
    )

    bundle_path = Path(os.environ.get("TEST_TMP_DIR") or repo_root / ".test" / "tmp") / "workflow_web_client_bundle.js"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(bundle_text, encoding="utf-8")

    proc = subprocess.run(
        ["node", "--check", str(bundle_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        cwd=str(repo_root),
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "node --check failed")

    summary = {
        "ok": True,
        "template": template_path.as_posix(),
        "css": css_path.as_posix(),
        "bundle": bundle_path.as_posix(),
    }
    artifacts_dir = os.environ.get("TEST_ARTIFACTS_DIR", "").strip()
    if artifacts_dir:
        artifact_path = Path(artifacts_dir) / "assignment-center-view-tabs-summary.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
