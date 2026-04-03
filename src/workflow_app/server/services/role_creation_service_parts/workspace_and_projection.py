def _workspace_dir_name(role_name: str) -> str:
    raw = _normalize_text(role_name, max_len=60) or "new-agent"
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", raw).strip().strip(".")
    return safe_name or f"new-agent-{uuid.uuid4().hex[:6]}"


def _workspace_path_for_role(search_root: Path, role_name: str) -> Path:
    candidate = search_root / _workspace_dir_name(role_name)
    if not candidate.exists():
        return candidate.resolve(strict=False)
    raise TrainingCenterError(409, "角色工作区已存在，请更换角色名", "role_creation_workspace_exists")


def _role_creation_agent_id(role_name: str) -> str:
    base = re.sub(r"[-._:]{2,}", "-", safe_token(role_name, "", 80)).strip(" -._:")
    if base:
        return base[:80]
    seed = role_name or uuid.uuid4().hex
    return f"agent-{uuid.uuid5(uuid.NAMESPACE_URL, seed).hex[:12]}"


def _render_workspace_agents_md(role_spec: dict[str, Any], *, workspace_name: str) -> str:
    role_name = _role_creation_title_from_spec(role_spec, workspace_name)
    capabilities = _split_items(role_spec.get("core_capabilities") or [], limit=8)
    boundaries = _split_items(role_spec.get("boundaries") or [], limit=8)
    scenarios = _split_items(role_spec.get("applicable_scenarios") or [], limit=8)
    style = _normalize_text(role_spec.get("collaboration_style"), max_len=280) or "默认以结构化、可落地的方式协作。"
    role_goal = _normalize_text(role_spec.get("role_goal"), max_len=280) or "持续完成当前角色目标。"
    return (
        f"# {role_name}\n\n"
        "## Identity\n"
        f"- Workspace: `{workspace_name}`\n"
        f"- Role: `{role_goal}`\n"
        "- Scope: only operate inside the current role workspace.\n\n"
        "## Portrait\n"
        f"capability_summary: {role_goal}\n"
        f"knowledge_scope: {'；'.join(scenarios[:3]) or '待补充'}\n"
        f"skills: {', '.join(capabilities[:6]) or '待补充'}\n"
        f"applicable_scenarios: {'；'.join(scenarios[:4]) or '待补充'}\n"
        "version_notes: 创建中，已完成初始工作区与记忆骨架初始化。\n\n"
        "## Collaboration\n"
        f"- collaboration_style: {style}\n"
        f"- boundaries: {'；'.join(boundaries[:4]) or '待补充'}\n\n"
        "## Startup Read Order\n"
        "1. `AGENTS.md`\n"
        "2. `.codex/SOUL.md`\n"
        "3. `.codex/USER.md`\n"
        "4. `.codex/MEMORY.md`\n"
        "5. `.codex/memory/全局记忆总览.md`\n"
        "6. `.codex/memory/YYYY-MM/记忆总览.md`\n"
        "7. `.codex/memory/YYYY-MM/YYYY-MM-DD.md`\n"
    )


def _render_workspace_soul_md(role_spec: dict[str, Any], *, workspace_name: str, workspace_path: Path) -> str:
    role_name = _role_creation_title_from_spec(role_spec, workspace_name)
    role_goal = _normalize_text(role_spec.get("role_goal"), max_len=280) or "持续完成当前角色目标。"
    return (
        f"# {role_name} Soul\n\n"
        "## Identity\n"
        f"- Workspace: `{workspace_name}`\n"
        f"- Role: {role_name}\n"
        f"- Scope: only operate inside `{workspace_path.as_posix()}`\n\n"
        "## Operating Principles\n"
        "- Execute with minimal disturbance and keep output traceable.\n"
        "- Keep `.codex/*` as memory and internal working notes, not runtime config.\n"
        "- Keep the role profile aligned with the latest accepted `role_spec`.\n"
        f"- Primary goal: {role_goal}\n"
    )


