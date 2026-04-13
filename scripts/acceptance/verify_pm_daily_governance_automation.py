#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _write_history_stub(path: Path, date_text: str) -> None:
    _write_text(
        path,
        "\n".join(
            [
                f"# PM 每日执行结果 {date_text}",
                "",
                f"- date: `{date_text}`",
                "- source_tasks: `pm/PM每日任务清单.md`",
                "- status: `completed`",
                "",
                "## system_ops_check",
                f"- executed_at: `{date_text}T08:00:00+08:00`",
                "- conclusion: `继续推进`",
                "- evidence_ref: `stub`",
                "",
                "## learning_prompt",
                "- `workflow(pm)`: stub",
                "- `workflow_devmate`: stub",
                "- `workflow_testmate`: stub",
                "- `workflow_qualitymate`: stub",
                "- `workflow_bugmate`: stub",
                "",
                "## next",
                "- stub",
                "",
            ]
        ),
    )


def _write_learning_report(path: Path, *, date_text: str, agent_id: str) -> None:
    _write_text(
        path,
        "\n".join(
            [
                f"# 学习报告 {agent_id}",
                "",
                f"- date: `{date_text}`",
                f"- agent_id: `{agent_id}`",
                "- learning_task: `stub`",
                "- source_type: `stub`",
                "- source_ref: `stub`",
                "- learned_points: `stub`",
                "- applied_to_project: `stub`",
                "- next_action: `stub`",
                "",
            ]
        ),
    )


