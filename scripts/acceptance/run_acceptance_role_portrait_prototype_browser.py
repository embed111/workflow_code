#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_release_review_acceptance_support import (
    api_file,
    call,
    capture_probe,
    dump_sql,
    ensure,
    find_agent,
    find_browser,
    run_cmd,
    seed_release_history_refs,
    write_agent_workspace,
    write_codex_stub,
    write_json,
)


PNG_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO0B7lQAAAAASUVORK5CYII="
EXPECTED_PORTRAIT_KEYS = [
    "intro",
    "what_i_can_do",
    "full_capability_inventory",
    "knowledge_scope",
    "agent_skills",
    "applicable_scenarios",
    "version_notes",
]
EXPECTED_PORTRAIT_LABELS = [
    "我是",
    "我当前能做什么",
    "全量能力清单",
    "角色知识范围",
    "Agent Skills",
    "适用场景",
    "版本说明",
]


def add_local_skill(workspace: Path, skill_name: str, summary: str) -> None:
    skill_dir = workspace / ".codex" / "skills" / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {skill_name}",
                f"description: {summary}",
                "---",
                "",
                f"# {skill_name}",
                "",
                summary,
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def clear_pre_release_note(workspace: Path) -> None:
    note_path = workspace / "WIP.md"
    if note_path.exists():
        note_path.unlink()


def clear_release_note_file(workspace: Path) -> None:
    note_path = workspace / ".release-note-v1.0.0.md"
    if note_path.exists():
        note_path.unlink()


def commit_local_skills(workspace: Path, message: str) -> None:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=workspace.as_posix(),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if status.returncode != 0:
        raise RuntimeError(f"git status failed for {workspace.as_posix()}: {status.stderr}")
    if not str(status.stdout or "").strip():
        return
    run_cmd(["git", "add", ".codex/skills"], workspace)
    run_cmd(["git", "commit", "-m", message], workspace)


