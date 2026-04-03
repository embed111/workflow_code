#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

POLICY_PROMPT_VERSION = "2026-03-01-codex-exec-v2-evidence"
POLICY_EXTRACT_SOURCE = "codex_exec"
POLICY_SCORE_WEIGHTS: dict[str, float] = {
    "completeness": 0.2,
    "executability": 0.2,
    "consistency": 0.2,
    "traceability": 0.15,
    "risk_coverage": 0.15,
    "operability": 0.1,
}


def build_cached_policy_payload(
    *,
    role_profile: str,
    session_goal: str,
    duty_constraints: list[str],
    clarity_score: int,
    clarity_gate: str,
    parse_status: str = "ok",
    policy_extract_ok: bool = True,
    policy_error: str = "",
) -> dict[str, Any]:
    score = max(0, min(100, int(clarity_score)))
    gate = str(clarity_gate or "").strip().lower() or "block"
    parse = str(parse_status or "").strip().lower() or "failed"
    dim_keys = tuple(POLICY_SCORE_WEIGHTS.keys())
    score_dimensions = {
        key: {
            "score": score,
            "weight": float(POLICY_SCORE_WEIGHTS[key]),
            "deduction_reason": "",
            "manual_review_required": False,
        }
        for key in dim_keys
    }
    return {
        "duty_title": "职责边界",
        "duty_excerpt": "cache-seeded policy payload",
        "duty_text": "\n".join(duty_constraints).strip(),
        "duty_truncated": False,
        "role_profile": role_profile,
        "session_goal": session_goal,
        "duty_constraints": duty_constraints,
        "duty_constraints_text": "\n".join(duty_constraints).strip(),
        "constraints": {
            "must": duty_constraints,
            "must_not": [],
            "preconditions": [],
            "issues": [],
            "conflicts": [],
            "missing_evidence_count": 0,
            "total": len(duty_constraints),
        },
        "parse_status": parse,
        "parse_warnings": [],
        "evidence_snippets": {
            "role": role_profile[:120],
            "goal": session_goal[:120],
            "duty": "\n".join(duty_constraints)[:160],
        },
        "score_model": "v2",
        "score_total": score,
        "score_weights": dict(POLICY_SCORE_WEIGHTS),
        "score_dimensions": score_dimensions,
        "clarity_score": score,
        "clarity_details": {
            "completeness": score,
            "specificity": score,
            "consistency": score,
            "traceability": score,
        },
        "clarity_gate": gate,
        "clarity_gate_reason": "cache_seed",
        "risk_tips": [],
        "policy_extract_ok": bool(policy_extract_ok),
        "policy_error": str(policy_error or ""),
        "policy_extract_source": POLICY_EXTRACT_SOURCE,
        "policy_prompt_version": POLICY_PROMPT_VERSION,
        "analysis_chain": {},
        "policy_contract_status": "ok" if parse == "ok" else "failed",
        "policy_contract_missing_fields": [],
        "policy_contract_issues": [],
        "policy_gate_state": "ready" if gate == "auto" else "manual_review",
        "policy_gate_reason": "cache_seed",
    }


def upsert_policy_cache(
    *,
    runtime_root: Path,
    workspace_root: Path,
    specs: list[dict[str, Any]],
) -> None:
    db_path = runtime_root / "state" / "workflow.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path.as_posix())
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_policy_cache (
                agent_path TEXT PRIMARY KEY,
                agents_hash TEXT NOT NULL,
                agents_mtime REAL NOT NULL DEFAULT 0,
                parse_status TEXT NOT NULL DEFAULT 'failed',
                clarity_score INTEGER NOT NULL DEFAULT 0,
                cached_at REAL NOT NULL DEFAULT 0,
                policy_payload_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_apc_hash_mtime ON agent_policy_cache(agents_hash,agents_mtime)"
        )

        for spec in specs:
            agent_name = str(spec.get("agent_name") or "").strip()
            if not agent_name:
                continue
            agent_file = (workspace_root / agent_name / "AGENTS.md").resolve(strict=False)
            if not agent_file.exists() or not agent_file.is_file():
                continue
            raw = agent_file.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            mtime = float(agent_file.stat().st_mtime or 0.0)

            payload = build_cached_policy_payload(
                role_profile=str(spec.get("role_profile") or ""),
                session_goal=str(spec.get("session_goal") or ""),
                duty_constraints=[
                    str(item).strip()
                    for item in (spec.get("duty_constraints") or [])
                    if str(item or "").strip()
                ],
                clarity_score=int(spec.get("clarity_score") or 0),
                clarity_gate=str(spec.get("clarity_gate") or "block"),
                parse_status=str(spec.get("parse_status") or "ok"),
                policy_extract_ok=bool(spec.get("policy_extract_ok", True)),
                policy_error=str(spec.get("policy_error") or ""),
            )
            override = spec.get("payload_override")
            if isinstance(override, dict):
                payload.update(override)
            cached_at = max(time.time(), mtime + 1.0)

            conn.execute(
                """
                INSERT INTO agent_policy_cache (
                    agent_path,agents_hash,agents_mtime,parse_status,clarity_score,cached_at,policy_payload_json
                ) VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(agent_path) DO UPDATE SET
                    agents_hash=excluded.agents_hash,
                    agents_mtime=excluded.agents_mtime,
                    parse_status=excluded.parse_status,
                    clarity_score=excluded.clarity_score,
                    cached_at=excluded.cached_at,
                    policy_payload_json=excluded.policy_payload_json
                """,
                (
                    agent_file.as_posix(),
                    digest,
                    mtime,
                    str(payload.get("parse_status") or "ok"),
                    int(payload.get("clarity_score") or 0),
                    cached_at,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        conn.commit()
    finally:
        conn.close()
