  // Training center role creation workbench.

  function roleCreationEscapeHtml(value) {
    return safe(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function roleCreationSessionStatusText(value) {
    const key = safe(value).trim().toLowerCase();
    if (key === 'creating') return '创建中';
    if (key === 'completed') return '已完成';
    return '草稿';
  }

  function normalizeRoleCreationStatusFilter(value) {
    const key = safe(value).trim().toLowerCase();
    if (key === 'draft' || key === 'creating' || key === 'completed') return key;
    return 'all';
  }

  function roleCreationStatusTone(value) {
    const key = safe(value).trim().toLowerCase();
    if (key === 'running' || key === 'creating' || key === 'current') return 'active';
    if (key === 'succeeded' || key === 'completed') return 'done';
    if (key === 'failed') return 'danger';
    if (key === 'archived') return 'archive';
    return 'pending';
  }

  function roleCreationStageStateText(value) {
    const key = safe(value).trim().toLowerCase();
    if (key === 'completed') return '已完成';
    if (key === 'current') return '当前阶段';
    return '待进入';
  }

  function roleCreationCurrentDetail() {
    return state.tcRoleCreationDetail && typeof state.tcRoleCreationDetail === 'object'
      ? state.tcRoleCreationDetail
      : {};
  }

  const ROLE_CREATION_ASSIGNMENT_SOURCE_WORKFLOW = 'workflow-ui';
  const ROLE_CREATION_ASSIGNMENT_GRAPH_REQUEST_ID = 'workflow-ui-global-graph-v1';

  function roleCreationAssignmentGraphOverview(detail) {
    const payload = detail && typeof detail === 'object' ? detail : roleCreationCurrentDetail();
    const assignmentGraph = payload.assignment_graph && typeof payload.assignment_graph === 'object'
      ? payload.assignment_graph
      : {};
    const graphOverview = assignmentGraph.graph && typeof assignmentGraph.graph === 'object'
      ? assignmentGraph.graph
      : {};
    if (safe(graphOverview.ticket_id).trim()) {
      return graphOverview;
    }
    const stageMeta = payload.stage_meta && typeof payload.stage_meta === 'object'
      ? payload.stage_meta
      : {};
    return stageMeta.graph_overview && typeof stageMeta.graph_overview === 'object'
      ? stageMeta.graph_overview
      : {};
  }

  function roleCreationMainGraphTicketId(session, detail) {
    const sessionSummary = session && typeof session === 'object' ? session : roleCreationCurrentSession();
    const payload = detail && typeof detail === 'object' ? detail : roleCreationCurrentDetail();
    const overview = roleCreationAssignmentGraphOverview(payload);
    const ticketId = safe(
      overview.ticket_id ||
      (payload.stage_meta && payload.stage_meta.ticket_id) ||
      sessionSummary.assignment_ticket_id
    ).trim();
    if (!ticketId) {
      return '';
    }
    if (safe(overview.source_workflow).trim().toLowerCase() !== ROLE_CREATION_ASSIGNMENT_SOURCE_WORKFLOW) {
      return '';
    }
    if (safe(overview.external_request_id).trim() !== ROLE_CREATION_ASSIGNMENT_GRAPH_REQUEST_ID) {
      return '';
    }
    return ticketId;
  }

  function roleCreationCurrentSession() {
    const detail = roleCreationCurrentDetail();
    return detail.session && typeof detail.session === 'object' ? detail.session : {};
  }

  function roleCreationCurrentProfile() {
    const detail = roleCreationCurrentDetail();
    return detail.profile && typeof detail.profile === 'object' ? detail.profile : {};
  }

  function roleCreationCurrentStructuredSpecs() {
    const detail = roleCreationCurrentDetail();
    return detail.structured_specs && typeof detail.structured_specs === 'object'
      ? detail.structured_specs
      : {};
  }

  function roleCreationCurrentStartGate() {
    const detail = roleCreationCurrentDetail();
    if (detail.start_gate && typeof detail.start_gate === 'object') {
      return detail.start_gate;
    }
    const profile = roleCreationCurrentProfile();
    return profile.start_gate && typeof profile.start_gate === 'object' ? profile.start_gate : {};
  }

  function roleCreationCurrentAnalysisProgress() {
    const detail = roleCreationCurrentDetail();
    if (detail.analysis_progress && typeof detail.analysis_progress === 'object') {
      return detail.analysis_progress;
    }
    const session = roleCreationCurrentSession();
    return session.analysis_progress && typeof session.analysis_progress === 'object'
      ? session.analysis_progress
      : {};
  }

  function roleCreationCurrentStages() {
    const detail = roleCreationCurrentDetail();
    return Array.isArray(detail.stages) ? detail.stages : [];
  }

  function roleCreationCurrentMessages() {
    const detail = roleCreationCurrentDetail();
    return Array.isArray(detail.messages) ? detail.messages : [];
  }

  function roleCreationSessionSearchText(session) {
    const row = session && typeof session === 'object' ? session : {};
    return [
      row.session_title,
      row.role_name,
      row.last_message_preview,
      row.created_agent_name,
      row.assignment_ticket_id,
      row.dialogue_agent_name,
      roleCreationSessionStatusText(row.status),
    ]
      .map((item) => safe(item).trim().toLowerCase())
      .filter((item) => !!item)
      .join('\n');
  }

  function roleCreationFilteredSessions() {
    const rows = Array.isArray(state.tcRoleCreationSessions) ? state.tcRoleCreationSessions : [];
    const query = safe(state.tcRoleCreationQuery).trim().toLowerCase();
    const statusFilter = normalizeRoleCreationStatusFilter(state.tcRoleCreationStatusFilter);
    return rows.filter((session) => {
      const status = safe(session && session.status).trim().toLowerCase();
      if (statusFilter !== 'all' && status !== statusFilter) {
        return false;
      }
      if (!query) {
        return true;
      }
      return roleCreationSessionSearchText(session).includes(query);
    });
  }

  function roleCreationOptimisticMessages(sessionId) {
    const key = safe(sessionId).trim();
    if (!key) return [];
    const store = state.tcRoleCreationOptimisticMessages && typeof state.tcRoleCreationOptimisticMessages === 'object'
      ? state.tcRoleCreationOptimisticMessages
      : {};
    return Array.isArray(store[key]) ? store[key] : [];
  }

  function roleCreationReplaceOptimisticMessages(sessionId, messages) {
    const key = safe(sessionId).trim();
    if (!key) return;
    const store = state.tcRoleCreationOptimisticMessages && typeof state.tcRoleCreationOptimisticMessages === 'object'
      ? Object.assign({}, state.tcRoleCreationOptimisticMessages)
      : {};
    const rows = Array.isArray(messages) ? messages.slice() : [];
    if (rows.length) {
      store[key] = rows;
    } else {
      delete store[key];
    }
    state.tcRoleCreationOptimisticMessages = store;
  }

  function roleCreationPushOptimisticMessage(sessionId, message) {
    const key = safe(sessionId).trim();
    if (!key || !message || typeof message !== 'object') return;
    const rows = roleCreationOptimisticMessages(key).slice();
    rows.push(Object.assign({}, message));
    roleCreationReplaceOptimisticMessages(key, rows);
  }

  function roleCreationDropOptimisticMessage(sessionId, clientMessageId) {
    const key = safe(sessionId).trim();
    const clientId = safe(clientMessageId).trim();
    if (!key || !clientId) return;
    const rows = roleCreationOptimisticMessages(key)
      .filter((item) => safe(item && item.client_message_id).trim() !== clientId);
    roleCreationReplaceOptimisticMessages(key, rows);
  }

  function roleCreationPruneOptimisticMessages(sessionId, serverMessages) {
    const key = safe(sessionId).trim();
    if (!key) return;
    const seen = new Set(
      (Array.isArray(serverMessages) ? serverMessages : [])
        .map((item) => safe(item && (item.client_message_id || (item.meta && item.meta.client_message_id))).trim())
        .filter((item) => !!item)
    );
    if (!seen.size) return;
    const rows = roleCreationOptimisticMessages(key)
      .filter((item) => !seen.has(safe(item && item.client_message_id).trim()));
    roleCreationReplaceOptimisticMessages(key, rows);
  }

  function roleCreationSessionProcessingInfo(sessionSummary) {
    const summary = sessionSummary && typeof sessionSummary === 'object' ? sessionSummary : {};
    const sessionId = safe(summary.session_id).trim();
    const optimisticCount = roleCreationOptimisticMessages(sessionId).length;
    const serverUnhandled = Math.max(0, Number(summary.unhandled_user_message_count || 0));
    const totalUnhandled = serverUnhandled + optimisticCount;
    let status = safe(summary.message_processing_status).trim().toLowerCase();
    if (optimisticCount > 0 && (!status || status === 'idle')) {
      status = 'pending';
    }
    if (!status) {
      status = totalUnhandled > 0 ? 'pending' : 'idle';
    }
    if (status === 'running' && totalUnhandled <= 0) {
      status = 'idle';
    } else if (status === 'pending' && totalUnhandled <= 0) {
      status = 'idle';
    } else if (status === 'idle' && totalUnhandled > 0) {
      status = 'pending';
    }
    const progress = summary.analysis_progress && typeof summary.analysis_progress === 'object'
      ? summary.analysis_progress
      : {};
    let text = safe(progress.status_text || summary.message_processing_status_text).trim();
    if (!text) {
      if (status === 'running') text = '分析中';
      else if (status === 'pending') text = '待分析';
      else if (status === 'failed') text = '分析失败';
      else text = '空闲';
    }
    return {
      status: status,
      text: text,
      active: status === 'pending' || status === 'running',
      failed: status === 'failed',
      unhandledCount: totalUnhandled,
      error: safe(summary.message_processing_error).trim(),
      stepLabel: safe(progress.current_step_label).trim(),
      progress: progress,
    };
  }

  function roleCreationCurrentProcessingInfo() {
    return roleCreationSessionProcessingInfo(roleCreationCurrentSession());
  }

  function roleCreationDisplayMessages() {
    const session = roleCreationCurrentSession();
    const serverRows = roleCreationCurrentMessages().slice();
    const optimisticRows = roleCreationOptimisticMessages(session.session_id);
    const merged = serverRows.slice();
    optimisticRows.forEach((item) => {
      merged.push(Object.assign({}, item));
    });
    merged.sort((a, b) => {
      const at = safe(a && a.created_at).trim();
      const bt = safe(b && b.created_at).trim();
      if (at !== bt) return at.localeCompare(bt);
      return safe(a && (a.message_id || a.client_message_id)).localeCompare(safe(b && (b.message_id || b.client_message_id)));
    });
    const processing = roleCreationCurrentProcessingInfo();
    const progress = roleCreationCurrentAnalysisProgress();
    if (safe(session.session_id).trim() && processing.active) {
      merged.push({
        message_id: 'local-processing-placeholder',
        role: 'assistant',
        content: safe(progress.placeholder_text || processing.text).trim()
          || (processing.status === 'pending' ? '已收到，正在合并本轮消息…' : '分析中…'),
        attachments: [],
        message_type: 'chat',
        created_at: new Date().toISOString(),
        processing_placeholder: true,
      });
    }
    return merged;
  }

  function roleCreationShouldPoll() {
    const sessionId = safe(state.tcRoleCreationSelectedSessionId).trim();
    if (!sessionId) return false;
    return roleCreationCurrentProcessingInfo().active || roleCreationOptimisticMessages(sessionId).length > 0;
  }

  function stopRoleCreationPoller() {
    if (state.tcRoleCreationPoller) {
      clearInterval(state.tcRoleCreationPoller);
      state.tcRoleCreationPoller = 0;
    }
  }

  function startRoleCreationPoller() {
    if (state.tcRoleCreationPoller) return;
    state.tcRoleCreationPoller = window.setInterval(() => {
      if (state.tcRoleCreationPollBusy) return;
      const sessionId = safe(state.tcRoleCreationSelectedSessionId).trim();
      if (!sessionId) {
        stopRoleCreationPoller();
        return;
      }
      state.tcRoleCreationPollBusy = true;
      refreshRoleCreationSessionDetail(sessionId, { skipRender: true, background: true })
        .catch((err) => {
          setRoleCreationError(err.message || String(err));
        })
        .finally(() => {
          state.tcRoleCreationPollBusy = false;
          if (!roleCreationShouldPoll()) {
            stopRoleCreationPoller();
          }
        });
    }, 900);
  }

  function syncRoleCreationPoller() {
    if (roleCreationShouldPoll()) {
      startRoleCreationPoller();
    } else {
      stopRoleCreationPoller();
    }
  }

  function roleCreationCurrentCreatedAgent() {
    const detail = roleCreationCurrentDetail();
    return detail.created_agent && typeof detail.created_agent === 'object' ? detail.created_agent : {};
  }

  function roleCreationCurrentDialogueAgent() {
    const detail = roleCreationCurrentDetail();
    return detail.dialogue_agent && typeof detail.dialogue_agent === 'object' ? detail.dialogue_agent : {};
  }

  function setRoleCreationError(text) {
    state.tcRoleCreationError = safe(text);
    const node = $('rcError');
    if (node) node.textContent = state.tcRoleCreationError;
  }

  function normalizeRoleCreationDetailTab(value) {
    return safe(value).trim().toLowerCase() === 'profile' ? 'profile' : 'evolution';
  }

  function setRoleCreationDetailTab(tabName) {
    const next = normalizeRoleCreationDetailTab(tabName);
    state.tcRoleCreationDetailTab = next;
    const evolutionBtn = $('rcDetailTabEvolution');
    const profileBtn = $('rcDetailTabProfile');
    const evolutionPane = $('rcDetailPaneEvolution');
    const profilePane = $('rcDetailPaneProfile');
    if (evolutionBtn) evolutionBtn.classList.toggle('active', next === 'evolution');
    if (profileBtn) profileBtn.classList.toggle('active', next === 'profile');
    if (evolutionPane) evolutionPane.classList.toggle('active', next === 'evolution');
    if (profilePane) profilePane.classList.toggle('active', next === 'profile');
  }

  function roleCreationUnresolvedTaskCount(detail) {
    const payload = detail && typeof detail === 'object' ? detail : roleCreationCurrentDetail();
    const stages = Array.isArray(payload.stages) ? payload.stages : [];
    let total = 0;
    stages.forEach((stage) => {
      const activeTasks = Array.isArray(stage && stage.active_tasks) ? stage.active_tasks : [];
      activeTasks.forEach((task) => {
        if (safe(task && task.status).trim().toLowerCase() !== 'succeeded') {
          total += 1;
        }
      });
    });
    return total;
  }

  function roleCreationCanComplete(detail) {
    const payload = detail && typeof detail === 'object' ? detail : roleCreationCurrentDetail();
    const session = payload.session && typeof payload.session === 'object' ? payload.session : {};
    return safe(session.status).trim().toLowerCase() === 'creating' && roleCreationUnresolvedTaskCount(payload) === 0;
  }

  function syncRoleCreationSessionSummary(sessionSummary) {
    const summary = sessionSummary && typeof sessionSummary === 'object' ? sessionSummary : {};
    const sessionId = safe(summary.session_id).trim();
    if (!sessionId) return;
    const rows = Array.isArray(state.tcRoleCreationSessions) ? state.tcRoleCreationSessions.slice() : [];
    const nextRows = [];
    let replaced = false;
    rows.forEach((row) => {
      if (safe(row && row.session_id).trim() !== sessionId) {
        nextRows.push(row);
        return;
      }
      nextRows.push(Object.assign({}, row || {}, summary));
      replaced = true;
    });
    if (!replaced) {
      nextRows.unshift(Object.assign({}, summary));
    }
    nextRows.sort((a, b) => safe(b && b.updated_at).localeCompare(safe(a && a.updated_at)));
    state.tcRoleCreationSessions = nextRows;
    state.tcRoleCreationTotal = nextRows.length;
  }

  function applyRoleCreationDetailPayload(payload, options) {
    const data = payload && typeof payload === 'object' ? payload : {};
    const session = data.session && typeof data.session === 'object' ? data.session : {};
    const sessionId = safe(session.session_id).trim();
    if (!sessionId) return null;
    roleCreationPruneOptimisticMessages(sessionId, data.messages);
    clearRoleCreationTaskPreview();
    state.tcRoleCreationDetail = data;
    state.tcRoleCreationSelectedSessionId = sessionId;
    writeSavedRoleCreationSessionId(sessionId);
    syncRoleCreationSessionSummary(session);
    syncRoleCreationPoller();
    if (!(options && options.skipRender)) {
      renderRoleCreationWorkbench();
    }
    return data;
  }

  async function refreshRoleCreationSessionDetail(sessionId, options) {
    const key = safe(sessionId).trim();
    const opts = options && typeof options === 'object' ? options : {};
    const background = !!opts.background;
    if (!key) {
      state.tcRoleCreationDetail = null;
      state.tcRoleCreationSelectedSessionId = '';
      writeSavedRoleCreationSessionId('');
      syncRoleCreationPoller();
      renderRoleCreationWorkbench();
      return null;
    }
    if (!background) {
      state.tcRoleCreationLoading = true;
    }
    if (!opts.skipRender && !background) {
      renderRoleCreationWorkbench();
    }
    try {
      const data = await getJSON('/api/training/role-creation/sessions/' + encodeURIComponent(key));
      if (safe(state.tcRoleCreationSelectedSessionId).trim() && safe(state.tcRoleCreationSelectedSessionId).trim() !== key) {
        return data;
      }
      setRoleCreationError('');
      return applyRoleCreationDetailPayload(data, opts);
    } finally {
      if (!background) {
        state.tcRoleCreationLoading = false;
      }
      syncRoleCreationPoller();
      renderRoleCreationWorkbench();
    }
  }

  async function selectRoleCreationSession(sessionId, options) {
    const key = safe(sessionId).trim();
    if (!key) return null;
    state.tcRoleCreationSelectedSessionId = key;
    writeSavedRoleCreationSessionId(key);
    if (
      state.tcRoleCreationDetail &&
      safe(roleCreationCurrentSession().session_id).trim() === key &&
      !(options && options.force)
    ) {
      syncRoleCreationPoller();
      renderRoleCreationWorkbench();
      return state.tcRoleCreationDetail;
    }
    return refreshRoleCreationSessionDetail(key, options);
  }

  async function refreshRoleCreationSessions(options) {
    const opts = options && typeof options === 'object' ? options : {};
    if (!state.agentSearchRootReady) {
      state.tcRoleCreationSessions = [];
      state.tcRoleCreationTotal = 0;
      state.tcRoleCreationSelectedSessionId = '';
      state.tcRoleCreationDetail = null;
      writeSavedRoleCreationSessionId('');
      syncRoleCreationPoller();
      renderRoleCreationWorkbench();
      return { items: [], total: 0 };
    }
    state.tcRoleCreationLoading = true;
    if (!opts.skipRender) {
      renderRoleCreationWorkbench();
    }
    try {
      const data = await getJSON('/api/training/role-creation/sessions');
      state.tcRoleCreationSessions = Array.isArray(data.items) ? data.items : [];
      state.tcRoleCreationTotal = Number(data.total || state.tcRoleCreationSessions.length || 0);
      const current = safe(state.tcRoleCreationSelectedSessionId).trim();
      const cached = readSavedRoleCreationSessionId();
      const availableIds = new Set(
        state.tcRoleCreationSessions
          .map((item) => safe(item && item.session_id).trim())
          .filter((item) => !!item)
      );
      let next = current;
      if (!availableIds.has(next)) {
        next = availableIds.has(cached) ? cached : '';
      }
      if (!availableIds.has(next)) {
        next = state.tcRoleCreationSessions.length
          ? safe(state.tcRoleCreationSessions[0].session_id).trim()
          : '';
      }
      state.tcRoleCreationSelectedSessionId = next;
      if (!next) {
        state.tcRoleCreationDetail = null;
        writeSavedRoleCreationSessionId('');
        setRoleCreationError('');
        syncRoleCreationPoller();
        return data;
      }
      return await refreshRoleCreationSessionDetail(next, { skipRender: true });
    } finally {
      state.tcRoleCreationLoading = false;
      syncRoleCreationPoller();
      renderRoleCreationWorkbench();
    }
  }

  async function createRoleCreationSession() {
    const data = await postJSON('/api/training/role-creation/sessions', {
      operator: 'web-user',
    });
    setRoleCreationError('');
    applyRoleCreationDetailPayload(data);
    return data;
  }

  async function deleteRoleCreationSession(sessionId) {
    const key = safe(sessionId).trim();
    if (!key) return null;
    const rows = Array.isArray(state.tcRoleCreationSessions) ? state.tcRoleCreationSessions : [];
    const session = rows.find((item) => safe(item && item.session_id).trim() === key) || {};
    const status = safe(session && session.status).trim().toLowerCase();
    const processing = roleCreationSessionProcessingInfo(session);
    if (processing.active) {
      throw new Error('当前对话仍在分析中，请等待处理完成后再删除');
    }
    const deleteAvailable = !!(session && session.delete_available);
    const deleteBlockReasonText = safe(session && session.delete_block_reason_text).trim();
    if ((status === 'creating' || status === 'draft' || status === 'completed') && !deleteAvailable) {
      throw new Error(deleteBlockReasonText || '当前状态暂不支持删除');
    }
    const title = safe(session && session.session_title).trim() || '未命名角色草稿';
    const confirmed = window.confirm(
      status === 'completed'
        ? ('确认从创建角色列表中删除“' + title + '”吗？已创建的角色工作区和任务中心主图历史任务不会被删除。')
        : status === 'creating'
          ? ('确认清理并删除“' + title + '”吗？当前会话、已创建工作区和映射到任务中心主图的任务节点会一并清理。仅在当前角色创建任务没有运行中节点时才能执行。')
          : ('确认删除草稿“' + title + '”吗？当前对话记录会一并删除。')
    );
    if (!confirmed) return null;
    const data = await deleteJSON(
      '/api/training/role-creation/sessions/' + encodeURIComponent(key),
      { operator: 'web-user' },
    );
    roleCreationReplaceOptimisticMessages(key, []);
    clearRoleCreationTaskPreview();
    setRoleCreationError('');
    await refreshRoleCreationSessions();
    refreshTrainingCenterAgents().catch(() => {});
    return data;
  }

  function resetRoleCreationDraft() {
    state.tcRoleCreationDraftAttachments = [];
    if ($('rcInput')) $('rcInput').value = '';
    if ($('rcImageInput')) $('rcImageInput').value = '';
    renderRoleCreationDraftAttachments();
  }

  async function postRoleCreationMessage() {
    const sessionId = safe(state.tcRoleCreationSelectedSessionId).trim();
    if (!sessionId) {
      throw new Error('请先创建或选择一个角色草稿');
    }
    const content = safe($('rcInput') ? $('rcInput').value : '').trim();
    const attachments = Array.isArray(state.tcRoleCreationDraftAttachments) ? state.tcRoleCreationDraftAttachments.slice() : [];
    if (!content && !attachments.length) {
      throw new Error('请先输入内容，或添加一张图片');
    }
    const clientMessageId = 'rc-local-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
    roleCreationPushOptimisticMessage(sessionId, {
      message_id: clientMessageId,
      client_message_id: clientMessageId,
      session_id: sessionId,
      role: 'user',
      content: content,
      attachments: attachments,
      message_type: 'chat',
      created_at: new Date().toISOString(),
      processing_state: 'pending',
      processing_state_text: '待处理',
      local_only: true,
    });
    resetRoleCreationDraft();
    syncRoleCreationPoller();
    renderRoleCreationWorkbench();
    let data;
    try {
      data = await postJSON(
        '/api/training/role-creation/sessions/' + encodeURIComponent(sessionId) + '/messages',
        {
          content: content,
          attachments: attachments,
          operator: 'web-user',
          client_message_id: clientMessageId,
        },
      );
    } catch (err) {
      roleCreationDropOptimisticMessage(sessionId, clientMessageId);
      if ($('rcInput') && !safe($('rcInput').value).trim()) {
        $('rcInput').value = content;
      }
      state.tcRoleCreationDraftAttachments = attachments.slice();
      renderRoleCreationDraftAttachments();
      syncRoleCreationPoller();
      renderRoleCreationWorkbench();
      throw err;
    }
    setRoleCreationError('');
    try {
      await refreshRoleCreationSessionDetail(sessionId, { skipRender: true });
    } catch (_) {
      applyRoleCreationDetailPayload(data, { skipRender: true });
    }
    renderRoleCreationWorkbench();
    return data;
  }

  async function startRoleCreationSelectedSession() {
    const sessionId = safe(state.tcRoleCreationSelectedSessionId).trim();
    if (!sessionId) {
      throw new Error('请先选择角色草稿');
    }
    const data = await postJSON(
      '/api/training/role-creation/sessions/' + encodeURIComponent(sessionId) + '/start',
      { operator: 'web-user' },
    );
    setRoleCreationError('');
    applyRoleCreationDetailPayload(data);
    refreshTrainingCenterAgents().catch(() => {});
    return data;
  }

  async function updateRoleCreationStage(stageKey) {
    const sessionId = safe(state.tcRoleCreationSelectedSessionId).trim();
    const key = safe(stageKey).trim();
    if (!sessionId || !key) return null;
    const data = await postJSON(
      '/api/training/role-creation/sessions/' + encodeURIComponent(sessionId) + '/stage',
      {
        stage_key: key,
        operator: 'web-user',
      },
    );
    setRoleCreationError('');
    applyRoleCreationDetailPayload(data);
    return data;
  }

  async function archiveRoleCreationTask(nodeId) {
    const sessionId = safe(state.tcRoleCreationSelectedSessionId).trim();
    const taskId = safe(nodeId).trim();
    if (!sessionId || !taskId) return null;
    const reason = window.prompt('请输入废案收口原因', '方向调整，暂不继续');
    if (reason === null) return null;
    if (!safe(reason).trim()) {
      throw new Error('废案收口原因不能为空');
    }
    const data = await postJSON(
      '/api/training/role-creation/sessions/' + encodeURIComponent(sessionId) + '/tasks/' + encodeURIComponent(taskId) + '/archive',
      {
        close_reason: safe(reason).trim(),
        operator: 'web-user',
      },
    );
    clearRoleCreationTaskPreview();
    setRoleCreationError('');
    applyRoleCreationDetailPayload(data);
    return data;
  }

  async function completeRoleCreationSelectedSession() {
    const sessionId = safe(state.tcRoleCreationSelectedSessionId).trim();
    if (!sessionId) {
      throw new Error('请先选择角色草稿');
    }
    const ok = window.confirm('确认当前后台任务已全部完成，并把该角色创建收口为已完成吗？');
    if (!ok) return null;
    const data = await postJSON(
      '/api/training/role-creation/sessions/' + encodeURIComponent(sessionId) + '/complete',
      {
        confirmed: true,
        operator: 'web-user',
      },
    );
    setRoleCreationError('');
    applyRoleCreationDetailPayload(data);
    refreshTrainingCenterAgents().catch(() => {});
    return data;
  }

  function roleCreationAttachmentThumbHtml(item, removable) {
    const attachment = item && typeof item === 'object' ? item : {};
    const attachmentId = safe(attachment.attachment_id).trim();
    const fileName = safe(attachment.file_name || 'image').trim();
    const dataUrl = safe(attachment.data_url).trim();
    return (
      "<div class='rc-draft-file'>" +
        "<img class='rc-draft-file-thumb' src='" + roleCreationEscapeHtml(dataUrl) + "' alt='" + roleCreationEscapeHtml(fileName) + "'/>" +
        "<div class='rc-draft-file-meta'>" +
          "<div class='rc-draft-file-name'>" + roleCreationEscapeHtml(fileName || '图片') + '</div>' +
          "<div class='rc-draft-file-sub'>" + roleCreationEscapeHtml(safe(attachment.content_type).trim() || 'image') + '</div>' +
        '</div>' +
        (
          removable
            ? "<button class='rc-draft-file-remove alt' type='button' data-attachment-id='" + roleCreationEscapeHtml(attachmentId) + "'>移除</button>"
            : ''
        ) +
      '</div>'
    );
  }

  function roleCreationMessageAttachmentsHtml(attachments) {
    const rows = Array.isArray(attachments) ? attachments : [];
    if (!rows.length) return '';
    return (
      "<div class='rc-message-assets'>" +
      rows.map((item) => (
        "<div class='rc-message-asset'>" +
          "<img src='" + roleCreationEscapeHtml(safe(item && item.data_url).trim()) + "' alt='" + roleCreationEscapeHtml(safe(item && item.file_name).trim() || '图片') + "'/>" +
        '</div>'
      )).join('') +
      '</div>'
    );
  }

  function roleCreationMessageRoleClass(message) {
    const item = message && typeof message === 'object' ? message : {};
    const messageType = safe(item.message_type).trim().toLowerCase();
    const role = safe(item.role).trim().toLowerCase();
    if (messageType !== 'chat' || role === 'system') return 'system';
    if (role === 'user') return 'user';
    return 'assistant';
  }

  function roleCreationMessageSenderText(message) {
    const role = safe(message && message.role).trim().toLowerCase();
    if (role === 'user') return '用户';
    if (role === 'system') return '系统';
    const dialogueAgent = roleCreationCurrentDialogueAgent();
    return safe(dialogueAgent.agent_name).trim() || '分析师';
  }

  function roleCreationMessageProcessingState(message) {
    const item = message && typeof message === 'object' ? message : {};
    return safe(item.processing_state || (item.meta && item.meta.processing_state)).trim().toLowerCase();
  }

  function roleCreationMessageProcessingText(message) {
    const stateKey = roleCreationMessageProcessingState(message);
    if (stateKey === 'processing') return '处理中';
    if (stateKey === 'processed') return '已处理';
    if (stateKey === 'failed') return '处理失败';
    if (stateKey === 'pending') return '待处理';
    return '';
  }

  function renderRoleCreationMessages() {
    const box = $('rcMessages');
    if (!box) return;
    const session = roleCreationCurrentSession();
    const sessionId = safe(session.session_id).trim();
    const rows = roleCreationDisplayMessages();
    const previousScrollTop = Number(box.scrollTop || 0);
    const previousScrollHeight = Number(box.scrollHeight || 0);
    const previousClientHeight = Number(box.clientHeight || 0);
    const wasNearBottom =
      previousScrollHeight <= previousClientHeight + 1 ||
      previousScrollHeight - (previousScrollTop + previousClientHeight) <= 24;
    const sessionChanged = sessionId !== safe(state.tcRoleCreationMessagesRenderedSessionId).trim();
    state.tcRoleCreationMessagesRenderedSessionId = sessionId;
    if (!sessionId) {
      box.innerHTML = "<div class='rc-empty'>还没有创建草稿。点击左侧“新建”后，直接用对话描述你要的角色即可。</div>";
      return;
    }
    if (!rows.length) {
      box.innerHTML = "<div class='rc-empty'>当前草稿还没有消息。</div>";
      return;
    }
    box.innerHTML = rows.map((message) => {
      const cls = roleCreationMessageRoleClass(message);
      const attachmentsHtml = roleCreationMessageAttachmentsHtml(message.attachments);
      const content = safe(message && message.content);
      const processingState = roleCreationMessageProcessingState(message);
      const processingText = roleCreationMessageProcessingText(message);
      const processingChip = cls === 'user' && processingText
        ? ("<span class='rc-message-processing " + roleCreationEscapeHtml(processingState || 'processed') + "'>" + roleCreationEscapeHtml(processingText) + '</span>')
        : '';
      const metaHtml = cls === 'system'
        ? ''
        : (
          "<div class='rc-message-meta'>" +
            "<span class='rc-message-sender'>" + roleCreationEscapeHtml(roleCreationMessageSenderText(message)) + '</span>' +
            processingChip +
            "<span>" + roleCreationEscapeHtml(formatDateTime(message.created_at)) + '</span>' +
          '</div>'
        );
      return (
        "<div class='message " + cls + (message && message.processing_placeholder ? ' pending' : '') + "'>" +
          (cls === 'system' ? '' : "<div class='message-role'>" + roleCreationEscapeHtml(roleCreationMessageSenderText(message).slice(0, 1)) + '</div>') +
          "<div class='message-body'>" +
            metaHtml +
            attachmentsHtml +
            (content ? "<div class='message-text'>" + roleCreationEscapeHtml(content) + '</div>' : '') +
          '</div>' +
        '</div>'
      );
    }).join('');
    if (sessionChanged || wasNearBottom) {
      box.scrollTop = box.scrollHeight;
      return;
    }
    const maxTop = Math.max(0, box.scrollHeight - box.clientHeight);
    box.scrollTop = Math.max(0, Math.min(maxTop, previousScrollTop));
  }