def _assert_contains(text: str, needle: str) -> None:
    assert needle in text, {"missing": needle, "text": text}


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    script_path = (repo_root / "scripts" / "bin" / "refresh_pm_daily_governance.py").resolve()

    with tempfile.TemporaryDirectory(prefix="pm-daily-governance-") as tmp_dir:
        shell_root = Path(tmp_dir).resolve() / "workflow-shell"
        pm_root = shell_root / "pm"
        history_root = pm_root / "daily-execution-history"
        learning_root = pm_root / "daily-learning-reports"
        fixtures_root = shell_root / "fixtures"

        _write_text(
            pm_root / "PM每日任务清单.md",
            "\n".join(
                [
                    "# PM每日任务清单",
                    "",
                    "- path: `pm/daily-execution-history/YYYY-MM-DD.md`",
                    "- learning_path: `pm/daily-learning-reports/YYYY-MM-DD/<agent_id>.md`",
                    "",
                ]
            ),
        )

        for date_text in (
            "2026-04-05",
            "2026-04-06",
            "2026-04-07",
            "2026-04-08",
            "2026-04-09",
            "2026-04-10",
            "2026-04-11",
            "2026-04-12",
        ):
            _write_history_stub(history_root / f"{date_text}.md", date_text)
            _write_learning_report(
                learning_root / date_text / "workflow.md",
                date_text=date_text,
                agent_id="workflow",
            )

        target_date = "2026-04-13"
        _write_json(fixtures_root / "healthz.json", {"ok": True, "ts": "2026-04-13T18:20:00+08:00"})
        _write_json(
            fixtures_root / "status.json",
            {
                "ok": True,
                "active_version": "V2",
                "truth_mismatch_count": 0,
                "running_task_count": 1,
                "queued_task_count": 1,
                "workflow_mainline_starvation_state": "mitigated",
                "pm_version_status": {
                    "lane": "功能开发",
                    "baseline": "prod=20260413-172654",
                },
            },
        )
        _write_json(
            fixtures_root / "schedules.json",
            {
                "ok": True,
                "total": 2,
                "items": [
                    {
                        "schedule_name": "[持续迭代] workflow",
                        "next_trigger_text": "2026-04-13T18:18:00+08:00",
                        "last_result_node_id": "node-sti-mainline",
                        "last_result_status_text": "运行中",
                    },
                    {
                        "schedule_name": "pm持续唤醒 - workflow 主线巡检",
                        "next_trigger_text": "2026-04-13T18:20:00+08:00",
                        "last_result_node_id": "node-sti-patrol",
                        "last_result_status_text": "已建单待调度",
                    },
                ],
            },
        )
        _write_json(
            fixtures_root / "runtime-upgrade.json",
            {
                "ok": True,
                "current_version": "20260413-172654",
                "candidate_version": "20260413-172654",
                "candidate_is_newer": False,
                "can_upgrade": False,
                "running_task_count": 1,
            },
        )

        proc = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--shell-root",
                shell_root.as_posix(),
                "--date",
                target_date,
                "--keep-count",
                "7",
                "--healthz-json",
                (fixtures_root / "healthz.json").as_posix(),
                "--status-json",
                (fixtures_root / "status.json").as_posix(),
                "--schedules-json",
                (fixtures_root / "schedules.json").as_posix(),
                "--runtime-upgrade-json",
                (fixtures_root / "runtime-upgrade.json").as_posix(),
            ],
            cwd=repo_root.as_posix(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert proc.returncode == 0, {"stdout": proc.stdout, "stderr": proc.stderr}
        payload = json.loads(proc.stdout)
        assert payload.get("ok") is True, payload
        assert payload.get("daily_history_action") == "created", payload
        assert payload.get("status") == "in_progress", payload
        assert payload.get("missing_learning_reports") == [
            "workflow",
            "workflow_devmate",
            "workflow_testmate",
            "workflow_qualitymate",
            "workflow_bugmate",
        ], payload
        created_history = history_root / f"{target_date}.md"
        assert created_history.exists(), created_history.as_posix()
        created_text = created_history.read_text(encoding="utf-8")
        _assert_contains(created_text, "- auto_generated: `true`")
        _assert_contains(created_text, "## system_ops_check")
        _assert_contains(created_text, "## learning_prompt")
        _assert_contains(created_text, "## next")
        _assert_contains(created_text, "`workflow(pm)`")
        _assert_contains(created_text, "pm/daily-execution-history/2026-04-13.md")

        history_files = sorted(path.name for path in history_root.iterdir() if path.is_file())
        learning_dirs = sorted(path.name for path in learning_root.iterdir() if path.is_dir())
        assert history_files == [
            "2026-04-07.md",
            "2026-04-08.md",
            "2026-04-09.md",
            "2026-04-10.md",
            "2026-04-11.md",
            "2026-04-12.md",
            "2026-04-13.md",
        ], history_files
        assert learning_dirs == [
            "2026-04-07",
            "2026-04-08",
            "2026-04-09",
            "2026-04-10",
            "2026-04-11",
            "2026-04-12",
            "2026-04-13",
        ], learning_dirs

        keep_marker = "\n## manual_notes\n- keep me\n"
        created_history.write_text(created_text + keep_marker, encoding="utf-8")
        second_proc = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--shell-root",
                shell_root.as_posix(),
                "--date",
                target_date,
                "--keep-count",
                "7",
                "--healthz-json",
                (fixtures_root / "healthz.json").as_posix(),
                "--status-json",
                (fixtures_root / "status.json").as_posix(),
                "--schedules-json",
                (fixtures_root / "schedules.json").as_posix(),
                "--runtime-upgrade-json",
                (fixtures_root / "runtime-upgrade.json").as_posix(),
            ],
            cwd=repo_root.as_posix(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert second_proc.returncode == 0, {
            "stdout": second_proc.stdout,
            "stderr": second_proc.stderr,
        }
        second_payload = json.loads(second_proc.stdout)
        assert second_payload.get("daily_history_action") == "kept_existing", second_payload
        assert created_history.read_text(encoding="utf-8").endswith(keep_marker), created_history.read_text(
            encoding="utf-8"
        )

        print(
            json.dumps(
                {
                    "ok": True,
                    "daily_history_path": created_history.as_posix(),
                    "history_files": history_files,
                    "learning_dirs": learning_dirs,
                    "first_run": payload,
                    "second_run": second_payload,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
