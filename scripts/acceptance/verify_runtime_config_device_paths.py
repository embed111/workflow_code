from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from workflow_app.runtime.device_path_config import (  # noqa: E402
    DEVICE_PATH_CONFIGS_KEY,
    apply_runtime_config_patch,
    resolve_runtime_config,
)


DEVICE_A = "AA-BB-CC-DD-EE-01"
DEVICE_B = "AA-BB-CC-DD-EE-02"
DEVICE_C = "AA-BB-CC-DD-EE-03"


def assert_eq(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="workflow-device-paths-") as tmp:
        runtime_root = Path(tmp).resolve()
        base_only = apply_runtime_config_patch(
            runtime_root,
            {
                "agent_search_root": "C:/work/base",
                "artifact_root": "C:/artifacts/base",
            },
            {"artifact_root": "C:/artifacts/base-next"},
            device_ids=[DEVICE_C],
        )
        assert_eq(
            DEVICE_PATH_CONFIGS_KEY in base_only,
            False,
            "base-only config should not create device slot",
        )
        assert_eq(
            base_only["artifact_root"],
            "C:/artifacts/base-next",
            "base-only artifact_root patch",
        )

        payload = {
            "show_test_data": False,
            DEVICE_PATH_CONFIGS_KEY: {
                DEVICE_A: {
                    "agent_search_root": "C:/work/device-a",
                },
                DEVICE_B: {
                    "agent_search_root": "C:/work/device-b",
                    "artifact_root": "C:/artifacts/device-b",
                },
            },
        }

        resolved_b = resolve_runtime_config(runtime_root, payload, device_ids=[DEVICE_B])
        assert_eq(
            resolved_b["agent_search_root"],
            "C:/work/device-b",
            "device B agent_search_root",
        )
        assert_eq(
            resolved_b["artifact_root"],
            "C:/artifacts/device-b",
            "device B artifact_root",
        )
        assert_eq(
            resolved_b["task_artifact_root"],
            "C:/artifacts/device-b",
            "device B task_artifact_root",
        )
        assert_eq(
            resolved_b["development_workspace_root"],
            "C:/work/device-b/workflow/.repository",
            "device B development_workspace_root",
        )
        assert_eq(
            resolved_b["agent_runtime_root"],
            "C:/artifacts/device-b/agent-runtime",
            "device B agent_runtime_root",
        )

        patched_c = apply_runtime_config_patch(
            runtime_root,
            payload,
            {"agent_search_root": "C:/work/device-c"},
            device_ids=[DEVICE_C],
        )
        resolved_c = resolve_runtime_config(runtime_root, patched_c, device_ids=[DEVICE_C])
        assert_eq(
            resolved_c["agent_search_root"],
            "C:/work/device-c",
            "device C agent_search_root",
        )
        assert_eq(
            resolved_c["artifact_root"],
            "C:/work/device-c/.output",
            "device C artifact_root",
        )
        assert_eq(
            resolved_c["development_workspace_root"],
            "C:/work/device-c/workflow/.repository",
            "device C development_workspace_root",
        )
        assert_eq(
            resolved_c["agent_runtime_root"],
            "C:/work/device-c/.output/agent-runtime",
            "device C agent_runtime_root",
        )

        patched_c_artifacts = apply_runtime_config_patch(
            runtime_root,
            patched_c,
            {"artifact_root": "C:/artifacts/device-c"},
            device_ids=[DEVICE_C],
        )
        resolved_c_artifacts = resolve_runtime_config(
            runtime_root,
            patched_c_artifacts,
            device_ids=[DEVICE_C],
        )
        assert_eq(
            resolved_c_artifacts["artifact_root"],
            "C:/artifacts/device-c",
            "device C updated artifact_root",
        )
        assert_eq(
            resolved_c_artifacts["task_artifact_root"],
            "C:/artifacts/device-c",
            "device C updated task_artifact_root",
        )
        assert_eq(
            resolved_c_artifacts["agent_runtime_root"],
            "C:/artifacts/device-c/agent-runtime",
            "device C updated agent_runtime_root",
        )

        print(
            json.dumps(
                {
                    "ok": True,
                    "devices": {
                        "device_b": resolved_b,
                        "device_c": resolved_c_artifacts,
                    },
                    "cwd": os.getcwd(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
