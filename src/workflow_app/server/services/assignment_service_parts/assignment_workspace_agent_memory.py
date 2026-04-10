from __future__ import annotations


def _current_assignment_agent_search_root(root: Path) -> Path | None:
    try:
        runtime_cfg = load_runtime_config(root)
    except Exception:
        runtime_cfg = {}
    raw = str((runtime_cfg or {}).get("agent_search_root") or "").strip()
    if not raw:
        return None
    try:
        return Path(raw).resolve(strict=False)
    except Exception:
        return None


def _upsert_assignment_agent_registry_row(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    agent_name: str,
    workspace_path: Path,
) -> None:
    now_text = iso_ts(now_local())
    conn.execute(
        """
        INSERT INTO agent_registry (agent_id,agent_name,workspace_path,updated_at)
        VALUES (?,?,?,?)
        ON CONFLICT(agent_id) DO UPDATE SET
            agent_name=excluded.agent_name,
            workspace_path=excluded.workspace_path,
            updated_at=excluded.updated_at
        """,
        (
            str(agent_id or "").strip(),
            str(agent_name or agent_id or "").strip(),
            workspace_path.as_posix(),
            now_text,
        ),
    )


def _discover_assignment_agent_workspace_path(root: Path, *, agent_id: str) -> tuple[str, Path] | None:
    search_root = _current_assignment_agent_search_root(root)
    discover_agents_fn = globals().get("discover_agents")
    if not isinstance(search_root, Path) or not callable(discover_agents_fn):
        return None
    try:
        rows = discover_agents_fn(
            search_root,
            cache_root=root,
            analyze_policy=False,
            target_agent_name=str(agent_id or "").strip(),
        )
    except TypeError:
        rows = discover_agents_fn(search_root, cache_root=root, analyze_policy=False)
    except Exception:
        return None
    for item in list(rows or []):
        agent_name = str((item or {}).get("agent_name") or "").strip()
        if agent_name.lower() != str(agent_id or "").strip().lower():
            continue
        agents_md_path = Path(str((item or {}).get("agents_md_path") or "")).resolve(strict=False)
        workspace_path = agents_md_path.parent.resolve(strict=False)
        if not workspace_path.exists() or not workspace_path.is_dir():
            continue
        if not path_in_scope(workspace_path, search_root):
            continue
        return agent_name, workspace_path
    return None


def _assignment_workspace_uses_codex_memory(workspace_path: Path) -> bool:
    memory_root = workspace_path / ".codex" / "memory"
    if memory_root.exists():
        return True
    agents_path = workspace_path / "AGENTS.md"
    if not agents_path.exists() or not agents_path.is_file():
        return False
    try:
        agents_text = agents_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    normalized = str(agents_text or "").replace("\\", "/").lower()
    return ".codex/memory/" in normalized


def _assignment_memory_spec_template() -> str:
    return (
        "# 工作区记忆规范\n\n"
        "## 目的\n"
        "- 本文件是当前工作区的顶层记忆规范。\n"
        "- 具体轮次总结不要写在这里，只写入每日日记文件。\n"
        "- 把 `.codex/` 视为 agent 记忆和内部指导，不得当成产品运行态。\n\n"
        "## 必读顺序\n"
        "1. `AGENTS.md`\n"
        "2. `.codex/experience/index.md`\n"
        "3. 读取 `.codex/experience/index.md` 中“必读经验”列出的经验文件\n"
        "4. `.codex/SOUL.md`\n"
        "5. `.codex/USER.md`\n"
        "6. `.codex/MEMORY.md`\n"
        "7. `.codex/memory/全局记忆总览.md`\n"
        "8. `.codex/memory/YYYY-MM/记忆总览.md`\n"
        "9. `.codex/memory/YYYY-MM/YYYY-MM-DD.md`\n\n"
        "## 目录模型\n"
        "- 经验索引：`.codex/experience/index.md`\n"
        "- 经验卡：`.codex/experience/*.md`\n"
        "- 全局总览：`.codex/memory/全局记忆总览.md`\n"
        "- 月度总览：`.codex/memory/YYYY-MM/记忆总览.md`\n"
        "- 每日日记：`.codex/memory/YYYY-MM/YYYY-MM-DD.md`\n\n"
        "## 写入规则\n"
        "- 经验卡只记录可复用模式、踩坑与规避规则；不要写成逐轮流水账。\n"
        "- 出现新的稳定经验时，更新对应 `.codex/experience/*.md`，并同步维护 `index.md`。\n"
        "- 每轮工作结束后，都要向当日日记追加一条带时间戳的总结。\n"
        "- 每日日记条目默认使用第一人称，写成“我这轮 / 我刚刚确认到”的日记口吻，并保持结构化、可检索。\n"
        "- 每日日记条目优先使用 `topic / context / actions / decisions / validation / artifacts / next` 结构。\n"
        "- 当日总结只保留在当日日记中，直到次日开始。\n"
        "- 当月总览只归档截至昨日的日级摘要。\n"
        "- 全局总览只归档已闭月的月度总结。\n\n"
        "## 每日条目字段说明\n"
        "- `topic`：我这轮主要在做什么。\n"
        "- `context`：我为什么开始处理这件事，包括触发原因或发现的缺口。\n"
        "- `actions`：我实际改了什么、创建了什么、迁移了什么、检查了什么。\n"
        "- `decisions`：我确认下来的规则、判断或会影响后续工作的结论。\n"
        "- `validation`：我执行过的命令、检查项和观察结果。\n"
        "- `artifacts`：我这轮触达的关键文件或目录。\n"
        "- `next`：我接下来还要跟进什么、延后检查什么、满足什么条件后再归档。\n\n"
        "## 归档检查\n"
        "- 日切检查：新一天首轮工作前，确认昨日日记已汇总到对应月度总览。\n"
        "- 月切检查：新一月首轮工作前，确认上月总览已汇总到全局总览。\n"
        "- 如果发现必须的总览条目缺失，先补归档，再继续正常工作。\n\n"
        "## 推荐命令\n"
        "- `python scripts/manage_codex_memory.py status --root .`\n"
        "- `python scripts/manage_codex_memory.py verify-rollups --root .`\n"
        "- `python scripts/manage_codex_memory.py repair-rollups --root .`\n"
    )


