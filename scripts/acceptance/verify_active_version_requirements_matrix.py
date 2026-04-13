#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_markdown_section(text: str, title: str) -> str:
    pattern = rf"^##+\s*[0-9.]*\s*{re.escape(title)}\s*(.*?)(?=^##+\s|\Z)"
    match = re.search(pattern, text or "", re.MULTILINE | re.DOTALL)
    assert match, f"section missing: {title}"
    return str(match.group(1) or "")


def _parse_active_version_reference(reference_text: str) -> tuple[str, str]:
    version_match = re.search(r"active_version:\s*`([^`]+)`", reference_text or "")
    version_file_match = re.search(r"active_version_file:\s*`([^`]+)`", reference_text or "")
    assert version_match, "active_version missing"
    assert version_file_match, "active_version_file missing"
    return str(version_match.group(1) or "").strip(), str(version_file_match.group(1) or "").strip()


def _extract_requirement_names_from_overview(text: str) -> list[str]:
    section = _extract_markdown_section(text, "详细需求文档索引")
    names: list[str] = []
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not re.match(r"^\d+\.\s", line):
            continue
        match = re.search(r"(需求详情-[^`]+?\.md)", line)
        if match:
            names.append(str(match.group(1) or "").strip())
    assert names, "overview requirement index is empty"
    return names


def _extract_requirement_names_from_matrix(text: str) -> list[str]:
    section = _extract_markdown_section(text, "当前有效需求文档 -> 版本归属")
    names: list[str] = []
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if cells[0] in {"#", "---"} or cells[1] == "需求文档":
            continue
        match = re.search(r"(需求详情-[^`]+?\.md)", cells[1])
        if match:
            names.append(str(match.group(1) or "").strip())
    assert names, "requirements matrix table is empty"
    return names


def _extract_matrix_version(text: str) -> str:
    match = re.search(r"^\s*-\s*version:\s*`([^`]+)`", text or "", re.MULTILINE)
    assert match, "matrix version missing"
    return str(match.group(1) or "").strip()


def _duplicates(items: list[str]) -> list[str]:
    counter = Counter(items)
    return sorted(name for name, count in counter.items() if count > 1)


def _first_order_mismatches(expected: list[str], actual: list[str], limit: int = 5) -> list[dict[str, object]]:
    mismatches: list[dict[str, object]] = []
    total = max(len(expected), len(actual))
    for index in range(total):
        expected_value = expected[index] if index < len(expected) else ""
        actual_value = actual[index] if index < len(actual) else ""
        if expected_value == actual_value:
            continue
        mismatches.append(
            {
                "index": index + 1,
                "overview": expected_value,
                "matrix": actual_value,
            }
        )
        if len(mismatches) >= limit:
            break
    return mismatches


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    shell_root = repo_root.parents[1]
    reference_path = shell_root / "pm" / "PM当前版本计划.md"
    overview_path = shell_root / "docs" / "workflow" / "overview" / "需求概述.md"

    active_version, active_version_file = _parse_active_version_reference(_read_text(reference_path))
    version_plan_path = (shell_root / active_version_file).resolve()
    matrix_path = (version_plan_path.parent / "需求映射与覆盖矩阵.md").resolve()
    assert version_plan_path.exists(), f"active version file missing: {version_plan_path.as_posix()}"
    assert matrix_path.exists(), f"requirements matrix missing: {matrix_path.as_posix()}"

    overview_names = _extract_requirement_names_from_overview(_read_text(overview_path))
    matrix_text = _read_text(matrix_path)
    matrix_names = _extract_requirement_names_from_matrix(matrix_text)
    matrix_version = _extract_matrix_version(matrix_text)

    overview_duplicates = _duplicates(overview_names)
    matrix_duplicates = _duplicates(matrix_names)
    overview_set = set(overview_names)
    matrix_set = set(matrix_names)
    missing_in_matrix = sorted(overview_set - matrix_set)
    extra_in_matrix = sorted(matrix_set - overview_set)
    order_mismatches = _first_order_mismatches(overview_names, matrix_names)

    ok = (
        matrix_version == active_version
        and not overview_duplicates
        and not matrix_duplicates
        and not missing_in_matrix
        and not extra_in_matrix
    )

    print(
        json.dumps(
            {
                "ok": ok,
                "active_version": active_version,
                "active_version_file": active_version_file,
                "shell_root": shell_root.as_posix(),
                "overview_path": overview_path.as_posix(),
                "matrix_path": matrix_path.as_posix(),
                "matrix_version": matrix_version,
                "overview_count": len(overview_names),
                "matrix_count": len(matrix_names),
                "overview_duplicates": overview_duplicates,
                "matrix_duplicates": matrix_duplicates,
                "missing_in_matrix": missing_in_matrix,
                "extra_in_matrix": extra_in_matrix,
                "order_mismatches": order_mismatches,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
