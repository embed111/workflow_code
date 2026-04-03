
from ..services.work_record_store import (
    append_workflow_event_log_record,
    ensure_store,
    latest_results_indexed,
    migrate_legacy_local_work_records,
    new_sessions_24h_indexed,
    pending_counts_indexed,
    unique_system_run_path,
    workflow_events_path,
)


_AVAILABLE_AGENT_CACHE_TTL_S = max(
    0.0,
    float(os.getenv("WORKFLOW_AVAILABLE_AGENT_CACHE_TTL_S") or 30.0),
)
_AVAILABLE_AGENT_CACHE_LOCK = threading.Lock()
_AVAILABLE_AGENT_CACHE: dict[tuple[str, str, str], dict[str, Any]] = {}


def analysis_run_id() -> str:
    ts = now_local()
    return f"ar-{date_key(ts)}-{ts.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"


def event_file(root: Path) -> Path:
    ensure_store(root)
    return workflow_events_path(root)


def unique_run_file(root: Path, prefix: str) -> Path:
    ensure_store(root)
    return unique_system_run_path(root, prefix)


def persist_event(root: Path, event: dict[str, Any]) -> None:
    append_workflow_event_log_record(root, dict(event or {}))


_AGENT_DUTY_KEYWORDS = (
    "职责边界",
    "核心职责",
    "职责",
    "角色定位",
    "角色",
    "目标",
)

_AGENT_ROLE_HEADINGS = ("角色定位", "角色身份", "角色")
_AGENT_GOAL_HEADINGS = ("会话目标", "任务目标", "目标", "使命", "mission")
_AGENT_DUTY_HEADINGS = ("职责边界", "核心职责", "关键约束", "决策边界", "职责范围", "职责")
_AGENT_LIMIT_HEADINGS = ("限制内容", "约束", "limits", "constraints")
_AGENT_MUST_HEADINGS = ("必须", "must", "硬性要求", "required")
_AGENT_MUST_NOT_HEADINGS = ("不得", "禁止", "mustnot", "must_not", "prohibited")
_AGENT_PRECONDITION_HEADINGS = ("前置条件", "前提", "先决条件", "precondition", "preconditions")
_CONSTRAINT_MUST_TERMS = ("必须", "应当", "务必", "must", "required")
_CONSTRAINT_MUST_NOT_TERMS = (
    "不得",
    "禁止",
    "不可",
    "不能",
    "严禁",
    "must not",
    "must_not",
    "mustnot",
    "prohibited",
)
_CONSTRAINT_PRECONDITION_TERMS = ("前置", "前提", "先决", "需先", "precondition", "prerequisite", "before")


# Policy contract parsing/clarity logic is extracted to services/policy_contract_runtime.py.


def discover_agents(
    agents_root: Path,
    *,
    cache_root: Path | None = None,
    analyze_policy: bool = True,
    target_agent_name: str = "",
) -> list[dict[str, Any]]:
    from ..services.policy_analysis import discover_agents as _discover_agents

    return _discover_agents(
        agents_root,
        cache_root=cache_root,
        analyze_policy=analyze_policy,
        target_agent_name=target_agent_name,
    )


def current_agent_search_root(cfg: AppConfig, state: RuntimeState) -> Path | None:
    with state.config_lock:
        return cfg.agent_search_root


def current_agent_search_root_text(cfg: AppConfig, state: RuntimeState) -> str:
    with state.config_lock:
        root = cfg.agent_search_root
        requested_text = str(getattr(cfg, "agent_search_root_requested_text", "") or "").strip()
    return agent_search_root_text(root) or requested_text


def current_agent_search_root_status(cfg: AppConfig, state: RuntimeState) -> tuple[Path | None, bool, str]:
    root = current_agent_search_root(cfg, state)
    ready, error_code = agent_search_root_state(root)
    return root, ready, error_code


def current_allow_manual_policy_input(cfg: AppConfig, state: RuntimeState) -> bool:
    with state.config_lock:
        return bool(cfg.allow_manual_policy_input)


def current_runtime_environment_name(cfg: AppConfig, state: RuntimeState) -> str:
    with state.config_lock:
        value = getattr(cfg, "runtime_environment", DEFAULT_RUNTIME_ENVIRONMENT)
    return normalize_runtime_environment(value)


