#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair role workspace memory governance files.")
    parser.add_argument(
        "--workspace",
        action="append",
        required=True,
        help="Role workspace path. Repeat for multiple workspaces.",
    )
    return parser.parse_args()


def _find_reference_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / ".codex" / "MEMORY.md").exists():
            return candidate
    raise FileNotFoundError("reference .codex/MEMORY.md not found")


def _memory_governance_section() -> str:
    return (
        "## Memory Governance\n"
        "- 经验入口以 `.codex/experience/index.md` 为准；正式工作前先读索引，再按其中“必读经验”顺序补充读取经验卡。\n"
        "- 记忆库规范以 `.codex/MEMORY.md` 为准；每轮正式工作前先按那份规范完成读链。\n"
        "- 若发生日切或月切，先执行 `.codex/MEMORY.md` 中的归档检查，再继续当前任务。\n"
        "- 需要补齐骨架或归档时，优先使用 `python scripts/manage_codex_memory.py repair-rollups --root .`。\n\n"
    )


def _patch_agents_text(text: str) -> str:
    startup_block = (
        "## Startup Read Order\n"
        "1. `AGENTS.md`\n"
        "2. `.codex/experience/index.md`\n"
        "3. 读取 `.codex/experience/index.md` 中“必读经验”列出的经验文件\n"
        "4. `.codex/SOUL.md`\n"
        "5. `.codex/USER.md`\n"
        "6. `.codex/MEMORY.md`\n"
        "7. `.codex/memory/全局记忆总览.md`\n"
        "8. `.codex/memory/YYYY-MM/记忆总览.md`\n"
        "9. `.codex/memory/YYYY-MM/YYYY-MM-DD.md`\n"
    )
    patched = text
    startup_pattern = re.compile(r"## Startup Read Order\s*\n(?:\d+\.\s.*\n?)+", re.MULTILINE)
    if startup_pattern.search(patched):
        patched = startup_pattern.sub(startup_block, patched, count=1)
    elif "## Startup Read Order" not in patched:
        patched = patched.rstrip() + "\n\n" + startup_block
    section = _memory_governance_section()
    if "## Memory Governance" in patched:
        return patched
    marker = "## Startup Read Order"
    if marker in patched:
        return patched.replace(marker, section + marker, 1)
    return patched.rstrip() + "\n\n" + section


def _sync_file(path: Path, content: str) -> bool:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _sync_reference_experience(reference_root: Path, workspace: Path) -> list[str]:
    updated: list[str] = []
    source_dir = reference_root / ".codex" / "experience"
    if not source_dir.exists() or not source_dir.is_dir():
        return updated
    target_dir = workspace / ".codex" / "experience"
    for source_path in source_dir.rglob("*.md"):
        if not source_path.is_file():
            continue
        relative_path = source_path.relative_to(source_dir)
        target_path = target_dir / relative_path
        if _sync_file(target_path, source_path.read_text(encoding="utf-8")):
            updated.append(target_path.as_posix())
    return updated


def repair_workspace(workspace_path: Path, *, reference_root: Path, script_source: Path) -> dict[str, object]:
    workspace = workspace_path.resolve(strict=False)
    agents_path = workspace / "AGENTS.md"
    memory_path = workspace / ".codex" / "MEMORY.md"
    script_target = workspace / "scripts" / "manage_codex_memory.py"

    if not workspace.exists() or not workspace.is_dir():
        raise FileNotFoundError(f"workspace not found: {workspace.as_posix()}")
    if not agents_path.exists():
        raise FileNotFoundError(f"AGENTS.md not found: {agents_path.as_posix()}")

    reference_memory = (reference_root / ".codex" / "MEMORY.md").read_text(encoding="utf-8")
    manage_script = script_source.read_text(encoding="utf-8")
    updated: list[str] = []

    if _sync_file(memory_path, reference_memory):
        updated.append(memory_path.as_posix())
    updated.extend(_sync_reference_experience(reference_root, workspace))
    agents_text = agents_path.read_text(encoding="utf-8")
    patched_agents = _patch_agents_text(agents_text)
    if _sync_file(agents_path, patched_agents):
        updated.append(agents_path.as_posix())
    if _sync_file(script_target, manage_script):
        updated.append(script_target.as_posix())

    proc = subprocess.run(
        [sys.executable, "scripts/manage_codex_memory.py", "repair-rollups", "--root", "."],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"repair-rollups failed for {workspace.as_posix()}: returncode={proc.returncode}, stderr={proc.stderr}"
        )
    return {
        "workspace": workspace.as_posix(),
        "updated_files": updated,
        "repair_stdout": str(proc.stdout or "").strip(),
    }


def main() -> int:
    args = parse_args()
    script_path = Path(__file__).resolve()
    reference_root = _find_reference_root(script_path)
    repairs: list[dict[str, object]] = []
    for raw in args.workspace:
        repairs.append(
            repair_workspace(
                Path(raw),
                reference_root=reference_root,
                script_source=script_path.parent / "manage_codex_memory.py",
            )
        )
    print(json.dumps({"ok": True, "repairs": repairs}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
