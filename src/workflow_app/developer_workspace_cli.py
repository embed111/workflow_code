from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .server.services.developer_workspace_service import (
    DeveloperWorkspaceError,
    bootstrap_developer_workspace,
    list_developer_workspaces,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage workflow developer workspaces.")
    parser.add_argument(
        "--root",
        "--runtime-root",
        dest="runtime_root",
        default=".runtime",
        help="runtime root that contains state/runtime-config.json",
    )
    parser.add_argument(
        "--workspace-root",
        default="",
        help="optional workspace umbrella root override; code_root is still fixed as <workspace-root>/workflow_code",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Print current workspace boundary and workspace registry.")

    bootstrap_parser = subparsers.add_parser("bootstrap", help="Bootstrap or refresh a developer workspace.")
    bootstrap_parser.add_argument("--developer-id", required=True, help="developer id for branch and trace records")
    bootstrap_parser.add_argument("--workspace-path", default="", help="optional target workspace path")
    bootstrap_parser.add_argument("--tracking-branch", default="", help="optional branch override")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runtime_root = Path(args.runtime_root).resolve()
    workspace_root = str(args.workspace_root or "").strip()

    try:
        if args.command == "status":
            payload = list_developer_workspaces(
                runtime_root=runtime_root,
                workspace_root=workspace_root or None,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.command == "bootstrap":
            payload = bootstrap_developer_workspace(
                runtime_root=runtime_root,
                workspace_root=workspace_root or None,
                developer_id=str(args.developer_id or ""),
                workspace_path=str(args.workspace_path or ""),
                tracking_branch=str(args.tracking_branch or ""),
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
    except DeveloperWorkspaceError as exc:
        payload = {
            "ok": False,
            "error": str(exc),
            "code": exc.code,
            **exc.extra,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
