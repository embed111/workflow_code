#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_pending_context(common_path: Path, source_root: Path, *, current_version: str = "") -> dict:
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            f"& {{ . '{common_path.as_posix()}'; "
            f"$ctx = Get-WorkflowPendingProdUpgradeContext -SourceRoot '{source_root.as_posix()}' -CurrentVersion '{current_version}'; "
            "$ctx | ConvertTo-Json -Depth 16 }"
        ),
    ]
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"powershell helper failed: returncode={proc.returncode} stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
    return json.loads(proc.stdout)


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    common_path = (workspace_root / "scripts" / "workflow_env_common.ps1").resolve()
    probe_root = (workspace_root / ".test" / "runtime-prod-watchdog-pending-upgrade").resolve()
    if probe_root.exists():
        shutil.rmtree(probe_root, ignore_errors=True)
    probe_root.mkdir(parents=True, exist_ok=True)

    control_root = (probe_root / ".running" / "control").resolve()
    candidate_version = "20260408-080001"
    current_version = "20260407-200414"
    candidate_app_root = (control_root / "candidates" / candidate_version / "app").resolve()
    candidate_app_root.mkdir(parents=True, exist_ok=True)
    evidence_path = (control_root / "reports" / f"test-gate-{candidate_version}.json").resolve()
    _write_json(evidence_path, {"ok": True})

    test_manifest_path = (control_root / "envs" / "test.json").resolve()
    prod_manifest_path = (control_root / "envs" / "prod.json").resolve()
    request_path = (control_root / "prod-upgrade-request.json").resolve()

    _write_json(
        test_manifest_path,
        {
            "environment": "test",
            "control_root": control_root.as_posix(),
            "source_root": probe_root.as_posix(),
            "manifest_path": test_manifest_path.as_posix(),
            "latest_test_gate_status": "passed",
            "latest_candidate_version": candidate_version,
            "latest_candidate_path": candidate_app_root.as_posix(),
            "latest_test_gate_evidence": evidence_path.as_posix(),
            "latest_candidate_created_at": "2026-04-08T00:00:00Z",
        },
    )
    _write_json(
        prod_manifest_path,
        {
            "environment": "prod",
            "control_root": control_root.as_posix(),
            "source_root": probe_root.as_posix(),
            "manifest_path": prod_manifest_path.as_posix(),
            "current_version": current_version,
        },
    )
    _write_json(
        request_path,
        {
            "environment": "prod",
            "requested_at": "2026-04-08T00:05:00Z",
            "requested_by": "acceptance",
            "current_version": current_version,
            "candidate_version": candidate_version,
            "candidate_evidence_path": evidence_path.as_posix(),
            "candidate_app_root": candidate_app_root.as_posix(),
        },
    )

    ready = _run_pending_context(common_path, probe_root)
    assert bool(ready.get("pending")), ready
    assert str(ready.get("reason") or "") == "request_ready", ready
    assert str(ready.get("current_version") or "") == current_version, ready
    assert str(ready.get("candidate_version") or "") == candidate_version, ready

    prod_candidate_path = control_root / "prod-candidate.json"
    prod_candidate = _load_json(prod_candidate_path)
    assert str(prod_candidate.get("version") or "") == candidate_version, prod_candidate

    _write_json(
        request_path,
        {
            "environment": "prod",
            "requested_at": "2026-04-08T00:06:00Z",
            "requested_by": "acceptance",
            "current_version": current_version,
            "candidate_version": "20260408-080999",
        },
    )
    mismatch = _run_pending_context(common_path, probe_root, current_version=current_version)
    assert not bool(mismatch.get("pending")), mismatch
    assert str(mismatch.get("reason") or "") == "request_candidate_mismatch", mismatch

    _write_json(
        request_path,
        {
            "environment": "prod",
            "requested_at": "2026-04-08T00:07:00Z",
            "requested_by": "acceptance",
            "current_version": current_version,
            "candidate_version": candidate_version,
        },
    )
    not_newer = _run_pending_context(common_path, probe_root, current_version=candidate_version)
    assert not bool(not_newer.get("pending")), not_newer
    assert str(not_newer.get("reason") or "") == "candidate_not_newer", not_newer

    print(
        json.dumps(
            {
                "ok": True,
                "request_ready_reason": str(ready.get("reason") or ""),
                "mismatch_reason": str(mismatch.get("reason") or ""),
                "not_newer_reason": str(not_newer.get("reason") or ""),
                "prod_candidate_path": prod_candidate_path.as_posix(),
                "candidate_version": candidate_version,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