def current_show_test_data(cfg: AppConfig, state: RuntimeState) -> bool:
    with state.config_lock:
        return bool(cfg.show_test_data)


def current_show_test_data_source(cfg: AppConfig, state: RuntimeState) -> str:
    with state.config_lock:
        value = str(getattr(cfg, "show_test_data_source", "") or "").strip()
    return value or SHOW_TEST_DATA_SOURCE_ENVIRONMENT_POLICY


def show_test_data_policy_fields(cfg: AppConfig, state: RuntimeState) -> dict[str, Any]:
    return {
        "environment": current_runtime_environment_name(cfg, state),
        "show_test_data": bool(current_show_test_data(cfg, state)),
        "show_test_data_source": current_show_test_data_source(cfg, state),
    }


def show_test_data_toggle_removed_payload(
    cfg: AppConfig,
    state: RuntimeState,
    *,
    requested_value: Any | None = None,
) -> dict[str, Any]:
    payload = {
        "ok": False,
        "error": "show_test_data runtime toggle removed; use environment policy",
        "code": "show_test_data_toggle_removed",
        "deprecated": True,
        "read_only": True,
        **show_test_data_policy_fields(cfg, state),
    }
    if requested_value is not None:
        payload["requested_show_test_data"] = bool(requested_value)
    return payload


def set_show_test_data(
    cfg: AppConfig,
    state: RuntimeState,
    value: bool,
) -> tuple[bool, bool]:
    _ignored = bool(value)
    current_value = current_show_test_data(cfg, state)
    return current_value, current_value


def set_artifact_root(
    cfg: AppConfig,
    state: RuntimeState,
    requested_root: str,
) -> dict[str, Any]:
    text = str(requested_root or "").strip()
    if not text:
        raise SessionGateError(400, "artifact_root required", "artifact_root_required")
    try:
        candidate = normalize_abs_path(text, base=WORKFLOW_PROJECT_ROOT)
        artifact_root, workspace_root = ensure_artifact_root_dirs(candidate)
    except Exception as exc:
        raise SessionGateError(
            400,
            f"artifact_root invalid: {exc}",
            "artifact_root_invalid",
        ) from exc
    previous = resolve_artifact_root_path(cfg.root)
    with state.config_lock:
        try:
            save_runtime_config(cfg.root, {"artifact_root": artifact_root.as_posix()})
        except Exception as exc:
            raise SessionGateError(
                500,
                f"artifact_root save failed: {exc}",
                "artifact_root_save_failed",
            ) from exc
    try:
        assignment_workspace_sync = migrate_assignment_workspace_records(
            cfg.root,
            artifact_root,
            previous_artifact_root=previous,
        )
    except Exception as exc:
        raise SessionGateError(
            500,
            f"artifact_root assignment sync failed: {exc}",
            "artifact_root_assignment_sync_failed",
            {
                "artifact_root": artifact_root.as_posix(),
                "previous_artifact_root": previous.as_posix(),
            },
        ) from exc
    append_change_log(
        cfg.root,
        "artifact_root_changed",
        f"from={previous.as_posix()}, to={artifact_root.as_posix()}, workspace={workspace_root.as_posix()}",
    )
    ensure_store(cfg.root)
    legacy_work_record_sync = migrate_legacy_local_work_records(cfg.root)
    if legacy_work_record_sync.get("migrated_roots"):
        append_change_log(
            cfg.root,
            "artifact_root_work_records_migrated",
            (
                f"roots={','.join(legacy_work_record_sync.get('migrated_roots') or [])}, "
                f"sessions={legacy_work_record_sync.get('migrated_sessions',0)}, "
                f"analyses={legacy_work_record_sync.get('migrated_analyses',0)}, "
                f"runs={legacy_work_record_sync.get('migrated_runs',0)}"
            ),
        )
    if int(assignment_workspace_sync.get("moved_count") or 0) > 0:
        append_change_log(
            cfg.root,
            "assignment_workspace_records_migrated",
            (
                f"target={assignment_workspace_sync.get('target_root')}, "
                f"moved={assignment_workspace_sync.get('moved_count')}, "
                f"skipped_existing={assignment_workspace_sync.get('skipped_existing_count')}"
            ),
        )
    return {
        "ok": True,
        "artifact_root": artifact_root.as_posix(),
        "delivery_root": assignment_delivery_root(artifact_root).as_posix(),
        "previous_artifact_root": previous.as_posix(),
        "workspace_root": workspace_root.as_posix(),
        "artifact_root_structure_path": artifact_root_structure_file_path(artifact_root).as_posix(),
        "path_validation_status": "ok",
        "workspace_ready": True,
        "default_artifact_root": DEFAULT_ARTIFACT_ROOT.as_posix(),
        "assignment_workspace_sync": assignment_workspace_sync,
    }


