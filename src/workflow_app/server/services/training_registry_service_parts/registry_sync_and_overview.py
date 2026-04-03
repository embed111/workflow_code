from __future__ import annotations

import base64
import binascii
import threading
import time

_REGISTRY_SYNC_LOCK = threading.Lock()
_REGISTRY_SYNC_CACHE_TTL_S = 8.0
_REGISTRY_SYNC_LAST_AT_S = 0.0
_REGISTRY_SYNC_LAST_ROOT = ""
_WORKSPACE_LOCAL_SKILLS_CACHE_TTL_S = 20.0
_WORKSPACE_LOCAL_SKILLS_CACHE_LOCK = threading.Lock()
_WORKSPACE_LOCAL_SKILLS_CACHE: dict[str, tuple[float, float, list[str]]] = {}


def _is_db_locked_error(exc: BaseException) -> bool:
    msg = str(exc or "").lower()
    return "database is locked" in msg or "database table is locked" in msg or "database schema is locked" in msg

def bind_runtime_symbols(symbols: dict[str, object]) -> None:
    if not isinstance(symbols, dict):
        return
    target = globals()
    module_name = str(target.get('__name__') or '')
    for key, value in symbols.items():
        if str(key).startswith('__'):
            continue
        current = target.get(key)
        if callable(current) and getattr(current, '__module__', '') == module_name:
            continue
        target[key] = value

def _resolve_training_agent(conn: sqlite3.Connection, target: str) -> dict[str, Any] | None:
    key = str(target or "").strip()
    if not key:
        return None
    row = conn.execute(
        """
        SELECT
            agent_id,agent_name,workspace_path,current_version,
            latest_release_version,bound_release_version,
            lifecycle_state,training_gate_state,parent_agent_id,runtime_status,
            core_capabilities,capability_summary,knowledge_scope,skills_json,applicable_scenarios,version_notes,avatar_uri,
            vector_icon,git_available,pre_release_state,pre_release_reason,pre_release_checked_at,pre_release_git_output,
            last_release_at,status_tags_json,active_role_profile_release_id,active_role_profile_ref,updated_at
        FROM agent_registry
        WHERE agent_id=?
        LIMIT 1
        """,
        (key,),
    ).fetchone()
    if row is None:
        row = conn.execute(
            """
                SELECT
                    agent_id,agent_name,workspace_path,current_version,
                    latest_release_version,bound_release_version,
                    lifecycle_state,training_gate_state,parent_agent_id,runtime_status,
                    core_capabilities,capability_summary,knowledge_scope,skills_json,applicable_scenarios,version_notes,avatar_uri,
                    vector_icon,git_available,pre_release_state,pre_release_reason,pre_release_checked_at,pre_release_git_output,
                    last_release_at,status_tags_json,active_role_profile_release_id,active_role_profile_ref,updated_at
                FROM agent_registry
                WHERE agent_name=?
                LIMIT 1
                """,
            (key,),
        ).fetchone()
    if row is None:
        return None
    return {name: row[name] for name in row.keys()}


def _list_workspace_local_skills(workspace_path_raw: Any) -> list[str]:
    workspace_text = str(workspace_path_raw or "").strip()
    if not workspace_text:
        return []
    try:
        workspace_path = Path(workspace_text).resolve(strict=False)
    except Exception:
        return []
    skills_root = workspace_path / ".codex" / "skills"
    if not skills_root.exists() or not skills_root.is_dir():
        return []
    try:
        cache_key = str(skills_root.resolve(strict=False))
    except Exception:
        cache_key = skills_root.as_posix()
    try:
        cache_stamp = float(skills_root.stat().st_mtime_ns)
    except Exception:
        cache_stamp = 0.0
    cached_payload = None
    now_mono = time.monotonic()
    with _WORKSPACE_LOCAL_SKILLS_CACHE_LOCK:
        cached_payload = _WORKSPACE_LOCAL_SKILLS_CACHE.get(cache_key)
        if (
            cached_payload is not None
            and now_mono < float(cached_payload[0])
            and float(cached_payload[1]) == cache_stamp
        ):
            return list(cached_payload[2])
    items: list[str] = []
    for child in skills_root.iterdir():
        name = str(child.name or "").strip()
        if not name or name.startswith("."):
            continue
        if not child.is_dir():
            continue
        if not (child / "SKILL.md").exists():
            continue
        items.append(name)
    items.sort(key=lambda value: value.lower())
    with _WORKSPACE_LOCAL_SKILLS_CACHE_LOCK:
        _WORKSPACE_LOCAL_SKILLS_CACHE[cache_key] = (
            now_mono + _WORKSPACE_LOCAL_SKILLS_CACHE_TTL_S,
            cache_stamp,
            list(items),
        )
    return items


