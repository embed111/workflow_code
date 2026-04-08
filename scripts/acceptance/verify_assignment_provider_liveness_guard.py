#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws

    probe_workspace = (workspace_root / ".test" / "assignment-provider-liveness-guard").resolve()
    probe_workspace.mkdir(parents=True, exist_ok=True)

    codex_command_path = ws._default_codex_command_path()
    command, _command_summary = ws._build_assignment_execution_command(
        provider="codex",
        codex_command_path=codex_command_path,
        command_template=ws.DEFAULT_ASSIGNMENT_CODEX_COMMAND_TEMPLATE,
        workspace_path=probe_workspace,
    )

    wrapper_bypass_detail: dict[str, object] = {
        "codex_command_path": codex_command_path,
        "command_prefix": command[:3],
        "skipped": os.name != "nt",
    }
    if os.name == "nt":
        assert len(command) >= 2, command
        command_head = Path(str(command[0] or "")).name.lower()
        command_script = str(command[1] or "").replace("\\", "/").lower()
        assert command_head in {"node", "node.exe"}, command
        assert command_script.endswith("/node_modules/@openai/codex/bin/codex.js"), command
        wrapper_bypass_detail["skipped"] = False

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        now_dt = ws.now_local()
        buffered_age_seconds = int(ws.DEFAULT_ASSIGNMENT_STALE_RUN_GRACE_SECONDS) + 1
        live_process_grace_seconds = max(
            int(ws.DEFAULT_ASSIGNMENT_STALE_RUN_GRACE_SECONDS),
            int(ws.DEFAULT_ASSIGNMENT_EVENT_STREAM_KEEPALIVE_S) * 3,
        )
        stale_age_seconds = int(live_process_grace_seconds) + 5
        buffered_text = ws.iso_ts(now_dt - timedelta(seconds=buffered_age_seconds))
        stale_text = ws.iso_ts(now_dt - timedelta(seconds=stale_age_seconds))

        base_row = {
            "run_id": "arun-provider-liveness-guard",
            "status": "running",
            "provider_pid": int(proc.pid),
            "latest_event_at": buffered_text,
            "updated_at": buffered_text,
            "started_at": buffered_text,
            "created_at": buffered_text,
        }
        is_live_with_buffer = ws._assignment_run_row_is_live(
            base_row,
            active_run_ids=set(),
            now_dt=now_dt,
            grace_seconds=ws.DEFAULT_ASSIGNMENT_STALE_RUN_GRACE_SECONDS,
        )
        assert is_live_with_buffer is True, base_row

        stale_row = dict(base_row)
        stale_row["latest_event_at"] = stale_text
        stale_row["updated_at"] = stale_text
        stale_row["started_at"] = stale_text
        stale_row["created_at"] = stale_text
        is_live_after_extended_grace = ws._assignment_run_row_is_live(
            stale_row,
            active_run_ids=set(),
            now_dt=now_dt,
            grace_seconds=ws.DEFAULT_ASSIGNMENT_STALE_RUN_GRACE_SECONDS,
        )
        assert is_live_after_extended_grace is False, stale_row

        print(
            json.dumps(
                {
                    "ok": True,
                    "wrapper_bypass": wrapper_bypass_detail,
                    "live_provider_buffer": {
                        "provider_pid": int(proc.pid),
                        "buffered_age_seconds": buffered_age_seconds,
                        "live_process_grace_seconds": live_process_grace_seconds,
                        "stale_age_seconds": stale_age_seconds,
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
