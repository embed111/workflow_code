from __future__ import annotations

# NOTE: policy-analysis and agent-discovery chain extracted from workflow_web_server.py
# Keep runtime behavior compatible during phased refactor.
from ..bootstrap.web_server_runtime import *  # noqa: F401,F403


def _parse_agent_policy_cache_payload(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except Exception:
        return {}
    return {}


def _policy_cache_required_payload_keys() -> tuple[str, ...]:
    return (
        "duty_title",
        "duty_excerpt",
        "duty_text",
        "duty_truncated",
        "role_profile",
        "session_goal",
        "duty_constraints",
        "duty_constraints_text",
        "constraints",
        "parse_status",
        "parse_warnings",
        "evidence_snippets",
        "score_model",
        "score_total",
        "score_weights",
        "score_dimensions",
        "clarity_score",
        "clarity_details",
        "clarity_gate",
        "clarity_gate_reason",
        "risk_tips",
        "policy_extract_ok",
        "policy_error",
        "policy_extract_source",
        "policy_prompt_version",
        "analysis_chain",
        "policy_contract_status",
        "policy_contract_missing_fields",
        "policy_contract_issues",
        "policy_gate_state",
        "policy_gate_reason",
    )


def _has_stage_progress(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    stages = raw.get("stages")
    return isinstance(stages, list) and len(stages) > 0


def _resolve_trace_file(runtime_root: Path, raw_path: Any) -> Path | None:
    text = str(raw_path or "").strip()
    if not text:
        return None
    root = runtime_root.resolve(strict=False)
    path = Path(text)
    if not path.is_absolute():
        path = (root / path).resolve(strict=False)
    else:
        path = path.resolve(strict=False)
    if not path_in_scope(path, root):
        return None
    return path


def _file_mtime_ms(path: Path | None) -> int:
    if path is None:
        return 0
    try:
        if not path.exists() or not path.is_file():
            return 0
        return max(0, int(float(path.stat().st_mtime or 0.0) * 1000))
    except Exception:
        return 0


def _ensure_analysis_chain_ui_progress(payload: dict[str, Any], runtime_root: Path) -> None:
    if not isinstance(payload, dict):
        return
    chain = payload.get("analysis_chain")
    if not isinstance(chain, dict):
        return
    if _has_stage_progress(chain.get("ui_progress")):
        return
    files = chain.get("files")
    if not isinstance(files, dict):
        return

    prompt_ms = _file_mtime_ms(_resolve_trace_file(runtime_root, files.get("prompt")))
    stdout_ms = _file_mtime_ms(_resolve_trace_file(runtime_root, files.get("stdout")))
    raw_ms = _file_mtime_ms(_resolve_trace_file(runtime_root, files.get("codex_result_raw")))
    parsed_ms = _file_mtime_ms(_resolve_trace_file(runtime_root, files.get("parsed_result")))
    gate_ms = _file_mtime_ms(_resolve_trace_file(runtime_root, files.get("gate_decision")))

    marks = [ts for ts in (prompt_ms, stdout_ms, raw_ms, parsed_ms, gate_ms) if ts > 0]
    if not marks:
        return

    start_ms = min(marks)
    ready_end_ms = prompt_ms if prompt_ms > 0 else start_ms
    running_start_ms = prompt_ms if prompt_ms > 0 else 0
    running_end_ms = stdout_ms if stdout_ms > 0 else (raw_ms if raw_ms > 0 else (parsed_ms if parsed_ms > 0 else 0))
    analyzed_start_ms = running_end_ms if running_end_ms > 0 else (stdout_ms if stdout_ms > 0 else ready_end_ms)
    analyzed_end_ms = parsed_ms if parsed_ms > 0 else (gate_ms if gate_ms > 0 else analyzed_start_ms)
    done_end_ms = gate_ms if gate_ms > 0 else analyzed_end_ms

    if ready_end_ms < start_ms:
        ready_end_ms = start_ms
    if running_start_ms > 0 and running_end_ms < running_start_ms:
        running_end_ms = running_start_ms
    if analyzed_start_ms <= 0:
        analyzed_start_ms = ready_end_ms
    if analyzed_end_ms < analyzed_start_ms:
        analyzed_end_ms = analyzed_start_ms
    if done_end_ms < analyzed_end_ms:
        done_end_ms = analyzed_end_ms

    def _dur_ms(start_val: int, end_val: int) -> int:
        if start_val <= 0 or end_val <= 0 or end_val < start_val:
            return 0
        return int(end_val - start_val)

    parse_failed = str(payload.get("parse_status") or "").strip().lower() == "failed"
    blocked = str(payload.get("clarity_gate") or "").strip().lower() == "block"
    chain["ui_progress"] = {
        "source": "cache_trace_mtime",
        "active": False,
        "failed": bool(parse_failed or blocked),
        "started_at_ms": start_ms,
        "finished_at_ms": done_end_ms,
        "total_ms": _dur_ms(start_ms, done_end_ms),
        "stages": [
            {
                "index": 1,
                "key": "ready",
                "label": "codex与agent信息就绪",
                "started_at_ms": start_ms,
                "duration_ms": _dur_ms(start_ms, ready_end_ms),
            },
            {
                "index": 2,
                "key": "running",
                "label": "codex分析中",
                "started_at_ms": running_start_ms,
                "duration_ms": _dur_ms(running_start_ms, running_end_ms),
            },
            {
                "index": 3,
                "key": "analyzed",
                "label": "codex分析完成",
                "started_at_ms": analyzed_start_ms,
                "duration_ms": _dur_ms(analyzed_start_ms, analyzed_end_ms),
            },
            {
                "index": 4,
                "key": "done",
                "label": "角色分析结束",
                "started_at_ms": analyzed_end_ms,
                "duration_ms": _dur_ms(analyzed_end_ms, done_end_ms),
            },
        ],
    }
    payload["analysis_chain"] = chain


def _load_policy_cache_probe_rows(cache_root: Path | None) -> dict[str, dict[str, Any]]:
    if cache_root is None:
        return {}
    conn: sqlite3.Connection | None = None
    out: dict[str, dict[str, Any]] = {}
    try:
        conn = connect_db(cache_root)
        rows = conn.execute(
            """
            SELECT agent_path,agents_hash,agents_mtime,parse_status,clarity_score,cached_at,policy_payload_json
            FROM agent_policy_cache
            """
        ).fetchall()
        for row in rows:
            agent_path = str(row["agent_path"] or "").strip()
            if not agent_path:
                continue
            try:
                agents_mtime = float(row["agents_mtime"] or 0.0)
            except Exception:
                agents_mtime = 0.0
            try:
                cached_at = float(row["cached_at"] or 0.0)
            except Exception:
                cached_at = 0.0
            try:
                clarity_score = int(row["clarity_score"] or 0)
            except Exception:
                clarity_score = 0
            out[agent_path] = {
                "agents_hash": str(row["agents_hash"] or "").strip(),
                "agents_mtime": agents_mtime,
                "parse_status": str(row["parse_status"] or "").strip().lower(),
                "clarity_score": clarity_score,
                "cached_at": cached_at,
                "policy_payload_json": str(row["policy_payload_json"] or ""),
            }
    except Exception:
        return {}
    finally:
        if conn is not None:
            conn.close()
    return out


def build_agent_policy_payload(markdown_text: str) -> dict[str, Any]:
    duty_title, duty_excerpt, duty_text, duty_truncated = extract_agent_duty_info(markdown_text)
    policy_fields = extract_agent_policy_fields(markdown_text)
    role_profile = str(policy_fields.get("role_profile") or "")
    session_goal = str(policy_fields.get("session_goal") or "")
    duty_constraints_items = [
        str(item).strip()
        for item in (policy_fields.get("duty_constraints") or [])
        if str(item or "").strip()
    ]
    duty_constraints_text = str(policy_fields.get("duty_constraints_text") or "").strip()
    parse_status = str(policy_fields.get("parse_status") or "failed").strip().lower() or "failed"
    parse_warnings = [
        str(item).strip()
        for item in (policy_fields.get("parse_warnings") or [])
        if str(item or "").strip()
    ]
    constraints_raw = policy_fields.get("constraints")
    constraints = constraints_raw if isinstance(constraints_raw, dict) else {}
    evidence_raw = policy_fields.get("evidence_snippets")
    evidence_snippets = evidence_raw if isinstance(evidence_raw, dict) else {}
    score_model = str(policy_fields.get("score_model") or POLICY_SCORE_MODEL).strip() or POLICY_SCORE_MODEL
    score_total = int(policy_fields.get("score_total") or policy_fields.get("clarity_score") or 0)
    score_weights_raw = policy_fields.get("score_weights")
    score_weights = score_weights_raw if isinstance(score_weights_raw, dict) else {}
    score_dimensions_raw = policy_fields.get("score_dimensions")
    score_dimensions = score_dimensions_raw if isinstance(score_dimensions_raw, dict) else {}
    clarity_score = int(policy_fields.get("clarity_score") or 0)
    clarity_details_raw = policy_fields.get("clarity_details")
    clarity_details = clarity_details_raw if isinstance(clarity_details_raw, dict) else {}
    clarity_gate = str(policy_fields.get("clarity_gate") or "").strip().lower() or "block"
    clarity_gate_reason = str(policy_fields.get("clarity_gate_reason") or "").strip()
    risk_tips = [
        str(item).strip()
        for item in (policy_fields.get("risk_tips") or [])
        if str(item or "").strip()
    ]
    policy_extract_ok = bool(role_profile and session_goal and duty_constraints_text)
    if not duty_constraints_text and duty_constraints_items:
        duty_constraints_text = "\n".join(duty_constraints_items)
    if parse_status == "failed":
        policy_error = parse_warnings[0] if parse_warnings else "policy_extract_failed"
    else:
        policy_error = ""

    normalized_constraints = {
        "must": [],
        "must_not": [],
        "preconditions": [],
        "issues": [],
        "conflicts": [],
        "missing_evidence_count": int(constraints.get("missing_evidence_count") or 0),
        "total": int(constraints.get("total") or 0),
    }
    for key in ("must", "must_not", "preconditions"):
        entries = constraints.get(key) if isinstance(constraints.get(key), list) else []
        normalized_constraints[key] = [
            {
                "text": str((entry or {}).get("text") or "").strip(),
                "evidence": str((entry or {}).get("evidence") or "").strip(),
                "source_title": str((entry or {}).get("source_title") or "").strip(),
            }
            for entry in entries
            if isinstance(entry, dict) and str((entry or {}).get("text") or "").strip()
        ]
    issues = constraints.get("issues") if isinstance(constraints.get("issues"), list) else []
    normalized_constraints["issues"] = [
        {
            "code": str((item or {}).get("code") or "").strip(),
            "message": str((item or {}).get("message") or "").strip(),
        }
        for item in issues
        if isinstance(item, dict) and str((item or {}).get("code") or "").strip()
    ]
    conflicts = constraints.get("conflicts") if isinstance(constraints.get("conflicts"), list) else []
    normalized_constraints["conflicts"] = [str(item).strip() for item in conflicts if str(item or "").strip()]
    if normalized_constraints["total"] <= 0:
        normalized_constraints["total"] = (
            len(normalized_constraints["must"])
            + len(normalized_constraints["must_not"])
            + len(normalized_constraints["preconditions"])
        )

    normalized_score_weights: dict[str, float] = {}
    for key, _label in POLICY_SCORE_DIMENSION_META:
        normalized_score_weights[key] = float(score_weights.get(key) or POLICY_SCORE_WEIGHTS.get(key) or 0.0)

    normalized_score_dimensions: dict[str, Any] = {}
    for key, label in POLICY_SCORE_DIMENSION_META:
        dim_raw = score_dimensions.get(key) if isinstance(score_dimensions.get(key), dict) else {}
        evidence_map_raw = dim_raw.get("evidence_map") if isinstance(dim_raw.get("evidence_map"), list) else []
        evidence_map: list[dict[str, str]] = []
        seen_evidence: set[str] = set()
        for item in evidence_map_raw:
            if not isinstance(item, dict):
                continue
            ref_text = str((item or {}).get("ref") or "").strip()
            snippet_text = str((item or {}).get("snippet") or "").strip()
            if not snippet_text:
                continue
            unique_key = f"{ref_text}:{snippet_text}"
            if unique_key in seen_evidence:
                continue
            seen_evidence.add(unique_key)
            evidence_map.append(
                {
                    "ref": ref_text,
                    "snippet": snippet_text,
                }
            )
        status_text = str(dim_raw.get("status") or "manual_review")
        manual_review_required = bool(dim_raw.get("manual_review_required"))
        deduction_reason = str(dim_raw.get("deduction_reason") or "").strip()
        has_evidence = bool(evidence_map)
        if not has_evidence:
            status_text = "manual_review"
            manual_review_required = True
            if not deduction_reason:
                deduction_reason = "证据不足，需人工确认（无证据不直接扣分）。"
        normalized_score_dimensions[key] = {
            "label": str(dim_raw.get("label") or label),
            "score": max(0, min(100, int(dim_raw.get("score") or 0))),
            "weight": float(dim_raw.get("weight") or normalized_score_weights.get(key) or 0.0),
            "status": status_text,
            "has_evidence": has_evidence,
            "manual_review_required": manual_review_required,
            "deduction_reason": deduction_reason,
            "evidence_map": evidence_map,
            "repair_suggestion": str(dim_raw.get("repair_suggestion") or "").strip(),
            "threshold": int(dim_raw.get("threshold") or POLICY_CLARITY_AUTO_THRESHOLD),
        }

    return {
        "duty_title": duty_title,
        "duty_excerpt": duty_excerpt,
        "duty_text": duty_text,
        "duty_truncated": bool(duty_truncated),
        "role_profile": role_profile,
        "session_goal": session_goal,
        "duty_constraints": duty_constraints_items,
        "duty_constraints_text": duty_constraints_text,
        "constraints": normalized_constraints,
        "parse_status": parse_status,
        "parse_warnings": parse_warnings,
        "evidence_snippets": {
            "role": str(evidence_snippets.get("role") or ""),
            "goal": str(evidence_snippets.get("goal") or ""),
            "duty": str(evidence_snippets.get("duty") or ""),
        },
        "score_model": score_model,
        "score_total": max(0, min(100, score_total)),
        "score_weights": normalized_score_weights,
        "score_dimensions": normalized_score_dimensions,
        "clarity_score": max(0, min(100, clarity_score)),
        "clarity_details": {
            "completeness": int((clarity_details or {}).get("completeness") or 0),
            "specificity": int((clarity_details or {}).get("specificity") or 0),
            "consistency": int((clarity_details or {}).get("consistency") or 0),
            "traceability": int((clarity_details or {}).get("traceability") or 0),
            "executability": int((clarity_details or {}).get("executability") or 0),
            "risk_coverage": int((clarity_details or {}).get("risk_coverage") or 0),
            "operability": int((clarity_details or {}).get("operability") or 0),
        },
        "clarity_gate": clarity_gate,
        "clarity_gate_reason": clarity_gate_reason,
        "risk_tips": risk_tips,
        "policy_extract_ok": bool(policy_extract_ok),
        "policy_error": policy_error,
    }



# Policy analysis domain logic is split into dedicated service modules.
from . import policy_fallback_service as _policy_fallback_service
from . import agent_discovery_service as _agent_discovery_service

_POLICY_ANALYSIS_MODULES = (
    _policy_fallback_service,
    _agent_discovery_service,
)

for _module in _POLICY_ANALYSIS_MODULES:
    _module.bind_runtime_symbols(globals())

for _module in _POLICY_ANALYSIS_MODULES:
    for _name, _value in _module.__dict__.items():
        if _name.startswith("__") or _name == "bind_runtime_symbols":
            continue
        globals()[_name] = _value

for _module in _POLICY_ANALYSIS_MODULES:
    _module.bind_runtime_symbols(globals())

del _module, _name, _value


