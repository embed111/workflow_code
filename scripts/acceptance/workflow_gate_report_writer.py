#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def write_gate_acceptance_report(
    *,
    repo_root: Path,
    base: str,
    default_root: str,
    runtime_root: Path,
    results: list[tuple[str, bool, dict]],
    errors: list[str],
) -> Path:
    now_key = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = (repo_root / ".test" / "runs").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"workflow-gate-acceptance-{now_key}.md"
    lines = [
        f"# Gate Acceptance - {now_key}",
        "",
        f"- base_url: {base}",
        f"- default_agent_root: {default_root}",
        f"- runtime_root: {runtime_root.as_posix()}",
        "",
    ]
    for name, ok, detail in results:
        lines.extend(
            [
                f"## {name}",
                f"- pass: {ok}",
                "- detail:",
                "```json",
                json.dumps(detail, ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    if errors:
        lines.extend(["## errors", "```text", *errors, "```", ""])
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