def seed_role_profile_report_assets(root: Path, agent_name: str, version_label: str) -> dict[str, str]:
    seed_dir = root / "logs" / "release-review" / "prototype-role-portrait" / agent_name / version_label
    report_path = seed_dir / "parsed-result.json"
    capability_snapshot_path = seed_dir / "capability-snapshot.json"
    public_profile_path = seed_dir / "public-profile.md"
    report_payload = {
        "target_version": version_label,
        "current_workspace_ref": f"{agent_name}-{version_label}-workspace",
        "previous_release_version": "",
        "first_person_summary": f"我是 {agent_name}，我当前负责正式版本的角色发布治理与画像说明。",
        "full_capability_inventory": [
            "我当前可以输出正式发布版本的第一人称角色说明。",
            "我当前可以整理发布治理、证据归档与角色详情展示来源。",
            "我当前可以把正式版本能力边界整理成对外可读的角色画像。",
        ],
        "knowledge_scope": "我当前覆盖发布治理、角色画像整理、版本说明与验收证据归档。",
        "agent_skills": ["release-governance", "historical-report-binding"],
        "applicable_scenarios": ["正式版本说明", "角色详情查看", "发布治理回顾"],
        "change_summary": "我本次补齐了正式版本角色画像的对外说明与展示来源。",
        "warnings": [],
    }
    snapshot_payload = {
        "target_version": version_label,
        "first_person_summary": report_payload["first_person_summary"],
        "what_i_can_do": [
            "我当前可以快速说明该角色当前正式版本能做什么。",
            "我当前可以补齐发布治理与角色画像的展示依据。",
            "我当前可以输出对外可读的版本说明。",
        ],
        "full_capability_inventory": report_payload["full_capability_inventory"],
        "knowledge_scope": report_payload["knowledge_scope"],
        "agent_skills": report_payload["agent_skills"],
        "applicable_scenarios": report_payload["applicable_scenarios"],
        "version_notes": "本次正式版本以角色画像整理与发布说明收口为主。",
    }
    write_json(report_path, report_payload)
    write_json(capability_snapshot_path, snapshot_payload)
    public_profile_path.parent.mkdir(parents=True, exist_ok=True)
    public_profile_path.write_text(
        "\n".join(
            [
                f"# {agent_name} {version_label}",
                "",
                report_payload["first_person_summary"],
                "",
                "## 我当前能做什么",
                *[f"- {item}" for item in snapshot_payload["what_i_can_do"]],
                "",
                "## 版本说明",
                snapshot_payload["version_notes"],
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "release_source_ref": report_path.resolve(strict=False).as_posix(),
        "public_profile_ref": public_profile_path.resolve(strict=False).as_posix(),
        "capability_snapshot_ref": capability_snapshot_path.resolve(strict=False).as_posix(),
    }


def check_probe_common(probe: dict[str, Any], *, expected_source: str) -> list[str]:
    errors: list[str] = []
    if str(probe.get("module") or "").strip() != "agents":
        errors.append("module_not_agents")
    if str(probe.get("role_profile_source") or "").strip() != expected_source:
        errors.append(f"unexpected_role_profile_source:{probe.get('role_profile_source')}")
    if list(probe.get("portrait_section_keys") or []) != EXPECTED_PORTRAIT_KEYS:
        errors.append(f"unexpected_portrait_keys:{probe.get('portrait_section_keys')}")
    if list(probe.get("portrait_section_labels") or []) != EXPECTED_PORTRAIT_LABELS:
        errors.append(f"unexpected_portrait_labels:{probe.get('portrait_section_labels')}")
    if not bool(probe.get("portrait_is_single_column")):
        errors.append("portrait_not_single_column")
    if bool(probe.get("portrait_has_source_section")):
        errors.append("portrait_has_source_section")
    if not bool(probe.get("portrait_meta_contains_source")):
        errors.append("portrait_meta_missing_source")
    if int(probe.get("avatar_preview_count") or 0) != 1:
        errors.append(f"avatar_preview_count:{probe.get('avatar_preview_count')}")
    if int(probe.get("avatar_trigger_count") or 0) != 1:
        errors.append(f"avatar_trigger_count:{probe.get('avatar_trigger_count')}")
    if int(probe.get("avatar_file_input_count") or 0) != 1:
        errors.append(f"avatar_file_input_count:{probe.get('avatar_file_input_count')}")
    if not bool(probe.get("portrait_release_history_title_visible")):
        errors.append("release_history_title_missing")
    if not str(probe.get("role_profile_first_person_summary") or "").strip().startswith("我"):
        errors.append("first_person_summary_missing")
    return errors


def wait_for_server(base_url: str, proc: subprocess.Popen[str], timeout_s: int = 60) -> None:
    deadline = time.time() + max(5, int(timeout_s))
    last_error = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited early: code={proc.returncode}")
        try:
            status, payload = call(base_url, "GET", "/healthz")
            if status == 200 and bool(payload.get("ok")):
                return
            last_error = f"status={status} payload={payload}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"healthz timeout: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="browser acceptance for role portrait prototype alignment")
    parser.add_argument("--root", default=".", help="repo root")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8164)
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    evidence_root = (repo_root / ".test" / "evidence" / "role-portrait-prototype-browser").resolve()
    runtime_root = (repo_root / ".test" / "runtime" / "role-portrait-prototype-browser").resolve()
    if evidence_root.exists():
        shutil.rmtree(evidence_root, ignore_errors=True)
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    for path in [evidence_root / "api", evidence_root / "db", evidence_root / "screenshots", runtime_root]:
        path.mkdir(parents=True, exist_ok=True)

    workspace_root = runtime_root / "workspace-root"
    (workspace_root / "workflow").mkdir(parents=True, exist_ok=True)
    (workspace_root / "workflow" / "README.md").write_text("fixture\n", encoding="utf-8")

    report_workspace = write_agent_workspace(
        workspace_root,
        "rp-report-agent",
        persist_git_identity=True,
        pre_release_note="report agent pending change",
    )
    fallback_workspace = write_agent_workspace(
        workspace_root,
        "rp-fallback-agent",
        persist_git_identity=True,
        pre_release_note="fallback agent pending change",
    )
    pre_release_workspace = write_agent_workspace(
        workspace_root,
        "rp-pre-release-agent",
        persist_git_identity=True,
        pre_release_note="pre release pending change",
    )
    add_local_skill(report_workspace, "historical-report-binding", "Bind the latest formal release report into role portrait display.")
    add_local_skill(fallback_workspace, "evidence-packaging", "Keep published evidence traceable when report binding is missing.")
    add_local_skill(pre_release_workspace, "evidence-packaging", "Keep pre-release evidence organized before manual publish.")
    commit_local_skills(report_workspace, "add local portrait skills")
    commit_local_skills(fallback_workspace, "add local portrait skills")
    commit_local_skills(pre_release_workspace, "add local portrait skills")
    clear_release_note_file(report_workspace)
    clear_release_note_file(fallback_workspace)
    clear_release_note_file(pre_release_workspace)
    clear_pre_release_note(report_workspace)
    clear_pre_release_note(fallback_workspace)

    db_path = runtime_root / "state" / "workflow.db"
    stub_bin = runtime_root / "bin"
    write_codex_stub(stub_bin)

    base_url = f"http://{args.host}:{args.port}"
    server_stdout = evidence_root / "server.stdout.log"
    server_stderr = evidence_root / "server.stderr.log"
    server_env = os.environ.copy()
    server_env["PATH"] = stub_bin.as_posix() + os.pathsep + server_env.get("PATH", "")
    proc = subprocess.Popen(
        [
            sys.executable,
            str((repo_root / "scripts" / "workflow_web_server.py").resolve()),
            "--root",
            runtime_root.as_posix(),
            "--entry-script",
            str((repo_root / "scripts" / "workflow_entry_cli.py").resolve()),
            "--host",
            args.host,
            "--port",
            str(args.port),
        ],
        cwd=repo_root.as_posix(),
        stdout=server_stdout.open("w", encoding="utf-8"),
        stderr=server_stderr.open("w", encoding="utf-8"),
        text=True,
        env=server_env,
    )

    try:
        wait_for_server(base_url, proc)
        browser = find_browser()
        api_dir = evidence_root / "api"
        db_dir = evidence_root / "db"

        st_root, body_root = call(
            base_url,
            "POST",
            "/api/config/agent-search-root",
            {"agent_search_root": workspace_root.as_posix()},
        )
        api_root = api_file(
            api_dir,
            "switch_root",
            "POST",
            "/api/config/agent-search-root",
            {"agent_search_root": workspace_root.as_posix()},
            st_root,
            body_root,
        )
        ensure(st_root == 200 and bool(body_root.get("ok")), f"switch root failed: {st_root} {body_root}")

        st_agents0, body_agents0 = call(base_url, "GET", "/api/training/agents")
        api_agents0 = api_file(api_dir, "agents_initial", "GET", "/api/training/agents", None, st_agents0, body_agents0)
        ensure(st_agents0 == 200, f"list agents failed: {st_agents0} {body_agents0}")
        items0 = list(body_agents0.get("items") or [])
        report_agent_id = str(find_agent(items0, "rp-report-agent").get("agent_id") or "")
        fallback_agent_id = str(find_agent(items0, "rp-fallback-agent").get("agent_id") or "")
        pre_release_agent_id = str(find_agent(items0, "rp-pre-release-agent").get("agent_id") or "")

        seed_release_history_refs(
            db_path,
            report_agent_id,
            "v1.0.0",
            seed_role_profile_report_assets(runtime_root, "rp-report-agent", "v1.0.0"),
        )

        st_agents1, body_agents1 = call(base_url, "GET", "/api/training/agents")
        api_agents1 = api_file(api_dir, "agents_after_report_seed", "GET", "/api/training/agents", None, st_agents1, body_agents1)
        ensure(st_agents1 == 200, f"list agents after seed failed: {st_agents1} {body_agents1}")

        st_report_releases, body_report_releases = call(
            base_url,
            "GET",
            f"/api/training/agents/{report_agent_id}/releases?page=1&page_size=20",
        )
        api_report_releases = api_file(
            api_dir,
            "report_agent_releases",
            "GET",
            f"/api/training/agents/{report_agent_id}/releases?page=1&page_size=20",
            None,
            st_report_releases,
            body_report_releases,
        )
        ensure(st_report_releases == 200, f"report releases failed: {st_report_releases} {body_report_releases}")

        st_fallback_releases, body_fallback_releases = call(
            base_url,
            "GET",
            f"/api/training/agents/{fallback_agent_id}/releases?page=1&page_size=20",
        )
        api_fallback_releases = api_file(
            api_dir,
            "fallback_agent_releases",
            "GET",
            f"/api/training/agents/{fallback_agent_id}/releases?page=1&page_size=20",
            None,
            st_fallback_releases,
            body_fallback_releases,
        )
        ensure(st_fallback_releases == 200, f"fallback releases failed: {st_fallback_releases} {body_fallback_releases}")

        report_shot, report_probe_path, report_probe = capture_probe(
            browser,
            base_url,
            evidence_root,
            "single_column_latest_release_report",
            "ac_rp_proto_report",
            {"tc_probe_agent": "rp-report-agent"},
        )
        fallback_shot, fallback_probe_path, fallback_probe = capture_probe(
            browser,
            base_url,
            evidence_root,
            "single_column_structured_fallback",
            "ac_rp_proto_fallback",
            {"tc_probe_agent": "rp-fallback-agent"},
        )
        pre_release_shot, pre_release_probe_path, pre_release_probe = capture_probe(
            browser,
            base_url,
            evidence_root,
            "pre_release_state",
            "ac_rp_proto_pre_release",
            {"tc_probe_agent": "rp-pre-release-agent"},
        )

        success_payload = {
            "upload_name": "role-avatar.png",
            "upload_content_type": "image/png",
            "upload_base64": PNG_BASE64,
            "operator": "rp-probe",
        }
        st_avatar_ok, body_avatar_ok = call(
            base_url,
            "POST",
            f"/api/training/agents/{report_agent_id}/avatar",
            success_payload,
        )
        api_avatar_ok = api_file(
            api_dir,
            "avatar_upload_success",
            "POST",
            f"/api/training/agents/{report_agent_id}/avatar",
            success_payload,
            st_avatar_ok,
            body_avatar_ok,
        )
        ensure(st_avatar_ok == 200 and bool(body_avatar_ok.get("avatar_uri")), f"avatar upload failed: {st_avatar_ok} {body_avatar_ok}")

        avatar_success_shot, avatar_success_probe_path, avatar_success_probe = capture_probe(
            browser,
            base_url,
            evidence_root,
            "avatar_upload_success",
            "ac_rp_proto_avatar_success",
            {"tc_probe_agent": "rp-report-agent"},
        )

        fail_payload = {
            "upload_name": "role-avatar.txt",
            "upload_content_type": "text/plain",
            "upload_base64": PNG_BASE64,
            "operator": "rp-probe",
        }
        st_avatar_fail, body_avatar_fail = call(
            base_url,
            "POST",
            f"/api/training/agents/{report_agent_id}/avatar",
            fail_payload,
        )
        api_avatar_fail = api_file(
            api_dir,
            "avatar_upload_fail",
            "POST",
            f"/api/training/agents/{report_agent_id}/avatar",
            fail_payload,
            st_avatar_fail,
            body_avatar_fail,
        )
        ensure(st_avatar_fail == 400, f"avatar invalid upload should fail: {st_avatar_fail} {body_avatar_fail}")

        avatar_fail_shot, avatar_fail_probe_path, avatar_fail_probe = capture_probe(
            browser,
            base_url,
            evidence_root,
            "avatar_upload_fail_fallback",
            "ac_rp_proto_avatar_fail",
            {"tc_probe_agent": "rp-report-agent"},
        )

        dump_sql(
            db_path,
            "SELECT agent_id,agent_name,lifecycle_state,latest_release_version,bound_release_version,active_role_profile_ref,active_role_profile_release_id,avatar_uri FROM agent_registry ORDER BY agent_name",
            (),
            db_dir / "agent_registry.db.json",
        )
        dump_sql(
            db_path,
            "SELECT release_id,agent_id,version_label,classification,release_source_ref,public_profile_ref,capability_snapshot_ref FROM agent_release_history ORDER BY agent_id,version_label",
            (),
            db_dir / "agent_release_history.db.json",
        )

        report_errors = check_probe_common(report_probe, expected_source="latest_release_report")
        fallback_errors = check_probe_common(fallback_probe, expected_source="structured_fields_fallback")
        pre_release_errors = check_probe_common(pre_release_probe, expected_source="structured_fields_fallback")
        avatar_success_errors = check_probe_common(avatar_success_probe, expected_source="latest_release_report")
        avatar_fail_errors = check_probe_common(avatar_fail_probe, expected_source="latest_release_report")

        if str(report_probe.get("lifecycle_state") or "").strip().lower() != "released":
            report_errors.append(f"report_lifecycle:{report_probe.get('lifecycle_state')}")
        if str(fallback_probe.get("lifecycle_state") or "").strip().lower() != "released":
            fallback_errors.append(f"fallback_lifecycle:{fallback_probe.get('lifecycle_state')}")
        if str(pre_release_probe.get("lifecycle_state") or "").strip().lower() != "pre_release":
            pre_release_errors.append(f"pre_release_lifecycle:{pre_release_probe.get('lifecycle_state')}")
        if int(avatar_success_probe.get("avatar_image_count") or 0) != 1:
            avatar_success_errors.append(f"avatar_image_count:{avatar_success_probe.get('avatar_image_count')}")
        if int(avatar_success_probe.get("avatar_fallback_svg_count") or 0) != 0:
            avatar_success_errors.append(f"avatar_fallback_svg_count:{avatar_success_probe.get('avatar_fallback_svg_count')}")
        if int(avatar_fail_probe.get("avatar_image_count") or 0) != 1:
            avatar_fail_errors.append(f"avatar_fail_image_count:{avatar_fail_probe.get('avatar_image_count')}")
        if str(body_avatar_fail.get("code") or "").strip() not in {
            "avatar_type_not_allowed",
            "avatar_content_type_not_allowed",
            "avatar_content_mismatch",
            "avatar_extension_mismatch",
        }:
            avatar_fail_errors.append(f"avatar_fail_code:{body_avatar_fail.get('code')}")

        checks = {
            "single_column_latest_release_report": {
                "pass": not report_errors,
                "errors": report_errors,
                "screenshot": report_shot,
                "probe": report_probe_path,
            },
            "single_column_structured_fallback": {
                "pass": not fallback_errors,
                "errors": fallback_errors,
                "screenshot": fallback_shot,
                "probe": fallback_probe_path,
            },
            "pre_release_state": {
                "pass": not pre_release_errors,
                "errors": pre_release_errors,
                "screenshot": pre_release_shot,
                "probe": pre_release_probe_path,
            },
            "avatar_upload_success": {
                "pass": not avatar_success_errors,
                "errors": avatar_success_errors,
                "screenshot": avatar_success_shot,
                "probe": avatar_success_probe_path,
            },
            "avatar_upload_fail_fallback": {
                "pass": not avatar_fail_errors,
                "errors": avatar_fail_errors,
                "screenshot": avatar_fail_shot,
                "probe": avatar_fail_probe_path,
            },
        }

        prototype_refs = {
            "single_column": (repo_root / "docs" / "workflow" / "prototypes" / "角色画像发布格式与预发布判定" / "角色画像发布格式与预发布判定参考图-单栏画像.png").resolve(strict=False).as_posix(),
            "layout_detail": (repo_root / "docs" / "workflow" / "prototypes" / "角色画像发布格式与预发布判定" / "角色画像发布格式与预发布判定参考图-单栏布局细节.png").resolve(strict=False).as_posix(),
            "pre_release": (repo_root / "docs" / "workflow" / "prototypes" / "角色画像发布格式与预发布判定" / "角色画像发布格式与预发布判定参考图-预发布态.png").resolve(strict=False).as_posix(),
            "avatar_success": (repo_root / "docs" / "workflow" / "prototypes" / "角色画像发布格式与预发布判定" / "角色画像发布格式与预发布判定参考图-头像上传成功.png").resolve(strict=False).as_posix(),
            "avatar_fail": (repo_root / "docs" / "workflow" / "prototypes" / "角色画像发布格式与预发布判定" / "角色画像发布格式与预发布判定参考图-头像上传失败回退.png").resolve(strict=False).as_posix(),
        }

        summary = {
            "generated_at": datetime.now().isoformat(),
            "repo_root": repo_root.as_posix(),
            "runtime_root": runtime_root.as_posix(),
            "workspace_root": workspace_root.as_posix(),
            "db_path": db_path.as_posix(),
            "prototype_refs": prototype_refs,
            "checks": checks,
            "api_refs": {
                "switch_root": api_root,
                "agents_initial": api_agents0,
                "agents_after_report_seed": api_agents1,
                "report_agent_releases": api_report_releases,
                "fallback_agent_releases": api_fallback_releases,
                "avatar_upload_success": api_avatar_ok,
                "avatar_upload_fail": api_avatar_fail,
            },
            "db_refs": {
                "agent_registry": (db_dir / "agent_registry.db.json").as_posix(),
                "agent_release_history": (db_dir / "agent_release_history.db.json").as_posix(),
            },
        }
        write_json(evidence_root / "summary.json", summary)

        report_lines = [
            "# Role Portrait Prototype Browser Acceptance",
            "",
            f"- generated_at: `{summary['generated_at']}`",
            f"- runtime_root: `{runtime_root.as_posix()}`",
            f"- workspace_root: `{workspace_root.as_posix()}`",
            f"- server_stdout: `{server_stdout.as_posix()}`",
            f"- server_stderr: `{server_stderr.as_posix()}`",
            "",
            "## Prototype Refs",
            f"- 单栏画像：`{prototype_refs['single_column']}`",
            f"- 单栏布局细节：`{prototype_refs['layout_detail']}`",
            f"- 预发布态：`{prototype_refs['pre_release']}`",
            f"- 头像上传成功：`{prototype_refs['avatar_success']}`",
            f"- 头像上传失败回退：`{prototype_refs['avatar_fail']}`",
            "",
            "## Check Results",
        ]
        for check_name, row in checks.items():
            report_lines.append(f"### {check_name}")
            report_lines.append(f"- pass: `{bool(row['pass'])}`")
            report_lines.append(f"- screenshot: `{row['screenshot']}`")
            report_lines.append(f"- probe: `{row['probe']}`")
            report_lines.append(f"- errors: `{json.dumps(row['errors'], ensure_ascii=False)}`")
            report_lines.append("")
        report_lines.extend(
            [
                "## API Refs",
                f"- switch_root: `{api_root}`",
                f"- agents_initial: `{api_agents0}`",
                f"- agents_after_report_seed: `{api_agents1}`",
                f"- report_agent_releases: `{api_report_releases}`",
                f"- fallback_agent_releases: `{api_fallback_releases}`",
                f"- avatar_upload_success: `{api_avatar_ok}`",
                f"- avatar_upload_fail: `{api_avatar_fail}`",
                "",
                "## DB Refs",
                f"- agent_registry: `{(db_dir / 'agent_registry.db.json').as_posix()}`",
                f"- agent_release_history: `{(db_dir / 'agent_release_history.db.json').as_posix()}`",
            ]
        )
        (evidence_root / "acceptance-report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

        print((evidence_root / "acceptance-report.md").as_posix())
        return 0 if all(bool(row.get("pass")) for row in checks.values()) else 1
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