def _render_workspace_user_md(role_spec: dict[str, Any]) -> str:
    style = _normalize_text(role_spec.get("collaboration_style"), max_len=280) or "默认以结构化、可执行的方式协作。"
    scenarios = _split_items(role_spec.get("applicable_scenarios") or [], limit=6)
    return (
        "# Role User Context\n\n"
        "## Stable Preferences\n"
        f"- Preferred collaboration style: {style}\n"
        f"- Preferred scenarios: {'；'.join(scenarios[:4]) or '待补充'}\n"
        "- Prefer concise, actionable delivery with explicit evidence references.\n"
        "- Prefer updating role memory after each meaningful work round.\n"
    )


def _render_memory_global_overview() -> str:
    return "# 全局记忆总览\n\n- 当前角色工作区初始化完成后，闭月总结在这里归档。\n"


def _render_memory_month_overview(month_key: str) -> str:
    return f"# 记忆总览 {month_key}\n\n- 当前月份的已归档日级摘要会收口到这里。\n"


def _render_memory_daily(day_key: str, month_key: str) -> str:
    return (
        f"# 每日记忆 {day_key}\n\n"
        "## Metadata\n"
        f"- month: `{month_key}`\n"
        f"- date: `{day_key}`\n\n"
        "## Entries\n"
    )


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(content or ""), encoding="utf-8")


def _role_creation_asset_root(cfg: Any) -> Path:
    os_mod = __import__("os")
    for env_name in ("WORKFLOW_RUNTIME_DEPLOY_ROOT", "WORKFLOW_RUNTIME_SOURCE_ROOT"):
        raw = str(os_mod.getenv(env_name) or "").strip()
        if not raw:
            continue
        candidate = Path(raw).resolve(strict=False)
        if candidate.exists():
            return candidate
    return Path(cfg.root).resolve(strict=False)


def _sync_workspace_profile(root: Path, session_summary: dict[str, Any], role_spec: dict[str, Any]) -> None:
    workspace_path_text = str(session_summary.get("created_agent_workspace_path") or "").strip()
    if not workspace_path_text:
        return
    workspace_path = Path(workspace_path_text).resolve(strict=False)
    _write_text(
        workspace_path / "AGENTS.md",
        _render_workspace_agents_md(role_spec, workspace_name=workspace_path.name),
    )


