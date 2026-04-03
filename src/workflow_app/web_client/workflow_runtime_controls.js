  async function runPolicyProbe() {
    const stage = policyProbeStage();
    const probeAgent = safe(queryParam('policy_probe_agent')).trim();
    const summary = {
      ts: new Date().toISOString(),
      stage: stage,
      gate: '',
      selected_agent: '',
      new_session_disabled: true,
      policy_gate_disabled: true,
      policy_modal_open: false,
      modal_module_order: [],
      modal_gate_open: false,
      modal_evidence_open: false,
      score_dimension_count: 0,
      score_low_with_explain_count: 0,
      score_manual_review_count: 0,
      score_model: '',
      constraints_counts: { must: 0, must_not: 0, preconditions: 0 },
      gate_fields_complete: false,
    };

    const pickAgent = () => {
      const preferred = probeAgent
        ? state.agents.find((item) => safe(item.agent_name) === probeAgent)
        : null;
      if (preferred) return preferred;
      if (stage === 'manual') {
        return (
          state.agents.find((item) => safe(item.parse_status).toLowerCase() === 'failed') ||
          state.agents.find((item) => safe(item.clarity_gate).toLowerCase() === 'block') ||
          state.agents[0]
        );
      }
      if (stage === 'ready') {
        return (
          state.agents.find((item) => safe(item.clarity_gate).toLowerCase() === 'auto') ||
          state.agents[0]
        );
      }
      return state.agents[0] || null;
    };

    if (stage === 'initial') {
      $('agentSelect').value = '';
      startPolicyAnalysisForSelection();
    } else {
      const chosen = pickAgent();
      if (chosen) {
        $('agentSelect').value = safe(chosen.agent_name);
        state.agentMetaPanelOpen = false;
        state.agentMetaDetailsOpen = false;
        state.agentMetaClarityOpen = false;
        startPolicyAnalysisForSelection();
      }
      if (stage === 'manual') {
        const openDelay = Number(queryParam('policy_probe_open_delay_ms') || '360');
        window.setTimeout(() => {
          try {
            openPolicyConfirmForSelectedAgent();
          } catch (_) {
            // ignore probe open failures
          }
        }, Number.isFinite(openDelay) && openDelay >= 0 ? Math.floor(openDelay) : 360);
      }
    }

    const captureDelayRaw = Number(queryParam('policy_probe_capture_delay_ms') || '');
    const captureDelay =
      Number.isFinite(captureDelayRaw) && captureDelayRaw >= 0
        ? Math.floor(captureDelayRaw)
        : stage === 'analyzing'
          ? 200
          : 520;
    await new Promise((resolve) => window.setTimeout(resolve, captureDelay));

    if (queryParam('policy_probe_expand_clarity') === '1') {
      const summaryNode = document.querySelector('#agentMeta .agent-policy-details > summary');
      if (summaryNode instanceof HTMLElement) {
        summaryNode.click();
      }
    }
    if (queryParam('policy_probe_expand_detail') === '1') {
      const nodes = document.querySelectorAll('#agentMeta .agent-policy-details > summary');
      if (nodes.length > 1 && nodes[1] instanceof HTMLElement) {
        nodes[1].click();
      }
    }
    if (queryParam('policy_probe_expand_gate') === '1') {
      const node = document.querySelector('#policyConfirmGateDetails > summary');
      if (node instanceof HTMLElement) {
        node.click();
      }
    }
    if (queryParam('policy_probe_expand_analysis') === '1') {
      const node = document.querySelector('#policyConfirmAnalysisChain > summary');
      if (node instanceof HTMLElement) {
        node.click();
      }
    }
    if (queryParam('policy_probe_expand_evidence') === '1') {
      const node = document.querySelector('#policyConfirmEvidence > summary');
      if (node instanceof HTMLElement) {
        node.click();
      }
    }

    summary.gate = safe(state.sessionPolicyGateState);
    summary.selected_agent = selectedAgent();
    summary.new_session_disabled = !!$('newSessionBtn').disabled;
    summary.policy_gate_disabled = !!$('policyGateBtn').disabled;
    summary.policy_modal_open = !$('policyConfirmMask').classList.contains('hidden');
    if (summary.policy_modal_open) {
      const moduleNodes = Array.from(document.querySelectorAll('#policyConfirmSummary [data-policy-module]'));
      summary.modal_module_order = moduleNodes.map((node) => safe(node.getAttribute('data-policy-module')));
      summary.modal_module_titles = moduleNodes.map((node) =>
        safe(node.querySelector('.policy-confirm-module-head') && node.querySelector('.policy-confirm-module-head').textContent).trim()
      );
      const gateDetail = $('policyConfirmGateDetails');
      const analysisDetail = $('policyConfirmAnalysisChain');
      const evidenceDetail = $('policyConfirmEvidence');
      summary.modal_gate_open = !!(gateDetail && gateDetail.open);
      summary.modal_analysis_open = !!(analysisDetail && analysisDetail.open);
      summary.modal_evidence_open = !!(evidenceDetail && evidenceDetail.open);
      const scoreDetail = document.querySelector('#policyConfirmSummary [data-policy-module=\"score\"]');
      summary.modal_score_open = !!(scoreDetail && scoreDetail.open);
      summary.modal_has_legacy_constraints_title = summary.modal_module_titles.includes(
        '限制内容（必须项 / 禁止项 / 前置条件）'
      );
      summary.modal_has_legacy_core_title = summary.modal_module_titles.includes('角色/职责/目标');
      const dimNodes = Array.from(document.querySelectorAll('#policyConfirmSummary .policy-score-dim'));
      summary.score_dimension_count = dimNodes.length;
      summary.score_low_with_explain_count = 0;
      summary.score_manual_review_count = 0;
      for (const node of dimNodes) {
        const cls = safe(node.className);
        const isLow = /\blow\b/.test(cls);
        const isManual = /\bmanual_review\b/.test(cls);
        if (isManual) summary.score_manual_review_count += 1;
        if (!isLow && !isManual) continue;
        const hasReason = !!safe(node.querySelector('.policy-score-dim-reason') && node.querySelector('.policy-score-dim-reason').textContent).trim();
        const hasEvidence = !!safe(node.querySelector('.policy-score-evidence') && node.querySelector('.policy-score-evidence').textContent).trim();
        const hasRepair = !!safe(node.querySelector('.policy-score-repair') && node.querySelector('.policy-score-repair').textContent).trim();
        if (hasReason && hasEvidence && hasRepair) {
          summary.score_low_with_explain_count += 1;
        }
      }
      const pending = state.pendingPolicyConfirmation && state.pendingPolicyConfirmation.payload
        ? state.pendingPolicyConfirmation.payload
        : {};
      summary.score_model = safe(pending.score_model || '');
      const constraints = pending.constraints && typeof pending.constraints === 'object' ? pending.constraints : {};
      summary.constraints_counts = {
        must: Array.isArray(constraints.must) ? constraints.must.length : 0,
        must_not: Array.isArray(constraints.must_not) ? constraints.must_not.length : 0,
        preconditions: Array.isArray(constraints.preconditions) ? constraints.preconditions.length : 0,
      };
      summary.gate_fields_complete = !!(
        safe(pending.clarity_gate).trim() &&
        safe(pending.parse_status).trim() &&
        safe(pending.agents_hash).trim() &&
        safe(pending.agents_path).trim() &&
        safe(pending.policy_cache_status).trim()
      );
    }

    let probeNode = $('policyProbeOutput');
    if (!probeNode) {
      probeNode = document.createElement('pre');
      probeNode.id = 'policyProbeOutput';
      probeNode.style.display = 'none';
      document.body.appendChild(probeNode);
    }
    probeNode.textContent = JSON.stringify(summary);
  }

  async function switchAgentSearchRoot() {
    const root = safe($('agentSearchRoot').value).trim();
    if (!root) throw new Error('agent路径不能为空');
    try {
      const data = await postJSON('/api/config/agent-search-root', {
        agent_search_root: root,
      });
      if (data.agent_search_root) {
        $('agentSearchRoot').value = safe(data.agent_search_root);
      }
      clearFrontendSessions();
      clearWorkflowPanel();
      await refreshAgents(false, { autoAnalyze: false });
      await refreshSessions();
      await refreshWorkflows();
      await refreshDashboard();
      setStatus('agent路径已更新，请重新选择角色并创建会话');
    } catch (err) {
      const payload = (err && err.data) || {};
      if (safe(payload.code) === 'active_sessions_open') {
        const active = Array.isArray(payload.active_sessions) ? payload.active_sessions : [];
        const names = active.slice(0, 6).map((it) => safe(it.session_id));
        let detail = names.length
          ? names.join('、')
          : '活动会话数量=' + safe(payload.active_count || active.length);
        if (active.length > names.length) {
          detail += '（其余 ' + String(active.length - names.length) + ' 个省略）';
        }
        throw new Error('存在未关闭会话，禁止切换根路径。请先关闭：' + detail);
      }
      throw err;
    }
  }

  async function switchArtifactRoot() {
    const root = safe($('artifactRootPathInput').value).trim();
    if (!root) throw new Error('任务产物路径不能为空');
    const data = await postJSON('/api/config/artifact-root', {
      artifact_root: root,
    });
    state.artifactRootPath = safe(data.task_artifact_root || data.artifact_root).trim();
    state.artifactWorkspaceRoot = safe(data.task_records_root || data.tasks_root || data.workspace_root).trim();
    state.artifactTasksRoot = safe(data.tasks_root || data.task_records_root || data.workspace_root).trim();
    state.artifactStructurePath = safe(data.tasks_structure_path || data.artifact_root_structure_path).trim();
    state.artifactRootDefaultPath = safe(data.default_task_artifact_root || data.default_artifact_root).trim();
    state.artifactRootValidationStatus = safe(data.path_validation_status).trim();
    updateArtifactRootMeta();
    await refreshAgents(false, { autoAnalyze: false });
    if (selectedAssignmentTicketId && typeof selectedAssignmentTicketId === 'function' && selectedAssignmentTicketId()) {
      await refreshAssignmentGraphData({ ticketId: selectedAssignmentTicketId() });
    }
    setStatus('任务产物路径已更新');
  }

  async function refreshAssignmentExecutionSettings() {
    if (!state.agentSearchRootReady) {
      updateAssignmentExecutionSettingsMeta();
      return assignmentExecutionSettingsPayload();
    }
    const data = await getJSON('/api/assignments/settings/execution');
    applyAssignmentExecutionSettingsPayload(data);
    return assignmentExecutionSettingsPayload();
  }

  async function saveAssignmentExecutionSettings() {
    if (!state.agentSearchRootReady) {
      throw new Error('agent路径未设置或无效，无法更新任务执行配置');
    }
    const provider = safe($('assignmentExecutionProviderSelect') ? $('assignmentExecutionProviderSelect').value : '').trim() || 'codex';
    const codexPath = safe($('assignmentCodexCommandPathInput') ? $('assignmentCodexCommandPathInput').value : '').trim();
    const commandTemplate = safe($('assignmentCommandTemplateInput') ? $('assignmentCommandTemplateInput').value : '');
    const concurrencyLimit = Number(
      safe($('assignmentExecutionConcurrencyInput') ? $('assignmentExecutionConcurrencyInput').value : '').trim() || '0',
    );
    const data = await postJSON('/api/assignments/settings/execution', {
      execution_provider: provider,
      codex_command_path: codexPath,
      command_template: commandTemplate,
      global_concurrency_limit: concurrencyLimit,
      operator: 'web-user',
    });
    applyAssignmentExecutionSettingsPayload(data);
    if (selectedAssignmentTicketId && typeof selectedAssignmentTicketId === 'function' && selectedAssignmentTicketId()) {
      await refreshAssignmentGraphData({ ticketId: selectedAssignmentTicketId() });
    }
    setStatus('任务执行设置已更新');
    return data;
  }
