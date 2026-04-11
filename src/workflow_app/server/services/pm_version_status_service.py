from __future__ import annotations

import re
from pathlib import Path
from typing import Any


PM_VERSION_PLAN_RELATIVE_PATH = Path("docs") / "workflow" / "governance" / "PM版本推进计划.md"

_CURRENT_SNAPSHOT_SECTION_RE = re.compile(r"### 4\.6\.1 当前现场更新(.*?)(?:\n### |\Z)", re.DOTALL)
_CURRENT_ACTIVE_VERSION_RE = re.compile(r"^\s*\d+\.\s*active\s*版本(?:仍是|为)?\s*`([^`]+)`", re.IGNORECASE | re.MULTILINE)
_CURRENT_LANE_RE = re.compile(r"^\s*\d+\.\s*当前最高价值泳道(?:为)?\s*`([^`]+)`", re.MULTILINE)
_CURRENT_LIFECYCLE_STAGE_RE = re.compile(r"^\s*\d+\.\s*生命周期阶段(?:为)?\s*`([^`]+)`", re.MULTILINE)
_CURRENT_BASELINE_RE = re.compile(
    r"^\s*\d+\.\s*baseline\s*(?:继续沿用|为|已切到)?\s*`([^`]+)`",
    re.IGNORECASE | re.MULTILINE,
)
_CURRENT_SNAPSHOT_AT_RE = re.compile(r"^\s*\d+\.\s*最新有效快照截至\s*`([^`]+)`", re.MULTILINE)
_ACTIVE_VERSION_RE = re.compile(r"active\s*版本(?:仍是|为)?\s*`([^`]+)`", re.IGNORECASE)
_LANE_RE = re.compile(r"当前最高价值泳道(?:为)?\s*`([^`]+)`")
_LIFECYCLE_STAGE_RE = re.compile(r"生命周期阶段(?:为)?\s*`([^`]+)`")
_BASELINE_RE = re.compile(r"(?:baseline=|baseline\s+(?:继续沿用|为|已切到))\s*`([^`]+)`", re.IGNORECASE)
_SNAPSHOT_AT_RE = re.compile(r"最新有效快照截至\s*`([^`]+)`")
_ACTIVE_TABLE_RE = re.compile(r"^\|\s*`([^`]+)`[^|]*\|\s*`active`\s*\|", re.MULTILINE)


def _plan_path_candidates(root: Path | None) -> list[Path]:
    if isinstance(root, Path):
        anchor = root.resolve(strict=False)
    else:
        anchor = Path(".").resolve(strict=False)
    bases = [anchor, *anchor.parents]
    candidates: list[Path] = []
    seen: set[str] = set()
    for base in bases:
        candidate = (base / PM_VERSION_PLAN_RELATIVE_PATH).resolve(strict=False)
        key = candidate.as_posix()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def resolve_pm_version_plan_path(root: Path | None = None) -> Path | None:
    for candidate in _plan_path_candidates(root):
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _match_text(pattern: re.Pattern[str], text: str) -> str:
    matched = pattern.search(str(text or ""))
    return str(matched.group(1) or "").strip() if matched else ""


def _current_snapshot_section(text: str) -> str:
    matched = _CURRENT_SNAPSHOT_SECTION_RE.search(str(text or ""))
    return str(matched.group(1) or "") if matched else ""