def _initialize_role_workspace(cfg: Any, *, session_summary: dict[str, Any], role_spec: dict[str, Any]) -> dict[str, Any]:
    search_root = getattr(cfg, "agent_search_root", None)
    if search_root is None:
        raise TrainingCenterError(409, "agent_search_root 未就绪，不能创建角色工作区", "agent_search_root_not_ready")
    search_root = Path(search_root).resolve(strict=False)
    if not search_root.exists() or not search_root.is_dir():
        raise TrainingCenterError(409, "agent_search_root 不可用", "agent_search_root_invalid")
    role_name = _role_creation_title_from_spec(role_spec, session_summary.get("session_title") or "")
    workspace_path = _workspace_path_for_role(search_root, role_name)
    if not path_in_scope(workspace_path, search_root):
        raise TrainingCenterError(409, "目标角色工作区超出 agent root", "role_creation_workspace_out_of_scope")
    runtime_root = Path(cfg.root).resolve(strict=False)
    asset_root = _role_creation_asset_root(cfg)
    now_dt = now_local()
    month_key = now_dt.strftime("%Y-%m")
    day_key = now_dt.strftime("%Y-%m-%d")
    scripts_dir = workspace_path / "scripts"
    codex_dir = workspace_path / ".codex"
    memory_dir = codex_dir / "memory" / month_key
    logs_dir = workspace_path / "logs" / "runs"
    state_dir = workspace_path / "state"
    workspace_path.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    _write_text(workspace_path / "AGENTS.md", _render_workspace_agents_md(role_spec, workspace_name=workspace_path.name))
    _write_text(
        codex_dir / "SOUL.md",
        _render_workspace_soul_md(role_spec, workspace_name=workspace_path.name, workspace_path=workspace_path),
    )
    _write_text(codex_dir / "USER.md", _render_workspace_user_md(role_spec))
    memory_spec_source = asset_root / ".codex" / "MEMORY.md"
    memory_script_source = asset_root / "scripts" / "manage_codex_memory.py"
    if memory_spec_source.exists():
        _write_text(codex_dir / "MEMORY.md", memory_spec_source.read_text(encoding="utf-8"))
    else:
        _write_text(codex_dir / "MEMORY.md", "# Memory Spec\n")
    if memory_script_source.exists():
        _write_text(scripts_dir / "manage_codex_memory.py", memory_script_source.read_text(encoding="utf-8"))
    else:
        raise TrainingCenterError(500, "manage_codex_memory.py 缺失，不能初始化角色记忆链", "role_creation_memory_script_missing")
    _write_text(codex_dir / "memory" / "全局记忆总览.md", _render_memory_global_overview())
    _write_text(memory_dir / "记忆总览.md", _render_memory_month_overview(month_key))
    _write_text(memory_dir / f"{day_key}.md", _render_memory_daily(day_key, month_key))
    verify_cmd = [sys.executable, "scripts/manage_codex_memory.py", "verify-rollups", "--root", "."]
    verify_result = subprocess.run(
        verify_cmd,
        cwd=workspace_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    verify_stdout = _normalize_text(verify_result.stdout, max_len=4000)
    verify_stderr = _normalize_text(verify_result.stderr, max_len=4000)
    if verify_result.returncode != 0:
        raise TrainingCenterError(
            500,
            "角色记忆链初始化失败",
            "role_creation_memory_verify_failed",
            {
                "returncode": int(verify_result.returncode),
                "stdout": verify_stdout,
            "stderr": verify_stderr,
        },
    )
    evidence_id = f"role-creation-workspace-init-{date_key(now_dt)}-{now_dt.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"
    evidence_path = runtime_root / "logs" / "runs" / f"{evidence_id}.md"
    evidence_body = (
        f"# 角色工作区初始化证据 {role_name}\n\n"
        f"- session_id: {session_summary.get('session_id')}\n"
        f"- workspace_path: {workspace_path.as_posix()}\n"
        f"- role_name: {role_name}\n"
        f"- verify_command: {' '.join(verify_cmd)}\n"
        f"- verify_stdout: {verify_stdout or '-'}\n"
        f"- verify_stderr: {verify_stderr or '-'}\n"
        "- generated_files:\n"
        f"  - {(workspace_path / 'AGENTS.md').as_posix()}\n"
        f"  - {(workspace_path / '.codex' / 'SOUL.md').as_posix()}\n"
        f"  - {(workspace_path / '.codex' / 'USER.md').as_posix()}\n"
        f"  - {(workspace_path / '.codex' / 'MEMORY.md').as_posix()}\n"
        f"  - {(workspace_path / '.codex' / 'memory' / '全局记忆总览.md').as_posix()}\n"
        f"  - {(memory_dir / '记忆总览.md').as_posix()}\n"
        f"  - {(memory_dir / f'{day_key}.md').as_posix()}\n"
        f"  - {(workspace_path / 'scripts' / 'manage_codex_memory.py').as_posix()}\n"
    )
    _write_text(evidence_path, evidence_body)
    agent_id = _role_creation_agent_id(role_name)
    return {
        "workspace_path": workspace_path.as_posix(),
        "workspace_init_status": "completed",
        "workspace_init_ref": relative_to_root(runtime_root, evidence_path),
        "created_agent_id": agent_id,
        "created_agent_name": role_name,
    }


def _upsert_created_agent_registry_row(
    root: Path,
    *,
    agent_id: str,
    agent_name: str,
    workspace_path: str,
    role_spec: dict[str, Any],
    runtime_status: str,
) -> None:
    now_text = _tc_now_text()
    capability_summary = _normalize_text(role_spec.get("role_goal"), max_len=280)
    knowledge_scope = "；".join(_split_items(role_spec.get("applicable_scenarios") or [], limit=4))
    skills = _split_items(role_spec.get("core_capabilities") or [], limit=8)
    scenarios = "；".join(_split_items(role_spec.get("applicable_scenarios") or [], limit=4))
    version_notes = "创建角色流程初始化完成，当前仍处于创建期。"
    conn = connect_db(root)
    try:
        conn.execute(
            """
            INSERT INTO agent_registry (
                agent_id,agent_name,workspace_path,current_version,latest_release_version,bound_release_version,
                lifecycle_state,training_gate_state,parent_agent_id,core_capabilities,capability_summary,knowledge_scope,
                skills_json,applicable_scenarios,version_notes,avatar_uri,vector_icon,git_available,pre_release_state,
                pre_release_reason,pre_release_checked_at,pre_release_git_output,last_release_at,status_tags_json,
                active_role_profile_release_id,active_role_profile_ref,runtime_status,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(agent_id) DO UPDATE SET
                agent_name=excluded.agent_name,
                workspace_path=excluded.workspace_path,
                core_capabilities=excluded.core_capabilities,
                capability_summary=excluded.capability_summary,
                knowledge_scope=excluded.knowledge_scope,
                skills_json=excluded.skills_json,
                applicable_scenarios=excluded.applicable_scenarios,
                version_notes=excluded.version_notes,
                runtime_status=excluded.runtime_status,
                updated_at=excluded.updated_at
            """,
            (
                agent_id,
                agent_name,
                workspace_path,
                "",
                "",
                "",
                "released",
                "trainable",
                "",
                capability_summary,
                capability_summary,
                knowledge_scope,
                _json_dumps(skills),
                scenarios,
                version_notes,
                "",
                "",
                0,
                "unknown",
                "role_creation_initializing",
                now_text,
                "",
                "",
                _json_dumps(["creating"]),
                "",
                "",
                str(runtime_status or "idle").strip().lower() or "idle",
                now_text,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _update_agent_runtime_status(root: Path, *, agent_id: str, runtime_status: str) -> None:
    if not agent_id:
        return
    conn = connect_db(root)
    try:
        conn.execute(
            "UPDATE agent_registry SET runtime_status=?,updated_at=? WHERE agent_id=?",
            (
                str(runtime_status or "idle").strip().lower() or "idle",
                _tc_now_text(),
                agent_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_task_refs(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    ticket_id: str,
    starter_nodes: list[dict[str, Any]],
    created_at: str,
) -> None:
    for item in starter_nodes:
        conn.execute(
            """
            INSERT INTO role_creation_task_refs (
                ref_id,session_id,ticket_id,node_id,stage_key,stage_index,relation_state,close_reason,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(session_id,node_id) DO UPDATE SET
                stage_key=excluded.stage_key,
                stage_index=excluded.stage_index,
                relation_state=excluded.relation_state,
                updated_at=excluded.updated_at
            """,
            (
                _role_creation_task_ref_id(),
                session_id,
                ticket_id,
                str(item.get("node_id") or "").strip(),
                str(item.get("stage_key") or "").strip(),
                int(item.get("stage_index") or 0),
                "active",
                "",
                created_at,
                created_at,
            ),
        )


def _current_agent_runtime_payload(root: Path, agent_id: str) -> dict[str, Any]:
    if not agent_id:
        return {}
    conn = connect_db(root)
    try:
        row = conn.execute(
            """
            SELECT agent_id,agent_name,workspace_path,current_version,latest_release_version,bound_release_version,
                   lifecycle_state,training_gate_state,runtime_status,updated_at
            FROM agent_registry
            WHERE agent_id=?
            LIMIT 1
            """,
            (agent_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {}
    return {
        "agent_id": str(row["agent_id"] or "").strip(),
        "agent_name": str(row["agent_name"] or "").strip(),
        "workspace_path": str(row["workspace_path"] or "").strip(),
        "current_version": str(row["current_version"] or "").strip(),
        "latest_release_version": str(row["latest_release_version"] or "").strip(),
        "bound_release_version": str(row["bound_release_version"] or "").strip(),
        "lifecycle_state": str(row["lifecycle_state"] or "").strip(),
        "training_gate_state": str(row["training_gate_state"] or "").strip(),
        "runtime_status": str(row["runtime_status"] or "idle").strip().lower() or "idle",
        "runtime_status_text": _runtime_status_label(row["runtime_status"]),
        "updated_at": str(row["updated_at"] or "").strip(),
    }


def _role_creation_expected_artifact_name(raw_name: str, *, fallback: str, suffix: str = ".html") -> str:
    name = safe_token(raw_name, fallback, 80).replace("_", "-").strip("-") or fallback
    return name + suffix


def _starter_task_blueprint(role_spec: dict[str, Any], *, agent_id: str, agent_name: str) -> list[dict[str, Any]]:
    role_name = _role_creation_title_from_spec(role_spec, "")
    ts_suffix = uuid.uuid4().hex[:6]
    seed_delivery_plan = dict(role_spec.get("seed_delivery_plan") or {})
    knowledge_asset_plan = dict(role_spec.get("knowledge_asset_plan") or {})
    task_suggestions = [dict(item) for item in list(seed_delivery_plan.get("task_suggestions") or []) if isinstance(item, dict)]
    capability_objects = [dict(item) for item in list(seed_delivery_plan.get("capability_objects") or []) if isinstance(item, dict)]
    knowledge_assets = [dict(item) for item in list(knowledge_asset_plan.get("assets") or []) if isinstance(item, dict)]
    items: list[dict[str, Any]] = []
    previous_node_ids: list[str] = []

    persona_suggestions = [item for item in task_suggestions if str(item.get("stage_key") or "").strip() == "persona_collection"]
    if not persona_suggestions and knowledge_assets:
        for asset in knowledge_assets[:2]:
            topic = str(asset.get("asset_topic") or "").strip()
            asset_type = str(asset.get("asset_type") or "").strip()
            persona_suggestions.append(
                {
                    "task_name": f"沉淀{topic}{asset_type}",
                    "linked_target": topic,
                    "task_type": "knowledge_asset",
                    "priority": str(asset.get("priority") or "P0").strip() or "P0",
                }
            )
    for index, suggestion in enumerate(persona_suggestions[:2], start=1):
        task_name = str(suggestion.get("task_name") or "").strip() or f"沉淀{role_name or '新角色'}知识资产"
        linked_target = str(suggestion.get("linked_target") or "").strip() or role_name or "当前角色"
        node_id = f"rc-{ts_suffix}-persona-{index}"
        items.append(
            {
                "stage_key": "persona_collection",
                "stage_index": 2,
                "node_id": node_id,
                "node_name": task_name,
                "node_goal": f"围绕{linked_target}整理首批资料、方法说明和约束依据，并回传结构化摘要。",
                "expected_artifact": _role_creation_expected_artifact_name(task_name, fallback=f"persona-{index}"),
                "priority": str(suggestion.get("priority") or "P0").strip() or "P0",
                "upstream_node_ids": list(previous_node_ids),
            }
        )
        previous_node_ids = [node_id]

    capability_suggestions = [item for item in task_suggestions if str(item.get("stage_key") or "").strip() == "capability_generation"]
    if not capability_suggestions and capability_objects:
        for capability in capability_objects[:3]:
            capability_name = str(capability.get("capability_name") or "").strip()
            capability_suggestions.append(
                {
                    "task_name": f"生成{capability_name}能力对象",
                    "linked_target": capability_name,
                    "task_type": "capability_object",
                    "priority": "P0",
                }
            )
    for index, suggestion in enumerate(capability_suggestions[:3], start=1):
        task_name = str(suggestion.get("task_name") or "").strip() or f"生成{role_name or '新角色'}能力对象"
        linked_target = str(suggestion.get("linked_target") or "").strip() or role_name or "当前角色"
        node_id = f"rc-{ts_suffix}-capability-{index}"
        items.append(
            {
                "stage_key": "capability_generation",
                "stage_index": 3,
                "node_id": node_id,
                "node_name": task_name,
                "node_goal": f"基于{linked_target}生成首批能力对象、执行模板和最小验收示例。",
                "expected_artifact": _role_creation_expected_artifact_name(task_name, fallback=f"capability-{index}"),
                "priority": str(suggestion.get("priority") or "P1").strip() or "P1",
                "upstream_node_ids": list(previous_node_ids),
            }
        )
        previous_node_ids = [node_id]

    review_target = ""
    if capability_objects:
        review_target = str(capability_objects[0].get("capability_name") or "").strip()
    elif knowledge_assets:
        review_target = str(knowledge_assets[0].get("asset_topic") or "").strip()
    review_name = f"回看{review_target or (role_name or '新角色')}首批交付"
    items.append(
        {
            "stage_key": "review_and_alignment",
            "stage_index": 4,
            "node_id": f"rc-{ts_suffix}-review",
            "node_name": review_name,
            "node_goal": f"整理{review_target or (role_name or '新角色')}的首批能力对象、知识沉淀和回看摘要，便于当前会话验收。",
            "expected_artifact": _role_creation_expected_artifact_name(review_name, fallback="review"),
            "priority": "P1",
            "upstream_node_ids": list(previous_node_ids),
        }
    )
    return [
        {
            "node_id": str(item["node_id"]),
            "node_name": str(item["node_name"]),
            "assigned_agent_id": agent_id,
            "assigned_agent_name": agent_name,
            "node_goal": str(item["node_goal"]),
            "expected_artifact": str(item["expected_artifact"]),
            "priority": str(item["priority"]),
            "upstream_node_ids": list(item["upstream_node_ids"]),
            "stage_key": str(item["stage_key"]),
            "stage_index": int(item["stage_index"]),
        }
        for item in items
    ]


def _stage_anchor_task_ids(task_refs: list[dict[str, Any]], *, stage_key: str) -> list[str]:
    stage_index = int((ROLE_CREATION_STAGE_BY_KEY.get(stage_key) or {}).get("index") or 0)
    current_stage_ids = [
        str(item.get("node_id") or "").strip()
        for item in task_refs
        if str(item.get("stage_key") or "").strip() == stage_key
        and str(item.get("relation_state") or "active").strip().lower() == "active"
    ]
    if current_stage_ids:
        return current_stage_ids[-1:]
    previous_ids = [
        str(item.get("node_id") or "").strip()
        for item in task_refs
        if int(item.get("stage_index") or 0) < stage_index
        and str(item.get("relation_state") or "active").strip().lower() == "active"
    ]
    return previous_ids[-1:]


def _task_payload_from_projection(
    ref_row: dict[str, Any],
    *,
    node_map: dict[str, dict[str, Any]],
    ticket_id: str,
) -> dict[str, Any]:
    node_id = str(ref_row.get("node_id") or "").strip()
    node = dict(node_map.get(node_id) or {})
    artifact_paths = [str(item or "").strip() for item in list(node.get("artifact_paths") or []) if str(item or "").strip()]
    upstream = [dict(item) for item in list(node.get("upstream_nodes") or [])]
    downstream = [dict(item) for item in list(node.get("downstream_nodes") or [])]
    detail_lines: list[str] = []
    if str(node.get("node_goal") or "").strip():
        detail_lines.append(str(node.get("node_goal") or "").strip())
    if artifact_paths:
        detail_lines.append("产物: " + "；".join(artifact_paths[:2]))
    if str(node.get("failure_reason") or "").strip():
        detail_lines.append("失败原因: " + str(node.get("failure_reason") or "").strip())
    if str(node.get("success_reason") or "").strip():
        detail_lines.append("结果: " + str(node.get("success_reason") or "").strip())
    if str(ref_row.get("close_reason") or "").strip():
        detail_lines.append("关闭原因: " + str(ref_row.get("close_reason") or "").strip())
    return {
        "ref_id": str(ref_row.get("ref_id") or "").strip(),
        "ticket_id": ticket_id,
        "node_id": node_id,
        "task_id": node_id,
        "task_name": str(node.get("node_name") or node_id).strip(),
        "status": str(node.get("status") or "pending").strip().lower() or "pending",
        "status_text": str(node.get("status_text") or "").strip() or "待开始",
        "assigned_agent_name": str(node.get("assigned_agent_name") or node.get("assigned_agent_id") or "").strip(),
        "expected_artifact": str(node.get("expected_artifact") or "").strip(),
        "result_ref": str(node.get("result_ref") or "").strip(),
        "success_reason": str(node.get("success_reason") or "").strip(),
        "failure_reason": str(node.get("failure_reason") or "").strip(),
        "artifact_paths": artifact_paths,
        "upstream_nodes": upstream,
        "downstream_nodes": downstream,
        "upstream_labels": [str(item.get("node_name") or item.get("node_id") or "").strip() for item in upstream if str(item.get("node_name") or item.get("node_id") or "").strip()],
        "downstream_labels": [str(item.get("node_name") or item.get("node_id") or "").strip() for item in downstream if str(item.get("node_name") or item.get("node_id") or "").strip()],
        "node_goal": str(node.get("node_goal") or "").strip(),
        "relation_state": str(ref_row.get("relation_state") or "active").strip().lower() or "active",
        "close_reason": str(ref_row.get("close_reason") or "").strip(),
        "created_at": str(node.get("created_at") or ref_row.get("created_at") or "").strip(),
        "updated_at": str(node.get("updated_at") or ref_row.get("updated_at") or "").strip(),
        "detail_lines": detail_lines,
    }


def _auto_stage_from_projection(
    session_summary: dict[str, Any],
    *,
    task_refs: list[dict[str, Any]],
    node_map: dict[str, dict[str, Any]],
) -> str:
    if session_summary.get("status") == "completed":
        return "complete_creation"
    if session_summary.get("status") != "creating":
        return "persona_collection"
    for stage_key in ("persona_collection", "capability_generation", "review_and_alignment"):
        stage_items = [
            item
            for item in task_refs
            if str(item.get("stage_key") or "").strip() == stage_key
            and str(item.get("relation_state") or "active").strip().lower() == "active"
        ]
        if not stage_items:
            continue
        unresolved = False
        for item in stage_items:
            node = node_map.get(str(item.get("node_id") or "").strip()) or {}
            status = str(node.get("status") or "pending").strip().lower()
            if status not in {"succeeded"}:
                unresolved = True
                break
        if unresolved:
            return stage_key
    return "acceptance_confirmation"


def _project_stages(
    session_summary: dict[str, Any],
    *,
    task_refs: list[dict[str, Any]],
    assignment_graph: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    graph_overview = dict((assignment_graph or {}).get("graph") or {})
    ticket_id = str((assignment_graph or {}).get("ticket_id") or session_summary.get("assignment_ticket_id") or "").strip()
    node_rows = [dict(item) for item in list((assignment_graph or {}).get("nodes") or [])]
    node_map = {str(item.get("node_id") or "").strip(): dict(item) for item in node_rows if str(item.get("node_id") or "").strip()}
    auto_stage_key = _auto_stage_from_projection(session_summary, task_refs=task_refs, node_map=node_map)
    preferred_stage_key = str(session_summary.get("current_stage_key") or "").strip().lower()
    if session_summary.get("status") == "completed":
        current_stage_key = "complete_creation"
    elif str(session_summary.get("workspace_init_status") or "").strip() != "completed":
        current_stage_key = "workspace_init"
    elif preferred_stage_key in ROLE_CREATION_STAGE_BY_KEY:
        current_stage_key = preferred_stage_key
    else:
        current_stage_key = auto_stage_key
    current_stage_index = int((ROLE_CREATION_STAGE_BY_KEY.get(current_stage_key) or {}).get("index") or 1)
    stage_rows: list[dict[str, Any]] = []
    archive_total = 0
    active_total = 0
    for stage in ROLE_CREATION_STAGES:
        stage_key = str(stage["key"])
        stage_index = int(stage["index"])
        stage_refs = [item for item in task_refs if str(item.get("stage_key") or "").strip() == stage_key]
        active_items = [
            _task_payload_from_projection(item, node_map=node_map, ticket_id=ticket_id)
            for item in stage_refs
            if str(item.get("relation_state") or "active").strip().lower() != "archived"
        ]
        archived_items = [
            _task_payload_from_projection(item, node_map=node_map, ticket_id=ticket_id)
            for item in stage_refs
            if str(item.get("relation_state") or "active").strip().lower() == "archived"
        ]
        archive_total += len(archived_items)
        active_total += len(active_items)
        if session_summary.get("status") == "completed":
            stage_state = "completed"
        elif stage_index < current_stage_index:
            stage_state = "completed"
        elif stage_index == current_stage_index:
            stage_state = "current"
        else:
            stage_state = "upcoming"
        if stage_key == "workspace_init":
            stage_state = "completed" if session_summary.get("workspace_init_status") == "completed" else "current"
        stage_rows.append(
            {
                "stage_key": stage_key,
                "stage_index": stage_index,
                "title": str(stage["title"]),
                "kind": str(stage["kind"]),
                "state": stage_state,
                "is_current": stage_key == current_stage_key and session_summary.get("status") != "completed",
                "active_tasks": active_items,
                "archived_tasks": archived_items,
                "archive_count": len(archived_items),
                "task_count": len(active_items),
                "analyst_action": {
                    "title": str(stage["analyst_title"]),
                    "description": str(stage["analyst_desc"]),
                    "next_hint": str(stage["next_hint"]),
                },
                "workspace_init": {
                    "status": str(session_summary.get("workspace_init_status") or "").strip(),
                    "status_text": "已完成" if session_summary.get("workspace_init_status") == "completed" else "待执行",
                    "evidence_ref": str(session_summary.get("workspace_init_ref") or "").strip(),
                }
                if stage_key == "workspace_init"
                else {},
            }
        )
    meta = {
        "current_stage_key": current_stage_key,
        "current_stage_index": current_stage_index,
        "current_stage_title": str((ROLE_CREATION_STAGE_BY_KEY.get(current_stage_key) or {}).get("title") or ""),
        "suggested_stage_key": auto_stage_key,
        "suggested_stage_index": int((ROLE_CREATION_STAGE_BY_KEY.get(auto_stage_key) or {}).get("index") or 0),
        "archive_total": archive_total,
        "active_total": active_total,
        "ticket_id": ticket_id,
        "graph_overview": graph_overview,
    }
    return stage_rows, meta


def _role_profile_payload(role_spec: dict[str, Any], missing_fields: list[str], session_summary: dict[str, Any]) -> dict[str, Any]:
    start_gate = dict(role_spec.get("start_gate") or {})
    role_profile_spec = dict(role_spec.get("role_profile_spec") or {})
    capability_package_spec = dict(role_spec.get("capability_package_spec") or {})
    knowledge_asset_plan = dict(role_spec.get("knowledge_asset_plan") or {})
    seed_delivery_plan = dict(role_spec.get("seed_delivery_plan") or {})
    return {
        "role_name": _role_creation_title_from_spec(role_spec, session_summary.get("session_title") or ""),
        "role_goal": _normalize_text(role_spec.get("role_goal"), max_len=280),
        "core_capabilities": _split_items(role_spec.get("core_capabilities") or [], limit=12),
        "boundaries": _split_items(role_spec.get("boundaries") or [], limit=10),
        "applicable_scenarios": _split_items(role_spec.get("applicable_scenarios") or [], limit=10),
        "collaboration_style": _normalize_text(role_spec.get("collaboration_style"), max_len=280),
        "example_assets": list(role_spec.get("example_assets") or []),
        "missing_fields": list(missing_fields),
        "missing_labels": _missing_field_labels(missing_fields),
        "can_start": bool(start_gate.get("can_start")) if start_gate else _session_can_start(role_spec),
        "profile_ready": bool(start_gate.get("profile_ready")),
        "capability_package_ready": bool(start_gate.get("capability_package_ready")),
        "knowledge_asset_ready": bool(start_gate.get("knowledge_asset_ready")),
        "seed_delivery_ready": bool(start_gate.get("seed_delivery_ready")),
        "start_gate": start_gate,
        "start_gate_blockers": [str(item).strip() for item in list(start_gate.get("blockers") or []) if str(item).strip()],
        "role_profile_spec": role_profile_spec,
        "capability_package_spec": capability_package_spec,
        "knowledge_asset_plan": knowledge_asset_plan,
        "seed_delivery_plan": seed_delivery_plan,
        "recent_changes": list(role_spec.get("recent_changes") or []),
        "pending_questions": list(role_spec.get("pending_questions") or []),
    }
