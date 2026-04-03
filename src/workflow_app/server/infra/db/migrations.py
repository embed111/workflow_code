from __future__ import annotations

import sqlite3
from pathlib import Path

from .connection import connect_db


def ensure_tables(
    root: Path,
    *,
    analysis_state_pending: str = "未分析",
    default_agents_root: str = "",
) -> None:
    def ensure_column(conn: sqlite3.Connection, table: str, column: str, column_def: str) -> None:
        cols = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")

    def drop_table_if_exists(conn: sqlite3.Connection, table: str) -> None:
        conn.execute(f"DROP TABLE IF EXISTS {table}")

    conn = connect_db(root)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS conversation_events (event_id TEXT PRIMARY KEY,timestamp TEXT NOT NULL,session_id TEXT NOT NULL,actor TEXT NOT NULL,stage TEXT NOT NULL,action TEXT NOT NULL,status TEXT NOT NULL,latency_ms INTEGER NOT NULL DEFAULT 0,task_id TEXT,reason_tags_json TEXT NOT NULL DEFAULT '[]',ref TEXT NOT NULL)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ce_ts ON conversation_events(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ce_sid ON conversation_events(session_id)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS analysis_tasks (analysis_id TEXT PRIMARY KEY,session_id TEXT NOT NULL UNIQUE,source_event_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',decision TEXT,decision_reason TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_at_status ON analysis_tasks(status)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS training_tasks (training_id TEXT PRIMARY KEY,analysis_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',result_summary TEXT,trainer_run_ref TEXT,attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tt_status ON training_tasks(status)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tt_analysis ON training_tasks(analysis_id)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS conversation_messages (message_id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cm_session ON conversation_messages(session_id,message_id)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS chat_sessions (session_id TEXT PRIMARY KEY,agent_name TEXT NOT NULL,agents_hash TEXT NOT NULL,agents_loaded_at TEXT NOT NULL,agents_path TEXT NOT NULL DEFAULT '',agents_version TEXT NOT NULL DEFAULT '',agent_search_root TEXT NOT NULL DEFAULT '',target_path TEXT NOT NULL DEFAULT '',is_test_data INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'active',closed_at TEXT,closed_reason TEXT,created_at TEXT NOT NULL)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cs_created ON chat_sessions(created_at)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS task_runs (task_id TEXT PRIMARY KEY,session_id TEXT NOT NULL,agent_name TEXT NOT NULL,agent_search_root TEXT NOT NULL DEFAULT '',default_agents_root TEXT NOT NULL DEFAULT '',target_path TEXT NOT NULL DEFAULT '',status TEXT NOT NULL,message TEXT NOT NULL,command_json TEXT NOT NULL,command_display TEXT NOT NULL,start_at TEXT,end_at TEXT,duration_ms INTEGER,stdout TEXT NOT NULL DEFAULT '',stderr TEXT NOT NULL DEFAULT '',summary TEXT NOT NULL DEFAULT '',ref TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_runs_session ON task_runs(session_id,created_at)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_task_runs_status ON task_runs(status)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS task_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT NOT NULL,timestamp TEXT NOT NULL,event_type TEXT NOT NULL,payload_json TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id,event_id)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS ingress_requests (request_id TEXT PRIMARY KEY,session_id TEXT NOT NULL,route TEXT NOT NULL,created_at TEXT NOT NULL,event_logged INTEGER NOT NULL DEFAULT 0)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ir_ts ON ingress_requests(created_at)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS reconcile_runs (run_id TEXT PRIMARY KEY,run_at TEXT NOT NULL,reason TEXT NOT NULL,ingress_count INTEGER NOT NULL,event_count_before INTEGER NOT NULL,event_count_after INTEGER NOT NULL,gap_before INTEGER NOT NULL,gap_after INTEGER NOT NULL,backfill_inserted INTEGER NOT NULL,malformed INTEGER NOT NULL,status TEXT NOT NULL,notes TEXT NOT NULL DEFAULT '',ref TEXT NOT NULL)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rr_ts ON reconcile_runs(run_at)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS training_workflows (workflow_id TEXT PRIMARY KEY,analysis_id TEXT NOT NULL UNIQUE,session_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',assigned_analyst TEXT NOT NULL DEFAULT '',assignment_note TEXT NOT NULL DEFAULT '',analysis_summary TEXT NOT NULL DEFAULT '',analysis_recommendation TEXT NOT NULL DEFAULT '',plan_json TEXT NOT NULL DEFAULT '[]',selected_plan_json TEXT NOT NULL DEFAULT '[]',train_result_ref TEXT NOT NULL DEFAULT '',train_result_summary TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tw_status ON training_workflows(status,updated_at)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS training_workflow_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT,workflow_id TEXT NOT NULL,analysis_id TEXT NOT NULL,session_id TEXT NOT NULL,stage TEXT NOT NULL,status TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_twe_workflow ON training_workflow_events(workflow_id,event_id)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS analysis_runs (analysis_run_id TEXT PRIMARY KEY,workflow_id TEXT NOT NULL,analysis_id TEXT NOT NULL,session_id TEXT NOT NULL,status TEXT NOT NULL,no_value_reason TEXT NOT NULL DEFAULT '',context_message_ids_json TEXT NOT NULL DEFAULT '[]',target_message_ids_json TEXT NOT NULL DEFAULT '[]',error_text TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ar_workflow ON analysis_runs(workflow_id,created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ar_analysis ON analysis_runs(analysis_id,created_at)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS analysis_run_plan_items (plan_item_id TEXT PRIMARY KEY,analysis_run_id TEXT NOT NULL,workflow_id TEXT NOT NULL,item_key TEXT NOT NULL,title TEXT NOT NULL,kind TEXT NOT NULL,decision TEXT NOT NULL DEFAULT '',description TEXT NOT NULL DEFAULT '',message_ids_json TEXT NOT NULL DEFAULT '[]',selected INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_arpi_run ON analysis_run_plan_items(analysis_run_id,created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_arpi_workflow ON analysis_run_plan_items(workflow_id,created_at)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS message_delete_audit (audit_id INTEGER PRIMARY KEY AUTOINCREMENT,audit_ts TEXT NOT NULL,operator TEXT NOT NULL,session_id TEXT NOT NULL,message_id INTEGER NOT NULL,status TEXT NOT NULL,reason_code TEXT NOT NULL,reason_text TEXT NOT NULL,impact_scope TEXT NOT NULL,workflow_id TEXT NOT NULL DEFAULT '',analysis_run_id TEXT NOT NULL DEFAULT '',training_plan_items INTEGER NOT NULL DEFAULT 0,ref TEXT NOT NULL DEFAULT '')"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mda_session_ts ON message_delete_audit(session_id,audit_ts)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS policy_confirmation_audit (audit_id INTEGER PRIMARY KEY AUTOINCREMENT,audit_ts TEXT NOT NULL,operator TEXT NOT NULL,action TEXT NOT NULL,status TEXT NOT NULL,reason_text TEXT NOT NULL DEFAULT '',session_id TEXT NOT NULL DEFAULT '',agent_name TEXT NOT NULL,agents_hash TEXT NOT NULL DEFAULT '',agents_version TEXT NOT NULL DEFAULT '',agents_path TEXT NOT NULL DEFAULT '',parse_status TEXT NOT NULL DEFAULT '',clarity_score INTEGER NOT NULL DEFAULT 0,old_policy_json TEXT NOT NULL DEFAULT '{}',new_policy_json TEXT NOT NULL DEFAULT '{}',ref TEXT NOT NULL DEFAULT '')"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pca_agent_ts ON policy_confirmation_audit(agent_name,audit_ts)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pca_session_ts ON policy_confirmation_audit(session_id,audit_ts)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_policy_patch_tasks (patch_task_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',source_session_id TEXT NOT NULL DEFAULT '',confirmation_audit_id INTEGER NOT NULL DEFAULT 0,agent_name TEXT NOT NULL,agents_hash TEXT NOT NULL DEFAULT '',agents_version TEXT NOT NULL DEFAULT '',agents_path TEXT NOT NULL DEFAULT '',policy_json TEXT NOT NULL DEFAULT '{}',notes TEXT NOT NULL DEFAULT '',completed_at TEXT NOT NULL DEFAULT '')"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_appt_status ON agent_policy_patch_tasks(status,updated_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_appt_agent_ts ON agent_policy_patch_tasks(agent_name,created_at)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_policy_cache (agent_path TEXT PRIMARY KEY,agents_hash TEXT NOT NULL,agents_mtime REAL NOT NULL DEFAULT 0,parse_status TEXT NOT NULL DEFAULT 'failed',clarity_score INTEGER NOT NULL DEFAULT 0,cached_at REAL NOT NULL DEFAULT 0,policy_payload_json TEXT NOT NULL DEFAULT '{}')"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_apc_hash_mtime ON agent_policy_cache(agents_hash,agents_mtime)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_registry (agent_id TEXT PRIMARY KEY,agent_name TEXT NOT NULL,workspace_path TEXT NOT NULL,current_version TEXT NOT NULL DEFAULT '',latest_release_version TEXT NOT NULL DEFAULT '',bound_release_version TEXT NOT NULL DEFAULT '',lifecycle_state TEXT NOT NULL DEFAULT 'released',training_gate_state TEXT NOT NULL DEFAULT 'trainable',parent_agent_id TEXT NOT NULL DEFAULT '',core_capabilities TEXT NOT NULL DEFAULT '',capability_summary TEXT NOT NULL DEFAULT '',knowledge_scope TEXT NOT NULL DEFAULT '',skills_json TEXT NOT NULL DEFAULT '[]',applicable_scenarios TEXT NOT NULL DEFAULT '',version_notes TEXT NOT NULL DEFAULT '',avatar_uri TEXT NOT NULL DEFAULT '',vector_icon TEXT NOT NULL DEFAULT '',git_available INTEGER NOT NULL DEFAULT 0,pre_release_state TEXT NOT NULL DEFAULT 'unknown',pre_release_reason TEXT NOT NULL DEFAULT '',pre_release_checked_at TEXT NOT NULL DEFAULT '',pre_release_git_output TEXT NOT NULL DEFAULT '',last_release_at TEXT NOT NULL DEFAULT '',status_tags_json TEXT NOT NULL DEFAULT '[]',active_role_profile_release_id TEXT NOT NULL DEFAULT '',active_role_profile_ref TEXT NOT NULL DEFAULT '',runtime_status TEXT NOT NULL DEFAULT 'idle',updated_at TEXT NOT NULL)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS role_creation_sessions (
                session_id TEXT PRIMARY KEY,
                session_title TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                current_stage_key TEXT NOT NULL DEFAULT 'persona_collection',
                current_stage_index INTEGER NOT NULL DEFAULT 2,
                role_spec_json TEXT NOT NULL DEFAULT '{}',
                missing_fields_json TEXT NOT NULL DEFAULT '[]',
                assignment_ticket_id TEXT NOT NULL DEFAULT '',
                created_agent_id TEXT NOT NULL DEFAULT '',
                created_agent_name TEXT NOT NULL DEFAULT '',
                created_agent_workspace_path TEXT NOT NULL DEFAULT '',
                workspace_init_status TEXT NOT NULL DEFAULT 'pending',
                workspace_init_ref TEXT NOT NULL DEFAULT '',
                last_message_preview TEXT NOT NULL DEFAULT '',
                last_message_at TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL DEFAULT '',
                completed_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_role_creation_sessions_updated ON role_creation_sessions(updated_at DESC)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS role_creation_messages (
                message_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                attachments_json TEXT NOT NULL DEFAULT '[]',
                message_type TEXT NOT NULL DEFAULT 'chat',
                meta_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_role_creation_messages_session ON role_creation_messages(session_id,created_at)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS role_creation_task_refs (
                ref_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                ticket_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                stage_key TEXT NOT NULL,
                stage_index INTEGER NOT NULL DEFAULT 0,
                relation_state TEXT NOT NULL DEFAULT 'active',
                close_reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_role_creation_task_refs_unique ON role_creation_task_refs(session_id,node_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_role_creation_task_refs_stage ON role_creation_task_refs(session_id,stage_index,updated_at)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS defect_reports (
                report_id TEXT PRIMARY KEY,
                dts_id TEXT NOT NULL DEFAULT '',
                dts_sequence INTEGER NOT NULL DEFAULT 0,
                defect_summary TEXT NOT NULL DEFAULT '',
                report_text TEXT NOT NULL DEFAULT '',
                evidence_images_json TEXT NOT NULL DEFAULT '[]',
                task_priority TEXT NOT NULL DEFAULT 'P1',
                reported_at TEXT NOT NULL DEFAULT '',
                is_formal INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'not_formal',
                discovered_iteration TEXT NOT NULL DEFAULT '',
                resolved_version TEXT NOT NULL DEFAULT '',
                current_decision_json TEXT NOT NULL DEFAULT '{}',
                report_source TEXT NOT NULL DEFAULT 'workflow-ui',
                automation_context_json TEXT NOT NULL DEFAULT '{}',
                is_test_data INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        ensure_column(conn, "defect_reports", "dts_id", "dts_id TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "defect_reports", "dts_sequence", "dts_sequence INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "defect_reports", "task_priority", "task_priority TEXT NOT NULL DEFAULT 'P1'")
        ensure_column(conn, "defect_reports", "reported_at", "reported_at TEXT NOT NULL DEFAULT ''")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_defect_reports_updated ON defect_reports(updated_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_defect_reports_status ON defect_reports(is_formal,status,updated_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_defect_reports_queue_sort ON defect_reports(status,task_priority,reported_at,dts_sequence,report_id)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_defect_reports_dts_id ON defect_reports(dts_id) WHERE dts_id<>''"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_defect_reports_dts_sequence ON defect_reports(dts_sequence) WHERE dts_sequence>0"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS defect_history (
                history_id TEXT PRIMARY KEY,
                report_id TEXT NOT NULL,
                entry_type TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                detail_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_defect_history_report_time ON defect_history(report_id,created_at)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS defect_task_refs (
                ref_id TEXT PRIMARY KEY,
                report_id TEXT NOT NULL,
                ticket_id TEXT NOT NULL,
                focus_node_id TEXT NOT NULL DEFAULT '',
                action_kind TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                external_request_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_defect_task_refs_report_time ON defect_task_refs(report_id,updated_at DESC)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_defect_task_refs_unique ON defect_task_refs(report_id,ticket_id,focus_node_id,external_request_id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS defect_queue_settings (
                settings_id TEXT PRIMARY KEY,
                sequential_task_creation_enabled INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ar_registry_name ON agent_registry(agent_name)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ar_registry_updated ON agent_registry(updated_at)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_release_history (release_id TEXT PRIMARY KEY,agent_id TEXT NOT NULL,version_label TEXT NOT NULL,released_at TEXT NOT NULL,change_summary TEXT NOT NULL DEFAULT '',commit_ref TEXT NOT NULL DEFAULT '',capability_summary TEXT NOT NULL DEFAULT '',knowledge_scope TEXT NOT NULL DEFAULT '',skills_json TEXT NOT NULL DEFAULT '[]',applicable_scenarios TEXT NOT NULL DEFAULT '',version_notes TEXT NOT NULL DEFAULT '',release_valid INTEGER NOT NULL DEFAULT 0,invalid_reasons_json TEXT NOT NULL DEFAULT '[]',classification TEXT NOT NULL DEFAULT 'normal_commit',raw_notes TEXT NOT NULL DEFAULT '',release_source_ref TEXT NOT NULL DEFAULT '',public_profile_ref TEXT NOT NULL DEFAULT '',capability_snapshot_ref TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_arh_agent_time ON agent_release_history(agent_id,released_at DESC)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_release_evaluation (evaluation_id TEXT PRIMARY KEY,agent_id TEXT NOT NULL,target_version TEXT NOT NULL DEFAULT '',decision TEXT NOT NULL,reviewer TEXT NOT NULL DEFAULT '',summary TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_are_agent_time ON agent_release_evaluation(agent_id,created_at DESC)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_release_review (review_id TEXT PRIMARY KEY,agent_id TEXT NOT NULL,target_version TEXT NOT NULL DEFAULT '',current_workspace_ref TEXT NOT NULL DEFAULT '',release_review_state TEXT NOT NULL DEFAULT 'idle',prompt_version TEXT NOT NULL DEFAULT '',analysis_chain_json TEXT NOT NULL DEFAULT '{}',report_json TEXT NOT NULL DEFAULT '{}',report_error TEXT NOT NULL DEFAULT '',review_decision TEXT NOT NULL DEFAULT '',reviewer TEXT NOT NULL DEFAULT '',review_comment TEXT NOT NULL DEFAULT '',reviewed_at TEXT NOT NULL DEFAULT '',publish_version TEXT NOT NULL DEFAULT '',publish_status TEXT NOT NULL DEFAULT '',publish_error TEXT NOT NULL DEFAULT '',execution_log_json TEXT NOT NULL DEFAULT '[]',fallback_json TEXT NOT NULL DEFAULT '{}',public_profile_markdown_path TEXT NOT NULL DEFAULT '',capability_snapshot_json_path TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_arr_agent_created ON agent_release_review(agent_id,created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_arr_agent_updated ON agent_release_review(agent_id,updated_at DESC)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS training_plan (plan_id TEXT PRIMARY KEY,source TEXT NOT NULL,target_agent_id TEXT NOT NULL,capability_goal TEXT NOT NULL,training_tasks_json TEXT NOT NULL DEFAULT '[]',acceptance_criteria TEXT NOT NULL DEFAULT '',priority TEXT NOT NULL,similar_flag INTEGER NOT NULL DEFAULT 0,created_by TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tp_target_created ON training_plan(target_agent_id,created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tp_source_created ON training_plan(source,created_at DESC)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS training_queue (queue_task_id TEXT PRIMARY KEY,plan_id TEXT NOT NULL,priority TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',execution_engine TEXT NOT NULL DEFAULT 'workflow_native',trainer_match TEXT NOT NULL DEFAULT '',enqueued_at TEXT NOT NULL,started_at TEXT NOT NULL DEFAULT '',finished_at TEXT NOT NULL DEFAULT '')"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tq_status_priority ON training_queue(status,priority,enqueued_at)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS training_run (run_id TEXT PRIMARY KEY,queue_task_id TEXT NOT NULL,run_ref TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT '',result_summary TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tr_queue_updated ON training_run(queue_task_id,updated_at DESC)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS training_eval_run (eval_run_id TEXT PRIMARY KEY,queue_task_id TEXT NOT NULL,round_index INTEGER NOT NULL DEFAULT 0,run_index INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'pending',score REAL,evaluation_summary TEXT NOT NULL DEFAULT '',started_at TEXT NOT NULL DEFAULT '',finished_at TEXT NOT NULL DEFAULT '',context_reset INTEGER NOT NULL DEFAULT 1,evidence_ref TEXT NOT NULL DEFAULT '',execution_engine TEXT NOT NULL DEFAULT 'workflow_native',created_at TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL DEFAULT '')"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_ter_queue_run ON training_eval_run(queue_task_id,run_index)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ter_queue_updated ON training_eval_run(queue_task_id,updated_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ter_round_updated ON training_eval_run(round_index,updated_at DESC)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS training_audit_log (audit_id TEXT PRIMARY KEY,action TEXT NOT NULL,operator TEXT NOT NULL,target_id TEXT NOT NULL,detail_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tal_action_time ON training_audit_log(action,created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tal_target_time ON training_audit_log(target_id,created_at DESC)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS training_loop_state (loop_id TEXT PRIMARY KEY,graph_json TEXT NOT NULL DEFAULT '{}',current_node_id TEXT NOT NULL DEFAULT '',metrics_available INTEGER NOT NULL DEFAULT 0,metrics_unavailable_reason TEXT NOT NULL DEFAULT '',is_test_data INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tls_updated ON training_loop_state(updated_at DESC)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS assignment_system_settings (setting_key TEXT PRIMARY KEY,setting_value TEXT NOT NULL,updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO assignment_system_settings(setting_key,setting_value,updated_at) VALUES ('global_concurrency_limit','5','')"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS assignment_system_audit (audit_id TEXT PRIMARY KEY,action TEXT NOT NULL,operator TEXT NOT NULL,reason TEXT NOT NULL DEFAULT '',detail_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_assignment_system_audit_action_time ON assignment_system_audit(action,created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_assignment_system_audit_time ON assignment_system_audit(created_at DESC)"
        )
        ensure_column(conn, "agent_registry", "vector_icon", "vector_icon TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_registry", "latest_release_version", "latest_release_version TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_registry", "bound_release_version", "bound_release_version TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_registry", "lifecycle_state", "lifecycle_state TEXT NOT NULL DEFAULT 'released'")
        ensure_column(conn, "agent_registry", "training_gate_state", "training_gate_state TEXT NOT NULL DEFAULT 'trainable'")
        ensure_column(conn, "agent_registry", "parent_agent_id", "parent_agent_id TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_registry", "capability_summary", "capability_summary TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_registry", "knowledge_scope", "knowledge_scope TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_registry", "skills_json", "skills_json TEXT NOT NULL DEFAULT '[]'")
        ensure_column(conn, "agent_registry", "applicable_scenarios", "applicable_scenarios TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_registry", "version_notes", "version_notes TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_registry", "avatar_uri", "avatar_uri TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_registry", "pre_release_state", "pre_release_state TEXT NOT NULL DEFAULT 'unknown'")
        ensure_column(conn, "agent_registry", "pre_release_reason", "pre_release_reason TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_registry", "pre_release_checked_at", "pre_release_checked_at TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_registry", "pre_release_git_output", "pre_release_git_output TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_registry", "active_role_profile_release_id", "active_role_profile_release_id TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_registry", "active_role_profile_ref", "active_role_profile_ref TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_registry", "runtime_status", "runtime_status TEXT NOT NULL DEFAULT 'idle'")
        ensure_column(conn, "agent_release_history", "capability_summary", "capability_summary TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_release_history", "knowledge_scope", "knowledge_scope TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_release_history", "skills_json", "skills_json TEXT NOT NULL DEFAULT '[]'")
        ensure_column(conn, "agent_release_history", "applicable_scenarios", "applicable_scenarios TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_release_history", "version_notes", "version_notes TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_release_history", "release_valid", "release_valid INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "agent_release_history", "invalid_reasons_json", "invalid_reasons_json TEXT NOT NULL DEFAULT '[]'")
        ensure_column(conn, "agent_release_history", "classification", "classification TEXT NOT NULL DEFAULT 'normal_commit'")
        ensure_column(conn, "agent_release_history", "raw_notes", "raw_notes TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_release_history", "release_source_ref", "release_source_ref TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_release_history", "public_profile_ref", "public_profile_ref TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_release_history", "capability_snapshot_ref", "capability_snapshot_ref TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_arh_agent_class_time ON agent_release_history(agent_id,classification,released_at DESC)")
        ensure_column(conn, "agent_release_review", "target_version", "target_version TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_release_review", "current_workspace_ref", "current_workspace_ref TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_release_review", "release_review_state", "release_review_state TEXT NOT NULL DEFAULT 'idle'")
        ensure_column(conn, "agent_release_review", "prompt_version", "prompt_version TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_release_review", "analysis_chain_json", "analysis_chain_json TEXT NOT NULL DEFAULT '{}'")
        ensure_column(conn, "agent_release_review", "report_json", "report_json TEXT NOT NULL DEFAULT '{}'")
        ensure_column(conn, "agent_release_review", "report_error", "report_error TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_release_review", "review_decision", "review_decision TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_release_review", "reviewer", "reviewer TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_release_review", "review_comment", "review_comment TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_release_review", "reviewed_at", "reviewed_at TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_release_review", "publish_version", "publish_version TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_release_review", "publish_status", "publish_status TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_release_review", "publish_error", "publish_error TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_release_review", "execution_log_json", "execution_log_json TEXT NOT NULL DEFAULT '[]'")
        ensure_column(conn, "agent_release_review", "fallback_json", "fallback_json TEXT NOT NULL DEFAULT '{}'")
        ensure_column(conn, "agent_release_review", "public_profile_markdown_path", "public_profile_markdown_path TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "agent_release_review", "capability_snapshot_json_path", "capability_snapshot_json_path TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_arr_agent_created ON agent_release_review(agent_id,created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_arr_agent_updated ON agent_release_review(agent_id,updated_at DESC)")
        ensure_column(conn, "training_plan", "is_test_data", "is_test_data INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "training_plan", "loop_id", "loop_id TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "training_queue", "is_test_data", "is_test_data INTEGER NOT NULL DEFAULT 0")
        ensure_column(
            conn,
            "training_queue",
            "execution_engine",
            "execution_engine TEXT NOT NULL DEFAULT 'workflow_native'",
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tp_test_data_created ON training_plan(is_test_data,created_at DESC)"
        )

        ensure_column(conn, "chat_sessions", "agent_search_root", "agent_search_root TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "chat_sessions", "target_path", "target_path TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "chat_sessions", "agents_path", "agents_path TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "chat_sessions", "agents_version", "agents_version TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "chat_sessions", "role_profile", "role_profile TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "chat_sessions", "session_goal", "session_goal TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "chat_sessions", "duty_constraints", "duty_constraints TEXT NOT NULL DEFAULT ''")
        ensure_column(
            conn,
            "chat_sessions",
            "policy_snapshot_json",
            "policy_snapshot_json TEXT NOT NULL DEFAULT '{}'",
        )
        ensure_column(conn, "chat_sessions", "is_test_data", "is_test_data INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "chat_sessions", "status", "status TEXT NOT NULL DEFAULT 'active'")
        ensure_column(conn, "chat_sessions", "closed_at", "closed_at TEXT")
        ensure_column(conn, "chat_sessions", "closed_reason", "closed_reason TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cs_status ON chat_sessions(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cs_test_data ON chat_sessions(is_test_data,status,created_at)")
        ensure_column(
            conn,
            "policy_confirmation_audit",
            "manual_fallback",
            "manual_fallback INTEGER NOT NULL DEFAULT 0",
        )
        ensure_column(conn, "task_runs", "agent_search_root", "agent_search_root TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "task_runs", "default_agents_root", "default_agents_root TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "task_runs", "target_path", "target_path TEXT NOT NULL DEFAULT ''")
        ensure_column(
            conn,
            "conversation_messages",
            "analysis_state",
            f"analysis_state TEXT NOT NULL DEFAULT '{analysis_state_pending}'",
        )
        ensure_column(conn, "conversation_messages", "analysis_reason", "analysis_reason TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "conversation_messages", "analysis_run_id", "analysis_run_id TEXT NOT NULL DEFAULT ''")
        ensure_column(
            conn,
            "conversation_messages",
            "analysis_updated_at",
            "analysis_updated_at TEXT NOT NULL DEFAULT ''",
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cm_analysis_state ON conversation_messages(session_id,analysis_state,message_id)"
        )
        ensure_column(
            conn,
            "training_workflows",
            "analysis_recommendation",
            "analysis_recommendation TEXT NOT NULL DEFAULT ''",
        )
        ensure_column(
            conn,
            "training_workflows",
            "latest_analysis_run_id",
            "latest_analysis_run_id TEXT NOT NULL DEFAULT ''",
        )
        ensure_column(
            conn,
            "training_workflows",
            "latest_no_value_reason",
            "latest_no_value_reason TEXT NOT NULL DEFAULT ''",
        )
        conn.execute(
            "UPDATE chat_sessions SET agent_search_root=target_path WHERE COALESCE(agent_search_root,'')=''"
        )
        conn.execute(
            "UPDATE chat_sessions SET target_path=? WHERE COALESCE(target_path,'')=''",
            (root.as_posix(),),
        )
        conn.execute(
            "UPDATE chat_sessions SET status='active' WHERE COALESCE(status,'')=''"
        )
        conn.execute(
            "UPDATE chat_sessions SET is_test_data=0 WHERE is_test_data IS NULL"
        )
        conn.execute(
            "UPDATE chat_sessions SET agents_version=SUBSTR(agents_hash,1,12) WHERE COALESCE(agents_version,'')=''"
        )
        conn.execute(
            "UPDATE chat_sessions SET agents_path=RTRIM(REPLACE(COALESCE(agent_search_root,''),'\\\\','/'),'/') || '/' || agent_name || '/AGENTS.md' WHERE COALESCE(agents_path,'')='' AND COALESCE(agent_search_root,'')<>'' AND COALESCE(agent_name,'')<>''"
        )
        conn.execute(
            "UPDATE chat_sessions SET role_profile='' WHERE COALESCE(role_profile,'')=''"
        )
        conn.execute(
            "UPDATE chat_sessions SET session_goal='' WHERE COALESCE(session_goal,'')=''"
        )
        conn.execute(
            "UPDATE chat_sessions SET duty_constraints='' WHERE COALESCE(duty_constraints,'')=''"
        )
        conn.execute(
            "UPDATE chat_sessions SET policy_snapshot_json='{}' WHERE COALESCE(policy_snapshot_json,'')=''"
        )
        conn.execute(
            "UPDATE task_runs SET agent_search_root=default_agents_root WHERE COALESCE(agent_search_root,'')=''"
        )
        conn.execute(
            "UPDATE task_runs SET default_agents_root=? WHERE COALESCE(default_agents_root,'')=''",
            (str(default_agents_root or root.resolve(strict=False).as_posix()),),
        )
        conn.execute(
            "UPDATE task_runs SET target_path=? WHERE COALESCE(target_path,'')=''",
            (root.as_posix(),),
        )
        conn.execute(
            "UPDATE conversation_messages SET analysis_state=? WHERE role IN ('user','assistant') AND TRIM(COALESCE(content,''))<>'' AND COALESCE(analysis_state,'')=''",
            (analysis_state_pending,),
        )
        conn.execute(
            "UPDATE conversation_messages SET analysis_reason='' WHERE COALESCE(analysis_reason,'')=''",
        )
        conn.execute(
            "UPDATE conversation_messages SET analysis_run_id='' WHERE COALESCE(analysis_run_id,'')=''",
        )
        conn.execute(
            "UPDATE conversation_messages SET analysis_updated_at=created_at WHERE COALESCE(analysis_updated_at,'')='' AND COALESCE(created_at,'')<>''",
        )
        conn.commit()
    finally:
        conn.close()
