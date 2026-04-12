#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


RUNTIME_ENV_KEYS = (
    "WORKFLOW_RUNTIME_ENV",
    "WORKFLOW_RUNTIME_SOURCE_ROOT",
    "WORKFLOW_RUNTIME_CONTROL_ROOT",
    "WORKFLOW_RUNTIME_MANIFEST_PATH",
    "WORKFLOW_RUNTIME_DEPLOY_ROOT",
    "WORKFLOW_RUNTIME_VERSION",
    "WORKFLOW_RUNTIME_PID_FILE",
    "WORKFLOW_RUNTIME_INSTANCE_FILE",
)


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str((workspace_root / "src").resolve()))

    from workflow_app.server.services import runtime_upgrade_service

    backup = {key: os.environ.get(key) for key in RUNTIME_ENV_KEYS}
    try:
        for key in RUNTIME_ENV_KEYS:
            os.environ.pop(key, None)

        with tempfile.TemporaryDirectory(prefix="workflow-runtime-instance-") as tmp:
            temp_root = Path(tmp).resolve()
            control_root = temp_root / "control"
            runtime_root = control_root / "runtime" / "prod"
            runtime_root.mkdir(parents=True, exist_ok=True)
            deploy_root = temp_root / "prod"
            deploy_root.mkdir(parents=True, exist_ok=True)
            manifest_path = control_root / "envs" / "prod.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "environment": "prod",
                        "current_version": "20260407-230500",
                        "deploy_root": deploy_root.as_posix(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            poisoned_root = temp_root / "poisoned-control"
            os.environ["WORKFLOW_RUNTIME_ENV"] = "prod"
            os.environ["WORKFLOW_RUNTIME_CONTROL_ROOT"] = str(poisoned_root)
            os.environ["WORKFLOW_RUNTIME_MANIFEST_PATH"] = str(poisoned_root / "envs" / "prod.json")
            os.environ["WORKFLOW_RUNTIME_DEPLOY_ROOT"] = str(temp_root / "poisoned-prod")
            os.environ["WORKFLOW_RUNTIME_VERSION"] = "poisoned-version"
            os.environ["WORKFLOW_RUNTIME_PID_FILE"] = str(poisoned_root / "pids" / "prod.pid")
            os.environ["WORKFLOW_RUNTIME_INSTANCE_FILE"] = str(poisoned_root / "instances" / "prod.json")

            runtime_upgrade_service.runtime_process_start(host="127.0.0.1", port=8090, runtime_root=runtime_root)

            pid_path = control_root / "pids" / "prod.pid"
            instance_path = control_root / "instances" / "prod.json"
            assert pid_path.exists(), pid_path
            assert instance_path.exists(), instance_path
            assert not (poisoned_root / "pids" / "prod.pid").exists(), poisoned_root
            assert not (poisoned_root / "instances" / "prod.json").exists(), poisoned_root

            instance_payload = json.loads(instance_path.read_text(encoding="utf-8"))
            pid_value = int(pid_path.read_text(encoding="utf-8").strip())
            assert pid_value == os.getpid(), pid_value
            assert instance_payload["pid"] == os.getpid(), instance_payload
            assert instance_payload["port"] == 8090, instance_payload
            assert instance_payload["environment"] == "prod", instance_payload
            assert instance_payload["control_root"] == str(control_root), instance_payload
            assert instance_payload["manifest_path"] == str(manifest_path), instance_payload
            assert instance_payload["deploy_root"] == str(deploy_root), instance_payload
            assert instance_payload["version"] == "20260407-230500", instance_payload
            assert instance_payload["status"] == "running", instance_payload

            os.environ["WORKFLOW_RUNTIME_CONTROL_ROOT"] = str(control_root)
            os.environ["WORKFLOW_RUNTIME_MANIFEST_PATH"] = str(manifest_path)
            os.environ["WORKFLOW_RUNTIME_DEPLOY_ROOT"] = str(deploy_root)
            os.environ["WORKFLOW_RUNTIME_PID_FILE"] = str(pid_path)
            os.environ["WORKFLOW_RUNTIME_INSTANCE_FILE"] = str(instance_path)
            snapshot = runtime_upgrade_service.runtime_snapshot()
            assert snapshot["current_version"] == "20260407-230500", snapshot
            assert snapshot["current_version_rank"] == "20260407-230500", snapshot

            runtime_upgrade_service.runtime_process_stop(runtime_root=runtime_root)
            stopped_payload = json.loads(instance_path.read_text(encoding="utf-8"))
            assert not pid_path.exists(), pid_path
            assert stopped_payload["status"] == "stopped", stopped_payload
            assert stopped_payload.get("stopped_at"), stopped_payload

            print(
                json.dumps(
                    {
                        "ok": True,
                        "pid_path": pid_path.as_posix(),
                        "instance_path": instance_path.as_posix(),
                        "poisoned_root": poisoned_root.as_posix(),
                        "instance_payload": stopped_payload,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 0
    finally:
        for key, value in backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
