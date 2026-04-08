#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import timedelta
from pathlib import Path


def _create_cfg(root: Path, agent_root: Path):
    return type(
        "Cfg",
        (),
        {
            "root": root,
            "agent_search_root": agent_root,
        },
    )()


def _seed_placeholder_workspace(workspace: Path, *, target_date, month_key: str, yesterday_key: str) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "AGENTS.md").write_text(
        "# repairmate\n\n"
        "## Startup Read Order\n"
        "1. `AGENTS.md`\n"
        "2. `.codex/SOUL.md`\n"
        "3. `.codex/USER.md`\n"
        "4. `.codex/MEMORY.md`\n"
        "5. `.codex/memory/全局记忆总览.md`\n"
        "6. `.codex/memory/YYYY-MM/记忆总览.md`\n"
        "7. `.codex/memory/YYYY-MM/YYYY-MM-DD.md`\n",
        encoding="utf-8",
    )
    codex_dir = workspace / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    (codex_dir / "SOUL.md").write_text("# SOUL\n", encoding="utf-8")
    (codex_dir / "USER.md").write_text("# USER\n", encoding="utf-8")
    (codex_dir / "MEMORY.md").write_text("# Memory Spec\n", encoding="utf-8")
    month_dir = codex_dir / "memory" / month_key
    month_dir.mkdir(parents=True, exist_ok=True)
    (codex_dir / "memory" / "全局记忆总览.md").write_text(
        "# 全局记忆总览\n\n- 当前角色工作区初始化完成后，闭月总结在这里归档。\n",
        encoding="utf-8",
    )
    (month_dir / "记忆总览.md").write_text(
        f"# 记忆总览 {month_key}\n\n- 当前月份的已归档日级摘要会收口到这里。\n",
        encoding="utf-8",
    )
    (month_dir / f"{yesterday_key}.md").write_text(
        f"# 每日记忆 {yesterday_key}\n\n"
        "## Entries\n\n"
        f"### {yesterday_key}T09:00:00+08:00 | 修复占位\n"
        "- topic: 历史占位修复\n"
        "- context: 为了验证 repair-rollups 会把昨日日记归档到月度总览\n"
        "- actions:\n"
        "  - 我补了一条测试日记\n"
        "- decisions:\n"
        "  - 期待 repair-rollups 自动补齐月度归档\n"
        "- validation:\n"
        "  - 占位 workspace 已初始化\n"
        "- artifacts:\n"
        "  - .codex/memory\n"
        "- next:\n"
        "  - 运行 repair-rollups\n",
        encoding="utf-8",
    )
    (month_dir / f"{target_date.isoformat()}.md").write_text(
        f"# 每日记忆 {target_date.isoformat()}\n\n## Entries\n",
        encoding="utf-8",
    )


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    src_root = repo_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws
    from workflow_app.server.services import role_creation_service as rc

    rc.bind_runtime_symbols(ws.__dict__)

    runtime_root = (repo_root / ".test" / "runtime-role-workspace-memory-governance").resolve()
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    agent_root = runtime_root / "agents"
    agent_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo_root / "scripts" / "manage_codex_memory.py", runtime_root / "scripts" / "manage_codex_memory.py")

    cfg = _create_cfg(runtime_root, agent_root)
    session_summary = {
        "session_id": "tc-memory-governance",
        "session_title": "memory-governance-agent",
    }
    role_spec = {
        "role_name": "memory-governance-agent",
        "role_goal": "沉淀自己的工作记忆并持续执行日切月切检查",
        "collaboration_style": "默认以第一人称、结构化、可复盘的方式协作",
        "applicable_scenarios": ["连续迭代", "日切归档", "月切归档"],
        "core_capabilities": ["记忆维护", "归档检查", "结构化记录"],
        "boundaries": ["不把记忆文件当运行态", "不跳过归档检查"],
    }
    init_result = rc._initialize_role_workspace(
        cfg,
        session_summary=session_summary,
        role_spec=role_spec,
    )
    created_workspace = Path(str(init_result.get("workspace_path") or "")).resolve(strict=False)
    agents_text = (created_workspace / "AGENTS.md").read_text(encoding="utf-8")
    memory_text = (created_workspace / ".codex" / "MEMORY.md").read_text(encoding="utf-8")
    experience_index = (created_workspace / ".codex" / "experience" / "index.md").read_text(encoding="utf-8")
    assert "## Memory Governance" in agents_text, agents_text
    assert ".codex/experience/index.md" in agents_text, agents_text
    assert "repair-rollups" in memory_text, memory_text
    assert ".codex/experience/index.md" in memory_text, memory_text
    assert "# Memory Spec" not in memory_text, memory_text
    assert "## 必读经验" in experience_index, experience_index

    target_date = rc.now_local().date()
    month_key = target_date.strftime("%Y-%m")
    yesterday_key = (target_date - timedelta(days=1)).isoformat()
    repair_workspace = agent_root / "repairmate"
    _seed_placeholder_workspace(repair_workspace, target_date=target_date, month_key=month_key, yesterday_key=yesterday_key)

    repair_proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "repair_role_workspace_memory.py"),
            "--workspace",
            repair_workspace.as_posix(),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert repair_proc.returncode == 0, repair_proc.stderr
    repaired_agents = (repair_workspace / "AGENTS.md").read_text(encoding="utf-8")
    repaired_memory = (repair_workspace / ".codex" / "MEMORY.md").read_text(encoding="utf-8")
    repaired_experience_index = (repair_workspace / ".codex" / "experience" / "index.md").read_text(encoding="utf-8")
    repaired_month = (repair_workspace / ".codex" / "memory" / month_key / "记忆总览.md").read_text(encoding="utf-8")
    assert "## Memory Governance" in repaired_agents, repaired_agents
    assert ".codex/experience/index.md" in repaired_agents, repaired_agents
    assert "## 归档检查" in repaired_memory, repaired_memory
    assert ".codex/experience/index.md" in repaired_memory, repaired_memory
    assert "## 先读这里" in repaired_experience_index, repaired_experience_index
    assert f"### {yesterday_key}" in repaired_month, repaired_month

    print(
        json.dumps(
            {
                "ok": True,
                "created_workspace": created_workspace.as_posix(),
                "repair_workspace": repair_workspace.as_posix(),
                "repair_stdout": str(repair_proc.stdout or "").strip(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
