#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CURRENT_SNAPSHOT_SECTION_RE = re.compile(
    r"^##+\s*[0-9.xX.]*\s*当前状态快照\s*(.*?)(?=^##+\s|\Z)",
    re.DOTALL | re.MULTILINE,
)
CURRENT_ACTIVE_VERSION_RE = re.compile(
    r"^\s*\d+\.\s*active\s*版本(?:仍是|为|已切到|已更新为)?\s*`([^`]+)`",
    re.MULTILINE,
)
CURRENT_LANE_RE = re.compile(
    r"^\s*\d+\.\s*当前最高价值泳道(?:为|仍为|继续保持|已切到|已更新为)?\s*`([^`]+)`",
    re.MULTILINE,
)
CURRENT_LIFECYCLE_STAGE_RE = re.compile(
    r"^\s*\d+\.\s*生命周期阶段(?:为|仍为|继续保持|已切到|已更新为)?\s*`([^`]+)`",
    re.MULTILINE,
)
CURRENT_BASELINE_RE = re.compile(
    r"^\s*\d+\.\s*baseline\s*(?:继续沿用|为|仍为|已切到|已更新为|已追到\s*live)?\s*`([^`]+)`",
    re.IGNORECASE | re.MULTILINE,
)
REFERENCE_ACTIVE_VERSION_RE = re.compile(r"^\s*-\s*active_version:\s*`([^`]+)`", re.MULTILINE)
REFERENCE_ACTIVE_VERSION_FILE_RE = re.compile(r"^\s*-\s*active_version_file:\s*`([^`]+)`", re.MULTILINE)
REFERENCE_ACTIVE_VERSION_TITLE_RE = re.compile(r"^\s*-\s*active_version_title:\s*`([^`]+)`", re.MULTILINE)
VERSION_HEADING_RE = re.compile(r"^#\s*(V\d+)\s+(.+)$", re.MULTILINE)
REQUIRED_COLUMNS = (
    "需求点",
    "责任人",
    "协作方",
    "状态",
    "进度评估",
    "预计完成",
    "超时/AAR",
    "说明",
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _match(pattern: re.Pattern[str], text: str) -> str:
    matched = pattern.search(str(text or ""))
    return str(matched.group(1) or "").strip() if matched else ""


def _extract_snapshot(text: str) -> dict[str, str]:
    section_match = CURRENT_SNAPSHOT_SECTION_RE.search(str(text or ""))
    section = str(section_match.group(1) or "") if section_match else ""
    return {
        "active_version": _match(CURRENT_ACTIVE_VERSION_RE, section),
        "lane": _match(CURRENT_LANE_RE, section),
        "lifecycle_stage": _match(CURRENT_LIFECYCLE_STAGE_RE, section),
        "baseline": _match(CURRENT_BASELINE_RE, section),
    }


def _extract_requirement_rows(text: str) -> tuple[list[str], list[dict[str, str]]]:
    section_match = re.search(
        r"^##+\s*[0-9.xX.]*\s*具体需求点\s*(.*?)(?=^##+\s|\Z)",
        str(text or ""),
        re.MULTILINE | re.DOTALL,
    )
    section = str(section_match.group(1) or "") if section_match else ""
    table_lines = [line.rstrip() for line in section.splitlines() if line.strip().startswith("|")]
    if len(table_lines) < 2:
        return [], []
    headers = [cell.strip() for cell in table_lines[0].strip().strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in table_lines[2:]:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != len(headers):
            continue
        row = {header: value for header, value in zip(headers, cells)}
        if not any(value.strip() for value in row.values()):
            continue
        rows.append(row)
    return headers, rows


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    shell_root = repo_root.parents[1]
    src_root = repo_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.services.pm_version_status_service import load_pm_version_status, resolve_pm_version_plan_path

    reference_path = shell_root / "pm" / "PM当前版本计划.md"
    reference_text = _read_text(reference_path)
    active_version = _match(REFERENCE_ACTIVE_VERSION_RE, reference_text)
    active_version_file = _match(REFERENCE_ACTIVE_VERSION_FILE_RE, reference_text)
    active_version_title = _match(REFERENCE_ACTIVE_VERSION_TITLE_RE, reference_text)
    version_plan_path = (shell_root / active_version_file).resolve()
    assert version_plan_path.exists(), f"active version file missing: {version_plan_path.as_posix()}"
    version_text = _read_text(version_plan_path)

    heading_match = VERSION_HEADING_RE.search(version_text)
    assert heading_match, "version heading missing"
    heading_version = str(heading_match.group(1) or "").strip()
    heading_title = str(heading_match.group(2) or "").strip()

    reference_snapshot = _extract_snapshot(reference_text)
    version_snapshot = _extract_snapshot(version_text)
    for field, value in reference_snapshot.items():
        assert value, {"reference_snapshot_missing": field}
    for field, value in version_snapshot.items():
        assert value, {"version_snapshot_missing": field}

    assert heading_version == active_version, {
        "active_version": active_version,
        "heading_version": heading_version,
    }
    assert heading_title == active_version_title, {
        "active_version_title": active_version_title,
        "heading_title": heading_title,
    }
    assert reference_snapshot["active_version"] == active_version, reference_snapshot
    assert version_snapshot["active_version"] == active_version, version_snapshot
    for field in ("lane", "lifecycle_stage", "baseline"):
        assert reference_snapshot[field] == version_snapshot[field], {
            "field": field,
            "reference": reference_snapshot[field],
            "version": version_snapshot[field],
        }

    plan_status = load_pm_version_status(shell_root)
    assert plan_status.get("ok"), plan_status
    assert str(plan_status.get("active_version") or "").strip() == active_version, plan_status
    assert str(plan_status.get("active_version_file") or "").strip() == active_version_file, plan_status
    assert str(plan_status.get("active_version_title") or "").strip() == active_version_title, plan_status
    for field in ("lane", "lifecycle_stage", "baseline"):
        assert str(plan_status.get(field) or "").strip() == version_snapshot[field], {
            "field": field,
            "plan_status": plan_status.get(field),
            "version_snapshot": version_snapshot[field],
        }
    assert resolve_pm_version_plan_path(shell_root) == reference_path.resolve(), {
        "resolved_reference": str(resolve_pm_version_plan_path(shell_root)),
        "reference_path": reference_path.as_posix(),
    }

    headers, rows = _extract_requirement_rows(version_text)
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in headers]
    assert not missing_columns, {"missing_columns": missing_columns, "headers": headers}
    assert rows, "active version requirement table empty"
    row_issues: list[dict[str, object]] = []
    for row in rows:
        requirement_id = str(row.get("需求点") or "").strip()
        missing_fields = [column for column in REQUIRED_COLUMNS if not str(row.get(column) or "").strip()]
        if missing_fields:
            row_issues.append({"requirement_id": requirement_id or "(missing)", "missing_fields": missing_fields})
    assert not row_issues, {"row_issues": row_issues}

    print(
        json.dumps(
            {
                "ok": True,
                "active_version": active_version,
                "active_version_file": active_version_file,
                "active_version_title": active_version_title,
                "reference_snapshot": reference_snapshot,
                "version_snapshot": version_snapshot,
                "requirement_count": len(rows),
                "requirement_ids": [str(row.get("需求点") or "").strip() for row in rows],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
