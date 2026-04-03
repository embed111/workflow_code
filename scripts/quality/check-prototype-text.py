#!/usr/bin/env python3
"""Scan runtime source for prototype phase text."""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path


PHASE_PATTERN = re.compile(r"phase\s*0|phase0|phase\s*1|phase1", re.IGNORECASE)
TARGET_EXTENSIONS = {".py", ".js"}
SCAN_ROOT_REL = "src/workflow_app"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check runtime source has no Phase0/Phase1 prototype text."
    )
    parser.add_argument("--root", default=".", help="Workspace root path.")
    parser.add_argument(
        "--report",
        default=".test/reports/PROTOTYPE_TEXT_SCAN_REPORT.txt",
        help="Report file path (absolute or relative to root).",
    )
    return parser.parse_args()


def resolve_report_path(root: Path, report_arg: str) -> Path:
    report_path = Path(report_arg)
    if report_path.is_absolute():
        return report_path
    return root / report_path


def scan_matches(scan_root: Path) -> list[tuple[Path, int, str]]:
    matches: list[tuple[Path, int, str]] = []
    for path in sorted(scan_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TARGET_EXTENSIONS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for idx, line in enumerate(text.splitlines(), start=1):
            if PHASE_PATTERN.search(line):
                matches.append((path, idx, line.strip()))
    return matches


def render_report(
    root: Path,
    scan_root: Path,
    matches: list[tuple[Path, int, str]],
) -> str:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    lines: list[str] = []
    lines.append("# PROTOTYPE_TEXT_SCAN_REPORT")
    lines.append("")
    lines.append(f"generated_at: {now}")
    lines.append(f"root: {root.as_posix()}")
    lines.append(f"scan_root: {scan_root.as_posix()}")
    lines.append(f"pattern: {PHASE_PATTERN.pattern}")
    lines.append(f"match_count: {len(matches)}")
    lines.append("")
    if matches:
        lines.append("matches:")
        for path, line_no, text in matches:
            rel = path.relative_to(root).as_posix()
            lines.append(f"- {rel}:{line_no}: {text}")
    else:
        lines.append("matches: NONE")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    scan_root = root / SCAN_ROOT_REL
    if not scan_root.exists():
        raise SystemExit(f"scan root not found: {scan_root.as_posix()}")
    matches = scan_matches(scan_root)
    report_path = resolve_report_path(root, args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(root, scan_root, matches), encoding="utf-8")
    print(report_path.as_posix())
    return 0 if not matches else 1


if __name__ == "__main__":
    raise SystemExit(main())
