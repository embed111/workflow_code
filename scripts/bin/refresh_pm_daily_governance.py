#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if SRC_ROOT.as_posix() not in sys.path:
    sys.path.insert(0, SRC_ROOT.as_posix())

from workflow_app.server.services.pm_daily_governance_service import (  # noqa: E402
    DEFAULT_PM_DAILY_BASE_URL,
    DEFAULT_PM_DAILY_KEEP_COUNT,
    run_pm_daily_governance,
)


def _load_json(path_text: str) -> dict | None:
    path = Path(str(path_text or "").strip()).resolve()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(path.as_posix())
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path.as_posix()}")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh PM daily governance history and retention state.")
    parser.add_argument(
        "--shell-root",
        default=REPO_ROOT.parents[1].as_posix(),
        help="workflow shell root that contains pm/ (default: current workspace shell root)",
    )
    parser.add_argument(
        "--date",
        default="",
        help="target date in YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_PM_DAILY_BASE_URL,
        help="workflow API base URL used when live payload JSON is not provided",
    )
    parser.add_argument(
        "--keep-count",
        type=int,
        default=DEFAULT_PM_DAILY_KEEP_COUNT,
        help="retention window for pm/daily-execution-history and pm/daily-learning-reports",
    )
    parser.add_argument(
        "--overwrite-existing",
        action="store_true",
        help="rewrite today's daily history even when the file already exists",
    )
    parser.add_argument("--healthz-json", default="", help="optional healthz payload JSON file")
    parser.add_argument("--status-json", default="", help="optional /api/status payload JSON file")
    parser.add_argument("--schedules-json", default="", help="optional /api/schedules payload JSON file")
    parser.add_argument(
        "--runtime-upgrade-json",
        default="",
        help="optional /api/runtime-upgrade/status payload JSON file",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_pm_daily_governance(
        root=Path(args.shell_root).resolve(),
        report_date=str(args.date or "").strip() or None,
        base_url=str(args.base_url or "").strip() or DEFAULT_PM_DAILY_BASE_URL,
        keep_count=max(1, int(args.keep_count or DEFAULT_PM_DAILY_KEEP_COUNT)),
        overwrite_existing=bool(args.overwrite_existing),
        healthz_payload=_load_json(args.healthz_json) if str(args.healthz_json or "").strip() else None,
        status_payload=_load_json(args.status_json) if str(args.status_json or "").strip() else None,
        schedules_payload=_load_json(args.schedules_json) if str(args.schedules_json or "").strip() else None,
        runtime_upgrade_payload=_load_json(args.runtime_upgrade_json)
        if str(args.runtime_upgrade_json or "").strip()
        else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if bool(result.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
