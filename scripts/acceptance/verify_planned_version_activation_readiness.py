#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

REQUIRED_SECTIONS = (
    "版本定位",
    "版本目标",
    "退出门槛",
    "激活前准入清单",
)
REQUIRED_SUBFIELDS = (
    "activation_readiness",
    "upstream_dependencies",
    "required_probes",
    "required_evidence_sources",
    "blocking_items",
    "go_no_go_rule",
)
REQUIRED_COLUMNS = (
    "需求点",
    "责任人",
    "协作方",
    "状态",
    "目标",
    "依赖",
    "验收/Probe",
    "Gate级别",
    "完成定义",
)
ALLOWED_GATE_LEVELS = {"workflow-gate", "activation-gate", "report-only"}
ENTRY_SECTION_ALIASES = ("进入前提", "进入条件")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_active_version(reference_text: str) -> str:
    match = re.search(r"active_version:\s*`([^`]+)`", reference_text or "")
    assert match, "active_version missing"
    return str(match.group(1) or "").strip()


def _parse_version_metadata(text: str) -> tuple[str, str]:
    version_match = re.search(r"^\s*-\s*version:\s*`([^`]+)`", text or "", re.MULTILINE)
    status_match = re.search(r"^\s*-\s*status:\s*`([^`]+)`", text or "", re.MULTILINE)
    assert version_match, "version metadata missing"
    assert status_match, "status metadata missing"
    return str(version_match.group(1) or "").strip(), str(status_match.group(1) or "").strip()


def _extract_section(text: str, title: str) -> str:
    pattern = rf"^##+\s*[0-9.xX.]*\s*{re.escape(title)}\s*(.*?)(?=^##+\s|\Z)"
    match = re.search(pattern, text or "", re.MULTILINE | re.DOTALL)
    return str(match.group(1) or "").strip() if match else ""


def _has_any_section(text: str, titles: tuple[str, ...]) -> bool:
    return any(_extract_section(text, title) for title in titles)


def _parse_version_number(version_id: str) -> int:
    match = re.search(r"V(\d+)", version_id or "")
    return int(match.group(1)) if match else -1


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _strip_code_ticks(value: str) -> str:
    return str(value or "").strip().strip("`").strip()


def _extract_requirement_id(value: str) -> str:
    match = re.search(r"(V\d+-R\d+)", str(value or ""))
    return str(match.group(1) or "").strip() if match else _strip_code_ticks(value)


def _parse_requirement_rows(section_text: str) -> tuple[list[str], list[dict[str, str]]]:
    table_lines = [line.rstrip() for line in section_text.splitlines() if line.strip().startswith("|")]
    if len(table_lines) < 2:
        return [], []
    headers = _split_table_row(table_lines[0])
    rows: list[dict[str, str]] = []
    for line in table_lines[2:]:
        cells = _split_table_row(line)
        if len(cells) != len(headers):
            continue
        row = {header: value for header, value in zip(headers, cells)}
        if not any(value.strip() for value in row.values()):
            continue
        rows.append(row)
    return headers, rows


