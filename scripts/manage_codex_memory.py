from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path


GLOBAL_OVERVIEW_NAME = "全局记忆总览.md"
MONTHLY_OVERVIEW_NAME = "记忆总览.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage and validate .codex memory files.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Workspace root path.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Print the required memory read order and file status.")
    status_parser.add_argument("--root", type=Path, default=Path("."), help="Workspace root path.")
    status_parser.add_argument("--date", type=parse_date, default=None, help="Target date in YYYY-MM-DD format.")

    append_parser = subparsers.add_parser("append", help="Append a timestamped round summary to today's daily memory.")
    append_parser.add_argument("--root", type=Path, default=Path("."), help="Workspace root path.")
    append_parser.add_argument("--date", type=parse_date, default=None, help="Target date in YYYY-MM-DD format.")
    append_parser.add_argument("--summary", default=None, help="Round summary to append.")
    append_parser.add_argument("--topic", default=None, help="Main topic of the round.")
    append_parser.add_argument("--context", default=None, help="Context or trigger for the round.")
    append_parser.add_argument(
        "--actions",
        default=None,
        help="Actions taken in this round. Use | to separate multiple items.",
    )
    append_parser.add_argument(
        "--decisions",
        default=None,
        help="Decisions or conclusions from this round. Use | to separate multiple items.",
    )
    append_parser.add_argument(
        "--validation",
        default=None,
        help="Validation steps and outcomes. Use | to separate multiple items.",
    )
    append_parser.add_argument(
        "--artifacts",
        default=None,
        help="Important files or directories touched. Use | to separate multiple items.",
    )
    append_parser.add_argument(
        "--next",
        default=None,
        help="Follow-up items or deferred checks. Use | to separate multiple items.",
    )
    append_parser.add_argument(
        "--timestamp",
        default=None,
        help="Override timestamp in ISO 8601 format. Defaults to local current time.",
    )

    verify_parser = subparsers.add_parser("verify-rollups", help="Verify day/month rollover archiving rules.")
    verify_parser.add_argument("--root", type=Path, default=Path("."), help="Workspace root path.")
    verify_parser.add_argument("--date", type=parse_date, default=None, help="Target date in YYYY-MM-DD format.")

    return parser.parse_args()


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def current_date() -> dt.date:
    return dt.datetime.now().astimezone().date()


def current_timestamp() -> str:
    return dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def memory_root(root: Path) -> Path:
    return root / ".codex" / "memory"


def month_dir(root: Path, target_date: dt.date) -> Path:
    return memory_root(root) / target_date.strftime("%Y-%m")


def global_overview_path(root: Path) -> Path:
    return memory_root(root) / GLOBAL_OVERVIEW_NAME


def monthly_overview_path(root: Path, target_date: dt.date) -> Path:
    return month_dir(root, target_date) / MONTHLY_OVERVIEW_NAME


def daily_memory_path(root: Path, target_date: dt.date) -> Path:
    return month_dir(root, target_date) / f"{target_date.isoformat()}.md"


