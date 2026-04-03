#!/usr/bin/env python3
"""Enforce workspace line-budget checks with separate hard and advisory results."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


DEFAULT_REFACTOR_TRIGGER_LINES = 1000
TARGET_EXTENSIONS = {
    ".bat",
    ".css",
    ".html",
    ".js",
    ".ps1",
    ".py",
    ".sql",
}
ROOT_LEVEL_FILE_EXTENSIONS = {
    ".bat",
    ".ps1",
    ".py",
}


@dataclass(frozen=True)
class ExclusionRule:
    label: str
    reason: str

    def matches(self, relative_path: Path) -> bool:
        raise NotImplementedError


@dataclass(frozen=True)
class DirectoryNameRule(ExclusionRule):
    names: tuple[str, ...]

    def matches(self, relative_path: Path) -> bool:
        return any(part in self.names for part in relative_path.parts)


@dataclass(frozen=True)
class PrefixRule(ExclusionRule):
    prefix: tuple[str, ...]

    def matches(self, relative_path: Path) -> bool:
        parts = relative_path.parts
        return parts[: len(self.prefix)] == self.prefix


@dataclass(frozen=True)
class HardRule:
    label: str
    path: str
    max_lines: int
    reason: str


@dataclass(frozen=True)
class ScopeRule:
    label: str
    max_lines: int
    reason: str
    prefixes: tuple[tuple[str, ...], ...]
    extensions: tuple[str, ...]
    action: str

    def matches(self, relative_path: Path) -> bool:
        parts = relative_path.parts
        suffix = relative_path.suffix.lower()
        if suffix not in self.extensions:
            return False
        return any(parts[: len(prefix)] == prefix for prefix in self.prefixes)


@dataclass(frozen=True)
class FileRecord:
    path: str
    line_count: int


@dataclass(frozen=True)
class GateOffender:
    path: str
    line_count: int
    threshold: int
    action: str
    rule: str


EXCLUSION_RULES: tuple[ExclusionRule, ...] = (
    DirectoryNameRule(
        label="runtime_artifacts",
        reason="运行态、审计和测试产物不纳入工程重构预算。",
        names=(
            ".codex",
            ".git",
            ".output",
            ".running",
            ".runtime",
            ".test",
            ".venv",
            "__pycache__",
            "incidents",
            "logs",
            "metrics",
            "node_modules",
            "state",
            "test-results",
        ),
    ),
    PrefixRule(
        label="workflow_docs",
        reason="需求、设计、报告和截图文档不纳入代码体量门禁。",
        prefix=("docs",),
    ),
)

HARD_RULES: tuple[HardRule, ...] = (
    HardRule(
        label="workflow_web_server_main",
        path="src/workflow_app/workflow_web_server.py",
        max_lines=3000,
        reason="工程化重构硬门禁：主入口必须瘦身到 3000 行以内。",
    ),
    HardRule(
        label="legacy_api_entry",
        path="src/workflow_app/server/api/legacy.py",
        max_lines=1000,
        reason="工程化重构硬门禁：legacy API 入口必须控制在 1000 行以内。",
    ),
)

GUIDELINE_RULES: tuple[ScopeRule, ...] = (
    ScopeRule(
        label="backend_core_advisory",
        max_lines=1500,
        reason="后端核心业务文件建议 <= 1500 行，超出需给拆分计划。",
        prefixes=(
            ("src", "workflow_app", "server"),
            ("src", "workflow_app", "history"),
        ),
        extensions=(".py", ".sql"),
        action="provide_split_plan",
    ),
    ScopeRule(
        label="frontend_core_advisory",
        max_lines=1200,
        reason="前端核心业务文件建议 <= 1200 行，超出需给拆分计划。",
        prefixes=(
            ("src", "workflow_app", "web_client"),
            ("src", "workflow_app", "server", "presentation", "templates"),
        ),
        extensions=(".js", ".css", ".html"),
        action="provide_split_plan",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check maintained source files against line-budget rules.")
    parser.add_argument("--root", default=".", help="Workspace root path.")
    parser.add_argument(
        "--max-lines",
        type=int,
        default=DEFAULT_REFACTOR_TRIGGER_LINES,
        help="Refactor-trigger threshold for maintained source files.",
    )
    parser.add_argument(
        "--report",
        default=".test/reports/WORKSPACE_LINE_BUDGET_REPORT.md",
        help="Markdown report path (absolute or relative to root).",
    )
    parser.add_argument(
        "--json-report",
        default="",
        help="JSON report path (absolute or relative to root). Defaults to report path with .json suffix.",
    )
    return parser.parse_args()


def resolve_output_path(root: Path, raw_path: str, *, fallback: Path | None = None) -> Path:
    if raw_path:
        path = Path(raw_path)
    elif fallback is not None:
        path = fallback
    else:
        raise ValueError("output path missing")
    if path.is_absolute():
        return path
    return root / path


def resolve_exclusion(relative_path: Path) -> ExclusionRule | None:
    for rule in EXCLUSION_RULES:
        if rule.matches(relative_path):
            return rule
    return None


def should_scan(relative_path: Path) -> bool:
    suffix = relative_path.suffix.lower()
    if suffix not in TARGET_EXTENSIONS:
        return False
    parts = relative_path.parts
    if not parts:
        return False
    if parts[0] in {"src", "scripts"}:
        return True
    return len(parts) == 1 and suffix in ROOT_LEVEL_FILE_EXTENSIONS


def count_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        return sum(1 for _ in handle)


def scan_workspace(root: Path) -> list[FileRecord]:
    records: list[FileRecord] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root)
        if resolve_exclusion(relative_path) is not None:
            continue
        if not should_scan(relative_path):
            continue
        records.append(
            FileRecord(
                path=relative_path.as_posix(),
                line_count=count_lines(path),
            )
        )
    records.sort(key=lambda item: (-item.line_count, item.path))
    return records


def find_record(records: list[FileRecord], path: str) -> FileRecord | None:
    for item in records:
        if item.path == path:
            return item
    return None


def collect_hard_gate(records: list[FileRecord]) -> dict[str, object]:
    results: list[dict[str, object]] = []
    for rule in HARD_RULES:
        record = find_record(records, rule.path)
        line_count = int(record.line_count) if record is not None else 0
        results.append(
            {
                "label": rule.label,
                "path": rule.path,
                "max_lines": int(rule.max_lines),
                "line_count": line_count,
                "pass": line_count <= int(rule.max_lines),
                "reason": rule.reason,
            }
        )
    passed = all(bool(item["pass"]) for item in results)
    return {
        "pass": passed,
        "offender_count": sum(1 for item in results if not bool(item["pass"])),
        "rules": results,
    }


def collect_refactor_trigger_gate(records: list[FileRecord], trigger_lines: int) -> dict[str, object]:
    offenders = [
        GateOffender(
            path=item.path,
            line_count=int(item.line_count),
            threshold=int(trigger_lines),
            action="trigger_refactor_skill",
            rule="refactor_trigger_gate",
        )
        for item in records
        if int(item.line_count) > int(trigger_lines)
    ]
    return {
        "pass": not offenders,
        "triggered": bool(offenders),
        "threshold": int(trigger_lines),
        "offender_count": len(offenders),
        "offenders": [asdict(item) for item in offenders],
    }


def collect_guideline_gate(records: list[FileRecord]) -> dict[str, object]:
    offenders: list[GateOffender] = []
    for item in records:
        relative_path = Path(item.path)
        for rule in GUIDELINE_RULES:
            if rule.matches(relative_path) and int(item.line_count) > int(rule.max_lines):
                offenders.append(
                    GateOffender(
                        path=item.path,
                        line_count=int(item.line_count),
                        threshold=int(rule.max_lines),
                        action=rule.action,
                        rule=rule.label,
                    )
                )
    offenders.sort(key=lambda offender: (-offender.line_count, offender.path, offender.rule))
    return {
        "pass": not offenders,
        "triggered": bool(offenders),
        "offender_count": len(offenders),
        "rules": [
            {
                "label": rule.label,
                "max_lines": int(rule.max_lines),
                "reason": rule.reason,
                "action": rule.action,
            }
            for rule in GUIDELINE_RULES
        ],
        "offenders": [asdict(item) for item in offenders],
    }


def build_report_payload(
    *,
    root: Path,
    report_path: Path,
    json_report_path: Path,
    refactor_trigger_lines: int,
) -> dict[str, object]:
    records = scan_workspace(root)
    hard_gate = collect_hard_gate(records)
    refactor_trigger_gate = collect_refactor_trigger_gate(records, refactor_trigger_lines)
    guideline_gate = collect_guideline_gate(records)
    trigger_action = "trigger_refactor_skill" if bool(refactor_trigger_gate["triggered"]) else "none"
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "root": root.as_posix(),
        "report_path": report_path.as_posix(),
        "json_report_path": json_report_path.as_posix(),
        "scan_scope": "maintained_source_and_automation_files",
        "refactor_trigger_lines": int(refactor_trigger_lines),
        "pass": bool(hard_gate["pass"]),
        "trigger_action": trigger_action,
        "file_count": len(records),
        "files": [asdict(item) for item in records],
        "hard_gate": hard_gate,
        "refactor_trigger_gate": refactor_trigger_gate,
        "guideline_gate": guideline_gate,
        "exclusions": [
            {
                "label": rule.label,
                "reason": rule.reason,
            }
            for rule in EXCLUSION_RULES
        ],
    }


def render_markdown_report(payload: dict[str, object]) -> str:
    hard_gate = dict(payload["hard_gate"])
    refactor_gate = dict(payload["refactor_trigger_gate"])
    guideline_gate = dict(payload["guideline_gate"])
    lines = [
        "# WORKSPACE_LINE_BUDGET_REPORT",
        "",
        f"- generated_at: {payload['generated_at']}",
        f"- root: {payload['root']}",
        f"- report_path: {payload['report_path']}",
        f"- json_report_path: {payload['json_report_path']}",
        f"- scan_scope: {payload['scan_scope']}",
        f"- refactor_trigger_lines: {payload['refactor_trigger_lines']}",
        f"- hard_gate_pass: {'true' if hard_gate['pass'] else 'false'}",
        f"- refactor_triggered: {'true' if refactor_gate['triggered'] else 'false'}",
        f"- guideline_triggered: {'true' if guideline_gate['triggered'] else 'false'}",
        f"- trigger_action: {payload['trigger_action']}",
        "",
        "## Exclusions",
        "",
        "| rule | reason |",
        "|---|---|",
    ]
    for item in payload["exclusions"]:
        lines.append(f"| `{item['label']}` | {item['reason']} |")

    lines.extend(
        [
            "",
            "## Hard Gate",
            "",
            "| rule | file | limit | lines | pass | reason |",
            "|---|---|---:|---:|---|---|",
        ]
    )
    for item in hard_gate["rules"]:
        lines.append(
            "| `{label}` | `{path}` | {limit} | {lines_count} | {passed} | {reason} |".format(
                label=item["label"],
                path=item["path"],
                limit=item["max_lines"],
                lines_count=item["line_count"],
                passed="pass" if item["pass"] else "fail",
                reason=item["reason"],
            )
        )

    lines.extend(
        [
            "",
            "## Refactor Trigger Gate",
            "",
            f"- note: 该门槛用于发现 `> {payload['refactor_trigger_lines']}` 行的维护中代码文件，并触发 `trigger_refactor_skill`。",
            "",
        ]
    )
    if refactor_gate["offenders"]:
        lines.extend(
            [
                "| file | lines | threshold | action |",
                "|---|---:|---:|---|",
            ]
        )
        for item in refactor_gate["offenders"]:
            lines.append(
                f"| `{item['path']}` | {item['line_count']} | {item['threshold']} | `{item['action']}` |"
            )
    else:
        lines.append("all maintained source files stay within the refactor-trigger threshold.")

    lines.extend(
        [
            "",
            "## Guideline Gate",
            "",
            "- note: 该部分用于输出拆分计划义务，不直接决定默认发布链路的退出码。",
            "",
            "| rule | limit | action | reason |",
            "|---|---:|---|---|",
        ]
    )
    for item in guideline_gate["rules"]:
        lines.append(
            f"| `{item['label']}` | {item['max_lines']} | `{item['action']}` | {item['reason']} |"
        )
    lines.extend(["", "### Guideline Offenders", ""])
    if guideline_gate["offenders"]:
        lines.extend(
            [
                "| file | lines | threshold | rule | action |",
                "|---|---:|---:|---|---|",
            ]
        )
        for item in guideline_gate["offenders"]:
            lines.append(
                f"| `{item['path']}` | {item['line_count']} | {item['threshold']} | `{item['rule']}` | `{item['action']}` |"
            )
    else:
        lines.append("no guideline offenders detected.")

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- 默认退出码仅由 `Hard Gate` 决定；`Refactor Trigger Gate` 与 `Guideline Gate` 用于提示后续重构动作。",
            "- 若 `Refactor Trigger Gate` 命中，说明本轮需求完成后应补一轮设计模式/职责拆分重构。",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    report_path = resolve_output_path(root, args.report)
    if str(args.json_report or "").strip():
        json_report_path = resolve_output_path(root, args.json_report)
    else:
        report_arg_path = Path(args.report)
        json_report_path = report_path.with_suffix(".json") if report_arg_path.is_absolute() else root / report_arg_path.with_suffix(".json")
    payload = build_report_payload(
        root=root,
        report_path=report_path,
        json_report_path=json_report_path,
        refactor_trigger_lines=max(1, int(args.max_lines)),
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_markdown_report(payload), encoding="utf-8")
    json_report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(report_path.as_posix())
    return 0 if bool(payload["pass"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
