#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


FILES = [
    "scripts/start_workflow_env.ps1",
    "scripts/launch_workflow.ps1",
    "scripts/workflow_env_common.ps1",
]


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    errors: list[dict[str, object]] = []
    for rel_path in FILES:
        file_path = (workspace_root / rel_path).resolve()
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "$tokens=$null; $errs=$null; "
                f"[void][System.Management.Automation.Language.Parser]::ParseFile('{file_path.as_posix()}', [ref]$tokens, [ref]$errs); "
                "if($errs -and $errs.Count -gt 0){ $errs | ForEach-Object { $_.Message }; exit 1 }"
            ),
        ]
        proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            errors.append(
                {
                    "file": rel_path,
                    "stdout": proc.stdout.strip(),
                    "stderr": proc.stderr.strip(),
                    "returncode": proc.returncode,
                }
            )
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, "files": FILES}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
