from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .pm_version_status_service import load_effective_pm_version_status, resolve_pm_version_plan_path


_VERSION_HEADING_RE = re.compile(r"^#\s*(V\d+)\s+(.+)$", re.MULTILINE)
_VERSION_STATUS_RE = re.compile(r"^\s*-\s*status:\s*`([^`]+)`", re.MULTILINE)
_VERSION_SECTION_RE = re.compile(
    r"^##+\s*[0-9.xX.]*\s*具体需求点\s*(.*?)(?=^##+\s|\Z)",
    re.MULTILINE | re.DOTALL,
)
_ACTIVATION_SECTION_RE = re.compile(
    r"^##+\s*[0-9.xX.]*\s*激活前准入清单\s*(.*?)(?=^##+\s|\Z)",
    re.MULTILINE | re.DOTALL,
)
_SECTION_TEMPLATE = r"^##+\s*[0-9.xX.]*\s*{title}\s*(.*?)(?=^##+\s|\Z)"
_ENTRY_SECTION_ALIASES = ("进入前提", "进入条件")
_REQUIRED_ACTIVATION_SECTIONS = (
    "版本定位",
    "版本目标",
    "退出门槛",
    "激活前准入清单",
)
_REQUIRED_ACTIVATION_SUBFIELDS = (
    "activation_readiness",
    "upstream_dependencies",
    "required_probes",
    "required_evidence_sources",
    "blocking_items",
    "go_no_go_rule",
)
_REQUIRED_REQUIREMENT_COLUMNS = (
    "需求点",
    "责任人",
    "协作方",
    "状态",
    "进度评估",
    "预计完成",
    "超时/AAR",
    "说明",
)
_REQUIRED_FUTURE_COLUMNS = (
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
_ALLOWED_GATE_LEVELS = {"workflow-gate", "activation-gate", "report-only"}
_PROGRESS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_REQUIREMENT_ID_RE = re.compile(r"(V\d+-R\d+)")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PROBE_SPLIT_RE = re.compile(r"(?:[、,，;；]+|\s+/\s+)")
_TEST_CASE_REF_RE = re.compile(r"^TC-[A-Z0-9-]+$")
_DRAFT_PROBE_PREFIX = "draft:"
_ACCEPTANCE_SCRIPT_EXTENSIONS = (".py", ".js", ".ps1")
_ACTIVATION_READY_VALUES = {"ready", "ok", "go"}
_EMPTY_LIKE_VALUES = {"", "-", "无", "none", "n/a"}


def _read_text(path: Path | None) -> str:
    if not isinstance(path, Path):
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _extract_section(text: str, title: str) -> str:
    pattern = re.compile(_SECTION_TEMPLATE.format(title=re.escape(title)), re.MULTILINE | re.DOTALL)
    matched = pattern.search(str(text or ""))
    return str(matched.group(1) or "").strip() if matched else ""


def _split_markdown_row(line: str) -> list[str]:
    return [cell.strip() for cell in str(line or "").strip().strip("|").split("|")]


def _parse_table(section_text: str) -> tuple[list[str], list[dict[str, str]]]:
    table_lines = [line.rstrip() for line in str(section_text or "").splitlines() if line.strip().startswith("|")]
    if len(table_lines) < 2:
        return [], []
    headers = _split_markdown_row(table_lines[0])
    rows: list[dict[str, str]] = []
    for line in table_lines[2:]:
        cells = _split_markdown_row(line)
        if len(cells) != len(headers):
            continue
        row = {header: value for header, value in zip(headers, cells)}
        if any(str(value or "").strip() for value in row.values()):
            rows.append(row)
    return headers, rows


def _parse_progress_value(raw: str) -> float | None:
    matched = _PROGRESS_RE.search(str(raw or ""))
    if not matched:
        return None
    try:
        return float(matched.group(1))
    except Exception:
        return None


def _parse_iso_date(raw: str) -> date | None:
    text = str(raw or "").strip()
    if not text or not _DATE_RE.fullmatch(text):
        return None
    try:
        return date.fromisoformat(text)
    except Exception:
        return None


def _requirement_id(raw: str) -> str:
    matched = _REQUIREMENT_ID_RE.search(str(raw or ""))
    return str(matched.group(1) or "").strip() if matched else str(raw or "").strip().strip("`").strip()


def _parse_version_number(version_id: str) -> int:
    matched = re.search(r"V(\d+)", str(version_id or ""))
    return int(matched.group(1)) if matched else -1


def _is_valid_dependency(value: str) -> bool:
    candidate = str(value or "").strip()
    if not candidate:
        return False
    if candidate in {"-", "无"}:
        return True
    if "/" in candidate or "\\" in candidate:
        return True
    return bool(re.fullmatch(r"V\d+-R\d+(?:\s*[/,，、;；]\s*V\d+-R\d+)*", candidate))


def _parse_activation_fields(section_text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw_line in str(section_text or "").splitlines():
        matched = re.match(r"^-\s*([a-z_]+)\s*:\s*(.+?)\s*$", raw_line.strip())
        if matched:
            fields[str(matched.group(1) or "").strip()] = str(matched.group(2) or "").strip()
    return fields


def _clean_token(value: str) -> str:
    return str(value or "").strip().strip("`").strip()


def _split_probe_refs(value: str) -> list[str]:
    tokens = [_clean_token(item) for item in _PROBE_SPLIT_RE.split(str(value or ""))]
    refs: list[str] = []
    for token in tokens:
        if token and token not in refs:
            refs.append(token)
    return refs


def _acceptance_search_roots(workspace_root: Path) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    candidates = [workspace_root / "scripts" / "acceptance"]
    repository_root = workspace_root / ".repository"
    if repository_root.exists():
        for item in sorted(repository_root.iterdir()):
            if item.is_dir():
                candidates.append(item / "scripts" / "acceptance")
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        key = resolved.as_posix()
        if key in seen:
            continue
        seen.add(key)
        roots.append(resolved)
    return roots


def _probe_ref_is_bound(workspace_root: Path, probe_ref: str) -> bool:
    candidate = _clean_token(probe_ref)
    if not candidate:
        return False
    if candidate.lower().startswith(_DRAFT_PROBE_PREFIX):
        return False
    if _TEST_CASE_REF_RE.fullmatch(candidate):
        return True
    paths: list[Path] = []
    if "/" in candidate or "\\" in candidate:
        path = Path(candidate)
        if path.is_absolute():
            paths.append(path.resolve(strict=False))
        else:
            paths.append((workspace_root / path).resolve(strict=False))
    else:
        for acceptance_root in _acceptance_search_roots(workspace_root):
            paths.append((acceptance_root / candidate).resolve(strict=False))
            if not any(candidate.endswith(ext) for ext in _ACCEPTANCE_SCRIPT_EXTENSIONS):
                for ext in _ACCEPTANCE_SCRIPT_EXTENSIONS:
                    paths.append((acceptance_root / f"{candidate}{ext}").resolve(strict=False))
    return any(path.exists() and path.is_file() for path in paths)


def _activation_gate_summary(
    *,
    schema_ok: bool,
    schema_issue_count: int,
    activation_readiness: str,
    activation_readiness_ready: bool,
    draft_probe_refs: list[str],
    unbound_probe_refs: list[str],
    blocking_items_clear: bool,
    activation_gate_ready: bool,
) -> str:
    if activation_gate_ready:
        return "activation gate 就绪"
    reasons: list[str] = []
    if not schema_ok:
        reasons.append(f"schema 缺口 {schema_issue_count} 项")
    if draft_probe_refs or unbound_probe_refs:
        reasons.append("probe binding 未完成")
    if not blocking_items_clear:
        reasons.append("存在 blocker")
    if not activation_readiness_ready:
        reasons.append(f"activation_readiness={activation_readiness or '-'}")
    if not reasons:
        return "activation gate 未就绪"
    return "activation gate 未就绪 · " + " / ".join(reasons)


def _parse_active_requirement_rows(version_text: str) -> tuple[list[str], list[dict[str, Any]]]:
    section = _extract_section(version_text, "具体需求点")
    headers, rows = _parse_table(section)
    today = date.today()
    payload_rows: list[dict[str, Any]] = []
    for row in rows:
        requirement_id = _requirement_id(row.get("需求点") or "")
        owner = str(row.get("责任人") or "").strip().strip("`").strip()
        collaborators = str(row.get("协作方") or "").strip().strip("`").strip()
        status = str(row.get("状态") or "").strip().strip("`").strip()
        progress_text = str(row.get("进度评估") or "").strip().strip("`").strip()
        eta_text = str(row.get("预计完成") or "").strip().strip("`").strip()
        timeout_text = str(row.get("超时/AAR") or "").strip().strip("`").strip()
        note = str(row.get("说明") or "").strip()
        eta_date = _parse_iso_date(eta_text)
        progress_value = _parse_progress_value(progress_text)
        is_overdue = bool(eta_date and eta_date < today and "未超时" not in timeout_text)
        payload_rows.append(
            {
                "requirement_id": requirement_id,
                "owner": owner,
                "collaborators": collaborators,
                "status": status,
                "progress_text": progress_text,
                "progress_value": progress_value,
                "eta": eta_text,
                "timeout_text": timeout_text,
                "summary": note,
                "is_overdue": is_overdue,
            }
        )
    return headers, payload_rows


def _group_owners(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in list(requirements or []):
        owner = str(item.get("owner") or "").strip() or "未指派"
        bucket = grouped.setdefault(
            owner,
            {
                "owner": owner,
                "requirement_ids": [],
                "active_count": 0,
                "overdue_count": 0,
            },
        )
        bucket["requirement_ids"].append(str(item.get("requirement_id") or "").strip())
        if str(item.get("status") or "").strip().lower() in {"in_progress", "planned"}:
            bucket["active_count"] += 1
        if bool(item.get("is_overdue")):
            bucket["overdue_count"] += 1
    items = list(grouped.values())
    items.sort(key=lambda item: (-int(item.get("active_count") or 0), -len(item.get("requirement_ids") or []), str(item.get("owner") or "")))
    return items


def _active_requirement_summary(requirements: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(list(requirements or []))
    status_counts: dict[str, int] = {}
    next_eta = ""
    next_eta_date: date | None = None
    overdue_ids: list[str] = []
    for item in list(requirements or []):
        status_key = str(item.get("status") or "").strip().lower() or "unknown"
        status_counts[status_key] = int(status_counts.get(status_key, 0) or 0) + 1
        eta_date = _parse_iso_date(str(item.get("eta") or ""))
        if isinstance(eta_date, date) and (next_eta_date is None or eta_date < next_eta_date):
            next_eta_date = eta_date
            next_eta = eta_date.isoformat()
        if bool(item.get("is_overdue")):
            overdue_ids.append(str(item.get("requirement_id") or "").strip())
    return {
        "total": total,
        "status_counts": status_counts,
        "owner_count": len({str(item.get("owner") or "").strip() or "未指派" for item in list(requirements or [])}),
        "overdue_count": len(overdue_ids),
        "overdue_requirement_ids": overdue_ids,
        "next_eta": next_eta,
    }


def _future_version_paths(pm_root: Path, active_version: str) -> list[Path]:
    active_number = _parse_version_number(active_version)
    items: list[Path] = []
    versions_root = pm_root / "versions"
    if not versions_root.exists():
        return items
    for version_path in sorted(versions_root.glob("V*/版本计划.md")):
        if _parse_version_number(version_path.parent.name) > active_number:
            items.append(version_path)
    return items


def _future_version_severity(version_id: str, status: str, next_candidate: str) -> str:
    normalized = str(status or "").strip().lower()
    if version_id == next_candidate:
        return "hard"
    if normalized == "planned":
        return "warning"
    return "report-only"


def _parse_future_version_card(
    version_path: Path,
    *,
    next_activation_candidate: str,
    workspace_root: Path,
) -> dict[str, Any]:
    text = _read_text(version_path)
    heading = _VERSION_HEADING_RE.search(text)
    status = ""
    status_match = _VERSION_STATUS_RE.search(text)
    if status_match:
        status = str(status_match.group(1) or "").strip()
    version_id = str(heading.group(1) or "").strip() if heading else version_path.parent.name
    title = str(heading.group(2) or "").strip() if heading else ""
    missing_sections = [title_text for title_text in _REQUIRED_ACTIVATION_SECTIONS if not _extract_section(text, title_text)]
    if not any(_extract_section(text, alias) for alias in _ENTRY_SECTION_ALIASES):
        missing_sections.append("进入前提/进入条件")
    requirement_section = _extract_section(text, "具体需求点")
    if not requirement_section:
        missing_sections.append("具体需求点")
    activation_fields = _parse_activation_fields(_extract_section(text, "激活前准入清单"))
    missing_subfields = [
        field
        for field in _REQUIRED_ACTIVATION_SUBFIELDS
        if not str(activation_fields.get(field) or "").strip()
    ]
    headers, rows = _parse_table(requirement_section)
    missing_columns = [column for column in _REQUIRED_FUTURE_COLUMNS if column not in headers]
    row_issues: list[dict[str, Any]] = []
    activation_gate_probe_refs: list[str] = []
    for row in rows:
        requirement_id = _requirement_id(row.get("需求点") or "")
        missing_fields = [
            column
            for column in _REQUIRED_FUTURE_COLUMNS
            if column in headers and not str(row.get(column) or "").strip()
        ]
        invalid_fields: list[str] = []
        if requirement_id and not requirement_id.startswith(f"{version_id}-R"):
            invalid_fields.append("需求点")
        dependency = str(row.get("依赖") or "").strip()
        if dependency and not _is_valid_dependency(dependency):
            invalid_fields.append("依赖")
        gate_level = str(row.get("Gate级别") or "").strip().strip("`").strip()
        if gate_level and gate_level not in _ALLOWED_GATE_LEVELS:
            invalid_fields.append("Gate级别")
        if gate_level == "activation-gate":
            for probe_ref in _split_probe_refs(str(row.get("验收/Probe") or "")):
                if probe_ref not in activation_gate_probe_refs:
                    activation_gate_probe_refs.append(probe_ref)
        if missing_fields or invalid_fields:
            row_issues.append(
                {
                    "requirement_id": requirement_id or "(missing)",
                    "missing_fields": missing_fields,
                    "invalid_fields": invalid_fields,
                }
            )
    required_probes = _split_probe_refs(str(activation_fields.get("required_probes") or ""))
    all_probe_refs: list[str] = []
    for probe_ref in [*required_probes, *activation_gate_probe_refs]:
        if probe_ref not in all_probe_refs:
            all_probe_refs.append(probe_ref)
    draft_probe_refs = [probe for probe in all_probe_refs if probe.lower().startswith(_DRAFT_PROBE_PREFIX)]
    unbound_probe_refs = [
        probe
        for probe in all_probe_refs
        if probe not in draft_probe_refs and not _probe_ref_is_bound(workspace_root, probe)
    ]
    activation_readiness = _clean_token(str(activation_fields.get("activation_readiness") or ""))
    activation_readiness_ready = activation_readiness.lower() in _ACTIVATION_READY_VALUES
    blocking_items_text = _clean_token(str(activation_fields.get("blocking_items") or ""))
    blocking_items_clear = blocking_items_text.lower() in _EMPTY_LIKE_VALUES
    schema_issue_count = len(missing_sections) + len(missing_subfields) + len(missing_columns) + len(row_issues)
    gate_issue_count = 0
    if not activation_readiness_ready:
        gate_issue_count += 1
    if draft_probe_refs:
        gate_issue_count += 1
    if unbound_probe_refs:
        gate_issue_count += 1
    if not blocking_items_clear:
        gate_issue_count += 1
    issue_count = schema_issue_count + gate_issue_count
    severity = _future_version_severity(version_id, status, next_activation_candidate)
    schema_ok = schema_issue_count == 0
    activation_gate_ready = schema_ok and gate_issue_count == 0
    ok = activation_gate_ready
    summary = _activation_gate_summary(
        schema_ok=schema_ok,
        schema_issue_count=schema_issue_count,
        activation_readiness=activation_readiness,
        activation_readiness_ready=activation_readiness_ready,
        draft_probe_refs=draft_probe_refs,
        unbound_probe_refs=unbound_probe_refs,
        blocking_items_clear=blocking_items_clear,
        activation_gate_ready=activation_gate_ready,
    )
    return {
        "version_id": version_id,
        "title": title,
        "status": status,
        "severity": severity,
        "ok": ok,
        "schema_ok": schema_ok,
        "activation_gate_ready": activation_gate_ready,
        "summary": summary,
        "issue_count": issue_count,
        "schema_issue_count": schema_issue_count,
        "gate_issue_count": gate_issue_count,
        "activation_readiness": activation_readiness,
        "required_probes": required_probes,
        "activation_gate_probe_refs": activation_gate_probe_refs,
        "draft_probe_refs": draft_probe_refs,
        "unbound_probe_refs": unbound_probe_refs,
        "blocking_items_text": blocking_items_text,
        "blocking_items_clear": blocking_items_clear,
        "missing_sections": missing_sections,
        "missing_subfields": missing_subfields,
        "missing_columns": missing_columns,
        "row_issue_count": len(row_issues),
        "row_issues": row_issues,
        "path": version_path.as_posix(),
    }


def _future_activation_summary(pm_root: Path, active_version: str, workspace_root: Path) -> dict[str, Any]:
    version_paths = _future_version_paths(pm_root, active_version)
    versions_meta: list[tuple[str, str, Path]] = []
    for version_path in version_paths:
        text = _read_text(version_path)
        heading = _VERSION_HEADING_RE.search(text)
        status_match = _VERSION_STATUS_RE.search(text)
        version_id = str(heading.group(1) or "").strip() if heading else version_path.parent.name
        status = str(status_match.group(1) or "").strip() if status_match else ""
        versions_meta.append((version_id, status, version_path))
    next_activation_candidate = next((version_id for version_id, status, _ in versions_meta if status.lower() == "planned"), "")
    versions = [
        _parse_future_version_card(
            version_path,
            next_activation_candidate=next_activation_candidate,
            workspace_root=workspace_root,
        )
        for _, _, version_path in versions_meta
    ]
    hard_failures = [item["version_id"] for item in versions if item["severity"] == "hard" and not item["ok"]]
    warning_versions = [item["version_id"] for item in versions if item["severity"] == "warning" and not item["ok"]]
    report_only_versions = [item["version_id"] for item in versions if item["severity"] == "report-only" and not item["ok"]]
    next_candidate_row = next((item for item in versions if str(item.get("version_id") or "") == next_activation_candidate), {})
    return {
        "checked_versions": [item["version_id"] for item in versions],
        "next_activation_candidate": next_activation_candidate,
        "next_activation_ready": bool(next_candidate_row.get("ok")) if next_candidate_row else False,
        "hard_failures": hard_failures,
        "warning_versions": warning_versions,
        "report_only_versions": report_only_versions,
        "versions": versions,
    }


def load_pm_version_board(root: Path | None = None, *, runtime_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "active_version": "",
        "active_version_title": "",
        "lane": "",
        "lifecycle_stage": "",
        "baseline": "",
        "requirements": [],
        "owners": [],
        "summary": {
            "total": 0,
            "status_counts": {},
            "owner_count": 0,
            "overdue_count": 0,
            "overdue_requirement_ids": [],
            "next_eta": "",
        },
        "activation_summary": {
            "checked_versions": [],
            "next_activation_candidate": "",
            "next_activation_ready": False,
            "hard_failures": [],
            "warning_versions": [],
            "report_only_versions": [],
            "versions": [],
        },
        "source_path": "",
    }
    status = load_effective_pm_version_status(root, runtime_snapshot=runtime_snapshot)
    reference_path = resolve_pm_version_plan_path(root)
    if not isinstance(reference_path, Path):
        return payload
    workspace_root = reference_path.parent.parent
    active_version_file = str(status.get("active_version_file") or "").strip()
    version_path = (workspace_root / active_version_file).resolve(strict=False) if active_version_file else None
    version_text = _read_text(version_path)
    if not version_text:
        return payload
    _, requirements = _parse_active_requirement_rows(version_text)
    activation_summary = _future_activation_summary(
        reference_path.parent,
        str(status.get("active_version") or "").strip(),
        workspace_root,
    )
    payload.update(
        {
            "ok": bool(requirements),
            "active_version": str(status.get("active_version") or "").strip(),
            "active_version_title": str(status.get("active_version_title") or "").strip(),
            "lane": str(status.get("lane") or "").strip(),
            "lifecycle_stage": str(status.get("lifecycle_stage") or "").strip(),
            "baseline": str(status.get("baseline") or "").strip(),
            "baseline_source": str(status.get("baseline_source") or "").strip(),
            "requirements": requirements,
            "owners": _group_owners(requirements),
            "summary": _active_requirement_summary(requirements),
            "activation_summary": activation_summary,
            "source_path": version_path.as_posix() if isinstance(version_path, Path) else "",
            "source_relative_path": active_version_file,
        }
    )
    return payload