def sync_training_agent_registry(cfg: AppConfig) -> list[dict[str, Any]]:
    root = cfg.agent_search_root
    if root is None:
        _REGISTRY_SYNC_LOCK.acquire()
        try:
            conn = connect_db(cfg.root)
        except Exception:
            _REGISTRY_SYNC_LOCK.release()
            raise
        try:
            for attempt in range(3):
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    break
                except Exception as exc:
                    if _is_db_locked_error(exc) and attempt < 2:
                        time.sleep(0.2 * float(attempt + 1))
                        continue
                    raise
            conn.execute("DELETE FROM agent_registry")
            conn.execute("DELETE FROM agent_release_history")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
            _REGISTRY_SYNC_LOCK.release()
        return []

    try:
        root_key = str(root.resolve(strict=False))
    except Exception:
        root_key = str(root or "").strip()
    now_mono = time.monotonic()
    global _REGISTRY_SYNC_LAST_AT_S, _REGISTRY_SYNC_LAST_ROOT
    if root_key and _REGISTRY_SYNC_LAST_ROOT == root_key and now_mono - _REGISTRY_SYNC_LAST_AT_S < _REGISTRY_SYNC_CACHE_TTL_S:
        return []

    available = list_available_agents(cfg, analyze_policy=False)
    now_text = iso_ts(now_local())
    _REGISTRY_SYNC_LOCK.acquire()
    try:
        conn = connect_db(cfg.root)
    except Exception:
        _REGISTRY_SYNC_LOCK.release()
        raise
    keep_ids: list[str] = []
    try:
        # Avoid sync storms: re-check after lock acquisition.
        now_mono = time.monotonic()
        if root_key and _REGISTRY_SYNC_LAST_ROOT == root_key and now_mono - _REGISTRY_SYNC_LAST_AT_S < _REGISTRY_SYNC_CACHE_TTL_S:
            return []
        for attempt in range(3):
            try:
                conn.execute("BEGIN IMMEDIATE")
                break
            except Exception as exc:
                if _is_db_locked_error(exc) and attempt < 2:
                    time.sleep(0.2 * float(attempt + 1))
                    continue
                raise
        for item in available:
            agent_name = safe_token(str(item.get("agent_name") or ""), "", 80)
            agents_path_text = str(item.get("agents_md_path") or "").strip()
            if not agent_name or not agents_path_text:
                continue
            agents_md_path = Path(agents_path_text).resolve(strict=False)
            workspace_path = agents_md_path.parent.resolve(strict=False)
            if not path_in_scope(workspace_path, root.resolve(strict=False)):
                continue
            agent_id = safe_token(agent_name, agent_name, 120)

            if not agent_id:

                continue

            existed = conn.execute(
                """
                SELECT
                    current_version,latest_release_version,bound_release_version,
                    lifecycle_state,training_gate_state,parent_agent_id,avatar_uri,last_release_at,
                    active_role_profile_release_id,active_role_profile_ref,runtime_status
                FROM agent_registry
                WHERE agent_id=?
                LIMIT 1
                """,
                (agent_id,),
            ).fetchone()
            existing_release_meta_rows = conn.execute(
                """
                SELECT
                    version_label,commit_ref,classification,
                    release_source_ref,public_profile_ref,capability_snapshot_ref
                FROM agent_release_history
                WHERE agent_id=?
                """,
                (agent_id,),
            ).fetchall()
            vector_icon = build_agent_vector_icon(agent_name, agent_id)

            current_version = str(item.get("agents_version") or "").strip()
            last_release_at = ""
            portrait = extract_agent_role_portrait(agents_md_path)
            core_capabilities = extract_core_capability_summary(agents_md_path)
            capability_summary = str(portrait.get("capability_summary") or "").strip()
            knowledge_scope = str(portrait.get("knowledge_scope") or "").strip()
            portrait_skills = _skills_list(portrait.get("skills"))
            applicable_scenarios = str(portrait.get("applicable_scenarios") or "").strip()
            version_notes = str(portrait.get("version_notes") or "").strip()
            git_available = _git_available_in_scope(workspace_path, root)
            status_tags: list[str] = []
            release_rows: list[dict[str, str]] = []
            latest_release_version = ""
            pre_release_state = "pre_release"
            pre_release_reason = "git_unavailable"
            pre_release_checked_at = now_text
            pre_release_git_output = ""
            if git_available:
                _, git_last_release_at, release_rows = _parse_git_release_rows(workspace_path, limit=60)
                latest_release_version = choose_latest_release_version(release_rows) or ""
                if git_last_release_at and latest_release_version:
                    last_release_at = git_last_release_at
                status_ok, status_out, status_err = _run_git_readonly_verbose(
                    workspace_path,
                    ["status", "--porcelain", "--untracked-files=normal"],
                    timeout_s=12,
                )
                if status_ok:
                    normalized_output = "\n".join(
                        [str(line or "").rstrip() for line in str(status_out or "").splitlines() if str(line or "").strip()]
                    )
                    pre_release_git_output = _short_text(normalized_output, 2000)
                    if normalized_output:
                        pre_release_state = "pre_release"
                        pre_release_reason = "git_status_non_empty"
                    else:
                        pre_release_state = "released"
                        pre_release_reason = "git_status_clean"
                else:
                    pre_release_state = "unknown"
                    pre_release_reason = "git_status_failed"
                    pre_release_git_output = _short_text(str(status_err or "").strip(), 500)
            else:
                status_tags.append("git_unavailable")

            existed_current = str(existed["current_version"] or "").strip() if existed is not None else ""
            existed_latest = str(existed["latest_release_version"] or "").strip() if existed is not None else ""
            existed_bound = str(existed["bound_release_version"] or "").strip() if existed is not None else ""
            existed_last_release_at = str(existed["last_release_at"] or "").strip() if existed is not None else ""
            existed_gate = (
                normalize_training_gate_state(existed["training_gate_state"]) if existed is not None else "trainable"
            )
            parent_agent_id = str(existed["parent_agent_id"] or "").strip() if existed is not None else ""
            avatar_uri = str(existed["avatar_uri"] or "").strip() if existed is not None else ""
            active_role_profile_release_id = (
                str(existed["active_role_profile_release_id"] or "").strip() if existed is not None else ""
            )
            active_role_profile_ref = (
                str(existed["active_role_profile_ref"] or "").strip() if existed is not None else ""
            )
            runtime_status = (
                str(existed["runtime_status"] or "").strip().lower() if existed is not None else ""
            ) or "idle"

            existing_release_meta: dict[tuple[str, str, str], dict[str, str]] = {}
            existing_release_meta_loose: dict[tuple[str, str], dict[str, str]] = {}
            for existing_row in existing_release_meta_rows:
                version_key = str(existing_row["version_label"] or "").strip()
                commit_key = str(existing_row["commit_ref"] or "").strip()
                classification_key = str(existing_row["classification"] or "normal_commit").strip() or "normal_commit"
                meta_payload = {
                    "release_source_ref": str(existing_row["release_source_ref"] or "").strip(),
                    "public_profile_ref": str(existing_row["public_profile_ref"] or "").strip(),
                    "capability_snapshot_ref": str(existing_row["capability_snapshot_ref"] or "").strip(),
                }
                if version_key:
                    existing_release_meta[(version_key, commit_key, classification_key)] = meta_payload
                    existing_release_meta_loose[(version_key, classification_key)] = meta_payload

            if not git_available:
                latest_release_version = existed_latest
                last_release_at = existed_last_release_at if existed_latest else ""

            if existed_current:
                current_version = existed_current
            elif latest_release_version:
                current_version = latest_release_version
            elif existed_latest:
                current_version = existed_latest

            release_labels = {
                str(rel.get("version_label") or "").strip()
                for rel in release_rows
                if str(rel.get("version_label") or "").strip()
                and str(rel.get("classification") or "release").strip().lower() == "release"
            }
            if parent_agent_id:
                # 克隆角色首期以当前基线为“最新可切回版本”。
                latest_release_version = (
                    latest_release_version
                    or existed_latest
                    or current_version
                )

            if existed_bound and existed_bound in release_labels:
                bound_release_version = existed_bound
            elif current_version and current_version in release_labels:
                bound_release_version = current_version
            else:
                bound_release_version = latest_release_version

            if not latest_release_version:
                last_release_at = ""

            lifecycle_state = normalize_lifecycle_state(pre_release_state)
            training_gate_state = derive_training_gate_state(
                lifecycle_state=lifecycle_state,
                current_version=current_version,
                latest_release_version=latest_release_version,
                parent_agent_id=parent_agent_id,
                preferred=existed_gate,
            )
            if lifecycle_state == "pre_release":
                status_tags.append("pre_release")
            if lifecycle_state == "unknown":
                status_tags.append("pre_release_unknown")
            if training_gate_state == "frozen_switched":
                status_tags.append("frozen_switched")
            if parent_agent_id:
                status_tags.append("cloned")
            if any(str(rel.get("classification") or "").strip().lower() == "normal_commit" for rel in release_rows):
                status_tags.append("normal_commit_present")

            conn.execute(
                """
                INSERT INTO agent_registry (
                    agent_id,agent_name,workspace_path,current_version,latest_release_version,bound_release_version,
                    lifecycle_state,training_gate_state,parent_agent_id,runtime_status,
                    core_capabilities,capability_summary,knowledge_scope,skills_json,applicable_scenarios,version_notes,avatar_uri,
                    vector_icon,git_available,pre_release_state,pre_release_reason,pre_release_checked_at,pre_release_git_output,
                    last_release_at,status_tags_json,active_role_profile_release_id,active_role_profile_ref,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    agent_name=excluded.agent_name,
                    workspace_path=excluded.workspace_path,
                    current_version=excluded.current_version,
                    latest_release_version=excluded.latest_release_version,
                    bound_release_version=excluded.bound_release_version,
                    lifecycle_state=excluded.lifecycle_state,
                    training_gate_state=excluded.training_gate_state,
                    parent_agent_id=excluded.parent_agent_id,
                    runtime_status=excluded.runtime_status,
                    core_capabilities=excluded.core_capabilities,
                    capability_summary=excluded.capability_summary,
                    knowledge_scope=excluded.knowledge_scope,
                    skills_json=excluded.skills_json,
                    applicable_scenarios=excluded.applicable_scenarios,
                    version_notes=excluded.version_notes,
                    avatar_uri=excluded.avatar_uri,
                    vector_icon=excluded.vector_icon,
                    git_available=excluded.git_available,
                    pre_release_state=excluded.pre_release_state,
                    pre_release_reason=excluded.pre_release_reason,
                    pre_release_checked_at=excluded.pre_release_checked_at,
                    pre_release_git_output=excluded.pre_release_git_output,
                    last_release_at=excluded.last_release_at,
                    status_tags_json=excluded.status_tags_json,
                    active_role_profile_release_id=excluded.active_role_profile_release_id,
                    active_role_profile_ref=excluded.active_role_profile_ref,
                    updated_at=excluded.updated_at
                """,
                (
                    agent_id,
                    agent_name,
                    workspace_path.as_posix(),
                    current_version,
                    latest_release_version,
                    bound_release_version,
                    lifecycle_state,
                    training_gate_state,
                    parent_agent_id,
                    runtime_status,
                    core_capabilities,
                    capability_summary,
                    knowledge_scope,
                    json.dumps(portrait_skills, ensure_ascii=False),
                    applicable_scenarios,
                    version_notes,
                    avatar_uri,
                    vector_icon,
                    1 if git_available else 0,
                    pre_release_state,
                    pre_release_reason,
                    pre_release_checked_at,
                    pre_release_git_output,
                    last_release_at,
                    json.dumps(status_tags, ensure_ascii=False),
                    active_role_profile_release_id,
                    active_role_profile_ref,
                    now_text,
                ),
            )
            keep_ids.append(agent_id)

            conn.execute("DELETE FROM agent_release_history WHERE agent_id=?", (agent_id,))
            if release_rows:
                for idx, rel in enumerate(release_rows, start=1):
                    digest = hashlib.sha1(
                        f"{agent_id}|{rel.get('commit_ref','')}|{rel.get('version_label','')}|{rel.get('classification','')}".encode(
                            "utf-8"
                        )
                    ).hexdigest()[:10]
                    release_id = f"rel-{agent_id}-{digest}"
                    rel_version = str(rel.get("version_label") or "").strip()
                    rel_commit = str(rel.get("commit_ref") or "").strip()
                    rel_classification = str(rel.get("classification") or "normal_commit").strip() or "normal_commit"
                    meta_payload = existing_release_meta.get((rel_version, rel_commit, rel_classification)) or existing_release_meta_loose.get((rel_version, rel_classification)) or {}
                    conn.execute(
                        """
                        INSERT INTO agent_release_history (
                            release_id,agent_id,version_label,released_at,change_summary,commit_ref,
                            capability_summary,knowledge_scope,skills_json,applicable_scenarios,version_notes,
                            release_valid,invalid_reasons_json,classification,raw_notes,
                            release_source_ref,public_profile_ref,capability_snapshot_ref,created_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            release_id,
                            agent_id,
                            str(rel.get("version_label") or ""),
                            str(rel.get("released_at") or ""),
                            str(rel.get("change_summary") or ""),
                            str(rel.get("commit_ref") or ""),
                            str(rel.get("capability_summary") or ""),
                            str(rel.get("knowledge_scope") or ""),
                            str(rel.get("skills_json") or "[]"),
                            str(rel.get("applicable_scenarios") or ""),
                            str(rel.get("version_notes") or ""),
                            int(rel.get("release_valid") or 0),
                            str(rel.get("invalid_reasons_json") or "[]"),
                            str(rel.get("classification") or "normal_commit"),
                            str(rel.get("raw_notes") or ""),
                            str(meta_payload.get("release_source_ref") or ""),
                            str(meta_payload.get("public_profile_ref") or ""),
                            str(meta_payload.get("capability_snapshot_ref") or ""),
                            now_text,
                        ),
                    )
        if keep_ids:
            marks = ",".join(["?"] * len(keep_ids))
            conn.execute(
                f"DELETE FROM agent_registry WHERE agent_id NOT IN ({marks}) AND COALESCE(runtime_status,'idle')<>'creating'",
                tuple(keep_ids),
            )
            conn.execute(
                f"DELETE FROM agent_release_history WHERE agent_id NOT IN ({marks}) AND agent_id NOT IN (SELECT agent_id FROM agent_registry WHERE COALESCE(runtime_status,'idle')='creating')",
                tuple(keep_ids),
            )
        else:
            conn.execute("DELETE FROM agent_registry WHERE COALESCE(runtime_status,'idle')<>'creating'")
            conn.execute(
                "DELETE FROM agent_release_history WHERE agent_id NOT IN (SELECT agent_id FROM agent_registry)"
            )
        conn.commit()
        _REGISTRY_SYNC_LAST_AT_S = time.monotonic()
        _REGISTRY_SYNC_LAST_ROOT = root_key
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        _REGISTRY_SYNC_LOCK.release()
    return available


def list_training_agents_overview(
    cfg: AppConfig,
    *,
    include_test_data: bool = True,
) -> dict[str, Any]:
    try:
        sync_training_agent_registry(cfg)
    except Exception as exc:
        # Best-effort: avoid hard-failing the UI when SQLite is contended.
        if not _is_db_locked_error(exc):
            raise
    include_flag = 1 if include_test_data else 0
    conn = connect_db(cfg.root)
    try:
        pending_queue = int(
            (
                conn.execute(
                    """
                    SELECT COUNT(1) AS cnt
                    FROM training_queue q
                    INNER JOIN training_plan p ON p.plan_id=q.plan_id
                    WHERE q.status='queued'
                      AND (?=1 OR COALESCE(p.is_test_data,0)=0)
                    """,
                    (include_flag,),
                ).fetchone()
                or {"cnt": 0}
            )["cnt"]
        )
        rows = conn.execute(
            """
            SELECT
                agent_id,agent_name,workspace_path,current_version,
                latest_release_version,bound_release_version,
                lifecycle_state,training_gate_state,parent_agent_id,runtime_status,
                core_capabilities,capability_summary,knowledge_scope,skills_json,applicable_scenarios,version_notes,avatar_uri,
                vector_icon,git_available,pre_release_state,pre_release_reason,pre_release_checked_at,pre_release_git_output,
                last_release_at,status_tags_json,active_role_profile_release_id,active_role_profile_ref,updated_at
            FROM agent_registry
            ORDER BY agent_name COLLATE NOCASE ASC
            """
        ).fetchall()
    finally:
        conn.close()

    items: list[dict[str, Any]] = []
    latest_release_at = ""
    git_available_count = 0
    for row in rows:
        tags_raw = str(row["status_tags_json"] or "[]")
        try:
            tags = json.loads(tags_raw)
            if not isinstance(tags, list):
                tags = []
        except Exception:
            tags = []
        skills_raw = str(row["skills_json"] or "[]")
        try:
            skills_value = json.loads(skills_raw)
            if not isinstance(skills_value, list):
                skills_value = []
        except Exception:
            skills_value = []
        item = {
            "agent_id": str(row["agent_id"] or ""),
            "agent_name": str(row["agent_name"] or ""),
            "vector_icon": str(row["vector_icon"] or ""),
            "workspace_path": str(row["workspace_path"] or ""),
            "current_version": str(row["current_version"] or ""),
            "latest_release_version": str(row["latest_release_version"] or ""),
            "bound_release_version": str(row["bound_release_version"] or ""),
            "lifecycle_state": normalize_lifecycle_state(row["lifecycle_state"]),
            "training_gate_state": normalize_training_gate_state(row["training_gate_state"]),
            "parent_agent_id": str(row["parent_agent_id"] or ""),
            "runtime_status": str(row["runtime_status"] or "idle").strip().lower() or "idle",
            "core_capabilities": str(row["core_capabilities"] or ""),
            "capability_summary": str(row["capability_summary"] or ""),
            "knowledge_scope": str(row["knowledge_scope"] or ""),
            "skills": [str(skill or "").strip() for skill in skills_value if str(skill or "").strip()],
            "agent_skills": _list_workspace_local_skills(row["workspace_path"]),
            "applicable_scenarios": str(row["applicable_scenarios"] or ""),
            "version_notes": str(row["version_notes"] or ""),
            "avatar_uri": str(row["avatar_uri"] or ""),
            "git_available": bool(int(row["git_available"] or 0)),
            "pre_release_state": str(row["pre_release_state"] or ""),
            "pre_release_reason": str(row["pre_release_reason"] or ""),
            "pre_release_checked_at": str(row["pre_release_checked_at"] or ""),
            "pre_release_git_output": str(row["pre_release_git_output"] or ""),
            "last_release_at": str(row["last_release_at"] or ""),
            "status_tags": [str(tag).strip() for tag in tags if str(tag or "").strip()],
            "active_role_profile_release_id": str(row["active_role_profile_release_id"] or ""),
            "active_role_profile_ref": str(row["active_role_profile_ref"] or ""),
            "updated_at": str(row["updated_at"] or ""),
        }
        if not include_test_data and is_system_or_test_workspace(
            item["workspace_path"],
            agent_search_root=cfg.agent_search_root,
        ):
            continue
        items.append(item)
        if item["git_available"]:
            git_available_count += 1
        if str(item["last_release_at"] or "") > latest_release_at:
            latest_release_at = str(item["last_release_at"] or "")

    return {
        "items": items,
        "stats": {
            "agent_total": len(items),
            "git_available_count": git_available_count,
            "latest_release_at": latest_release_at,
            "training_queue_pending": pending_queue,
        },
    }