def relative_to_root(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def required_paths(root: Path, target_date: dt.date) -> list[Path]:
    return [
        root / ".codex" / "SOUL.md",
        root / ".codex" / "USER.md",
        root / ".codex" / "MEMORY.md",
        global_overview_path(root),
        monthly_overview_path(root, target_date),
        daily_memory_path(root, target_date),
    ]


def build_daily_template(target_date: dt.date) -> str:
    month_value = target_date.strftime("%Y-%m")
    return (
        f"# 每日记忆 {target_date.isoformat()}\n\n"
        "## Metadata\n"
        f"- month: `{month_value}`\n"
        f"- month_overview: `.codex/memory/{month_value}/{MONTHLY_OVERVIEW_NAME}`\n"
        "- archival_rule: 今日总结仅写入本文件，待日切后再归档到月度总览。\n\n"
        "## Entry Schema\n"
        "- topic: 本轮主主题\n"
        "- context: 触发背景或问题来源\n"
        "- actions: 本轮实际动作\n"
        "- decisions: 对后续有影响的约束或结论\n"
        "- validation: 已做检查与结果\n"
        "- artifacts: 关键文件或目录\n"
        "- next: 后续待跟进事项\n\n"
        "## Entries\n"
    )


def ensure_daily_memory(root: Path, target_date: dt.date) -> Path:
    daily_path = daily_memory_path(root, target_date)
    daily_path.parent.mkdir(parents=True, exist_ok=True)
    if not daily_path.exists():
        daily_path.write_text(build_daily_template(target_date), encoding="utf-8")
    return daily_path


def print_status(root: Path, target_date: dt.date) -> int:
    read_order = [
        Path("AGENTS.md"),
        Path(".codex/SOUL.md"),
        Path(".codex/USER.md"),
        Path(".codex/MEMORY.md"),
        Path(".codex/memory/全局记忆总览.md"),
        Path(f".codex/memory/{target_date.strftime('%Y-%m')}/记忆总览.md"),
        Path(f".codex/memory/{target_date.strftime('%Y-%m')}/{target_date.isoformat()}.md"),
    ]

    print("READ_ORDER")
    for index, path in enumerate(read_order, start=1):
        print(f"{index}. {path.as_posix()}")

    missing = [path for path in required_paths(root, target_date) if not path.exists()]
    print("")
    print("FILE_STATUS")
    if missing:
        for path in missing:
            print(f"MISSING {relative_to_root(root, path)}")
        return 1

    for path in required_paths(root, target_date):
        print(f"OK {relative_to_root(root, path)}")
    return 0


def split_items(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split("|") if item.strip()]


def build_bullet_section(label: str, items: list[str]) -> str:
    if not items:
        return ""
    lines = [f"- {label}:"]
    lines.extend(f"  - {item}" for item in items)
    return "\n".join(lines)


def build_entry_body(args: argparse.Namespace) -> str:
    sections: list[str] = []

    if args.summary:
        normalized_lines = [line.strip() for line in args.summary.splitlines() if line.strip()]
        if normalized_lines:
            sections.append("- summary:")
            sections.extend(f"  - {line}" for line in normalized_lines)

    scalar_sections = [
        ("topic", args.topic),
        ("context", args.context),
    ]
    for label, value in scalar_sections:
        if value and value.strip():
            sections.append(f"- {label}: {value.strip()}")

    list_sections = [
        ("actions", split_items(args.actions)),
        ("decisions", split_items(args.decisions)),
        ("validation", split_items(args.validation)),
        ("artifacts", split_items(args.artifacts)),
        ("next", split_items(args.next)),
    ]
    for label, items in list_sections:
        section = build_bullet_section(label, items)
        if section:
            sections.append(section)

    if not sections:
        raise ValueError(
            "append requires at least one of: --summary, --topic, --context, --actions, --decisions, "
            "--validation, --artifacts, --next"
        )
    return "\n".join(sections)


def append_summary(root: Path, target_date: dt.date, args: argparse.Namespace) -> int:
    daily_path = ensure_daily_memory(root, target_date)
    timestamp_value = args.timestamp or current_timestamp()
    title_suffix = f" | {args.topic.strip()}" if args.topic and args.topic.strip() else ""
    body = build_entry_body(args)

    existing = daily_path.read_text(encoding="utf-8").rstrip()
    entry = f"\n\n### {timestamp_value}{title_suffix}\n{body}\n"
    daily_path.write_text(existing + entry, encoding="utf-8")
    print(f"APPENDED {relative_to_root(root, daily_path)}")
    print(f"TIMESTAMP {timestamp_value}")
    return 0


def verify_rollups(root: Path, target_date: dt.date) -> int:
    issues: list[str] = []
    messages: list[str] = []
    yesterday = target_date - dt.timedelta(days=1)

    yesterday_daily = daily_memory_path(root, yesterday)
    yesterday_monthly = monthly_overview_path(root, yesterday)
    global_overview = global_overview_path(root)

    if yesterday_daily.exists():
        if not yesterday_monthly.exists():
            issues.append(f"missing monthly overview for {yesterday.strftime('%Y-%m')}")
        else:
            monthly_text = yesterday_monthly.read_text(encoding="utf-8")
            archived_daily_pattern = re.compile(rf"^### {re.escape(yesterday.isoformat())}\s*$", re.MULTILINE)
            if not archived_daily_pattern.search(monthly_text):
                issues.append(
                    f"yesterday daily memory {yesterday.isoformat()} is not archived in "
                    f"{relative_to_root(root, yesterday_monthly)}"
                )
            else:
                messages.append(
                    f"DAY_ROLLOVER_OK {yesterday.isoformat()} -> {relative_to_root(root, yesterday_monthly)}"
                )
    else:
        messages.append(f"DAY_ROLLOVER_SKIPPED {yesterday.isoformat()} daily memory not found")

    if yesterday.strftime("%Y-%m") != target_date.strftime("%Y-%m"):
        if not global_overview.exists():
            issues.append(f"missing global overview {relative_to_root(root, global_overview)}")
        else:
            global_text = global_overview.read_text(encoding="utf-8")
            archived_month_pattern = re.compile(rf"^### {re.escape(yesterday.strftime('%Y-%m'))}\s*$", re.MULTILINE)
            if not archived_month_pattern.search(global_text):
                issues.append(
                    f"closed month {yesterday.strftime('%Y-%m')} is not archived in "
                    f"{relative_to_root(root, global_overview)}"
                )
            else:
                messages.append(
                    f"MONTH_ROLLOVER_OK {yesterday.strftime('%Y-%m')} -> "
                    f"{relative_to_root(root, global_overview)}"
                )
    else:
        messages.append("MONTH_ROLLOVER_SKIPPED current date is still in the same month as yesterday")

    for message in messages:
        print(message)
    for issue in issues:
        print(f"ERROR {issue}")

    return 1 if issues else 0


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    target_date = args.date or current_date()

    if args.command == "status":
        return print_status(root, target_date)
    if args.command == "append":
        return append_summary(root, target_date, args)
    if args.command == "verify-rollups":
        return verify_rollups(root, target_date)
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