def _parse_activation_readiness_fields(section_text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw_line in section_text.splitlines():
        line = raw_line.strip()
        match = re.match(r"^-\s*([a-z_]+)\s*:\s*(.+?)\s*$", line)
        if not match:
            continue
        fields[str(match.group(1) or "").strip()] = str(match.group(2) or "").strip()
    return fields


def _is_valid_dependency(value: str) -> bool:
    candidate = str(value or "").strip()
    if not candidate:
        return False
    if candidate in {"-", "无"}:
        return True
    if "/" in candidate or "\\" in candidate:
        return True
    return bool(re.fullmatch(r"V\d+-R\d+(?:\s*[/,，、;；]\s*V\d+-R\d+)*", candidate))


def _future_version_paths(pm_root: Path, active_version: str) -> list[Path]:
    active_number = _parse_version_number(active_version)
    candidates = []
    for version_path in sorted((pm_root / "versions").glob("V*/版本计划.md")):
        version_id = version_path.parent.name
        if _parse_version_number(version_id) > active_number:
            candidates.append(version_path)
    return candidates


def _severity_for_version(version_id: str, status: str, next_candidate: str) -> str:
    normalized_status = str(status or "").strip().lower()
    if version_id == next_candidate:
        return "hard"
    if normalized_status == "planned":
        return "warning"
    if normalized_status == "backlog":
        return "report-only"
    return "report-only"


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    shell_root = repo_root.parents[1]
    pm_root = shell_root / "pm"
    reference_path = pm_root / "PM当前版本计划.md"
    active_version = _parse_active_version(_read_text(reference_path))
    version_paths = _future_version_paths(pm_root, active_version)

    version_meta: list[tuple[str, str, Path, str]] = []
    for version_path in version_paths:
        version_id, status = _parse_version_metadata(_read_text(version_path))
        version_meta.append((version_id, status, version_path, _read_text(version_path)))

    next_activation_candidate = next((version_id for version_id, status, _, _ in version_meta if status == "planned"), "")
    versions_payload: dict[str, object] = {}
    hard_failures: list[str] = []
    warning_versions: list[str] = []
    report_only_versions: list[str] = []

    for version_id, status, version_path, text in version_meta:
        severity = _severity_for_version(version_id, status, next_activation_candidate)
        missing_sections = [title for title in REQUIRED_SECTIONS if not _extract_section(text, title)]
        if not _has_any_section(text, ENTRY_SECTION_ALIASES):
            missing_sections.append("进入前提/进入条件")

        requirement_section = _extract_section(text, "具体需求点")
        if not requirement_section:
            missing_sections.append("具体需求点")

        activation_fields = _parse_activation_readiness_fields(_extract_section(text, "激活前准入清单"))
        missing_subfields = [
            field
            for field in REQUIRED_SUBFIELDS
            if not str(activation_fields.get(field) or "").strip()
        ]

        headers, rows = _parse_requirement_rows(requirement_section)
        missing_columns = [column for column in REQUIRED_COLUMNS if column not in headers]
        row_issues: list[dict[str, object]] = []
        for row in rows:
            requirement_id = _extract_requirement_id(str(row.get("需求点") or ""))
            missing_fields = [
                column for column in REQUIRED_COLUMNS if column in headers and not str(row.get(column) or "").strip()
            ]
            invalid_fields: list[str] = []
            if requirement_id and not requirement_id.startswith(f"{version_id}-R"):
                invalid_fields.append("需求点")
            dependency = str(row.get("依赖") or "").strip()
            if dependency and not _is_valid_dependency(dependency):
                invalid_fields.append("依赖")
            gate_level = _strip_code_ticks(str(row.get("Gate级别") or ""))
            if gate_level and gate_level not in ALLOWED_GATE_LEVELS:
                invalid_fields.append("Gate级别")
            if missing_fields or invalid_fields:
                row_issues.append(
                    {
                        "requirement_id": requirement_id or "(missing)",
                        "missing_fields": missing_fields,
                        "invalid_fields": invalid_fields,
                    }
                )

        issue_count = len(missing_sections) + len(missing_subfields) + len(missing_columns) + len(row_issues)
        version_ok = issue_count == 0
        if not version_ok:
            if severity == "hard":
                hard_failures.append(version_id)
            elif severity == "warning":
                warning_versions.append(version_id)
            else:
                report_only_versions.append(version_id)

        versions_payload[version_id] = {
            "path": version_path.as_posix(),
            "status": status,
            "severity": severity,
            "ok": version_ok,
            "missing_sections": missing_sections,
            "missing_subfields": missing_subfields,
            "missing_columns": missing_columns,
            "row_issue_count": len(row_issues),
            "row_issues": row_issues,
        }

    ok = not hard_failures
    print(
        json.dumps(
            {
                "ok": ok,
                "active_version": active_version,
                "next_activation_candidate": next_activation_candidate,
                "checked_versions": [version_id for version_id, _, _, _ in version_meta],
                "hard_failures": hard_failures,
                "warning_versions": warning_versions,
                "report_only_versions": report_only_versions,
                "versions": versions_payload,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
