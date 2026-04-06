#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.services import work_record_store as store

    root = workspace_root / ".test" / "runtime-work-record-lock"
    root.mkdir(parents=True, exist_ok=True)

    original_sync = store._record_index.sync_assignment_task_bundle

    def fake_sync(_root: Path, _ticket_id: str) -> None:
        raise sqlite3.OperationalError("database is locked")

    store._record_index.sync_assignment_task_bundle = fake_sync
    try:
        store.sync_assignment_task_bundle(root, "asg-lock-test")
    finally:
        store._record_index.sync_assignment_task_bundle = original_sync

    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