def resolve_include_test_data(
    query: dict[str, list[str]],
    cfg: AppConfig,
    state: RuntimeState,
) -> bool:
    _unused_query = query
    return bool(current_show_test_data(cfg, state))


def set_agent_search_root(
    cfg: AppConfig,
    state: RuntimeState,
    value: Path,
) -> tuple[Path | None, Path]:
    new_root = value.resolve(strict=False)
    with state.config_lock:
        old_root = cfg.agent_search_root
        save_runtime_config(cfg.root, {"agent_search_root": new_root.as_posix()})
        cfg.agent_search_root = new_root
        cfg.agent_search_root_requested_text = new_root.as_posix()
    invalidate_available_agents_cache(config_root=cfg.root)
    return old_root, new_root


class QuietDisconnectHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:
        _exc_type, exc, _tb = sys.exc_info()
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        if isinstance(exc, OSError):
            if getattr(exc, "winerror", None) in {10053, 10054}:
                return
            if getattr(exc, "errno", None) in {32, 103, 104}:
                return
        super().handle_error(request, client_address)


def set_allow_manual_policy_input(
    cfg: AppConfig,
    state: RuntimeState,
    value: bool,
) -> tuple[bool, bool]:
    new_value = bool(value)
    with state.config_lock:
        old_value = bool(cfg.allow_manual_policy_input)
        cfg.allow_manual_policy_input = new_value
    return old_value, new_value


def _available_agent_cache_key(cfg: AppConfig, *, target_agent_name: str = "") -> tuple[str, str, str]:
    cfg_root_text = cfg.root.resolve(strict=False).as_posix().lower()
    agent_root = cfg.agent_search_root
    agent_root_text = (
        agent_root.resolve(strict=False).as_posix().lower()
        if isinstance(agent_root, Path)
        else ""
    )
    target_name = safe_token(str(target_agent_name or ""), "", 80).lower()
    return (cfg_root_text, agent_root_text, target_name)


def invalidate_available_agents_cache(
    *,
    config_root: Path | None = None,
    agent_root: Path | None = None,
    target_agent_name: str = "",
) -> int:
    config_root_text = (
        config_root.resolve(strict=False).as_posix().lower()
        if isinstance(config_root, Path)
        else ""
    )
    agent_root_text = (
        agent_root.resolve(strict=False).as_posix().lower()
        if isinstance(agent_root, Path)
        else ""
    )
    target_name = safe_token(str(target_agent_name or ""), "", 80).lower()
    deleted = 0
    with _AVAILABLE_AGENT_CACHE_LOCK:
        matched_keys = [
            key
            for key in list(_AVAILABLE_AGENT_CACHE.keys())
            if (not config_root_text or key[0] == config_root_text)
            and (not agent_root_text or key[1] == agent_root_text)
            and (not target_name or key[2] == target_name)
        ]
        for key in matched_keys:
            _AVAILABLE_AGENT_CACHE.pop(key, None)
            deleted += 1
    return deleted