def _assignment_memory_spec_needs_fallback(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return True
    if normalized in {"# Memory Spec", "# MEMORY"}:
        return True
    return "## 归档检查" not in normalized or ".codex/memory/YYYY-MM/YYYY-MM-DD.md" not in normalized


def _assignment_memory_global_overview_template(month_key: str) -> str:
    return (
        "# 全局记忆总览\n\n"
        "## 角色说明\n"
        "- 作用：提供跨月份的记忆索引，只归档已闭月的月度总结。\n"
        f"- 后续读取：继续读取 `.codex/memory/{month_key}/记忆总览.md`。\n"
        f"- 当前活动月份： `{month_key}`\n"
        f"- 当前活动月份总览： `.codex/memory/{month_key}/记忆总览.md`\n\n"
        "## 当前状态\n"
        "- 已归档闭月数量： `0`\n"
        "- 当前活动月份状态： `in_progress`\n"
        f"- 当前活动日记： `.codex/memory/{month_key}/{now_local().strftime('%Y-%m-%d')}.md`\n"
        "- 全局归档说明：仅在闭月后把月度总结写入本文件；当前活动月份只保留索引，不复制日级增量。\n\n"
        "## 已归档月份\n"
        "- 暂无，等待闭月后归档。\n\n"
        "## 活动月份导航\n"
        f"### {month_key}\n"
        "- 状态：当前活动月份，尚未进入全局归档\n"
        f"- 当前活动月份： `{month_key}`\n"
        f"- 当前活动月份总览： `.codex/memory/{month_key}/记忆总览.md`\n"
    )


def _assignment_memory_month_overview_template(month_key: str, day_key: str) -> str:
    return (
        f"# 记忆总览 {month_key}\n\n"
        "## 月份状态\n"
        "- 状态： `in_progress`\n"
        "- 已归档日记范围： `待补齐`\n"
        f"- 当前活动日记： `.codex/memory/{month_key}/{day_key}.md`\n"
        "- 月度归档目标： `.codex/memory/全局记忆总览.md`\n\n"
        "## 归档规则\n"
        "- 仅归档截至昨日的日级摘要。\n"
        "- 当日新增总结只保留在对应的 `YYYY-MM-DD.md` 中，待日切后再归档。\n"
        "- 若发生跨月，需先确认本月总览已被全局总览收录，再进入新月份工作。\n\n"
        "## 已归档日索引\n"
        "- 暂无，等待日切后归档。\n"
    )


def _assignment_memory_daily_template(month_key: str, day_key: str) -> str:
    return (
        f"# 每日记忆 {day_key}\n\n"
        "## Metadata\n"
        f"- month: `{month_key}`\n"
        f"- month_overview: `.codex/memory/{month_key}/记忆总览.md`\n"
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


def _assignment_experience_index_template() -> str:
    return (
        "# 经验索引\n\n"
        "## 先读这里\n"
        "- 本文件是当前角色工作区的经验入口。\n"
        "- 先读“必读经验”，再按需扩展阅读其他经验卡。\n"
        "- 经验卡只记录可复用模式、踩坑复盘与规避动作，不记录单次流水账。\n\n"
        "## 必读经验\n"
        "- 暂无；等沉淀出稳定经验后再在这里追加。\n\n"
        "## 经验文件\n"
        "- 暂无。\n\n"
        "## 更新规则\n"
        "- 新经验优先补到已有经验卡；仅当主题明显不同再新建文件。\n"
        "- 每次新增经验卡时，同步更新“必读经验”或“经验文件”引用。\n"
        "- 如果只是一次性现象、还没验证稳定结论，不进入经验卡，只留在当日日记。\n"
    )


def _ensure_assignment_workspace_memory_scaffold(workspace_path: Path) -> list[str]:
    if not _assignment_workspace_uses_codex_memory(workspace_path):
        return []
    now_dt = now_local()
    month_key = now_dt.strftime("%Y-%m")
    day_key = now_dt.strftime("%Y-%m-%d")
    codex_dir = workspace_path / ".codex"
    experience_index = codex_dir / "experience" / "index.md"
    memory_root = workspace_path / ".codex" / "memory"
    month_dir = memory_root / month_key
    memory_spec = codex_dir / "MEMORY.md"
    global_overview = memory_root / "全局记忆总览.md"
    month_overview = month_dir / "记忆总览.md"
    daily_memory = month_dir / f"{day_key}.md"
    created: list[str] = []
    month_dir.mkdir(parents=True, exist_ok=True)
    existing_memory_spec = memory_spec.read_text(encoding="utf-8") if memory_spec.exists() else ""
    if _assignment_memory_spec_needs_fallback(existing_memory_spec):
        memory_spec.parent.mkdir(parents=True, exist_ok=True)
        memory_spec.write_text(_assignment_memory_spec_template(), encoding="utf-8")
        created.append(memory_spec.as_posix())
    existing_experience_index = experience_index.read_text(encoding="utf-8") if experience_index.exists() else ""
    if not existing_experience_index.strip():
        experience_index.parent.mkdir(parents=True, exist_ok=True)
        experience_index.write_text(_assignment_experience_index_template(), encoding="utf-8")
        created.append(experience_index.as_posix())
    targets = [
        (global_overview, _assignment_memory_global_overview_template(month_key)),
        (month_overview, _assignment_memory_month_overview_template(month_key, day_key)),
        (daily_memory, _assignment_memory_daily_template(month_key, day_key)),
    ]
    for path, content in targets:
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        created.append(path.as_posix())
    return created


def _resolve_assignment_workspace_path(conn: sqlite3.Connection, root: Path, *, agent_id: str) -> Path:
    row = conn.execute(
        """
        SELECT agent_name,workspace_path
        FROM agent_registry
        WHERE agent_id=?
        LIMIT 1
        """,
        (str(agent_id or "").strip(),),
    ).fetchone()
    if row is None:
        discovered = _discover_assignment_agent_workspace_path(root, agent_id=str(agent_id or "").strip())
        if discovered is None:
            raise AssignmentCenterError(
                409,
                "assigned agent workspace path not found",
                "assignment_agent_workspace_missing",
                {"assigned_agent_id": str(agent_id or "").strip()},
            )
        discovered_name, discovered_path = discovered
        _upsert_assignment_agent_registry_row(
            conn,
            agent_id=str(agent_id or "").strip(),
            agent_name=discovered_name,
            workspace_path=discovered_path,
        )
        return discovered_path
    workspace_path = Path(str(row["workspace_path"] or "")).resolve(strict=False)
    if not workspace_path.exists() or not workspace_path.is_dir():
        discovered = _discover_assignment_agent_workspace_path(root, agent_id=str(agent_id or "").strip())
        if discovered is not None:
            discovered_name, discovered_path = discovered
            _upsert_assignment_agent_registry_row(
                conn,
                agent_id=str(agent_id or "").strip(),
                agent_name=discovered_name,
                workspace_path=discovered_path,
            )
            return discovered_path
        raise AssignmentCenterError(
            409,
            "assigned agent workspace path invalid",
            "assignment_agent_workspace_invalid",
            {
                "assigned_agent_id": str(agent_id or "").strip(),
                "workspace_path": workspace_path.as_posix(),
            },
        )
    search_root = _current_assignment_agent_search_root(root)
    if isinstance(search_root, Path) and not path_in_scope(workspace_path, search_root):
        raise AssignmentCenterError(
            409,
            "assigned agent workspace path out of scope",
            "assignment_agent_workspace_out_of_scope",
            {
                "assigned_agent_id": str(agent_id or "").strip(),
                "workspace_path": workspace_path.as_posix(),
                "agent_search_root": search_root.as_posix(),
            },
        )
    try:
        _ensure_assignment_workspace_memory_scaffold(workspace_path)
    except Exception as exc:
        raise AssignmentCenterError(
            409,
            "assigned agent workspace memory bootstrap failed",
            "assignment_agent_workspace_memory_bootstrap_failed",
            {
                "assigned_agent_id": str(agent_id or "").strip(),
                "workspace_path": workspace_path.as_posix(),
                "error": str(exc),
            },
        ) from exc
    return workspace_path
