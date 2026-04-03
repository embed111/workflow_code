

def list_training_agent_releases(
    root: Path,
    agent_id: str,
    *,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    pid = safe_token(str(agent_id or ""), "", 120)
    if not pid:
        raise TrainingCenterError(400, "agent_id required", "agent_id_required")
    safe_page = max(1, int(page or 1))
    safe_size = min(200, max(1, int(page_size or 50)))
    offset = (safe_page - 1) * safe_size
    conn = connect_db(root)
    try:
        meta = conn.execute(
            """
            SELECT
                agent_id,agent_name,workspace_path,current_version,
                latest_release_version,bound_release_version,
                lifecycle_state,training_gate_state,parent_agent_id,
                core_capabilities,capability_summary,knowledge_scope,skills_json,applicable_scenarios,version_notes,avatar_uri,
                vector_icon,git_available,pre_release_state,pre_release_reason,pre_release_checked_at,pre_release_git_output,
                last_release_at,status_tags_json,active_role_profile_release_id,active_role_profile_ref,updated_at
            FROM agent_registry
            WHERE agent_id=?
            LIMIT 1
            """,
            (pid,),
        ).fetchone()
        if meta is None:
            raise TrainingCenterError(404, "agent not found", "agent_not_found", {"agent_id": pid})
        meta = {name: meta[name] for name in meta.keys()}
        release_total = int(
            (
                conn.execute(
                    "SELECT COUNT(1) AS cnt FROM agent_release_history WHERE agent_id=? AND COALESCE(classification,'normal_commit')='release'",
                    (pid,),
                ).fetchone()
                or {"cnt": 0}
            )["cnt"]
        )
        normal_total = int(
            (
                conn.execute(
                    "SELECT COUNT(1) AS cnt FROM agent_release_history WHERE agent_id=? AND COALESCE(classification,'normal_commit')='normal_commit'",
                    (pid,),
                ).fetchone()
                or {"cnt": 0}
            )["cnt"]
        )
        rows = conn.execute(
            """
            SELECT
                release_id,agent_id,version_label,released_at,change_summary,commit_ref,
                capability_summary,knowledge_scope,skills_json,applicable_scenarios,version_notes,
                release_valid,invalid_reasons_json,classification,raw_notes,
                release_source_ref,public_profile_ref,capability_snapshot_ref,created_at
            FROM agent_release_history
            WHERE agent_id=?
              AND COALESCE(classification,'normal_commit')='release'
            ORDER BY released_at DESC, created_at DESC
            LIMIT ? OFFSET ?
            """,
            (pid, safe_size, offset),
        ).fetchall()
        normal_rows = conn.execute(
            """
            SELECT
                release_id,agent_id,version_label,released_at,change_summary,commit_ref,
                capability_summary,knowledge_scope,skills_json,applicable_scenarios,version_notes,
                release_valid,invalid_reasons_json,classification,raw_notes,
                release_source_ref,public_profile_ref,capability_snapshot_ref,created_at
            FROM agent_release_history
            WHERE agent_id=?
              AND COALESCE(classification,'normal_commit')='normal_commit'
            ORDER BY released_at DESC, created_at DESC
            LIMIT 60
            """,
            (pid,),
        ).fetchall()
    finally:
        conn.close()

    meta_skills_raw = str(meta["skills_json"] or "[]")
    try:
        meta_skills = json.loads(meta_skills_raw)
        if not isinstance(meta_skills, list):
            meta_skills = []
    except Exception:
        meta_skills = []
    agent_skills = _list_workspace_local_skills(meta.get("workspace_path"))

    def decode_json_list(raw: Any) -> list[str]:
        text = str(raw or "").strip()
        if not text:
            return []
        try:
            payload = json.loads(text)
            if not isinstance(payload, list):
                return []
            return [str(item or "").strip() for item in payload if str(item or "").strip()]
        except Exception:
            return []

    def decode_skill_names(raw: Any) -> list[str]:
        skill_parser = globals().get("_skills_list")
        if callable(skill_parser):
            try:
                rows = skill_parser(raw)
            except Exception:
                rows = []
            if rows:
                return [str(item or "").strip() for item in rows if str(item or "").strip()]
        return decode_json_list(raw)

    def decode_skill_profiles(raw_notes: Any, fallback_skills: list[str]) -> list[dict[str, str]]:
        parser = globals().get("parse_release_portrait_fields")
        if callable(parser):
            try:
                parsed = parser(str(raw_notes or ""))
            except Exception:
                parsed = {}
            raw_profiles = parsed.get("skill_profiles") if isinstance(parsed, dict) else []
            if isinstance(raw_profiles, list):
                rows: list[dict[str, str]] = []
                for item in raw_profiles:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    if not name:
                        continue
                    rows.append(
                        {
                            "name": name,
                            "summary": str(item.get("summary") or "").strip(),
                            "details": str(item.get("details") or "").strip(),
                        }
                    )
                if rows:
                    return rows
        return [
            {
                "name": str(name or "").strip(),
                "summary": "",
                "details": "",
            }
            for name in fallback_skills
            if str(name or "").strip()
        ]

    def build_release_payload(row: Any, *, fallback_classification: str) -> dict[str, Any]:
        skills = decode_skill_names(row["skills_json"])
        return {
            "release_id": str(row["release_id"] or ""),
            "agent_id": str(row["agent_id"] or ""),
            "version_label": str(row["version_label"] or ""),
            "released_at": str(row["released_at"] or ""),
            "change_summary": str(row["change_summary"] or ""),
            "capability_summary": str(row["capability_summary"] or ""),
            "knowledge_scope": str(row["knowledge_scope"] or ""),
            "skills": skills,
            "skill_profiles": decode_skill_profiles(row["raw_notes"], skills),
            "applicable_scenarios": str(row["applicable_scenarios"] or ""),
            "version_notes": str(row["version_notes"] or ""),
            "release_valid": bool(int(row["release_valid"] or 0)),
            "invalid_reasons": decode_json_list(row["invalid_reasons_json"]),
            "classification": str(row["classification"] or fallback_classification),
            "release_source_ref": str(row["release_source_ref"] or ""),
            "public_profile_ref": str(row["public_profile_ref"] or ""),
            "capability_snapshot_ref": str(row["capability_snapshot_ref"] or ""),
            "created_at": str(row["created_at"] or ""),
        }

    def profile_text_items(raw: Any, *, limit: int = 6, item_limit: int = 180) -> list[str]:
        values = raw if isinstance(raw, list) else re.split(r"[\r\n]+|(?<=[。；;!?！？])", str(raw or "").strip())
        out: list[str] = []
        seen: set[str] = set()
        for item in values:
            text = _short_text(str(item or "").strip().strip("-•* \t"), item_limit)
            if not text:
                continue
            key = re.sub(r"\s+", "", text).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(text)
            if len(out) >= max(1, int(limit or 1)):
                break
        return out

    def ensure_first_person(text: Any, prefix: str, *, limit: int = 320) -> str:
        value = _short_text(str(text or "").strip(), limit)
        if not value:
            return ""
        if value.startswith(("我是", "我当前", "我能", "我已", "我会", "我建议", "本次发布", "当前工作区")):
            return value
        if value.startswith("你是"):
            return "我" + value[1:]
        if value.startswith("作为"):
            return "我" + value
        return prefix + value

    def load_json_ref(ref: Any) -> dict[str, Any]:
        ref_text = str(ref or "").strip()
        if not ref_text:
            return {}
        base_root = root.resolve(strict=False)
        try:
            target = (base_root / ref_text).resolve(strict=False)
        except Exception:
            try:
                target = Path(ref_text).resolve(strict=False)
            except Exception:
                return {}
        if not path_in_scope(target, base_root):
            return {}
        if not target.exists() or not target.is_file():
            return {}
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def fallback_role_profile(release_payload: dict[str, Any] | None, *, reason: str) -> dict[str, Any]:
        current_release = release_payload if isinstance(release_payload, dict) else {}
        summary_source = (
            str(current_release.get("capability_summary") or "").strip()
            or str(meta["capability_summary"] or "").strip()
            or str(meta["core_capabilities"] or "").strip()
        )
        first_person_summary = ensure_first_person(summary_source, "我当前的核心能力是：", limit=320)
        full_capability_inventory = profile_text_items(
            str(current_release.get("capability_summary") or "").strip() or str(meta["core_capabilities"] or "").strip(),
            limit=10,
            item_limit=220,
        )
        if not full_capability_inventory and first_person_summary:
            full_capability_inventory = [ensure_first_person(first_person_summary, "我当前可以：", limit=220)]
        knowledge_scope = ensure_first_person(
            str(current_release.get("knowledge_scope") or meta["knowledge_scope"] or "").strip(),
            "我当前覆盖的知识范围是：",
            limit=320,
        )
        scenario_items = profile_text_items(
            current_release.get("applicable_scenarios") or meta["applicable_scenarios"] or "",
            limit=6,
            item_limit=140,
        )
        profile_skills = (
            _skills_list(current_release.get("skills"))
            or _skills_list(meta_skills)
            or list(agent_skills)
        )
        what_i_can_do = [ensure_first_person(item, "我当前可以：", limit=180) for item in full_capability_inventory[:5]]
        if not what_i_can_do and first_person_summary:
            what_i_can_do = profile_text_items(first_person_summary, limit=5, item_limit=180)
            what_i_can_do = [ensure_first_person(item, "我当前可以：", limit=180) for item in what_i_can_do]
        return {
            "profile_source": "structured_fields_fallback",
            "fallback_reason": reason,
            "source_release_id": str(current_release.get("release_id") or "").strip(),
            "source_release_version": str(current_release.get("version_label") or meta["latest_release_version"] or "").strip(),
            "source_ref": str(current_release.get("public_profile_ref") or current_release.get("capability_snapshot_ref") or meta["active_role_profile_ref"] or "").strip(),
            "first_person_summary": first_person_summary or "我当前暂无可展示的正式发布角色介绍。",
            "what_i_can_do": what_i_can_do,
            "full_capability_inventory": [ensure_first_person(item, "我当前可以：", limit=220) for item in full_capability_inventory],
            "knowledge_scope": knowledge_scope,
            "agent_skills": profile_skills,
            "applicable_scenarios": scenario_items,
            "version_notes": str(current_release.get("version_notes") or current_release.get("change_summary") or meta["version_notes"] or "").strip(),
            "public_profile_ref": str(current_release.get("public_profile_ref") or "").strip(),
            "capability_snapshot_ref": str(current_release.get("capability_snapshot_ref") or "").strip(),
        }

    release_payloads = [build_release_payload(row, fallback_classification="release") for row in rows]
    normal_commit_payloads = [build_release_payload(row, fallback_classification="normal_commit") for row in normal_rows]

    active_profile_release_id = str(meta["active_role_profile_release_id"] or "").strip()
    latest_release_version = str(meta["latest_release_version"] or "").strip()
    active_release_payload = None
    if active_profile_release_id:
        active_release_payload = next(
            (item for item in release_payloads if str(item.get("release_id") or "").strip() == active_profile_release_id),
            None,
        )
    if active_release_payload is None and latest_release_version:
        active_release_payload = next(
            (item for item in release_payloads if str(item.get("version_label") or "").strip() == latest_release_version),
            None,
        )
    if active_release_payload is None:
        active_release_payload = release_payloads[0] if release_payloads else None

    role_profile_payload: dict[str, Any]
    snapshot_payload = load_json_ref(
        (active_release_payload or {}).get("capability_snapshot_ref") or meta["active_role_profile_ref"]
    )
    if snapshot_payload and (
        str(snapshot_payload.get("first_person_summary") or "").strip()
        or isinstance(snapshot_payload.get("full_capability_inventory"), list)
    ):
        role_profile_payload = {
            "profile_source": "latest_release_report",
            "fallback_reason": "",
            "source_release_id": str((active_release_payload or {}).get("release_id") or active_profile_release_id or "").strip(),
            "source_release_version": str((active_release_payload or {}).get("version_label") or latest_release_version or "").strip(),
            "source_ref": str(
                (active_release_payload or {}).get("public_profile_ref")
                or (active_release_payload or {}).get("capability_snapshot_ref")
                or meta["active_role_profile_ref"]
                or ""
            ).strip(),
            "first_person_summary": ensure_first_person(snapshot_payload.get("first_person_summary"), "我当前的核心能力是：", limit=320),
            "what_i_can_do": [
                ensure_first_person(item, "我当前可以：", limit=180)
                for item in profile_text_items(snapshot_payload.get("what_i_can_do") or snapshot_payload.get("full_capability_inventory"), limit=5, item_limit=180)
            ],
            "full_capability_inventory": [
                ensure_first_person(item, "我当前可以：", limit=220)
                for item in profile_text_items(snapshot_payload.get("full_capability_inventory"), limit=12, item_limit=220)
            ],
            "knowledge_scope": ensure_first_person(snapshot_payload.get("knowledge_scope"), "我当前覆盖的知识范围是：", limit=320),
            "agent_skills": _skills_list(snapshot_payload.get("agent_skills") or (active_release_payload or {}).get("skills") or meta_skills or agent_skills),
            "applicable_scenarios": profile_text_items(snapshot_payload.get("applicable_scenarios"), limit=6, item_limit=140),
            "version_notes": str(snapshot_payload.get("version_notes") or snapshot_payload.get("change_summary") or "").strip(),
            "public_profile_ref": str((active_release_payload or {}).get("public_profile_ref") or "").strip(),
            "capability_snapshot_ref": str((active_release_payload or {}).get("capability_snapshot_ref") or "").strip(),
        }
        if not role_profile_payload["what_i_can_do"] and role_profile_payload["full_capability_inventory"]:
            role_profile_payload["what_i_can_do"] = role_profile_payload["full_capability_inventory"][:5]
        if not role_profile_payload["applicable_scenarios"]:
            role_profile_payload["applicable_scenarios"] = profile_text_items(meta["applicable_scenarios"], limit=6, item_limit=140)
    else:
        fallback_reason = "latest_release_report_missing" if active_release_payload else "no_released_profile"
        if active_release_payload and str((active_release_payload or {}).get("capability_snapshot_ref") or "").strip():
            fallback_reason = "latest_release_report_invalid"
        role_profile_payload = fallback_role_profile(active_release_payload, reason=fallback_reason)

    return {
        "agent": {
            "agent_id": str(meta["agent_id"] or ""),
            "agent_name": str(meta["agent_name"] or ""),
            "vector_icon": str(meta["vector_icon"] or ""),
            "workspace_path": str(meta["workspace_path"] or ""),
            "current_version": str(meta["current_version"] or ""),
            "latest_release_version": str(meta["latest_release_version"] or ""),
            "bound_release_version": str(meta["bound_release_version"] or ""),
            "lifecycle_state": normalize_lifecycle_state(meta["lifecycle_state"]),
            "training_gate_state": normalize_training_gate_state(meta["training_gate_state"]),
            "parent_agent_id": str(meta["parent_agent_id"] or ""),
            "core_capabilities": str(meta["core_capabilities"] or ""),
            "capability_summary": str(meta["capability_summary"] or ""),
            "knowledge_scope": str(meta["knowledge_scope"] or ""),
            "skills": [str(item or "").strip() for item in meta_skills if str(item or "").strip()],
            "agent_skills": agent_skills,
            "applicable_scenarios": str(meta["applicable_scenarios"] or ""),
            "version_notes": str(meta["version_notes"] or ""),
            "avatar_uri": str(meta["avatar_uri"] or ""),
            "git_available": bool(int(meta["git_available"] or 0)),
            "pre_release_state": str(meta["pre_release_state"] or ""),
            "pre_release_reason": str(meta["pre_release_reason"] or ""),
            "pre_release_checked_at": str(meta["pre_release_checked_at"] or ""),
            "pre_release_git_output": str(meta["pre_release_git_output"] or ""),
            "last_release_at": str(meta["last_release_at"] or ""),
            "active_role_profile_release_id": str(meta["active_role_profile_release_id"] or ""),
            "active_role_profile_ref": str(meta["active_role_profile_ref"] or ""),
            "role_profile": role_profile_payload,
            "updated_at": str(meta["updated_at"] or ""),
        },
        "releases": release_payloads,
        "normal_commits": normal_commit_payloads,
        "page": safe_page,
        "page_size": safe_size,
        "release_total": release_total,
        "normal_commit_total": normal_total,
        "total": release_total,
        "has_more": offset + len(rows) < release_total,
    }


def set_training_agent_avatar(
    cfg: AppConfig,
    *,
    agent_id: str,
    avatar_uri: str = "",
    upload_name: str = "",
    upload_content_type: str = "",
    upload_base64: str = "",
    operator: str = "web-user",
) -> dict[str, Any]:
    sync_training_agent_registry(cfg)
    pid = safe_token(str(agent_id or ""), "", 120)
    if not pid:
        raise TrainingCenterError(400, "agent_id required", "agent_id_required")

    def _detect_avatar_kind(binary: bytes) -> str:
        if binary.startswith(b"\x89PNG\r\n\x1a\n"):
            return "png"
        if len(binary) >= 3 and binary[:3] == b"\xff\xd8\xff":
            return "jpg"
        if len(binary) >= 12 and binary[:4] == b"RIFF" and binary[8:12] == b"WEBP":
            return "webp"
        return ""

    def _normalize_upload_avatar(
        *,
        file_name: str,
        content_type: str,
        payload_base64: str,
    ) -> tuple[str, dict[str, Any]]:
        raw_name = str(file_name or "").strip()
        raw_type = str(content_type or "").strip().lower()
        raw_payload = str(payload_base64 or "").strip()
        if not raw_payload:
            raise TrainingCenterError(400, "头像文件内容为空", "avatar_payload_empty")
        try:
            binary = base64.b64decode(raw_payload, validate=True)
        except (binascii.Error, ValueError):
            raise TrainingCenterError(400, "头像文件编码无效", "avatar_payload_invalid_base64")
        size_limit = 2 * 1024 * 1024
        size_bytes = len(binary)
        if size_bytes <= 0:
            raise TrainingCenterError(400, "头像文件内容为空", "avatar_payload_empty")
        if size_bytes > size_limit:
            raise TrainingCenterError(400, "头像文件超过 2MB 限制", "avatar_too_large", {"size": size_bytes})

        ext = ""
        if "." in raw_name:
            ext = str(raw_name.rsplit(".", 1)[-1] or "").strip().lower()
        if ext == "jpeg":
            ext = "jpg"
        if ext and ext not in {"png", "jpg", "webp"}:
            raise TrainingCenterError(
                400,
                "头像格式仅支持 png/jpg/webp",
                "avatar_type_not_allowed",
                {"filename": raw_name, "extension": ext},
            )

        detected = _detect_avatar_kind(binary)
        if detected not in {"png", "jpg", "webp"}:
            raise TrainingCenterError(400, "头像格式仅支持 png/jpg/webp", "avatar_type_not_allowed")

        if raw_type and raw_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise TrainingCenterError(
                400,
                "头像格式仅支持 png/jpg/webp",
                "avatar_content_type_not_allowed",
                {"content_type": raw_type},
            )
        if raw_type:
            type_to_kind = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
            expected_kind = type_to_kind.get(raw_type, "")
            if expected_kind and expected_kind != detected:
                raise TrainingCenterError(
                    400,
                    "头像文件类型与内容不一致",
                    "avatar_content_mismatch",
                    {"content_type": raw_type, "detected": detected},
                )
        if ext and ext != detected:
            raise TrainingCenterError(
                400,
                "头像后缀与文件内容不一致",
                "avatar_extension_mismatch",
                {"extension": ext, "detected": detected},
            )

        mime = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}[detected]
        normalized = base64.b64encode(binary).decode("ascii")
        avatar_data_uri = f"data:{mime};base64,{normalized}"
        detail = {
            "filename": raw_name,
            "content_type": mime,
            "size": size_bytes,
        }
        return avatar_data_uri, detail

    avatar_text = str(avatar_uri or "").strip()
    upload_payload = str(upload_base64 or "").strip()
    upload_detail: dict[str, Any] | None = None
    if upload_payload:
        avatar_text, upload_detail = _normalize_upload_avatar(
            file_name=str(upload_name or "").strip(),
            content_type=str(upload_content_type or "").strip(),
            payload_base64=upload_payload,
        )
    if avatar_text and len(avatar_text) > (2 * 1024 * 1024 * 2):
        raise TrainingCenterError(400, "avatar_uri too long", "avatar_uri_too_long")
    operator_text = safe_token(str(operator or "web-user"), "web-user", 80)

    now_text = iso_ts(now_local())
    conn = connect_db(cfg.root)
    try:
        agent = _resolve_training_agent(conn, pid)
        if agent is None:
            raise TrainingCenterError(404, "agent not found", "agent_not_found", {"agent_id": pid})
        target_agent_id = str(agent.get("agent_id") or "").strip()
        conn.execute(
            """
            UPDATE agent_registry
            SET avatar_uri=?,
                updated_at=?
            WHERE agent_id=?
            """,
            (avatar_text, now_text, target_agent_id),
        )
        conn.commit()
        updated = _resolve_training_agent(conn, target_agent_id) or {}
    finally:
        conn.close()

    audit_id = append_training_center_audit(
        cfg.root,
        action="set_avatar",
        operator=operator_text,
        target_id=pid,
        detail={
            "avatar_uri": _short_text(avatar_text, 240),
            "cleared": not bool(avatar_text),
            "upload": upload_detail or {},
        },
    )
    return {
        "agent_id": str(updated.get("agent_id") or pid),
        "avatar_uri": str(updated.get("avatar_uri") or avatar_text),
        "audit_id": audit_id,
        "agent": updated,
    }
