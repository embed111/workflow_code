from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from workflow_app.runtime import device_path_config as device_cfg


TARGET_DEVICE_ID = "14-18-C3-E0-DD-4B"


def _reset_cache() -> None:
    device_cfg._DEVICE_ID_CACHE = None


def _restore_env(snapshot: dict[str, str | None]) -> None:
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _payload() -> dict[str, Any]:
    return {
        device_cfg.DEVICE_PATH_CONFIGS_KEY: {
            TARGET_DEVICE_ID: {
                "agent_search_root": "C:/work/J-Agents",
            }
        }
    }


def verify_empty_config_skips_getmac() -> dict[str, Any]:
    env_snapshot = {key: os.getenv(key) for key in device_cfg.DEVICE_ID_ENV_KEYS}
    original_getnode = device_cfg.uuid.getnode
    original_run = device_cfg.subprocess.run
    observed: dict[str, Any] = {"case": "empty_config", "getmac_called": False}
    try:
        os.environ.pop("WORKFLOW_DEVICE_ID", None)
        os.environ.pop("WORKFLOW_DEVICE_IDS", None)
        device_cfg.uuid.getnode = lambda: 0

        def fail_run(*args: Any, **kwargs: Any) -> Any:
            observed["getmac_called"] = True
            raise AssertionError("getmac should not run when no device configs exist")

        device_cfg.subprocess.run = fail_run
        _reset_cache()
        matched_key, matched_entry, candidates = device_cfg.match_device_config({})
        _assert(matched_key == "", f"expected no match, got {matched_key!r}")
        _assert(not matched_entry, "expected no matched entry")
        _assert(not observed["getmac_called"], "getmac unexpectedly called")
        observed["candidates"] = list(candidates)
        return observed
    finally:
        device_cfg.uuid.getnode = original_getnode
        device_cfg.subprocess.run = original_run
        _restore_env(env_snapshot)
        _reset_cache()


def verify_env_fast_match_skips_getmac() -> dict[str, Any]:
    env_snapshot = {key: os.getenv(key) for key in device_cfg.DEVICE_ID_ENV_KEYS}
    original_getnode = device_cfg.uuid.getnode
    original_run = device_cfg.subprocess.run
    observed: dict[str, Any] = {"case": "env_fast_match", "getmac_called": False}
    try:
        os.environ["WORKFLOW_DEVICE_ID"] = TARGET_DEVICE_ID
        os.environ.pop("WORKFLOW_DEVICE_IDS", None)
        device_cfg.uuid.getnode = lambda: (_ for _ in ()).throw(RuntimeError("skip uuid fallback"))

        def fail_run(*args: Any, **kwargs: Any) -> Any:
            observed["getmac_called"] = True
            raise AssertionError("getmac should not run when env fast path already matches")

        device_cfg.subprocess.run = fail_run
        _reset_cache()
        matched_key, matched_entry, candidates = device_cfg.match_device_config(_payload())
        _assert(matched_key == TARGET_DEVICE_ID, f"expected env match, got {matched_key!r}")
        _assert(bool(matched_entry), "expected matched device entry")
        _assert(TARGET_DEVICE_ID in candidates, f"expected env candidate, got {candidates!r}")
        _assert(not observed["getmac_called"], "getmac unexpectedly called")
        observed["candidates"] = list(candidates)
        return observed
    finally:
        device_cfg.uuid.getnode = original_getnode
        device_cfg.subprocess.run = original_run
        _restore_env(env_snapshot)
        _reset_cache()


def verify_getmac_result_is_cached() -> dict[str, Any]:
    env_snapshot = {key: os.getenv(key) for key in device_cfg.DEVICE_ID_ENV_KEYS}
    original_getnode = device_cfg.uuid.getnode
    original_run = device_cfg.subprocess.run
    calls: list[dict[str, Any]] = []
    try:
        os.environ.pop("WORKFLOW_DEVICE_ID", None)
        os.environ.pop("WORKFLOW_DEVICE_IDS", None)
        device_cfg.uuid.getnode = lambda: 0

        class FakeResult:
            returncode = 0
            stdout = f'"{TARGET_DEVICE_ID}","\\\\Device\\\\Tcpip_FAKE"'

        def fake_run(*args: Any, **kwargs: Any) -> Any:
            calls.append(
                {
                    "args": list(args[0]) if args else [],
                    "timeout": kwargs.get("timeout"),
                }
            )
            return FakeResult()

        device_cfg.subprocess.run = fake_run
        _reset_cache()
        first = device_cfg.match_device_config(_payload())
        second = device_cfg.match_device_config(_payload())
        _assert(first[0] == TARGET_DEVICE_ID, f"expected first match, got {first[0]!r}")
        _assert(second[0] == TARGET_DEVICE_ID, f"expected cached second match, got {second[0]!r}")
        _assert(len(calls) == 1, f"expected getmac once, got {len(calls)}")
        _assert(calls[0]["timeout"] == 1.5, f"unexpected getmac timeout: {calls[0]['timeout']!r}")
        return {
            "case": "getmac_cache",
            "call_count": len(calls),
            "timeout": calls[0]["timeout"],
        }
    finally:
        device_cfg.uuid.getnode = original_getnode
        device_cfg.subprocess.run = original_run
        _restore_env(env_snapshot)
        _reset_cache()


def main() -> int:
    results = [
        verify_empty_config_skips_getmac(),
        verify_env_fast_match_skips_getmac(),
        verify_getmac_result_is_cached(),
    ]
    print(json.dumps({"ok": True, "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
