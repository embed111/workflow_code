#!/usr/bin/env python3
"""Check backend module README contract sections."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


REQUIRED_READMES = [
    "src/workflow_app/server/README.md",
    "src/workflow_app/server/api/README.md",
    "src/workflow_app/server/services/README.md",
    "src/workflow_app/server/infra/README.md",
    "src/workflow_app/server/presentation/README.md",
    "src/workflow_app/server/bootstrap/README.md",
]

REQUIRED_SECTIONS = [
    "模块目标与非目标",
    "目录职责边界（In/Out）",
    "对外接口（API/Event/函数入口）",
    "允许依赖与禁止依赖",
    "状态与数据存储（表/文件/缓存）",
    "关键回归命令",
    "常见变更操作步骤（新增接口/改字段）",
    "回滚策略",
    "Agent 接管入口（先读文件、执行顺序、最小验证）",
]


@dataclass
class CheckRow:
    path: str
    exists: bool
    missing_sections: list[str]

    @property
    def passed(self) -> bool:
        return self.exists and not self.missing_sections


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check module README contract required sections."
    )
    parser.add_argument("--root", default=".", help="Workspace root path.")
    parser.add_argument(
        "--report",
        default=".test/reports/README_CONTRACT_REPORT.md",
        help="Report file path (absolute or relative to root).",
    )
    return parser.parse_args()


def resolve_report_path(root: Path, report_arg: str) -> Path:
    report_path = Path(report_arg)
    if report_path.is_absolute():
        return report_path
    return root / report_path


def scan_readme(path: Path) -> CheckRow:
    if not path.exists():
        return CheckRow(path=str(path), exists=False, missing_sections=REQUIRED_SECTIONS[:])
    text = path.read_text(encoding="utf-8")
    missing = [section for section in REQUIRED_SECTIONS if section not in text]
    return CheckRow(path=str(path), exists=True, missing_sections=missing)


def render_report(root: Path, rows: list[CheckRow], passed: bool) -> str:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    lines: list[str] = []
    lines.append("# README_CONTRACT_REPORT")
    lines.append("")
    lines.append(f"- generated_at: {now}")
    lines.append(f"- root: {root.as_posix()}")
    lines.append(f"- pass: {'true' if passed else 'false'}")
    lines.append("")
    lines.append("## Required Sections")
    for section in REQUIRED_SECTIONS:
        lines.append(f"- {section}")
    lines.append("")
    lines.append("## Result")
    lines.append("")
    lines.append("| module | exists | section_check | missing_sections |")
    lines.append("|---|---|---|---|")
    for row in rows:
        missing = ", ".join(row.missing_sections) if row.missing_sections else "-"
        section_check = "pass" if not row.missing_sections else "fail"
        lines.append(
            f"| `{Path(row.path).as_posix()}` | "
            f"{'yes' if row.exists else 'no'} | {section_check} | {missing} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    rows = [scan_readme(root / rel) for rel in REQUIRED_READMES]
    passed = all(row.passed for row in rows)
    report_path = resolve_report_path(root, args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(root, rows, passed), encoding="utf-8")
    print(report_path.as_posix())
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