def list_available_agents(
    cfg: AppConfig,
    *,
    analyze_policy: bool = False,
    target_agent_name: str = "",
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    if cfg.agent_search_root is None:
        return []
    target_name = safe_token(str(target_agent_name or ""), "", 80)
    use_cache = not analyze_policy and not force_refresh and _AVAILABLE_AGENT_CACHE_TTL_S > 0
    cache_key = _available_agent_cache_key(cfg, target_agent_name=target_name)
    if use_cache:
        now_ts = time.time()
        with _AVAILABLE_AGENT_CACHE_LOCK:
            cached = _AVAILABLE_AGENT_CACHE.get(cache_key)
            if cached and float(cached.get("expires_at") or 0.0) > now_ts:
                cached_items = cached.get("items")
                if isinstance(cached_items, list):
                    return cached_items
    items = discover_agents(
        cfg.agent_search_root,
        cache_root=cfg.root,
        analyze_policy=analyze_policy,
        target_agent_name=target_name,
    )
    if not bool(cfg.show_test_data):
        filtered_items: list[dict[str, Any]] = []
        for item in items:
            agents_path_text = str(item.get("agents_md_path") or "").strip()
            if not agents_path_text:
                continue
            workspace_path = Path(agents_path_text).resolve(strict=False).parent
            if is_system_or_test_workspace(
                workspace_path.as_posix(),
                agent_search_root=cfg.agent_search_root,
            ):
                continue
            filtered_items.append(item)
        items = filtered_items
    if use_cache:
        with _AVAILABLE_AGENT_CACHE_LOCK:
            _AVAILABLE_AGENT_CACHE[cache_key] = {
                "expires_at": time.time() + _AVAILABLE_AGENT_CACHE_TTL_S,
                "items": items,
            }
    return items


def load_agent_with_policy(cfg: AppConfig, agent_name: str) -> dict[str, Any] | None:
    name = safe_token(str(agent_name or ""), "", 80)
    if not name:
        return None
    items = list_available_agents(
        cfg,
        analyze_policy=True,
        target_agent_name=name,
    )
    if not items:
        return None
    for item in items:
        if str(item.get("agent_name") or "") == name:
            return item
    return items[0]



_TRAINING_CENTER_RUNTIME_BOUND = False


def bind_training_center_runtime_once() -> None:
    global _TRAINING_CENTER_RUNTIME_BOUND
    if _TRAINING_CENTER_RUNTIME_BOUND:
        return
    bind_training_center_runtime(
        {
            "connect_db": connect_db,
            "safe_token": safe_token,
            "now_local": now_local,
            "iso_ts": iso_ts,
            "date_key": date_key,
            "path_in_scope": path_in_scope,
            "extract_agent_policy_fields": extract_agent_policy_fields,
            "relative_to_root": relative_to_root,
            "event_file": event_file,
            "persist_event": persist_event,
            "event_id": event_id,
            "list_available_agents": list_available_agents,
            "TRAINER_SOURCE_ROOT": TRAINER_SOURCE_ROOT,
            "TRAINING_PRIORITY_LEVELS": TRAINING_PRIORITY_LEVELS,
            "TRAINING_PRIORITY_RANK": TRAINING_PRIORITY_RANK,
        }
    )
    _TRAINING_CENTER_RUNTIME_BOUND = True

_POLICY_REANALYZE_REASON_CODES = {
    "agents_hash_mismatch",
    "cached_before_agents_mtime",
    "cached_at_missing",
    "agents_mtime_missing",
    "cache_payload_invalid_json",
    "cache_payload_incomplete",
    "cache_parse_status_missing",
    "cache_clarity_score_invalid",
    "cache_prompt_version_mismatch",
    "cache_extract_source_mismatch",
    "cache_write_failed",
    "manual_clear",
}
_POLICY_REANALYZE_AGENTS_UPDATED_CODES = {
    "agents_hash_mismatch",
    "cached_before_agents_mtime",
}



# Runtime domain logic is split into layered modules.
from ..services import policy_session_runtime as _policy_session_runtime
from ..services import policy_contract_runtime as _policy_contract_runtime
from ..services import session_orchestration as _session_orchestration
from ..services import task_orchestration as _task_orchestration
from ..services import chat_session_runtime as _chat_session_runtime
from ..services import training_workflow as _training_workflow
from ..services import assignment_service as _assignment_service
from ..services import schedule_service as _schedule_service
from ..services import defect_service as _defect_service
from ..infra import audit_runtime as _audit_runtime

_RUNTIME_DOMAIN_MODULES = (
    _policy_contract_runtime,
    _policy_session_runtime,
    _session_orchestration,
    _task_orchestration,
    _chat_session_runtime,
    _training_workflow,
    _assignment_service,
    _schedule_service,
    _defect_service,
    _audit_runtime,
)

for _runtime_domain_module in _RUNTIME_DOMAIN_MODULES:
    _runtime_domain_module.bind_runtime_symbols(globals())

for _runtime_domain_module in _RUNTIME_DOMAIN_MODULES:
    for _name, _value in _runtime_domain_module.__dict__.items():
        if _name.startswith("__") or _name == "bind_runtime_symbols":
            continue
        globals()[_name] = _value

# Re-bind once after exporting symbols so cross-domain function references
# are visible in every extracted module namespace.
for _runtime_domain_module in _RUNTIME_DOMAIN_MODULES:
    _runtime_domain_module.bind_runtime_symbols(globals())

del _runtime_domain_module, _name, _value

def make_handler(cfg: AppConfig, state: RuntimeState) -> type[BaseHTTPRequestHandler]:
    bind_training_center_runtime_once()

    class Handler(BaseHTTPRequestHandler):
        def _safe_write(self, raw: bytes) -> None:
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # Client disconnected; ignore to avoid noisy server tracebacks.
                return

        def send_json(self, status: int, payload: dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self._safe_write(raw)

        def send_html(self, text: str) -> None:
            raw = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self._safe_write(raw)

        def send_text(self, status: int, text: str, content_type: str) -> None:
            raw = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self._safe_write(raw)

        def read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length > 0 else b""
            if not body:
                return {}
            obj = json.loads(body.decode("utf-8"))
            return obj if isinstance(obj, dict) else {}

        def root_status(self) -> tuple[Path | None, bool, str, str]:
            root, ready, error_code = current_agent_search_root_status(cfg, state)
            return root, ready, error_code, agent_search_root_text(root)

        def root_not_ready_payload(self) -> dict[str, Any]:
            _root, ready, error_code, root_text = self.root_status()
            if ready:
                return {}
            return {
                "ok": False,
                "error": agent_search_root_block_message(error_code),
                "code": error_code or AGENT_SEARCH_ROOT_NOT_SET_CODE,
                "agent_search_root": root_text,
                "agent_search_root_ready": False,
                "features_locked": True,
            }

        def ensure_root_ready(self) -> bool:
            payload = self.root_not_ready_payload()
            if payload:
                self.send_json(409, payload)
                return False
            return True

        def payload_common(self, body: dict[str, Any]) -> tuple[str, str, str, str, bool]:
            agent = safe_token(str(body.get("agent_name") or body.get("agent") or ""), "", 80)
            session_id = safe_token(str(body.get("session_id") or ""), "", 140)
            focus = str(body.get("focus") or cfg.focus).strip()[:180]
            agent_search_root = str(
                body.get("agent_search_root")
                or body.get("agentSearchRoot")
                or body.get("target_path")
                or body.get("targetPath")
                or ""
            ).strip()
            is_test_data = parse_bool_flag(
                body.get("is_test_data", body.get("isTestData")),
                default=False,
            )
            if not focus:
                focus = cfg.focus
            return agent, session_id, focus, agent_search_root, is_test_data

        def resolve_session(
            self,
            body: dict[str, Any],
            *,
            allow_create: bool,
        ) -> tuple[dict[str, Any], str] | None:
            (
                requested_agent,
                requested_session_id,
                focus,
                requested_agent_search_root,
                requested_is_test_data,
            ) = self.payload_common(body)
            try:
                session, _created = ensure_session(
                    cfg,
                    state,
                    requested_session_id=requested_session_id,
                    requested_agent_name=requested_agent,
                    requested_agent_search_root=requested_agent_search_root,
                    requested_is_test_data=requested_is_test_data,
                    allow_create=allow_create,
                )
            except SessionGateError as exc:
                persist_event(
                    cfg.root,
                    {
                        "event_id": event_id(),
                        "timestamp": iso_ts(now_local()),
                        "session_id": requested_session_id or "sess-gate",
                        "actor": "workflow",
                        "stage": "governance",
                        "action": "session_gate_blocked",
                        "status": "failed",
                        "latency_ms": 0,
                        "task_id": "",
                        "reason_tags": [exc.code],
                        "ref": "",
                    },
                )
                self.send_json(
                    exc.status_code,
                    {
                        "ok": False,
                        "error": str(exc),
                        "code": exc.code,
                        "agent_search_root": current_agent_search_root_text(cfg, state),
                        "available_agents": [
                            {
                                "agent_name": item["agent_name"],
                                "agents_hash": item["agents_hash"],
                                "agents_loaded_at": item["agents_loaded_at"],
                            }
                            for item in list_available_agents(cfg)
                        ],
                        **exc.extra,
                    },
                )
                return None
            return session, focus

        def enforce_session_policy_reanalyze(self, session: dict[str, Any], route: str) -> bool:
            guard = session_policy_reanalyze_guard(cfg, session)
            if not bool(guard.get("required")):
                return True
            reason = str(guard.get("message") or "当前会话角色策略缓存已过期，请先重新分析。")
            reason_codes = [
                str(code).strip()
                for code in (guard.get("reason_codes") or [])
                if str(code or "").strip()
            ]
            tags = [AGENT_POLICY_REANALYZE_REQUIRED_CODE]
            tags.extend(reason_codes[:4])
            persist_event(
                cfg.root,
                {
                    "event_id": event_id(),
                    "timestamp": iso_ts(now_local()),
                    "session_id": str(session.get("session_id") or "sess-gate"),
                    "actor": "workflow",
                    "stage": "governance",
                    "action": "session_policy_reanalyze_blocked",
                    "status": "failed",
                    "latency_ms": 0,
                    "task_id": "",
                    "reason_tags": tags,
                    "ref": "",
                },
            )
            self.send_json(
                409,
                {
                    "ok": False,
                    "error": reason,
                    "code": AGENT_POLICY_REANALYZE_REQUIRED_CODE,
                    "session_id": str(session.get("session_id") or ""),
                    "agent_name": str(session.get("agent_name") or ""),
                    "session_agents_hash": str(session.get("agents_hash") or ""),
                    "action_hint": "请在会话入口点击“生成缓存”并等待分析完成后再发送。",
                    "policy_reanalyze": guard,
                },
            )
            return False

        def refresh_after_round(self) -> None:
            sync_analysis_tasks(cfg.root)
            sync_training_workflows(cfg.root)
            refresh_status(cfg)

        def do_GET(self) -> None:  # noqa: N802
            from ..api.router import dispatch_get

            dispatch_get(self, cfg, state)

        def do_POST(self) -> None:  # noqa: N802
            from ..api.router import dispatch_post

            dispatch_post(self, cfg, state)

        def do_DELETE(self) -> None:  # noqa: N802
            from ..api.router import dispatch_delete

            dispatch_delete(self, cfg, state)

        def log_message(self, fmt: str, *args: object) -> None:
            return

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Workflow web workbench")
    parser.add_argument("--root", default=".runtime", help="runtime root")
    parser.add_argument("--entry-script", default="scripts/workflow_entry_cli.py", help="default entry script")
    parser.add_argument(
        "--agent-search-root",
        "--default-agents-root",
        "--agents-root",
        dest="agent_search_root",
        default="",
        help="scan root for AGENTS.md (default: runtime-config -> WORKFLOW_AGENTS_ROOT -> C:/work/agents; invalid path => empty/unset)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=8090, help="bind port")
    parser.add_argument("--focus", default=DEFAULT_WORKFLOW_FOCUS, help="default focus")
    parser.add_argument("--reconcile-interval-s", type=int, default=86400, help="auto reconcile interval")
    parser.add_argument(
        "--allow-manual-policy-input",
        default="",
        help="allow manual policy fallback input (1/0, true/false). default from WORKFLOW_ALLOW_MANUAL_POLICY_INPUT",
    )
    return parser.parse_args()


def resolve_entry_script(runtime_root: Path, raw_entry_script: str) -> Path:
    token = str(raw_entry_script or "").strip() or "scripts/workflow_entry_cli.py"
    source = Path(token)
    this_dir = WORKFLOW_APP_ROOT
    candidates: list[Path] = []
    if source.is_absolute():
        candidates.append(source.resolve(strict=False))
    else:
        candidates.append((runtime_root / source).resolve(strict=False))
        candidates.append((this_dir / source.name).resolve(strict=False))
        candidates.append((WORKFLOW_PROJECT_ROOT / source).resolve(strict=False))
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    checked = ", ".join(item.as_posix() for item in candidates)
    raise SystemExit(f"entry script not found: {token}; checked=[{checked}]")


def resolve_startup_agent_search_root(raw: str, *, base: Path) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        candidate = normalize_abs_path(text, base=base)
    except Exception:
        return None
    ready, _code = agent_search_root_state(candidate)
    if not ready:
        return None
    return candidate


def main() -> None:
    from ..services import runtime_upgrade_service as runtime_upgrade

    args = parse_args()
    root = Path(args.root).resolve()
    entry_script = resolve_entry_script(root, args.entry_script)
    runtime_cfg = load_runtime_config(root)
    cli_root_text = str(args.agent_search_root or "").strip()
    configured_root_text = str(runtime_cfg.get("agent_search_root") or "").strip()
    requested_root_text = cli_root_text or configured_root_text or DEFAULT_AGENTS_ROOT.as_posix()
    agent_search_root = resolve_startup_agent_search_root(requested_root_text, base=root)
    if requested_root_text and agent_search_root is None:
        print(
            f"web> agent_search_root unavailable on startup, fallback to empty: {requested_root_text}",
            flush=True,
        )
    requested_root_text_for_state = (
        agent_search_root.as_posix()
        if isinstance(agent_search_root, Path)
        else cli_root_text or configured_root_text
    )
    allow_manual_text = str(args.allow_manual_policy_input or "").strip()
    if allow_manual_text:
        allow_manual_policy_input = parse_bool_flag(
            allow_manual_text,
            default=ALLOW_MANUAL_POLICY_INPUT_DEFAULT,
        )
    else:
        allow_manual_policy_input = ALLOW_MANUAL_POLICY_INPUT_DEFAULT
    runtime_environment = normalize_runtime_environment(runtime_upgrade.current_runtime_environment())
    show_test_data, show_test_data_source = resolve_show_test_data_policy(
        runtime_cfg,
        environment=runtime_environment,
    )
    if runtime_environment == "prod" and parse_bool_flag(runtime_cfg.get("show_test_data"), default=False):
        print(
            "web> prod environment ignores show_test_data=true in runtime-config; forced false",
            flush=True,
        )
    cfg = AppConfig(
        root=root,
        entry_script=entry_script,
        agent_search_root=agent_search_root,
        agent_search_root_requested_text=requested_root_text_for_state,
        show_test_data=show_test_data,
        host=args.host,
        port=int(args.port),
        focus=str(args.focus),
        reconcile_interval_s=max(60, int(args.reconcile_interval_s)),
        allow_manual_policy_input=allow_manual_policy_input,
        runtime_environment=runtime_environment,
        show_test_data_source=show_test_data_source,
    )
    state = RuntimeState()
    ensure_dirs(cfg.root)
    artifact_settings = get_artifact_root_settings(cfg.root)
    if str(artifact_settings.get("path_validation_status") or "").strip() != "ok":
        requested_artifact_root = str(artifact_settings.get("requested_artifact_root") or "").strip()
        validation_error = str(artifact_settings.get("path_validation_error") or "").strip()
        detail = requested_artifact_root or str(artifact_settings.get("artifact_root") or "").strip()
        if validation_error:
            detail = f"{detail} ({validation_error})"
        print(
            f"web> artifact_root unavailable on startup, fallback to default: {detail}",
            flush=True,
        )
    runtime_patch = {
        "show_test_data": bool(show_test_data),
        "artifact_root": str(artifact_settings.get("artifact_root") or ""),
    }
    if isinstance(agent_search_root, Path):
        runtime_patch["agent_search_root"] = agent_search_root.as_posix()
    elif configured_root_text:
        runtime_patch["agent_search_root"] = configured_root_text
    elif cli_root_text:
        runtime_patch["agent_search_root"] = cli_root_text
    save_runtime_config(cfg.root, runtime_patch)
    try:
        assignment_workspace_sync = migrate_assignment_workspace_records(
            cfg.root,
            Path(str(artifact_settings.get("artifact_root") or DEFAULT_ARTIFACT_ROOT.as_posix())),
        )
        if int(assignment_workspace_sync.get("moved_count") or 0) > 0:
            append_change_log(
                cfg.root,
                "startup_assignment_workspace_records_migrated",
                (
                    f"target={assignment_workspace_sync.get('target_root')}, "
                    f"moved={assignment_workspace_sync.get('moved_count')}, "
                    f"skipped_existing={assignment_workspace_sync.get('skipped_existing_count')}"
                ),
            )
    except Exception as exc:
        append_failure_case(cfg.root, "startup_assignment_workspace_records_migrate_failed", str(exc))
        append_change_log(cfg.root, "startup assignment workspace records migrate failed", str(exc))
    ensure_tables(cfg.root)
    ensure_store(cfg.root)
    try:
        legacy_work_record_sync = migrate_legacy_local_work_records(cfg.root)
        if legacy_work_record_sync.get("migrated_roots"):
            append_change_log(
                cfg.root,
                "startup_work_records_migrated",
                (
                    f"roots={','.join(legacy_work_record_sync.get('migrated_roots') or [])}, "
                    f"sessions={legacy_work_record_sync.get('migrated_sessions',0)}, "
                    f"analyses={legacy_work_record_sync.get('migrated_analyses',0)}, "
                    f"runs={legacy_work_record_sync.get('migrated_runs',0)}"
                ),
            )
    except Exception as exc:
        append_failure_case(cfg.root, "startup_work_records_migrate_failed", str(exc))
        append_change_log(cfg.root, "startup work-records migrate failed", str(exc))
    ensure_metric_files(cfg.root)
    bind_training_center_runtime_once()
    init_ab_state(cfg)
    refresh_status(cfg)
    sync_analysis_tasks(cfg.root)
    sync_training_workflows(cfg.root)
    with state.reconcile_lock:
        run_reconcile(cfg, "startup")
    if TEST_DATA_AUTO_CLEANUP_ENABLED and active_runtime_task_count(state) <= 0:
        try:
            cleanup_result = admin_cleanup_history(
                cfg.root,
                mode="test_data",
                delete_artifacts=True,
                delete_log_files=False,
                max_age_hours=TEST_DATA_MAX_AGE_HOURS,
                include_active_test_sessions=False,
            )
            deleted = int(cleanup_result.get("deleted_sessions") or 0)
            if deleted > 0:
                append_change_log(
                    cfg.root,
                    "startup test-data cleanup",
                    (
                        f"deleted_sessions={deleted}, "
                        f"max_age_hours={cleanup_result.get('max_age_hours')}, "
                        f"skipped_active={cleanup_result.get('skipped_active',0)}, "
                        f"skipped_recent={cleanup_result.get('skipped_recent',0)}"
                    ),
                )
        except Exception as exc:
            append_failure_case(cfg.root, "startup_testdata_cleanup_failed", str(exc))
            append_change_log(cfg.root, "startup test-data cleanup failed", str(exc))
    scheduler = start_reconcile_scheduler(cfg, state)
    schedule_worker = start_schedule_trigger_worker(cfg, state)
    setattr(state, "_runtime_shutdown_code", 0)
    setattr(state, "_runtime_shutdown_reason", "")
    QuietDisconnectHTTPServer.allow_reuse_address = True
    server = QuietDisconnectHTTPServer((cfg.host, cfg.port), make_handler(cfg, state))
    setattr(state, "_runtime_server_shutdown", server.shutdown)
    runtime_upgrade.runtime_process_start(host=cfg.host, port=cfg.port)
    print(f"web> http://{cfg.host}:{cfg.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        state.stop_event.set()
        scheduler.join(timeout=3)
        schedule_worker.join(timeout=3)
        server.server_close()
        runtime_upgrade.runtime_process_stop()
    exit_code = runtime_upgrade.requested_shutdown_code(state)
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
