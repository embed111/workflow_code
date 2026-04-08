from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path


GLOBAL_OVERVIEW_NAME = "全局记忆总览.md"
MONTHLY_OVERVIEW_NAME = "记忆总览.md"

LEGACY_GLOBAL_PLACEHOLDERS = {
    "# 全局记忆总览\n\n- 当前角色工作区初始化完成后，闭月总结在这里归档。",
    "# 全局记忆总览\n\n## 当前状态\n- 当前活动月份： `2026-04`\n- 当前活动月份总览： `.codex/memory/2026-04/记忆总览.md`",
}


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

    repair_parser = subparsers.add_parser("repair-rollups", help="Repair missing scaffold files and archive day/month rollovers.")
    repair_parser.add_argument("--root", type=Path, default=Path("."), help="Workspace root path.")
    repair_parser.add_argument("--date", type=parse_date, default=None, help="Target date in YYYY-MM-DD format.")

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


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def build_global_template(target_date: dt.date) -> str:
    month_value = target_date.strftime("%Y-%m")
    return (
        "# 全局记忆总览\n\n"
        "## 角色说明\n"
        "- 作用：提供跨月份的记忆索引，只归档已闭月的月度总结。\n"
        f"- 后续读取：继续读取 `.codex/memory/{month_value}/{MONTHLY_OVERVIEW_NAME}`。\n"
        f"- 当前活动月份： `{month_value}`\n"
        f"- 当前活动月份总览： `.codex/memory/{month_value}/{MONTHLY_OVERVIEW_NAME}`\n\n"
        "## 当前状态\n"
        "- 已归档闭月数量： `0`\n"
        "- 当前活动月份状态： `in_progress`\n"
        f"- 当前活动日记： `.codex/memory/{month_value}/{target_date.isoformat()}.md`\n"
        "- 全局归档说明：仅在闭月后把月度总结写入本文件；当前活动月份只保留索引，不复制日级增量。\n\n"
        "## 已归档月份\n"
        "- 暂无，等待闭月后归档。\n\n"
        "## 活动月份导航\n"
        f"### {month_value}\n"
        "- 状态：当前活动月份，尚未进入全局归档\n"
        f"- 总览路径： `.codex/memory/{month_value}/{MONTHLY_OVERVIEW_NAME}`\n"
        f"- 日记范围： `{month_value}-01` 至今\n"
        "- 重点：等待当前工作区持续积累日记与月度摘要后再收口。\n"
    )


def build_monthly_template(target_date: dt.date) -> str:
    month_value = target_date.strftime("%Y-%m")
    return (
        f"# 记忆总览 {month_value}\n\n"
        "## 月份状态\n"
        "- 状态： `in_progress`\n"
        "- 已归档日记范围： `待补齐`\n"
        f"- 当前活动日记： `.codex/memory/{month_value}/{target_date.isoformat()}.md`\n"
        "- 月度归档目标： `.codex/memory/全局记忆总览.md`\n\n"
        "## 归档规则\n"
        "- 仅归档截至昨日的日级摘要。\n"
        "- 当日新增总结只保留在对应的 `YYYY-MM-DD.md` 中，待日切后再归档。\n"
        "- 若发生跨月，需先确认本月总览已被全局总览收录，再进入新月份工作。\n\n"
        "## 已归档日索引\n"
        "- 暂无，等待日切后归档。\n"
    )


