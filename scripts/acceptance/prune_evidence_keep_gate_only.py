#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


KEEP_NAME_PATTERNS = (
    re.compile(r"^ac_[a-z0-9_]+_summary\.md$"),
    re.compile(r"^ac_[a-z0-9_]+_evidence_matrix\.png$"),
    re.compile(r"^ac_[a-z0-9_]+_evidence_matrix\.json$"),
    re.compile(r"^ac_[a-z0-9_]+_evidence_manifest\.json$"),
)


def under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def dir_stats(root: Path) -> dict[str, int]:
    files = [p for p in root.rglob("*") if p.is_file()]
    return {
        "file_count": len(files),
        "size_bytes": sum(int(p.stat().st_size) for p in files),
    }


def is_keep_file(path: Path) -> bool:
    name = path.name
    return any(pat.fullmatch(name) is not None for pat in KEEP_NAME_PATTERNS)


def parse_summary_md(summary_md: Path) -> tuple[bool, int]:
    rows = 0
    all_pass = True
    pattern = re.compile(r"^\|\s*([A-Za-z0-9\-]+)\s*\|\s*(pass|fail)\s*\|", re.IGNORECASE)
    for line in summary_md.read_text(encoding="utf-8").splitlines():
        matched = pattern.match(line.strip())
        if not matched:
            continue
        ac_id = str(matched.group(1) or "").strip().upper()
        if not ac_id.startswith("AC-"):
            continue
        rows += 1
        verdict = str(matched.group(2) or "").strip().lower()
        if verdict != "pass":
            all_pass = False
    return all_pass and rows > 0, rows


def parse_summary_json(summary_json: Path) -> tuple[bool, int]:
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return False, 0
    rows = 0
    all_pass = True
    for key, value in payload.items():
        if not str(key).upper().startswith("AC-"):
            continue
        rows += 1
        if not isinstance(value, dict) or not bool(value.get("pass")):
            all_pass = False
    return all_pass and rows > 0, rows


def check_acceptance_passed(evidence_dir: Path) -> tuple[bool, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    summary_files = sorted(evidence_dir.glob("ac_*_summary.md"))
    if not summary_files:
        return False, checks
    overall_pass = True
    for summary_md in summary_files:
        summary_json = summary_md.with_suffix(".json")
        source = "md"
        passed = False
        rows = 0
        if summary_json.exists() and summary_json.is_file():
            source = "json"
            passed, rows = parse_summary_json(summary_json)
        else:
            passed, rows = parse_summary_md(summary_md)
        checks.append(
            {
                "summary": summary_md.as_posix(),
                "source": source,
                "rows": rows,
                "pass": passed,
            }
        )
        overall_pass = overall_pass and passed
    return overall_pass, checks


def collect_files(evidence_dir: Path) -> list[Path]:
    return sorted([p for p in evidence_dir.rglob("*") if p.is_file()], key=lambda p: p.as_posix().lower())


def plan_prune(evidence_dir: Path) -> tuple[list[Path], list[Path]]:
    files = collect_files(evidence_dir)
    keep = [p for p in files if is_keep_file(p)]
    delete = [p for p in files if p not in keep]
    return keep, delete


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prune acceptance evidence after all AC pass; keep only gate screenshot and summary artifacts."
    )
    parser.add_argument("--evidence-dir", required=True, help="target evidence directory")
    parser.add_argument("--dry-run", action="store_true", help="preview only; no file deletion")
    parser.add_argument("--report-json", default="", help="optional report output path")
    args = parser.parse_args()

    evidence_dir = Path(args.evidence_dir).resolve()
    if not evidence_dir.exists() or not evidence_dir.is_dir():
        print(f"[error] evidence directory not found: {evidence_dir.as_posix()}", file=sys.stderr)
        return 2

    before_stats = dir_stats(evidence_dir)
    passed, pass_checks = check_acceptance_passed(evidence_dir)
    if not passed:
        print("[error] acceptance not fully passed; prune is blocked.", file=sys.stderr)
        for item in pass_checks:
            print(
                f"  - summary={item['summary']} source={item['source']} rows={item['rows']} pass={item['pass']}",
                file=sys.stderr,
            )
        return 3

    keep_files, delete_files = plan_prune(evidence_dir)
    keep_rel = [str(p.relative_to(evidence_dir)).replace("\\", "/") for p in keep_files]
    delete_rel = [str(p.relative_to(evidence_dir)).replace("\\", "/") for p in delete_files]

    print(f"[target] {evidence_dir.as_posix()}")
    print(f"[mode] {'dry-run' if args.dry_run else 'execute'}")
    print(f"[acceptance] pass ({len(pass_checks)} summary file(s))")
    print(
        "[before] "
        + f"files={before_stats['file_count']} size_bytes={before_stats['size_bytes']}"
    )
    print(f"[plan] keep={len(keep_rel)} delete={len(delete_rel)}")
    print("[delete-list]")
    if delete_rel:
        for rel in delete_rel:
            print(f"  - {rel}")
    else:
        print("  - (none)")

    after_stats: dict[str, int] | None = None
    if not args.dry_run:
        for path in delete_files:
            if not under_root(path, evidence_dir):
                print(f"[error] blocked out-of-root delete: {path.as_posix()}", file=sys.stderr)
                return 4
            path.unlink(missing_ok=True)
        after_stats = dir_stats(evidence_dir)
        print(
            "[after] "
            + f"files={after_stats['file_count']} size_bytes={after_stats['size_bytes']}"
        )

    print("[keep-list]")
    for rel in keep_rel:
        print(f"  - {rel}")

    if args.report_json:
        report_path = Path(args.report_json).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "target": evidence_dir.as_posix(),
            "mode": "dry-run" if args.dry_run else "execute",
            "acceptance_passed": passed,
            "acceptance_checks": pass_checks,
            "before": before_stats,
            "after": after_stats,
            "keep_files": keep_rel,
            "delete_files": delete_rel,
        }
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[report] {report_path.as_posix()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

