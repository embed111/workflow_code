#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CANONICAL_DAILY_HISTORY_HINT = "pm/daily-execution-history/YYYY-MM-DD.md"
CANONICAL_DAILY_LEARNING_HINT = "pm/daily-learning-reports/YYYY-MM-DD/<agent_id>.md"
CORE_LEARNING_AGENTS = (
    "workflow",
    "workflow_devmate",
    "workflow_testmate",
    "workflow_qualitymate",
    "workflow_bugmate",
)
CORE_LEARNING_PROMPT_IDS = (
    "workflow(pm)",
    "workflow_devmate",
    "workflow_testmate",
    "workflow_qualitymate",
    "workflow_bugmate",
)
REQUIRED_DAILY_TASK_SNIPPETS = (
    CANONICAL_DAILY_HISTORY_HINT,
    CANONICAL_DAILY_LEARNING_HINT,
    "retention_rule: 目录只保留最近 `7` 份历史文件",
    "### D1. 每日 `1` 次系统 7x24 运维质量检查",
    "### D2. 团队内每个小伙伴每日学习任务与学习报告",
    "### D3. 每日执行结果落盘",
)
REQUIRED_PLAN_SNIPPETS = (
    CANONICAL_DAILY_HISTORY_HINT,
    CANONICAL_DAILY_LEARNING_HINT,
    "每日学习必须产出真实学习报告",
    "每日任务与每轮主线分离",
)
REQUIRED_README_SNIPPETS = (
    CANONICAL_DAILY_HISTORY_HINT,
    CANONICAL_DAILY_LEARNING_HINT,
    "daily-execution-history",
    "daily-learning-reports",
)
DATED_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
DATED_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _contains(text: str, snippet: str) -> bool:
    return str(snippet or "") in str(text or "")


def _field_present(text: str, label: str) -> bool:
    patterns = (
        rf"^\s*-\s*{re.escape(label)}\s*:\s*.+$",
        rf"^\s*{re.escape(label)}\s*:\s*.+$",
        rf"^\s*##+\s*{re.escape(label)}\s*$",
    )
    return any(re.search(pattern, text or "", re.MULTILINE) for pattern in patterns)


def _metadata_value(text: str, label: str) -> str:
    match = re.search(
        rf"^\s*-?\s*{re.escape(label)}\s*:\s*`?([^`\n]+?)`?\s*$",
        text or "",
        re.MULTILINE,
    )
    return str(match.group(1) or "").strip() if match else ""


def _validate_daily_history_file(path: Path) -> list[str]:
    text = _read_text(path)
    issues: list[str] = []
    date_match = re.search(r"^\s*-\s*date:\s*`([^`]+)`", text, re.MULTILINE)
    if not date_match or str(date_match.group(1) or "").strip() != path.stem:
        issues.append("date field mismatch")
    if not re.search(r"^\s*-\s*source_tasks:\s*`pm/PM每日任务清单\.md`", text, re.MULTILINE):
        issues.append("source_tasks missing")
    if not re.search(r"^\s*-\s*status:\s*`[^`]+`", text, re.MULTILINE):
        issues.append("status missing")
    for section in ("system_ops_check", "learning_prompt", "next"):
        if not re.search(rf"^\s*##+\s*{re.escape(section)}\s*$", text, re.MULTILINE):
            issues.append(f"missing section: {section}")
    for field in ("executed_at", "conclusion", "evidence_ref"):
        if not _field_present(text, field):
            issues.append(f"missing field: {field}")
    for agent_id in CORE_LEARNING_PROMPT_IDS:
        if f"`{agent_id}`" not in text:
            issues.append(f"learning prompt missing agent: {agent_id}")
    return issues