def build_daily_template(target_date: dt.date) -> str:
    month_value = target_date.strftime("%Y-%m")
    return (
        f"# 每日记忆 {target_date.isoformat()}\n\n"
        "## Metadata\n"
        f"- month: `{month_value}`\n"
        f"- month_overview: `.codex/memory/{month_value}/{MONTHLY_OVERVIEW_NAME}`\n"
        "- archival_rule: 今日总结仅写入本文件，待日切后再归档到月度总览。\n\n"
        "## Writing Notes\n"
        "- 我默认用第一人称记录这一天的工作，语气可以带一点日记感，但要保持结构化、可检索。\n"
        "- 每条记录优先写清楚：topic / context / actions / decisions / validation / artifacts / next。\n\n"
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


def _is_legacy_global_placeholder(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return True
    if normalized in LEGACY_GLOBAL_PLACEHOLDERS:
        return True
    return "## " not in normalized and "### " not in normalized


def _is_legacy_month_placeholder(text: str, target_date: dt.date) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return True
    legacy_exact = {
        f"# 记忆总览 {target_date.strftime('%Y-%m')}\n\n- 当前月份的已归档日级摘要会收口到这里。",
        (
            f"# 记忆总览 {target_date.strftime('%Y-%m')}\n\n"
            "## 月份状态\n"
            "- 状态： `in_progress`\n"
            f"- 当前活动日记： `.codex/memory/{target_date.strftime('%Y-%m')}/{target_date.isoformat()}.md`\n"
        ).strip(),
    }
    if normalized in legacy_exact:
        return True
    return "## " not in normalized and "### " not in normalized


def _daily_has_real_entries(text: str) -> bool:
    if not text.strip():
        return False
    marker = text.split("## Entries", 1)
    body = marker[1] if len(marker) > 1 else text
    return bool(re.search(r"^###\s+\d{4}-\d{2}-\d{2}T", body, re.MULTILINE))


def ensure_memory_scaffold(root: Path, target_date: dt.date) -> list[str]:
    created_or_upgraded: list[str] = []
    global_path = global_overview_path(root)
    month_path = monthly_overview_path(root, target_date)
    daily_path = daily_memory_path(root, target_date)

    global_path.parent.mkdir(parents=True, exist_ok=True)
    month_path.parent.mkdir(parents=True, exist_ok=True)
    daily_path.parent.mkdir(parents=True, exist_ok=True)

    global_text = read_text(global_path)
    if not global_text or _is_legacy_global_placeholder(global_text):
        global_path.write_text(build_global_template(target_date), encoding="utf-8")
        created_or_upgraded.append(relative_to_root(root, global_path))

    month_text = read_text(month_path)
    if not month_text or _is_legacy_month_placeholder(month_text, target_date):
        month_path.write_text(build_monthly_template(target_date), encoding="utf-8")
        created_or_upgraded.append(relative_to_root(root, month_path))

    daily_text = read_text(daily_path)
    if not daily_text:
        daily_path.write_text(build_daily_template(target_date), encoding="utf-8")
        created_or_upgraded.append(relative_to_root(root, daily_path))
    elif not _daily_has_real_entries(daily_text) and "## Entry Schema" not in daily_text:
        daily_path.write_text(build_daily_template(target_date), encoding="utf-8")
        created_or_upgraded.append(relative_to_root(root, daily_path))

    return created_or_upgraded


def ensure_daily_memory(root: Path, target_date: dt.date) -> Path:
    ensure_memory_scaffold(root, target_date)
    return daily_memory_path(root, target_date)


def print_status(root: Path, target_date: dt.date) -> int:
    ensure_memory_scaffold(root, target_date)
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


def _monthly_entry_exists(monthly_text: str, target_date: dt.date) -> bool:
    pattern = re.compile(rf"^### {re.escape(target_date.isoformat())}\s*$", re.MULTILINE)
    return bool(pattern.search(monthly_text))


def _global_entry_exists(global_text: str, month_value: str) -> bool:
    pattern = re.compile(rf"^### {re.escape(month_value)}\s*$", re.MULTILINE)
    return bool(pattern.search(global_text))


def _daily_topic_from_text(target_date: dt.date, daily_text: str) -> str:
    topics = [item.strip() for item in re.findall(r"^- topic:\s*(.+)$", daily_text, re.MULTILINE) if item.strip()]
    if topics:
        return topics[-1]
    titles = [
        item.strip()
        for item in re.findall(r"^###\s+\d{4}-\d{2}-\d{2}T[^\n|]*\|\s*(.+)$", daily_text, re.MULTILINE)
        if item.strip()
    ]
    if titles:
        return titles[-1]
    if _daily_has_real_entries(daily_text):
        return f"{target_date.isoformat()} 工作纪要"
    return "日切归档占位"


def _daily_summary_from_text(target_date: dt.date, daily_text: str) -> str:
    if not _daily_has_real_entries(daily_text):
        return "当日日记已创建但未追加正式工作条目。"
    summary_lines = [item.strip() for item in re.findall(r"^- summary:\s*(.+)$", daily_text, re.MULTILINE) if item.strip()]
    if summary_lines:
        return "；".join(summary_lines[-2:])[:240]
    decisions = [item.strip() for item in re.findall(r"^- decisions:\s*(.+)$", daily_text, re.MULTILINE) if item.strip()]
    if decisions:
        return f"基于当日日记自动归档：{decisions[-1][:180]}"
    return f"基于 {target_date.isoformat()} 当日日记自动归档，详见对应日记。"


def _build_monthly_archive_entry(root: Path, target_date: dt.date) -> str:
    daily_path = daily_memory_path(root, target_date)
    daily_text = read_text(daily_path)
    month_value = target_date.strftime("%Y-%m")
    topic = _daily_topic_from_text(target_date, daily_text)
    summary = _daily_summary_from_text(target_date, daily_text)
    return (
        f"\n\n### {target_date.isoformat()}\n"
        f"- 主题： {topic}\n"
        f"- 摘要： {summary}\n"
        f"- 日记路径： `.codex/memory/{month_value}/{target_date.isoformat()}.md`\n"
    )


def _build_global_archive_entry(root: Path, month_date: dt.date) -> str:
    month_value = month_date.strftime("%Y-%m")
    month_path = monthly_overview_path(root, month_date)
    month_text = read_text(month_path)
    archived_days = re.findall(r"^### (\d{4}-\d{2}-\d{2})\s*$", month_text, re.MULTILINE)
    range_text = f"`{archived_days[0]}` 至 `{archived_days[-1]}`" if archived_days else f"`{month_value}`"
    summary = (
        f"本月已归档日记数量：`{len(archived_days)}`；详见 `.codex/memory/{month_value}/{MONTHLY_OVERVIEW_NAME}`。"
        if archived_days
        else f"本月总览已建立，后续详见 `.codex/memory/{month_value}/{MONTHLY_OVERVIEW_NAME}`。"
    )
    return (
        f"\n\n### {month_value}\n"
        "- 状态： `closed`\n"
        f"- 月度总览： `.codex/memory/{month_value}/{MONTHLY_OVERVIEW_NAME}`\n"
        f"- 月内范围： {range_text}\n"
        f"- 月度摘要： {summary}\n"
    )


def verify_rollups(root: Path, target_date: dt.date) -> int:
    ensure_memory_scaffold(root, target_date)
    issues: list[str] = []
    messages: list[str] = []
    yesterday = target_date - dt.timedelta(days=1)

    yesterday_daily = daily_memory_path(root, yesterday)
    yesterday_monthly = monthly_overview_path(root, yesterday)
    global_path = global_overview_path(root)

    if yesterday_daily.exists():
        if not yesterday_monthly.exists():
            issues.append(f"missing monthly overview for {yesterday.strftime('%Y-%m')}")
        else:
            monthly_text = yesterday_monthly.read_text(encoding="utf-8")
            if not _monthly_entry_exists(monthly_text, yesterday):
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
        if not global_path.exists():
            issues.append(f"missing global overview {relative_to_root(root, global_path)}")
        else:
            global_text = global_path.read_text(encoding="utf-8")
            if not _global_entry_exists(global_text, yesterday.strftime("%Y-%m")):
                issues.append(
                    f"closed month {yesterday.strftime('%Y-%m')} is not archived in "
                    f"{relative_to_root(root, global_path)}"
                )
            else:
                messages.append(
                    f"MONTH_ROLLOVER_OK {yesterday.strftime('%Y-%m')} -> "
                    f"{relative_to_root(root, global_path)}"
                )
    else:
        messages.append("MONTH_ROLLOVER_SKIPPED current date is still in the same month as yesterday")

    for message in messages:
        print(message)
    for issue in issues:
        print(f"ERROR {issue}")

    return 1 if issues else 0


def repair_rollups(root: Path, target_date: dt.date) -> int:
    changed = ensure_memory_scaffold(root, target_date)
    yesterday = target_date - dt.timedelta(days=1)
    yesterday_daily = daily_memory_path(root, yesterday)
    yesterday_monthly = monthly_overview_path(root, yesterday)
    global_path = global_overview_path(root)

    if yesterday_daily.exists():
        ensure_memory_scaffold(root, yesterday)
        monthly_text = read_text(yesterday_monthly)
        if not _monthly_entry_exists(monthly_text, yesterday):
            with yesterday_monthly.open("a", encoding="utf-8") as handle:
                handle.write(_build_monthly_archive_entry(root, yesterday))
            changed.append(relative_to_root(root, yesterday_monthly))

    if yesterday.strftime("%Y-%m") != target_date.strftime("%Y-%m") and yesterday_monthly.exists():
        global_text = read_text(global_path)
        month_value = yesterday.strftime("%Y-%m")
        if not _global_entry_exists(global_text, month_value):
            with global_path.open("a", encoding="utf-8") as handle:
                handle.write(_build_global_archive_entry(root, yesterday))
            changed.append(relative_to_root(root, global_path))

    if changed:
        print("REPAIRED")
        for item in dict.fromkeys(changed):
            print(f"UPDATED {item}")
    else:
        print("REPAIRED")
        print("UPDATED none")
    return verify_rollups(root, target_date)


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
    if args.command == "repair-rollups":
        return repair_rollups(root, target_date)
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
