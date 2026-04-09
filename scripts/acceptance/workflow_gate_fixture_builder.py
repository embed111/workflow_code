#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def write_agents_fixture(runtime_root: Path) -> Path:
    workspace_root = runtime_root / "workspace-root"
    (workspace_root / "workflow").mkdir(parents=True, exist_ok=True)
    (workspace_root / "workflow" / "README.md").write_text("fixture\n", encoding="utf-8")
    trainer_dir = workspace_root / "trainer"
    trainer_dir.mkdir(parents=True, exist_ok=True)
    (trainer_dir / "AGENTS.md").write_text(
        "\n".join(
            [
                "# trainer",
                "",
                "## 角色定位",
                "你是训练执行助手。",
                "",
                "## 会话目标",
                "在职责边界内完成用户要求并输出可验证结果。",
                "",
                "## 职责边界",
                "### must",
                "- 先复述任务目标与约束，再给执行步骤。",
                "- 输出必须包含可验证结果与回归检查点。",
                "- 仅在 agent_search_root 范围内进行文件写入。",
                "",
                "### must_not",
                "- 不得执行越界路径写入或高风险破坏性命令。",
                "- 不得跳过失败原因说明与替代方案。",
                "",
                "### preconditions",
                "- 在执行前确认输入上下文完整且目标明确。",
                "- 涉及删除/覆盖时先给风险提示并请求确认。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return workspace_root


def init_code_root_fixture(workspace_root: Path) -> dict[str, str]:
    code_root = workspace_root / "workflow_code"
    code_root.mkdir(parents=True, exist_ok=True)
    (code_root / "README.md").write_text("# workflow_code fixture\n", encoding="utf-8")
    git_bin = shutil.which("git")
    if not git_bin:
        raise RuntimeError("git not found in PATH")
    subprocess.run([git_bin, "init"], cwd=str(code_root), check=True, capture_output=True, text=True)
    subprocess.run([git_bin, "config", "user.email", "gate@example.com"], cwd=str(code_root), check=True, capture_output=True, text=True)
    subprocess.run([git_bin, "config", "user.name", "workflow-gate"], cwd=str(code_root), check=True, capture_output=True, text=True)
    subprocess.run([git_bin, "add", "README.md"], cwd=str(code_root), check=True, capture_output=True, text=True)
    subprocess.run(
        [git_bin, "commit", "-m", "chore: init workflow_code fixture"],
        cwd=str(code_root),
        check=True,
        capture_output=True,
        text=True,
    )
    branch = subprocess.run(
        [git_bin, "branch", "--show-current"],
        cwd=str(code_root),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    commit = subprocess.run(
        [git_bin, "rev-parse", "HEAD"],
        cwd=str(code_root),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {
        "code_root": code_root.as_posix(),
        "default_branch": branch,
        "head_commit": commit,
    }


def write_runtime_config_fixture(runtime_root: Path, workspace_root: Path) -> Path:
    artifact_root = (runtime_root / "artifact-root").resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    pm_root = (workspace_root / "workflow").resolve()
    path = runtime_root / "state" / "runtime-config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "agent_search_root": workspace_root.as_posix(),
                "artifact_root": artifact_root.as_posix(),
                "development_workspace_root": (pm_root / ".repository").as_posix(),
                "agent_runtime_root": (artifact_root / "agent-runtime").as_posix(),
                "show_test_data": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path
