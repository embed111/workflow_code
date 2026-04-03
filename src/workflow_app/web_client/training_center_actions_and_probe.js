  // Training center probe and diagnostics helpers.
  function roleCreationProbeSessionId() {
    return safe(queryParam('tc_probe_session')).trim();
  }

  function roleCreationProbeNodeId() {
    return safe(queryParam('tc_probe_node')).trim();
  }

  function roleCreationProbeDelayMs() {
    return Math.max(0, Number(queryParam('tc_probe_delay_ms') || '180') || 180);
  }

  function roleCreationProbeTaskCardNodes() {
    return Array.from(document.querySelectorAll('#rcStageFlow .rc-task-card'));
  }

  function roleCreationProbeArchivePocketNodes() {
    return Array.from(document.querySelectorAll('#rcStageFlow .archive-pocket'));
  }

  function collectTrainingLoopLayoutProbe(output) {
    if (safe(state.tcModule).trim() !== 'ops') return;
    const moduleOps = $('tcModuleOps');
    const centerPane = $('tcLoopCenterPane');
    const detailBody = $('tcLoopDetailBody');
    const chatShell = detailBody ? detailBody.querySelector('.tc-loop-chat-shell') : null;
    const chatStream = detailBody ? detailBody.querySelector('.tc-loop-chat-stream') : null;
    const composer = detailBody ? detailBody.querySelector('.tc-loop-create-composer') : null;
    const rightColumn = $('tcLoopRightColumn');
    const rightPane = $('tcLoopRightPane');
    const activeRightPane = rightPane ? rightPane.querySelector('.tc-loop-right-pane-shell.active') : null;
    const runPanel = rightColumn ? rightColumn.querySelector('.tc-loop-run-panel') : null;

    function metrics(node) {
      if (!node) return null;
      const rect = node.getBoundingClientRect();
      const style = window.getComputedStyle(node);
      return {
        top: Math.round(rect.top),
        bottom: Math.round(rect.bottom),
        height: Math.round(rect.height),
        client_height: Math.round(node.clientHeight || 0),
        scroll_height: Math.round(node.scrollHeight || 0),
        overflow_y: safe(style.overflowY).trim().toLowerCase(),
        display: safe(style.display).trim().toLowerCase(),
      };
    }

    const detailMetrics = metrics(detailBody);
    const composerMetrics = metrics(composer);
    const rightMetrics = metrics(rightColumn);
    const runMetrics = metrics(runPanel);

    output.loop_layout = {
      window_inner_height: Math.round(window.innerHeight || 0),
      document_client_height: Math.round(document.documentElement ? document.documentElement.clientHeight || 0 : 0),
      document_scroll_height: Math.round(document.documentElement ? document.documentElement.scrollHeight || 0 : 0),
      body_scroll_height: Math.round(document.body ? document.body.scrollHeight || 0 : 0),
      module_ops: metrics(moduleOps),
      center_pane: metrics(centerPane),
      detail_body: detailMetrics,
      chat_shell: metrics(chatShell),
      chat_stream: metrics(chatStream),
      composer: composerMetrics,
      right_column: rightMetrics,
      right_pane: metrics(rightPane),
      active_right_pane: metrics(activeRightPane),
      run_panel: runMetrics,
      page_overflowing: Math.round(document.documentElement ? document.documentElement.scrollHeight || 0 : 0) > Math.round(window.innerHeight || 0) + 8,
      composer_bottom_gap:
        detailMetrics && composerMetrics ? Math.round(detailMetrics.bottom - composerMetrics.bottom) : null,
      right_bottom_gap:
        rightMetrics && runMetrics ? Math.round(rightMetrics.bottom - runMetrics.bottom) : null,
    };
  }

  async function prepareRoleCreationProbe(caseId, output) {
    const probeCase = safe(caseId).trim().toLowerCase();
    if (!probeCase.startsWith('rc_')) return;
    setTrainingCenterModule('create-role');
    await refreshRoleCreationSessions({ skipRender: true });
    let sessionId = roleCreationProbeSessionId();
    if (!sessionId) {
      const sessions = Array.isArray(state.tcRoleCreationSessions) ? state.tcRoleCreationSessions : [];
      sessionId = safe((sessions[0] || {}).session_id).trim();
    }
    if (!sessionId) {
      throw new Error('role creation probe session missing');
    }
    await selectRoleCreationSession(sessionId, { force: true, skipRender: true });
    setRoleCreationDetailTab(
      probeCase === 'rc_profile_tab' || probeCase === 'rc_failure'
        ? 'profile'
        : 'evolution'
    );
    if (typeof clearRoleCreationTaskPreview === 'function') {
      clearRoleCreationTaskPreview();
    }
    renderRoleCreationWorkbench();
    await new Promise((resolve) => window.setTimeout(resolve, roleCreationProbeDelayMs()));
    if (probeCase === 'rc_task_hover' || probeCase === 'rc_task_pinned') {
      const requestedNodeId = roleCreationProbeNodeId();
      const targetNode = roleCreationProbeTaskCardNodes().find((node) => {
        return !requestedNodeId || safe(node.getAttribute('data-node-id')).trim() === requestedNodeId;
      }) || roleCreationProbeTaskCardNodes()[0] || null;
      if (!targetNode) {
        throw new Error('role creation probe task missing');
      }
      showRoleCreationTaskPreviewFromNode(targetNode, { pinned: probeCase === 'rc_task_pinned' });
      await new Promise((resolve) => window.setTimeout(resolve, 180));
    }
    output.rc_selected_session_id = sessionId;
  }

  function collectRoleCreationProbeState(output) {
    if (!safe(output.case).trim().toLowerCase().startsWith('rc_')) return;
    const detail = roleCreationCurrentDetail();
    const session = roleCreationCurrentSession();
    const profile = roleCreationCurrentProfile();
    const stages = roleCreationCurrentStages();
    const messages = roleCreationCurrentMessages();
    const preview = state.tcRoleCreationTaskPreview && typeof state.tcRoleCreationTaskPreview === 'object'
      ? state.tcRoleCreationTaskPreview
      : {};
    const floatNode = $('rcTaskHoverFloat');
    const taskCards = roleCreationProbeTaskCardNodes();
    const archivePockets = roleCreationProbeArchivePocketNodes();
    const taskRefIds = Array.isArray(detail.task_refs)
      ? detail.task_refs.map((item) => safe(item && item.node_id).trim()).filter(Boolean)
      : [];
    const activeTaskIds = [];
    const archivedTaskIds = [];
    const statusSet = new Set();
    stages.forEach((stage) => {
      const activeTasks = Array.isArray(stage && stage.active_tasks) ? stage.active_tasks : [];
      const archivedTasks = Array.isArray(stage && stage.archived_tasks) ? stage.archived_tasks : [];
      activeTasks.forEach((task) => {
        const nodeId = safe(task && task.node_id).trim();
        if (nodeId) activeTaskIds.push(nodeId);
        const status = safe(task && task.status).trim().toLowerCase();
        if (status) statusSet.add(status);
      });
      archivedTasks.forEach((task) => {
        const nodeId = safe(task && task.node_id).trim();
        if (nodeId) archivedTaskIds.push(nodeId);
        statusSet.add('archived');
      });
    });
    output.rc_module = safe(state.tcModule).trim();
    output.rc_detail_tab = safe(state.tcRoleCreationDetailTab).trim();
    output.rc_session_id = safe(session.session_id).trim();
    output.rc_session_status = safe(session.status).trim().toLowerCase();
    output.rc_current_stage_key = safe(session.current_stage_key || (detail.stage_meta && detail.stage_meta.current_stage_key)).trim();
    output.rc_current_stage_title = safe(session.current_stage_title || (detail.stage_meta && detail.stage_meta.current_stage_title)).trim();
    output.rc_ticket_id = safe((detail.stage_meta && detail.stage_meta.ticket_id) || session.assignment_ticket_id).trim();
    output.rc_workspace_init_ref = safe(session.workspace_init_ref).trim();
    output.rc_role_name = safe(profile.role_name).trim();
    output.rc_role_goal = safe(profile.role_goal).trim();
    output.rc_core_capability_count = Array.isArray(profile.core_capabilities) ? profile.core_capabilities.length : 0;
    output.rc_missing_field_count = Array.isArray(profile.missing_fields) ? profile.missing_fields.length : 0;
    output.rc_start_gate_blocker_count = Array.isArray(profile.start_gate_blockers) ? profile.start_gate_blockers.length : 0;
    output.rc_can_start = !!profile.can_start;
    output.rc_stage_count = stages.length;
    output.rc_message_count = messages.length;
    output.rc_message_attachment_count = messages.reduce((total, message) => {
      const attachments = Array.isArray(message && message.attachments) ? message.attachments : [];
      return total + attachments.length;
    }, 0);
    output.rc_user_image_message_count = messages.filter((message) => {
      const role = safe(message && message.role).trim().toLowerCase();
      const attachments = Array.isArray(message && message.attachments) ? message.attachments : [];
      return role === 'user' && attachments.length >= 1;
    }).length;
    output.rc_system_task_update_count = messages.filter((message) => {
      return safe(message && message.message_type).trim().toLowerCase() === 'system_task_update';
    }).length;
    output.rc_profile_card_count = document.querySelectorAll('#rcDetailPaneProfile .rc-profile-card').length;
    output.rc_profile_visible = !!($('rcDetailPaneProfile') && $('rcDetailPaneProfile').classList.contains('active'));
    output.rc_profile_section_titles = Array.from(document.querySelectorAll('#rcDetailPaneProfile [data-rc-profile-title]'))
      .map((node) => safe(node.getAttribute('data-rc-profile-title')).trim())
      .filter(Boolean);
    output.rc_structured_section_titles = Array.from(document.querySelectorAll('#rcDetailPaneProfile [data-rc-structured-section]'))
      .map((node) => safe(node.getAttribute('data-rc-structured-section')).trim())
      .filter(Boolean);
    output.rc_profile_summary_exists = !!document.querySelector("#rcDetailPaneProfile [data-rc-profile-kind='summary']");
    output.rc_progress_step_count = document.querySelectorAll('#rcDetailPaneProfile [data-rc-progress-step]').length;
    output.rc_recent_change_count = document.querySelectorAll('#rcDetailPaneProfile [data-rc-recent-change]').length;
    output.rc_pending_question_count = document.querySelectorAll('#rcDetailPaneProfile [data-rc-pending-question]').length;
    output.rc_seed_capability_count = document.querySelectorAll('#rcDetailPaneProfile [data-rc-seed-capability]').length;
    output.rc_seed_task_count = document.querySelectorAll('#rcDetailPaneProfile [data-rc-seed-task]').length;
    output.rc_knowledge_asset_count = document.querySelectorAll('#rcDetailPaneProfile [data-rc-knowledge-asset]').length;
    output.rc_failure_visible = !!document.querySelector('#rcFailureCardHost .codex-failure-card');
    output.rc_failure_retry_visible = !!Array.from(document.querySelectorAll('#rcFailureCardHost button'))
      .find((node) => safe(node && node.textContent).trim() === '重试本轮分析');
    output.rc_message_image_count = document.querySelectorAll('#rcMessages .rc-message-asset img').length;
    output.rc_task_card_count = taskCards.length;
    output.rc_task_card_ids = taskCards.map((node) => safe(node.getAttribute('data-node-id')).trim()).filter(Boolean);
    output.rc_active_task_ids = activeTaskIds;
    output.rc_archived_task_ids = archivedTaskIds;
    output.rc_archive_pocket_count = archivePockets.length;
    output.rc_archive_total = Number((detail.stage_meta && detail.stage_meta.archive_total) || archivedTaskIds.length || 0);
    output.rc_active_total = Number((detail.stage_meta && detail.stage_meta.active_total) || activeTaskIds.length || 0);
    output.rc_task_ids_match_refs = output.rc_task_card_ids.every((nodeId) => taskRefIds.includes(nodeId));
    output.rc_task_statuses = Array.from(statusSet);
    output.rc_preview_visible = !!(floatNode && floatNode.classList.contains('visible'));
    output.rc_preview_kind = safe(preview.kind).trim();
    output.rc_preview_pinned = !!preview.pinned;
    output.rc_preview_node_id = safe(preview.node_id).trim();
    output.rc_preview_has_task_center_button = !!document.querySelector('#rcTaskHoverFloat [data-rc-open-task-center]');
    output.rc_preview_text = safe(floatNode && floatNode.textContent).trim().slice(0, 1200);
  }

  async function runTrainingCenterProbe() {
    const output = {
      ts: new Date().toISOString(),
      case: trainingCenterProbeCase(),
      pass: false,
      error: '',
      error_code: '',
      module: '',
      agent_count: 0,
      selected_agent_id: '',
      selected_agent_name: '',
      release_count: 0,
      release_versions: [],
      release_has_commit_ref: false,
      lifecycle_state: '',
      training_gate_state: '',
      queue_count: 0,
      queue_removed_count: 0,
      queue_sources: [],
      clone_agent_id: '',
      risk_tip: '',
      run_status: '',
      api_result: {},
      review_state: '',
      review_decision: '',
      review_reviewer: '',
      review_can_review: false,
      review_can_confirm: false,
      review_error: '',
      publish_status: '',
      publish_error: '',
      fallback_status: '',
      release_review_card_mode: '',
      release_review_visible_grid_count: 0,
      release_report_ref_count: 0,
      release_report_button_count: 0,
      release_report_button_versions: [],
      release_report_unavailable_count: 0,
      release_report_unavailable_versions: [],
      release_report_dialog_open: false,
      release_report_dialog_title: '',
      release_report_dialog_version: '',
      release_report_dialog_text: '',
      release_review_current_pills: [],
      report_first_person_summary: '',
      report_change_summary: '',
      report_has_inventory: false,
      report_has_delta: false,
      analysis_chain_paths: {},
      execution_log_phases: [],
      role_profile_source: '',
      role_profile_source_release_id: '',
      role_profile_first_person_summary: '',
      active_role_profile_ref: '',
      portrait_section_keys: [],
      portrait_section_labels: [],
      portrait_item_count: 0,
      portrait_has_source_section: false,
      portrait_is_single_column: false,
      portrait_layout_display: '',
      portrait_layout_direction: '',
      portrait_meta_contains_source: false,
      portrait_release_history_title_visible: false,
      avatar_preview_count: 0,
      avatar_image_count: 0,
      avatar_fallback_svg_count: 0,
      avatar_trigger_count: 0,
      avatar_file_input_count: 0,
      rc_module: '',
      rc_detail_tab: '',
      rc_selected_session_id: '',
      rc_session_id: '',
      rc_session_status: '',
      rc_current_stage_key: '',
      rc_current_stage_title: '',
      rc_ticket_id: '',
      rc_workspace_init_ref: '',
      rc_role_name: '',
      rc_role_goal: '',
      rc_core_capability_count: 0,
      rc_missing_field_count: 0,
      rc_start_gate_blocker_count: 0,
      rc_can_start: false,
      rc_stage_count: 0,
      rc_message_count: 0,
      rc_message_attachment_count: 0,
      rc_user_image_message_count: 0,
      rc_system_task_update_count: 0,
      rc_profile_card_count: 0,
      rc_profile_visible: false,
      rc_profile_section_titles: [],
      rc_structured_section_titles: [],
      rc_progress_step_count: 0,
      rc_recent_change_count: 0,
      rc_pending_question_count: 0,
      rc_seed_capability_count: 0,
      rc_seed_task_count: 0,
      rc_knowledge_asset_count: 0,
      rc_failure_visible: false,
      rc_failure_retry_visible: false,
      rc_message_image_count: 0,
      rc_task_card_count: 0,
      rc_task_card_ids: [],
      rc_active_task_ids: [],
      rc_archived_task_ids: [],
      rc_archive_pocket_count: 0,
      rc_archive_total: 0,
      rc_active_total: 0,
      rc_task_ids_match_refs: false,
      rc_task_statuses: [],
      rc_preview_visible: false,
      rc_preview_kind: '',
      rc_preview_pinned: false,
      rc_preview_node_id: '',
      rc_preview_has_task_center_button: false,
      rc_preview_text: '',
    };
    const errorPayload = (err) => ({
      ok: false,
      error: safe(err && err.message ? err.message : err),
      code: safe(err && err.code),
      status: Number(err && err.status) || 0,
      data: err && err.data ? err.data : {},
    });
    try {
      switchTab('training-center');
      setTrainingCenterModule('agents');
      await refreshTrainingCenterAgents();
      await refreshTrainingCenterQueue();
      const rows = Array.isArray(state.tcAgents) ? state.tcAgents : [];
      output.agent_count = rows.length;
      const probeCase = output.case;
      const requestedAgent = safe(queryParam('tc_probe_agent')).trim().toLowerCase();
      let selected = await selectTrainingCenterProbeAgent({ nonGitFirst: probeCase === 'ac_uo_04' });
      if (!selected) {
        selected = findTrainingCenterProbeAgent({});
      }
      const pickAgentBy = async (matcher) => {
        const list = Array.isArray(state.tcAgents) ? state.tcAgents : [];
        for (const row of list) {
          const aid = safe(row && row.agent_id).trim();
          if (!aid) continue;
          state.tcSelectedAgentId = aid;
          state.tcSelectedAgentName = safe(row.agent_name || '');
          state.tcSelectedAgentDetail = row;
          syncTrainingCenterPlanAgentOptions();
          updateTrainingCenterSelectedMeta();
          renderTrainingCenterAgentList();
          await refreshTrainingCenterSelectedAgentContext(aid);
          const detail = state.tcSelectedAgentDetail || {};
          const releases = Array.isArray(state.tcReleasesByAgent[aid]) ? state.tcReleasesByAgent[aid] : [];
          if (matcher(detail, releases)) {
            return row;
          }
        }
        return null;
      };

      if (requestedAgent) {
        const explicit = await pickAgentBy((detail) => {
          const agentId = safe(detail && detail.agent_id).trim().toLowerCase();
          const agentName = safe(detail && detail.agent_name).trim().toLowerCase();
          return requestedAgent === agentId || requestedAgent === agentName;
        });
        if (explicit) selected = explicit;
      }
      if (probeCase.startsWith('ac_ar_') && !requestedAgent) {
        const preferred = await pickAgentBy((detail, releases) => {
          return !!detail.git_available && releases.length >= 2;
        });
        if (preferred) selected = preferred;
      }
      const selectedId = safe(selected && selected.agent_id).trim();
      const selectedName = safe(selected && selected.agent_name).trim();
      output.selected_agent_id = selectedId;
      output.selected_agent_name = selectedName;

      if (probeCase.startsWith('rc_')) {
        await prepareRoleCreationProbe(probeCase, output);
      } else if (probeCase.startsWith('ac_rp_')) {
        setTrainingCenterModule('agents');
        if (selectedId) {
          await refreshTrainingCenterSelectedAgentContext(selectedId);
        }
      } else if (probeCase === 'ac_uo_01') {
        setTrainingCenterModule('agents');
      } else if (probeCase === 'ac_uo_02' || probeCase === 'ac_uo_03' || probeCase === 'ac_uo_04') {
        setTrainingCenterModule('agents');
      } else if (probeCase === 'ac_uo_05_before') {
        setTrainingCenterModule('ops');
        fillTrainingCenterProbePlan(selectedId, 'before', 'P1');
      } else if (probeCase === 'ac_uo_05_after') {
        setTrainingCenterModule('ops');
        fillTrainingCenterProbePlan(selectedId, 'after', 'P1');
        output.api_result = await postJSON('/api/training/plans/manual', trainingCenterPlanPayload());
        await refreshTrainingCenterQueue();
      } else if (probeCase === 'ac_uo_06') {
        setTrainingCenterModule('ops');
        fillTrainingCenterProbePlan(selectedId, 'priority-missing', '');
        try {
          await postJSON('/api/training/plans/manual', trainingCenterPlanPayload());
        } catch (err) {
          setTrainingCenterError(err.message || String(err));
        }
      } else if (probeCase === 'ac_uo_07') {
        setTrainingCenterModule('ops');
        fillTrainingCenterProbePlan(selectedId, 'dispatch-p2', 'P2');
        await postJSON('/api/training/plans/manual', trainingCenterPlanPayload());
        fillTrainingCenterProbePlan(selectedId, 'dispatch-p0', 'P0');
        await postJSON('/api/training/plans/manual', trainingCenterPlanPayload());
        fillTrainingCenterProbePlan(selectedId, 'dispatch-p1', 'P1');
        await postJSON('/api/training/plans/manual', trainingCenterPlanPayload());
        await refreshTrainingCenterQueue();
      } else if (probeCase === 'ac_uo_08') {
        setTrainingCenterModule('ops');
        fillTrainingCenterProbePlan(selectedId, 'similarity', 'P2');
        if ($('tcPlanGoalInput')) $('tcPlanGoalInput').value = 'similarity-case';
        if ($('tcPlanTasksInput')) $('tcPlanTasksInput').value = 'normalize output\nstabilize retry';
        if ($('tcPlanAcceptanceInput')) $('tcPlanAcceptanceInput').value = 'shape stable';
        await postJSON('/api/training/plans/manual', trainingCenterPlanPayload());
        await postJSON('/api/training/plans/manual', trainingCenterPlanPayload());
        await refreshTrainingCenterQueue();
      } else if (probeCase === 'ac_uo_09_before') {
        setTrainingCenterModule('ops');
        fillTrainingCenterProbePlan(selectedId, 'remove-before', 'P1');
        await postJSON('/api/training/plans/manual', trainingCenterPlanPayload());
        await refreshTrainingCenterQueue();
      } else if (probeCase === 'ac_uo_09_after') {
        setTrainingCenterModule('ops');
        fillTrainingCenterProbePlan(selectedId, 'remove-after', 'P1');
        await postJSON('/api/training/plans/manual', trainingCenterPlanPayload());
        await refreshTrainingCenterQueue();
        const toRemove = (state.tcQueue || []).find((row) => safe(row.status).toLowerCase() === 'queued');
        if (toRemove && safe(toRemove.queue_task_id).trim()) {
          output.api_result = await postJSON(
            '/api/training/queue/' + encodeURIComponent(safe(toRemove.queue_task_id)) + '/remove',
            { operator: 'probe-user', reason: 'tc_probe_remove' }
          );
        }
        // Probe for AC-UO-09 needs to validate removed item state from queue payload.
        await refreshTrainingCenterQueue(true);
      } else if (probeCase === 'ac_uo_10') {
        setTrainingCenterModule('ops');
        fillTrainingCenterProbePlan(selectedId, 'manual-source', 'P2');
        await postJSON('/api/training/plans/manual', trainingCenterPlanPayload());
        fillTrainingCenterProbePlan(selectedId, 'auto-source', 'P2');
        await postJSON('/api/training/plans/auto', trainingCenterPlanPayload());
        await refreshTrainingCenterQueue();
      } else if (probeCase === 'ac_uo_11') {
        setTrainingCenterModule('ops');
        fillTrainingCenterProbePlan(selectedId, 'execute', 'P2');
        const created = await postJSON('/api/training/plans/manual', trainingCenterPlanPayload());
        const queueTaskId = safe(created && created.queue_task_id).trim();
        if (queueTaskId) {
          output.api_result = await postJSON('/api/training/queue/' + encodeURIComponent(queueTaskId) + '/execute', {
            operator: 'probe-user',
          });
        }
        await refreshTrainingCenterQueue();
      } else if (probeCase === 'ac_ar_01') {
        setTrainingCenterModule('agents');
      } else if (probeCase === 'ac_ar_02') {
        setTrainingCenterModule('agents');
      } else if (probeCase === 'ac_ar_03') {
        setTrainingCenterModule('agents');
        try {
          output.api_result = await postJSON('/api/training/agents/' + encodeURIComponent(selectedId) + '/switch', {
            version_label: 'deadbeef-not-release',
            operator: 'probe-user',
          });
        } catch (err) {
          output.api_result = errorPayload(err);
          output.error_code = safe(err && err.code);
        }
      } else if (probeCase === 'ac_ar_04') {
        setTrainingCenterModule('ops');
        const releases = Array.isArray(state.tcReleasesByAgent[selectedId]) ? state.tcReleasesByAgent[selectedId] : [];
        const latest = safe((releases[0] || {}).version_label).trim();
        const older = safe((releases[1] || {}).version_label).trim();
        if (older && latest && older !== latest) {
          await postJSON('/api/training/agents/' + encodeURIComponent(selectedId) + '/switch', {
            version_label: older,
            operator: 'probe-user',
          });
        }
        await refreshTrainingCenterAgents();
        await refreshTrainingCenterSelectedAgentContext(selectedId);
        fillTrainingCenterProbePlan(selectedId, 'ar04-frozen-enqueue', 'P1');
        try {
          output.api_result = await postJSON('/api/training/plans/manual', trainingCenterPlanPayload());
        } catch (err) {
          output.api_result = errorPayload(err);
          output.error_code = safe(err && err.code);
        }
      } else if (probeCase === 'ac_ar_05') {
        setTrainingCenterModule('ops');
        const releases = Array.isArray(state.tcReleasesByAgent[selectedId]) ? state.tcReleasesByAgent[selectedId] : [];
        const latest = safe((releases[0] || {}).version_label).trim();
        if (latest) {
          await postJSON('/api/training/agents/' + encodeURIComponent(selectedId) + '/switch', {
            version_label: latest,
            operator: 'probe-user',
          });
        }
        await refreshTrainingCenterAgents();
        await refreshTrainingCenterSelectedAgentContext(selectedId);
        fillTrainingCenterProbePlan(selectedId, 'ar05-unfreeze-enqueue', 'P1');
        output.api_result = await postJSON('/api/training/plans/manual', trainingCenterPlanPayload());
        await refreshTrainingCenterQueue();
      } else if (probeCase === 'ac_ar_06') {
        setTrainingCenterModule('ops');
        const releases = Array.isArray(state.tcReleasesByAgent[selectedId]) ? state.tcReleasesByAgent[selectedId] : [];
        const latest = safe((releases[0] || {}).version_label).trim();
        const older = safe((releases[1] || {}).version_label).trim();
        if (older && latest && older !== latest) {
          await postJSON('/api/training/agents/' + encodeURIComponent(selectedId) + '/switch', {
            version_label: older,
            operator: 'probe-user',
          });
        }
        const cloneName = safe(selectedId || 'probe-agent')
          .replace(/[^0-9A-Za-z._:-]/g, '')
          .slice(0, 72) + '-clone-' + String(Date.now()).slice(-5);
        const cloneResp = await postJSON('/api/training/agents/' + encodeURIComponent(selectedId) + '/clone', {
          new_agent_name: cloneName,
          operator: 'probe-user',
        });
        output.clone_agent_id = safe(cloneResp.agent_id || '').trim();
        await refreshTrainingCenterAgents();
        state.tcSelectedAgentId = output.clone_agent_id;
        await refreshTrainingCenterSelectedAgentContext(output.clone_agent_id);
        fillTrainingCenterProbePlan(output.clone_agent_id, 'ar06-clone-enqueue', 'P1');
        output.api_result = await postJSON('/api/training/plans/manual', trainingCenterPlanPayload());
        await refreshTrainingCenterQueue();
      } else if (probeCase === 'ac_ar_07') {
        setTrainingCenterModule('ops');
        const trainable = await pickAgentBy((detail) => safe(detail.training_gate_state).toLowerCase() !== 'frozen_switched');
        const trainableId = safe((trainable || {}).agent_id || state.tcSelectedAgentId).trim();
        fillTrainingCenterProbePlan(trainableId, 'ar07-train', 'P1');
        const created = await postJSON('/api/training/plans/manual', trainingCenterPlanPayload());
        const queueTaskId = safe(created.queue_task_id).trim();
        if (queueTaskId) {
          output.api_result = await postJSON('/api/training/queue/' + encodeURIComponent(queueTaskId) + '/execute', {
            operator: 'probe-user',
          });
        }
        await refreshTrainingCenterAgents();
        await refreshTrainingCenterSelectedAgentContext(trainableId);
        await refreshTrainingCenterQueue();
      } else if (probeCase === 'ac_ar_08') {
        setTrainingCenterModule('agents');
        let preRelease = await pickAgentBy((detail) => safe(detail.lifecycle_state).toLowerCase() === 'pre_release');
        if (!preRelease) {
          const trainable = await pickAgentBy((detail) => safe(detail.training_gate_state).toLowerCase() !== 'frozen_switched');
          const aid = safe((trainable || {}).agent_id || state.tcSelectedAgentId).trim();
          setTrainingCenterModule('ops');
          fillTrainingCenterProbePlan(aid, 'ar08-train-to-pre', 'P1');
          const created = await postJSON('/api/training/plans/manual', trainingCenterPlanPayload());
          const queueTaskId = safe(created.queue_task_id).trim();
          if (queueTaskId) {
            await postJSON('/api/training/queue/' + encodeURIComponent(queueTaskId) + '/execute', {
              operator: 'probe-user',
            });
          }
          await refreshTrainingCenterAgents();
          preRelease = await pickAgentBy((detail) => safe(detail.lifecycle_state).toLowerCase() === 'pre_release');
        }
        const discardAgentId = safe((preRelease || {}).agent_id || state.tcSelectedAgentId).trim();
        output.api_result = await postJSON(
          '/api/training/agents/' + encodeURIComponent(discardAgentId) + '/pre-release/discard',
          { operator: 'probe-user' }
        );
        await refreshTrainingCenterAgents();
        await refreshTrainingCenterSelectedAgentContext(discardAgentId);
      } else if (probeCase === 'ac_ar_09') {
        setTrainingCenterModule('agents');
        let preRelease = await pickAgentBy((detail) => safe(detail.lifecycle_state).toLowerCase() === 'pre_release');
        if (!preRelease) {
          const trainable = await pickAgentBy((detail) => safe(detail.training_gate_state).toLowerCase() !== 'frozen_switched');
          const aid = safe((trainable || {}).agent_id || state.tcSelectedAgentId).trim();
          setTrainingCenterModule('ops');
          fillTrainingCenterProbePlan(aid, 'ar09-train-to-pre', 'P1');
          const created = await postJSON('/api/training/plans/manual', trainingCenterPlanPayload());
          const queueTaskId = safe(created.queue_task_id).trim();
          if (queueTaskId) {
            await postJSON('/api/training/queue/' + encodeURIComponent(queueTaskId) + '/execute', {
              operator: 'probe-user',
            });
          }
          await refreshTrainingCenterAgents();
          preRelease = await pickAgentBy((detail) => safe(detail.lifecycle_state).toLowerCase() === 'pre_release');
        }
        const evalAgentId = safe((preRelease || {}).agent_id || state.tcSelectedAgentId).trim();
        output.api_result = await postJSON(
          '/api/training/agents/' + encodeURIComponent(evalAgentId) + '/release-evaluations/manual',
          {
            decision: 'approve',
            reviewer: 'probe-reviewer',
            summary: 'manual evaluation approve in probe',
            operator: 'probe-user',
          }
        );
        await refreshTrainingCenterAgents();
        await refreshTrainingCenterSelectedAgentContext(evalAgentId);
      } else if (probeCase === 'ac_ar_10') {
        setTrainingCenterModule('agents');
      } else if (
        probeCase === 'ac_ar_rr_09' ||
        probeCase === 'ac_ar_rr_10' ||
        probeCase === 'ac_ar_rr_11' ||
        probeCase === 'ac_ar_rr_12' ||
        probeCase === 'ac_ar_rr_13' ||
        probeCase === 'ac_ar_rr_14' ||
        probeCase === 'ac_ar_rr_15' ||
        probeCase === 'ac_ar_rr_16'
      ) {
        setTrainingCenterModule('agents');
        if (selectedId) {
          await refreshTrainingCenterSelectedAgentContext(selectedId);
        }
      } else {
        setTrainingCenterModule('ops');
        await refreshTrainingCenterQueue();
      }

      const selectedDetail = state.tcSelectedAgentDetail || {};
      const roleProfile = trainingCenterRoleProfile(selectedDetail);
      const currentReview = currentTrainingCenterReleaseReview(safe(state.tcSelectedAgentId).trim());
      const releases = state.tcReleasesByAgent[safe(state.tcSelectedAgentId)] || [];
      const queueItems = Array.isArray(state.tcQueue) ? state.tcQueue : [];
      output.module = safe(state.tcModule);
      output.selected_agent_id = safe(state.tcSelectedAgentId);
      output.selected_agent_name = safe(state.tcSelectedAgentName || selectedName);
      output.release_count = releases.length;
      output.release_versions = releases.map((row) => safe(row.version_label)).filter(Boolean);
      output.release_has_commit_ref = releases.some((row) => Object.prototype.hasOwnProperty.call(row || {}, 'commit_ref'));
      output.queue_count = queueItems.length;
      output.queue_removed_count = queueItems.filter((row) => safe(row.status).toLowerCase() === 'removed').length;
      output.queue_sources = Array.from(
        new Set(queueItems.map((row) => safe(row.source).toLowerCase()).filter(Boolean))
      );
      output.risk_tip = safe((output.api_result && output.api_result.risk_tip) || ($('tcOpsRisk') ? $('tcOpsRisk').textContent : ''));
      output.run_status = safe((output.api_result && output.api_result.status) || '');
      output.git_available = !!selectedDetail.git_available;
      output.status_tags = Array.isArray(selectedDetail.status_tags) ? selectedDetail.status_tags : [];
      output.lifecycle_state = safe(selectedDetail.lifecycle_state || '').toLowerCase();
      output.training_gate_state = safe(selectedDetail.training_gate_state || '').toLowerCase();
      output.review_state = safe(currentReview.release_review_state || '').toLowerCase();
      output.review_decision = safe(currentReview.review_decision || '').trim();
      output.review_reviewer = safe(currentReview.reviewer || '').trim();
      output.review_can_enter = !!currentReview.can_enter;
      output.review_can_discard = !!currentReview.can_discard;
      output.review_can_review = !!currentReview.can_review;
      output.review_can_confirm = !!currentReview.can_confirm;
      output.review_error = safe(currentReview.report_error || '').trim();
      output.review_report_error_code = safe(currentReview.report_error_code || '').trim().toLowerCase();
      output.review_report_missing_fields = Array.isArray(currentReview.report_missing_fields) ? currentReview.report_missing_fields : [];
      output.review_required_report_fields = Array.isArray(currentReview.required_report_fields) ? currentReview.required_report_fields : [];
      output.publish_status = safe(currentReview.publish_status || '').toLowerCase();
      output.publish_error = safe(currentReview.publish_error || '').trim();
      output.fallback_status = safe(currentReview.fallback && currentReview.fallback.status).toLowerCase();
      const releaseReviewCard = $('tcReleaseReviewCard');
      output.release_review_card_mode = safe(releaseReviewCard && releaseReviewCard.dataset && releaseReviewCard.dataset.reviewMode).trim().toLowerCase();
      output.release_review_visible_grid_count = Array.from(document.querySelectorAll('#tcReleaseReviewCard .tc-release-review-grid'))
        .filter((node) => !!node && !node.hidden)
        .length;
      const releaseReportButtons = Array.from(document.querySelectorAll('#tcReleaseList button'))
        .filter((node) => safe(node && node.textContent).trim() === '查看发布报告');
      const releaseReportUnavailableNodes = Array.from(document.querySelectorAll('#tcReleaseList .tc-item-sub'))
        .filter((node) => /未绑定可展示的发布报告文件/.test(safe(node && node.textContent).trim()));
      output.release_report_ref_count = releases.filter((row) => !!safe((row && (row.release_source_ref || row.capability_snapshot_ref)) || '').trim()).length;
      output.release_report_button_count = releaseReportButtons.length;
      output.release_report_button_versions = releaseReportButtons
        .map((node) => safe(node && node.dataset && node.dataset.releaseVersion).trim())
        .filter(Boolean);
      output.release_report_unavailable_count = releaseReportUnavailableNodes.length;
      output.release_report_unavailable_versions = releaseReportUnavailableNodes
        .map((node) => safe(node && node.dataset && node.dataset.releaseVersion).trim())
        .filter(Boolean);
      output.release_review_current_pills = Array.from(document.querySelectorAll('#tcReleaseReviewSubstage .tc-release-review-pill.current'))
        .map((node) => safe(node && node.textContent).trim())
        .filter(Boolean);
      output.report_previous_release_version = safe(currentReview.report && currentReview.report.previous_release_version).trim();
      output.report_first_person_summary = safe(currentReview.report && currentReview.report.first_person_summary).trim();
      output.report_change_summary = safe(currentReview.report && currentReview.report.change_summary).trim();
      output.report_release_recommendation = safe(currentReview.report && currentReview.report.release_recommendation).trim().toLowerCase();
      output.report_has_inventory =
        !!(currentReview.report && Array.isArray(currentReview.report.full_capability_inventory) && currentReview.report.full_capability_inventory.length);
      output.report_has_delta =
        !!(currentReview.report && Array.isArray(currentReview.report.capability_delta) && currentReview.report.capability_delta.length);
      output.report_has_knowledge_scope = !!safe(currentReview.report && currentReview.report.knowledge_scope).trim();
      output.report_agent_skill_count =
        currentReview.report && Array.isArray(currentReview.report.agent_skills) ? currentReview.report.agent_skills.length : 0;
      output.report_applicable_scenario_count =
        currentReview.report && Array.isArray(currentReview.report.applicable_scenarios) ? currentReview.report.applicable_scenarios.length : 0;
      output.report_warning_count =
        currentReview.report && Array.isArray(currentReview.report.warnings) ? currentReview.report.warnings.length : 0;
      output.report_has_failure_skeleton =
        !!safe(currentReview.report && currentReview.report.target_version).trim() &&
        !!safe(currentReview.report && currentReview.report.current_workspace_ref).trim() &&
        !!safe(currentReview.report && currentReview.report.change_summary).trim() &&
        !!safe(currentReview.report && currentReview.report.release_recommendation).trim() &&
        !!safe(currentReview.report && currentReview.report.next_action_suggestion).trim();
      output.analysis_chain_paths = {
        prompt_path: safe(currentReview.analysis_chain && currentReview.analysis_chain.prompt_path).trim(),
        stdout_path: safe(currentReview.analysis_chain && currentReview.analysis_chain.stdout_path).trim(),
        stderr_path: safe(currentReview.analysis_chain && currentReview.analysis_chain.stderr_path).trim(),
        report_path: safe(currentReview.analysis_chain && currentReview.analysis_chain.report_path).trim(),
        public_profile_markdown_path: safe(currentReview.public_profile_markdown_path).trim(),
        capability_snapshot_json_path: safe(currentReview.capability_snapshot_json_path).trim(),
      };
      output.execution_log_phases = Array.from(
        new Set(
          (Array.isArray(currentReview.execution_logs) ? currentReview.execution_logs : [])
            .map((row) => safe(row && row.phase).trim().toLowerCase())
            .filter(Boolean)
        )
      );
      output.role_profile_source = safe(roleProfile.profile_source).trim();
      output.role_profile_source_release_id = safe(roleProfile.source_release_id).trim();
      output.role_profile_first_person_summary = safe(roleProfile.first_person_summary).trim();
      output.active_role_profile_ref = safe(selectedDetail.active_role_profile_ref || '').trim();
      const portraitFieldsNode = $('tcPortraitFields');
      const portraitItems = Array.from(document.querySelectorAll('#tcPortraitFields .tc-portrait-item'));
      const portraitLabels = portraitItems
        .map((node) => safe(node && node.querySelector ? node.querySelector('.tc-portrait-k') && node.querySelector('.tc-portrait-k').textContent : '').trim())
        .filter((text) => !!text);
      const portraitKeys = portraitItems
        .map((node) => safe(node && node.getAttribute ? node.getAttribute('data-portrait-key') : '').trim())
        .filter((text) => !!text);
      const portraitStyle = portraitFieldsNode ? window.getComputedStyle(portraitFieldsNode) : null;
      output.portrait_section_labels = portraitLabels;
      output.portrait_section_keys = portraitKeys;
      output.portrait_item_count = portraitItems.length;
      output.portrait_has_source_section = portraitLabels.includes('角色详情来源');
      output.portrait_layout_display = safe(portraitStyle && portraitStyle.display).trim().toLowerCase();
      output.portrait_layout_direction = safe(portraitStyle && portraitStyle.flexDirection).trim().toLowerCase();
      output.portrait_is_single_column =
        output.portrait_layout_display === 'flex' && output.portrait_layout_direction === 'column';
      output.portrait_meta_contains_source = safe($('tcAgentDetailMeta') ? $('tcAgentDetailMeta').textContent : '').includes('角色详情来源=');
      output.portrait_release_history_title_visible = Array.from(document.querySelectorAll('#tcAgentDetailBody .card-title'))
        .some((node) => safe(node && node.textContent).trim() === '发布历史与操作');
      output.avatar_preview_count = document.querySelectorAll('#tcPortraitCard #tcAvatarPreview').length;
      output.avatar_image_count = document.querySelectorAll('#tcPortraitCard #tcAvatarPreview img').length;
      output.avatar_fallback_svg_count = document.querySelectorAll('#tcPortraitCard #tcAvatarPreview svg').length;
      output.avatar_trigger_count = document.querySelectorAll('#tcPortraitCard .tc-avatar-trigger').length;
      output.avatar_file_input_count = document.querySelectorAll('#tcPortraitCard .tc-avatar-file-input').length;
      collectRoleCreationProbeState(output);
      collectTrainingLoopLayoutProbe(output);
      if ((probeCase === 'ac_ar_rr_12' || probeCase === 'ac_ar_rr_19') && output.release_report_button_count >= 1) {
        const requestedReleaseVersion = safe(queryParam('tc_probe_release_version')).trim();
        const releaseReportBtn = Array.from(document.querySelectorAll('#tcReleaseList button'))
          .find((node) => {
            if (safe(node && node.textContent).trim() !== '查看发布报告') return false;
            if (!requestedReleaseVersion) return true;
            return safe(node && node.dataset && node.dataset.releaseVersion).trim() === requestedReleaseVersion;
          });
        if (releaseReportBtn) {
          releaseReportBtn.click();
          await new Promise((resolve) => window.setTimeout(resolve, 250));
          const reportDialog = $('tcPublishedReleaseReportDialog');
          output.release_report_dialog_open = !!(reportDialog && reportDialog.open);
          const reportTitleNode = reportDialog ? reportDialog.querySelector('.tc-report-dialog-title') : null;
          const reportBodyNode = reportDialog ? reportDialog.querySelector('.tc-report-dialog-body') : null;
          output.release_report_dialog_title = safe(reportTitleNode && reportTitleNode.textContent).trim();
          output.release_report_dialog_version = safe(reportDialog && reportDialog.dataset && reportDialog.dataset.releaseVersion).trim();
          output.release_report_dialog_text = safe(reportBodyNode && reportBodyNode.textContent).trim().slice(0, 1600);
          if (probeCase !== 'ac_ar_rr_19' && reportDialog && reportDialog.open && typeof reportDialog.close === 'function') {
            reportDialog.close();
          }
        }
      }
      if (!output.error_code) {
        output.error_code = safe((output.api_result && output.api_result.code) || '').toLowerCase();
      }

      output.pass =
        output.agent_count >= 0 &&
        (probeCase === 'ac_uo_01'
          ? output.agent_count >= 1
          : probeCase === 'ac_uo_02' || probeCase === 'ac_uo_03'
            ? output.release_count >= 1
            : probeCase === 'ac_uo_04'
              ? output.status_tags.includes('git_unavailable')
              : probeCase === 'ac_uo_06'
                ? !!safe($('tcOpsErr').textContent)
              : probeCase === 'ac_uo_09_after'
                  ? output.queue_removed_count >= 1
                  : probeCase === 'ac_uo_10'
                    ? output.queue_sources.includes('manual') && output.queue_sources.includes('auto_analysis')
                    : probeCase === 'ac_ar_01'
                      ? output.agent_count >= 1
                      : probeCase === 'rc_default'
                        ? output.rc_module === 'create-role' &&
                          !!output.rc_session_id &&
                          output.rc_message_count >= 1
                        : probeCase === 'rc_message_with_image'
                          ? output.rc_module === 'create-role' &&
                            output.rc_user_image_message_count >= 1 &&
                            output.rc_message_attachment_count >= 1 &&
                            output.rc_message_image_count >= 1
                          : probeCase === 'rc_profile_tab'
                            ? output.rc_module === 'create-role' &&
                              output.rc_detail_tab === 'profile' &&
                              output.rc_profile_visible &&
                              output.rc_profile_card_count >= 7 &&
                              output.rc_profile_summary_exists &&
                              output.rc_progress_step_count >= 4 &&
                              output.rc_recent_change_count >= 1 &&
                              output.rc_seed_capability_count >= 1 &&
                              output.rc_seed_task_count >= 1 &&
                              output.rc_knowledge_asset_count >= 1 &&
                              ['角色画像', '能力包', '知识沉淀', '首批任务'].every((title) => output.rc_structured_section_titles.includes(title)) &&
                              !!output.rc_role_name
                            : probeCase === 'rc_failure'
                              ? output.rc_module === 'create-role' &&
                                output.rc_detail_tab === 'profile' &&
                                output.rc_profile_visible &&
                                output.rc_failure_visible &&
                                output.rc_failure_retry_visible
                            : probeCase === 'rc_task_hover'
                              ? output.rc_module === 'create-role' &&
                                output.rc_preview_visible &&
                                output.rc_preview_kind === 'task' &&
                                !output.rc_preview_pinned &&
                                !!output.rc_preview_node_id &&
                                output.rc_preview_has_task_center_button
                              : probeCase === 'rc_task_pinned'
                                ? output.rc_module === 'create-role' &&
                                  output.rc_preview_visible &&
                                  output.rc_preview_kind === 'task' &&
                                  output.rc_preview_pinned &&
                                  !!output.rc_preview_node_id &&
                                  output.rc_preview_has_task_center_button
                                : probeCase === 'rc_archive'
                                  ? output.rc_module === 'create-role' &&
                                    output.rc_archive_total >= 1 &&
                                    output.rc_archive_pocket_count >= 1
                                  : probeCase === 'rc_high_load'
                                    ? output.rc_module === 'create-role' &&
                                      output.rc_task_card_count >= 6 &&
                                      output.rc_archive_total >= 1 &&
                                      output.rc_task_ids_match_refs &&
                                      output.rc_task_statuses.includes('succeeded') &&
                                      output.rc_task_statuses.some((item) => item !== 'succeeded')
                      : probeCase === 'ac_ar_02'
                        ? output.release_count >= 1 && !output.release_has_commit_ref
                        : probeCase === 'ac_ar_03'
                          ? output.error_code === 'version_not_released'
                          : probeCase === 'ac_ar_04'
                            ? output.error_code === 'training_frozen_after_switch' || output.training_gate_state === 'frozen_switched'
                            : probeCase === 'ac_ar_05'
                              ? safe(output.api_result && output.api_result.queue_task_id) && output.training_gate_state !== 'frozen_switched'
                              : probeCase === 'ac_ar_06'
                                ? safe(output.clone_agent_id) && safe(output.api_result && output.api_result.queue_task_id)
                                : probeCase === 'ac_ar_07'
                                  ? safe(output.api_result && output.api_result.status).toLowerCase() === 'done' && output.lifecycle_state === 'pre_release'
                                  : probeCase === 'ac_ar_08'
                                    ? !!(output.api_result && output.api_result.discarded) && output.lifecycle_state === 'released'
                                    : probeCase === 'ac_ar_09'
                                      ? !!safe(output.api_result && output.api_result.evaluation_id) && safe(output.api_result && output.api_result.decision) === 'approve'
                                      : probeCase === 'ac_ar_10'
                                        ? true
                                        : probeCase === 'ac_ar_rr_09'
                                          ? output.review_state === 'report_generating'
                                            : probeCase === 'ac_ar_rr_10'
                                              ? output.review_state === 'report_ready' &&
                                                output.report_has_inventory &&
                                                output.report_has_delta &&
                                                output.report_has_knowledge_scope &&
                                                output.report_agent_skill_count >= 1 &&
                                                output.report_applicable_scenario_count >= 1 &&
                                                !!safe(output.analysis_chain_paths.prompt_path) &&
                                                !!safe(output.analysis_chain_paths.stdout_path) &&
                                                !!safe(output.analysis_chain_paths.stderr_path) &&
                                                !!safe(output.analysis_chain_paths.report_path) &&
                                                /^我/.test(output.report_first_person_summary)
                                            : probeCase === 'ac_ar_rr_11'
                                              ? output.review_state === 'review_approved' &&
                                                output.review_decision === 'approve_publish' &&
                                                !!output.review_reviewer
                                            : probeCase === 'ac_ar_rr_12'
                                                ? output.publish_status === 'success' &&
                                                  output.release_review_card_mode === 'inactive' &&
                                                  output.release_review_visible_grid_count === 0 &&
                                                  output.role_profile_source === 'latest_release_report' &&
                                                  !!output.active_role_profile_ref &&
                                                  output.release_report_ref_count >= 1 &&
                                                  output.release_report_button_count >= 1 &&
                                                  output.release_report_dialog_open &&
                                                  /发布报告/.test(output.release_report_dialog_title) &&
                                                  output.release_review_current_pills.length === 0 &&
                                                  /^我/.test(output.role_profile_first_person_summary)
                                                : probeCase === 'ac_ar_rr_19'
                                                  ? output.publish_status === 'success' &&
                                                    output.release_report_button_count >= 1 &&
                                                    output.release_report_dialog_open &&
                                                    /发布报告/.test(output.release_report_dialog_title) &&
                                                    (!safe(queryParam('tc_probe_release_version')).trim() ||
                                                      output.release_report_button_versions.includes(safe(queryParam('tc_probe_release_version')).trim())) &&
                                                    (!safe(queryParam('tc_probe_release_version')).trim() ||
                                                      output.release_report_dialog_version === safe(queryParam('tc_probe_release_version')).trim()) &&
                                                    (!safe(queryParam('tc_probe_release_version')).trim() ||
                                                      output.release_report_dialog_text.includes(safe(queryParam('tc_probe_release_version')).trim()))
                                                : probeCase === 'ac_ar_rr_20'
                                                  ? output.release_report_unavailable_count >= 1 &&
                                                    !output.release_report_dialog_open &&
                                                    (!safe(queryParam('tc_probe_release_version')).trim() ||
                                                      output.release_report_unavailable_versions.includes(safe(queryParam('tc_probe_release_version')).trim())) &&
                                                    (!safe(queryParam('tc_probe_release_version')).trim() ||
                                                      !output.release_report_button_versions.includes(safe(queryParam('tc_probe_release_version')).trim()))
                                                : probeCase === 'ac_ar_rr_13'
                                                  ? output.execution_log_phases.includes('prepare') &&
                                                    output.execution_log_phases.includes('git_execute') &&
                                                    output.execution_log_phases.includes('release_note') &&
                                                    output.execution_log_phases.includes('verify')
                                                  : probeCase === 'ac_ar_rr_14'
                                                    ? output.review_state === 'publish_failed' &&
                                                      !!output.fallback_status &&
                                                      output.execution_log_phases.includes('fallback_trigger') &&
                                                      output.execution_log_phases.includes('fallback_result')
                                                  : probeCase === 'ac_ar_rr_15'
                                                    ? output.review_state === 'report_failed' &&
                                                      !!output.review_error &&
                                                      !!output.review_report_error_code &&
                                                      output.report_has_failure_skeleton &&
                                                      !output.review_can_confirm
                                                    : probeCase === 'ac_ar_rr_16'
                                                      ? output.review_state === 'review_discarded' &&
                                                        output.review_can_enter &&
                                                        !output.review_can_confirm
                                         : true);
    } catch (err) {
      output.error = safe(err && err.message ? err.message : err);
      output.error_code = safe(err && err.code ? err.code : output.error_code);
    }
    const node = ensureTrainingCenterProbeOutputNode();
    node.textContent = JSON.stringify(output);
    node.setAttribute('data-pass', output.pass ? '1' : '0');
  }