def load_pm_version_status(root: Path | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "active_version": "",
        "lane": "",
        "lifecycle_stage": "",
        "baseline": "",
        "snapshot_updated_at": "",
        "source_path": "",
        "source_relative_path": PM_VERSION_PLAN_RELATIVE_PATH.as_posix(),
    }
    plan_path = resolve_pm_version_plan_path(root)
    if not isinstance(plan_path, Path):
        return payload
    payload["source_path"] = plan_path.as_posix()
    try:
        text = plan_path.read_text(encoding="utf-8")
    except Exception:
        return payload
    current_snapshot = _current_snapshot_section(text)
    active_version = (
        _match_text(_CURRENT_ACTIVE_VERSION_RE, current_snapshot)
        or _match_text(_ACTIVE_VERSION_RE, text)
        or _match_text(_ACTIVE_TABLE_RE, text)
    )
    lane = _match_text(_CURRENT_LANE_RE, current_snapshot) or _match_text(_LANE_RE, text)
    lifecycle_stage = _match_text(_CURRENT_LIFECYCLE_STAGE_RE, current_snapshot) or _match_text(
        _LIFECYCLE_STAGE_RE, text
    )
    baseline = _match_text(_CURRENT_BASELINE_RE, current_snapshot) or _match_text(_BASELINE_RE, text)
    snapshot_updated_at = _match_text(_CURRENT_SNAPSHOT_AT_RE, current_snapshot) or _match_text(
        _SNAPSHOT_AT_RE, text
    )
    payload.update(
        {
            "ok": bool(active_version or lane or lifecycle_stage or baseline),
            "active_version": active_version,
            "lane": lane,
            "lifecycle_stage": lifecycle_stage,
            "baseline": baseline,
            "snapshot_updated_at": snapshot_updated_at,
        }
    )
    return payload


def format_pm_version_prompt_lines(status: dict[str, Any]) -> list[str]:
    payload = status if isinstance(status, dict) else {}
    active_version = str(payload.get("active_version") or "").strip()
    lane = str(payload.get("lane") or "").strip()
    lifecycle_stage = str(payload.get("lifecycle_stage") or "").strip()
    baseline = str(payload.get("baseline") or "").strip()
    snapshot_at = str(payload.get("snapshot_updated_at") or "").strip()
    source_relative_path = str(payload.get("source_relative_path") or PM_VERSION_PLAN_RELATIVE_PATH.as_posix()).strip()
    fields = []
    if active_version:
        fields.append(f"active_version={active_version}")
    if lane:
        fields.append(f"lane={lane}")
    if lifecycle_stage:
        fields.append(f"lifecycle_stage={lifecycle_stage}")
    if baseline:
        fields.append(f"baseline={baseline}")
    lines: list[str] = []
    if fields:
        lines.append("当前版本快照： " + " ; ".join(fields))
    if snapshot_at:
        lines.append(f"版本快照时间： {snapshot_at} ; source={source_relative_path}")
    return lines


def build_pm_version_truth_payload(
    *,
    reported_active_version: Any,
    reported_active_slot: Any,
    plan_status: dict[str, Any] | None,
) -> dict[str, Any]:
    plan_payload = plan_status if isinstance(plan_status, dict) else {}
    plan_active_version = str(plan_payload.get("active_version") or "").strip()
    runtime_active_version = str(reported_active_version or "").strip()
    runtime_active_slot = str(reported_active_slot or "").strip()
    active_version = plan_active_version or runtime_active_version or "disabled"
    active_slot = runtime_active_slot or ("pm-plan" if plan_active_version else "disabled")
    source = "pm_version_plan" if plan_active_version else "runtime_ab_status"
    mismatches: list[dict[str, str]] = []
    if plan_active_version and runtime_active_version and runtime_active_version != plan_active_version:
        mismatches.append(
            {
                "code": "active_version_mismatch",
                "actual": runtime_active_version,
                "expected": plan_active_version,
                "source_path": str(plan_payload.get("source_relative_path") or PM_VERSION_PLAN_RELATIVE_PATH.as_posix()),
            }
        )
    return {
        "active_version": active_version,
        "active_slot": active_slot,
        "active_version_source": source,
        "runtime_active_version": runtime_active_version or "disabled",
        "runtime_active_slot": runtime_active_slot or "disabled",
        "truth_mismatch_count": len(mismatches),
        "truth_mismatch_items": mismatches,
        "pm_version_status": {
            "active_version": plan_active_version,
            "lane": str(plan_payload.get("lane") or "").strip(),
            "lifecycle_stage": str(plan_payload.get("lifecycle_stage") or "").strip(),
            "baseline": str(plan_payload.get("baseline") or "").strip(),
            "snapshot_updated_at": str(plan_payload.get("snapshot_updated_at") or "").strip(),
            "source_path": str(plan_payload.get("source_path") or "").strip(),
            "source_relative_path": str(
                plan_payload.get("source_relative_path") or PM_VERSION_PLAN_RELATIVE_PATH.as_posix()
            ),
        },
    }