def _validate_learning_report(path: Path, expected_agent_id: str) -> list[str]:
    text = _read_text(path)
    issues: list[str] = []
    if not _metadata_value(text, "date"):
        issues.append("date missing")
    if _metadata_value(text, "agent_id") != expected_agent_id:
        issues.append("agent_id mismatch")
    for field in ("learning_task", "source_type", "source_ref"):
        if not _field_present(text, field):
            issues.append(f"missing field: {field}")
    for field in ("learned_points", "applied_to_project", "next_action"):
        if not _field_present(text, field):
            issues.append(f"missing field: {field}")
    return issues


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    shell_root = repo_root.parents[1]
    src_root = repo_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.services.assignment_service_parts import assignment_self_iteration_runtime
    from workflow_app.server.services import schedule_service, schedule_text_repair

    readme_path = shell_root / "pm" / "README.md"
    master_plan_path = shell_root / "pm" / "PM版本推进计划.md"
    daily_task_path = shell_root / "pm" / "PM每日任务清单.md"
    daily_history_root = shell_root / "pm" / "daily-execution-history"
    learning_report_root = shell_root / "pm" / "daily-learning-reports"

    readme_text = _read_text(readme_path)
    master_plan_text = _read_text(master_plan_path)
    daily_task_text = _read_text(daily_task_path)

    for snippet in REQUIRED_README_SNIPPETS:
        assert _contains(readme_text, snippet), {"missing_in_readme": snippet}
    for snippet in REQUIRED_PLAN_SNIPPETS:
        assert _contains(master_plan_text, snippet), {"missing_in_master_plan": snippet}
    for snippet in REQUIRED_DAILY_TASK_SNIPPETS:
        assert _contains(daily_task_text, snippet), {"missing_in_daily_task": snippet}

    assert (
        assignment_self_iteration_runtime.ASSIGNMENT_SELF_ITERATION_DAILY_HISTORY_HINT
        == CANONICAL_DAILY_HISTORY_HINT
    ), assignment_self_iteration_runtime.ASSIGNMENT_SELF_ITERATION_DAILY_HISTORY_HINT
    assert (
        assignment_self_iteration_runtime.ASSIGNMENT_SELF_ITERATION_DAILY_LEARNING_REPORT_HINT
        == CANONICAL_DAILY_LEARNING_HINT
    ), assignment_self_iteration_runtime.ASSIGNMENT_SELF_ITERATION_DAILY_LEARNING_REPORT_HINT
    assert schedule_service.SCHEDULE_PM_DAILY_HISTORY_HINT == CANONICAL_DAILY_HISTORY_HINT, schedule_service.SCHEDULE_PM_DAILY_HISTORY_HINT
    assert (
        schedule_service.SCHEDULE_PM_DAILY_LEARNING_REPORT_HINT == CANONICAL_DAILY_LEARNING_HINT
    ), schedule_service.SCHEDULE_PM_DAILY_LEARNING_REPORT_HINT
    assert schedule_text_repair.SCHEDULE_DAILY_HISTORY_HINT == CANONICAL_DAILY_HISTORY_HINT, schedule_text_repair.SCHEDULE_DAILY_HISTORY_HINT
    assert (
        schedule_text_repair.SCHEDULE_DAILY_LEARNING_REPORT_HINT == CANONICAL_DAILY_LEARNING_HINT
    ), schedule_text_repair.SCHEDULE_DAILY_LEARNING_REPORT_HINT

    daily_history_files = sorted(
        path for path in daily_history_root.iterdir() if path.is_file() and DATED_FILE_RE.fullmatch(path.name)
    )
    assert daily_history_files, "daily history files missing"
    assert len(daily_history_files) <= 7, {"daily_history_count": len(daily_history_files)}
    history_issues = {
        path.name: _validate_daily_history_file(path)
        for path in daily_history_files
    }
    history_issues = {name: issues for name, issues in history_issues.items() if issues}
    assert not history_issues, history_issues

    learning_report_dirs = sorted(
        path for path in learning_report_root.iterdir() if path.is_dir() and DATED_DIR_RE.fullmatch(path.name)
    )
    assert learning_report_dirs, "learning report directories missing"
    latest_learning_dir = learning_report_dirs[-1]
    missing_reports = [
        f"{agent_id}.md" for agent_id in CORE_LEARNING_AGENTS if not (latest_learning_dir / f"{agent_id}.md").exists()
    ]
    assert not missing_reports, {"latest_learning_dir": latest_learning_dir.as_posix(), "missing_reports": missing_reports}
    learning_issues = {
        agent_id: _validate_learning_report(latest_learning_dir / f"{agent_id}.md", agent_id)
        for agent_id in CORE_LEARNING_AGENTS
    }
    learning_issues = {agent_id: issues for agent_id, issues in learning_issues.items() if issues}
    assert not learning_issues, learning_issues

    print(
        json.dumps(
            {
                "ok": True,
                "daily_history_hint": CANONICAL_DAILY_HISTORY_HINT,
                "daily_learning_hint": CANONICAL_DAILY_LEARNING_HINT,
                "daily_history_files": [path.name for path in daily_history_files],
                "latest_learning_dir": latest_learning_dir.as_posix(),
                "validated_learning_reports": [f"{agent_id}.md" for agent_id in CORE_LEARNING_AGENTS],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
