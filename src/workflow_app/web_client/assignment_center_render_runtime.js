  function assignmentArtifactPreviewUrl(ticketId, nodeId, pathIndex) {
    const tid = safe(ticketId).trim();
    const nid = safe(nodeId).trim();
    const index = Math.max(0, Number(pathIndex || 0));
    return withTestDataQuery(
      '/api/assignments/' + encodeURIComponent(tid) +
      '/nodes/' + encodeURIComponent(nid) +
      '/artifact-preview?path_index=' + encodeURIComponent(String(index)),
    );
  }

  function renderAssignmentDetail() {
    const body = $('assignmentDetailBody');
    if (!body) return;
    captureAssignmentExecutionScrollState(body);
    const detail = assignmentDetailPayload();
    const selected = selectedAssignmentNode();
    const metaNode = $('assignmentDetailMeta');
    if (!safe(selected.node_id).trim()) {
      if (metaNode) metaNode.textContent = '请选择任务节点';
      body.innerHTML =
        "<div class='assignment-detail-card'>" +
        "<div class='assignment-empty-title'>暂无任务详情</div>" +
        "<div class='hint'>点击任务图中的节点后，在这里查看执行主体、执行链路、回执、产物与任务管理动作。</div>" +
        '</div>';
      syncAssignmentExecutionRealtime({});
      return;
    }
    if (metaNode) metaNode.textContent = '当前选中 ' + safe(selected.node_name || selected.node_id);
    const statusMeta = assignmentNodeStatusMeta(selected);
    const upstream = Array.isArray(selected.upstream_nodes) ? selected.upstream_nodes : [];
    const downstream = Array.isArray(selected.downstream_nodes) ? selected.downstream_nodes : [];
    const availableActions = Array.isArray(detail.available_actions)
      ? detail.available_actions.map((item) => safe(item).trim().toLowerCase())
      : [];
    const audits = Array.isArray(detail.audit_refs)
      ? detail.audit_refs.filter((item) => {
        const action = safe(item && item.action).trim().toLowerCase();
        return action === 'rerun' || action === 'override_status' || action === 'deliver_artifact';
      })
      : [];
    const blockings = Array.isArray(detail.blocking_reasons) ? detail.blocking_reasons : [];
    const artifactPaths = Array.isArray(selected.artifact_paths) ? selected.artifact_paths : [];
    const ticketId = selectedAssignmentTicketId();
    const codexFailure =
      detail && typeof detail === 'object' && detail.codex_failure
        ? detail.codex_failure
        : selected && typeof selected === 'object' && selected.codex_failure
          ? selected.codex_failure
          : detail && detail.execution_chain && detail.execution_chain.latest_run && typeof detail.execution_chain.latest_run === 'object'
            ? detail.execution_chain.latest_run.codex_failure
            : null;
    const rawStatus = safe(selected.status).trim().toLowerCase();
    let receiptActionHtml = '';
    let managementHtml = '';
    if (statusMeta.tone === 'running') {
      receiptActionHtml =
        "<div class='assignment-action-form'>" +
        "<textarea id='assignmentReceiptReason' rows='4' placeholder='请填写成功/失败理由（必填）'></textarea>" +
        "<input id='assignmentReceiptRef' type='text' placeholder='结果引用（选填，仅成功时使用）' />" +
        "<div class='assignment-action-row'>" +
        "<button id='assignmentMarkSuccessBtn' type='button'>标记成功</button>" +
        "<button id='assignmentMarkFailedBtn' class='bad' type='button'>标记失败</button>" +
        '</div></div>';
    }
    if (availableActions.includes('override-status')) {
      managementHtml =
        "<div class='assignment-action-form'>" +
        "<input id='assignmentOverrideReason' type='text' placeholder='人工修改执行状态时必须填写理由' />" +
        "<select id='assignmentOverrideStatus'>" +
        "<option value='ready'>改为待开始</option>" +
        "<option value='pending'>改为 pending</option>" +
        "<option value='blocked'>改为阻塞</option>" +
        "<option value='succeeded'>改为已完成</option>" +
        "<option value='failed'>保持失败</option>" +
        "</select>" +
        "<div class='assignment-action-row'>" +
        (availableActions.includes('rerun') ? "<button id='assignmentRerunBtn' class='alt' type='button'>重跑任务</button>" : '') +
        "<button id='assignmentOverrideBtn' type='button'>人工修改执行状态</button>" +
        (availableActions.includes('delete') ? "<button id='assignmentDeleteBtn' class='bad' type='button'>删除任务</button>" : '') +
        '</div></div>';
    } else if (rawStatus === 'running') {
      managementHtml =
        "<div class='assignment-action-form'>" +
        "<div class='hint'>运行中的任务不可删除，请先完成状态回写。</div>" +
        "<div class='assignment-action-row'>" +
        "<button id='assignmentDeleteBtn' class='bad' type='button' disabled>删除任务</button>" +
        '</div></div>';
    } else {
      managementHtml =
        "<div class='assignment-action-form'>" +
        "<div class='hint'>当前任务支持删除；若位于依赖链中间，系统会自动桥接其上下游。</div>" +
        "<div class='assignment-action-row'>" +
        (availableActions.includes('delete') ? "<button id='assignmentDeleteBtn' class='bad' type='button'>删除任务</button>" : '') +
        '</div></div>';
    }
    const artifactActionHtml =
      "<div class='assignment-action-form'>" +
      "<input id='assignmentArtifactLabelInput' type='text' placeholder='产物名称（选填，默认使用预期产物或任务名称）' />" +
      "<textarea id='assignmentArtifactNoteInput' rows='4' placeholder='交付说明（选填）'></textarea>" +
      "<div class='assignment-action-row'>" +
      "<button id='assignmentDeliverBtn' class='alt' type='button'>" +
      (safe(selected.artifact_delivery_status).trim().toLowerCase() === 'delivered' ? '重新交付产物' : '提交产物') +
      "</button>" +
      "<button id='assignmentViewArtifactBtn' type='button'" + (artifactPaths.length ? '>' : ' disabled>') + '查看产物</button>' +
      '</div></div>';
    const overviewMetaHtml =
      "<span class='assignment-chip " + statusMeta.tone + "'>" + escapeHtml(statusMeta.text) + '</span>' +
      assignmentSectionMetaTextHtml('优先级 ' + assignmentPriorityLabel(selected.priority));
    const overviewBody =
      "<div class='assignment-detail-grid'>" +
      assignmentStatHtml('执行 agent', escapeHtml(safe(selected.assigned_agent_name || selected.assigned_agent_id) || '-')) +
      assignmentStatHtml('任务 ID', escapeHtml(safe(selected.node_id) || '-')) +
      assignmentStatHtml('上游任务', assignmentNodeListHtml(upstream, '无上游任务')) +
      assignmentStatHtml('下游任务', assignmentNodeListHtml(downstream, '无下游任务')) +
      assignmentStatHtml('确认任务目标', escapeHtml(safe(selected.node_goal).trim() || '-')) +
      assignmentStatHtml('完成时间', escapeHtml(safe(selected.completed_at) ? assignmentFormatBeijingTime(selected.completed_at) : '-')) +
      '</div>';
    const receiptInfoBody =
      "<div class='assignment-detail-grid'>" +
      assignmentStatHtml('预期产物', escapeHtml(safe(selected.expected_artifact) || '-')) +
      assignmentStatHtml('结果引用', escapeHtml(safe(selected.result_ref) || '-')) +
      assignmentStatHtml('成功理由', escapeHtml(safe(selected.success_reason) || '-')) +
      assignmentStatHtml('失败原因', escapeHtml(safe(selected.failure_reason) || '-')) +
      '</div>';
    const artifactInfoBody =
      "<div class='assignment-detail-grid'>" +
      assignmentStatHtml(
        '产物状态',
        escapeHtml(safe(selected.artifact_delivery_status_text) || assignmentArtifactDeliveryStatusText(selected.artifact_delivery_status))
      ) +
      assignmentStatHtml(
        '交付方式',
        escapeHtml(safe(selected.delivery_mode_text) || assignmentDeliveryModeText(selected.delivery_mode))
      ) +
      assignmentStatHtml(
        '交付对象',
        escapeHtml(assignmentDeliveryTargetLabel(selected))
      ) +
      assignmentStatHtml(
        '最近交付时间',
        escapeHtml(safe(selected.artifact_delivered_at) ? assignmentFormatBeijingTime(selected.artifact_delivered_at) : '-')
      ) +
      '</div>' +
      "<div class='assignment-path-list'>" +
      (artifactPaths.length
        ? artifactPaths.map((item, index) =>
          "<div class='assignment-path-item'>" +
            "<div class='assignment-path-text'>" + escapeHtml(safe(item)) + '</div>' +
            "<a class='assignment-path-open' href='" +
              escapeHtml(assignmentArtifactPreviewUrl(ticketId, selected.node_id, index)) +
              "' target='_blank' rel='noopener'>打开</a>" +
          '</div>'
        ).join('')
        : "<div class='assignment-path-item'>尚未交付，路径将在提交产物后生成。</div>") +
      '</div>' +
      artifactActionHtml;
    body.innerHTML =
      assignmentDetailSectionHtml('任务概览', overviewBody, {
        open: true,
        state_key: 'overview',
        description: safe(selected.node_name || selected.node_id),
        meta_html: overviewMetaHtml,
      }) +
      assignmentExecutionChainHtml() +
      (codexFailureHasValue(codexFailure)
        ? assignmentDetailSectionHtml('执行失败治理', "<div id='assignmentCodexFailureHost'></div>", {
          open: true,
          state_key: 'codex-failure',
          meta_html: assignmentSectionMetaTextHtml('统一失败视图'),
        })
        : '') +
      assignmentDetailSectionHtml('回执信息', receiptInfoBody, {
        state_key: 'receipt-info',
        meta_html: assignmentSectionMetaTextHtml(safe(selected.result_ref).trim() ? '已附结果引用' : '暂无结果引用'),
      }) +
      assignmentDetailSectionHtml('产物', artifactInfoBody, {
        state_key: 'artifact',
        meta_html: assignmentSectionMetaTextHtml(
          safe(selected.artifact_delivery_status_text) || assignmentArtifactDeliveryStatusText(selected.artifact_delivery_status)
        ),
      }) +
      (blockings.length
        ? assignmentDetailSectionHtml(
          '阻塞来源',
          "<div class='assignment-audit-list'>" +
            blockings.map((item) => "<div class='assignment-audit-item'>" + escapeHtml(safe(item.node_name)) + ' · ' + escapeHtml(safe(item.status_text)) + '</div>').join('') +
            '</div>',
          {
            open: rawStatus === 'blocked',
            state_key: 'blockings',
            meta_html: assignmentSectionMetaTextHtml('共 ' + String(blockings.length) + ' 项'),
          }
        )
        : '') +
      (receiptActionHtml
        ? assignmentDetailSectionHtml('回执操作', receiptActionHtml, {
          open: true,
          state_key: 'receipt-action',
          meta_html: assignmentSectionMetaTextHtml('待人工回执'),
        })
        : '') +
      assignmentDetailSectionHtml('任务管理', managementHtml, {
        open: true,
        state_key: 'management',
        meta_html: assignmentSectionMetaTextHtml('可执行操作'),
      }) +
      (audits.length
        ? assignmentDetailSectionHtml(
          '人工处置留痕',
          "<div class='assignment-audit-list'>" +
            audits.map((item) => "<div class='assignment-audit-item'>" +
              escapeHtml(assignmentFormatBeijingTime(item.created_at)) + '\n' +
              escapeHtml(safe(item.action)) + ' · ' + escapeHtml(safe(item.reason || '-')) + '\n' +
              escapeHtml(safe(item.ref || '-')) +
              '</div>').join('') +
            '</div>',
          {
            state_key: 'audits',
            meta_html: assignmentSectionMetaTextHtml('共 ' + String(audits.length) + ' 条'),
          }
        )
        : '');
    const failureHost = $('assignmentCodexFailureHost');
    if (failureHost && codexFailureHasValue(codexFailure)) {
      renderCodexFailureCard(failureHost, codexFailure, {
        title: '节点执行失败',
        context: {
          ticketId: ticketId,
          nodeId: safe(selected.node_id).trim(),
        },
      });
    }
    bindAssignmentDetailToggleState(body);
    window.requestAnimationFrame(() => {
      restoreAssignmentExecutionScrollState(body);
    });
    syncAssignmentExecutionRealtime(detail);
  }

  function renderAssignmentAgentOptions() {
    const select = $('assignmentAgentSelect');
    const receiverSelect = $('assignmentDeliveryReceiverSelect');
    if (!select) return;
    const items = Array.isArray(state.tcAgents) ? state.tcAgents : [];
    const current = safe(state.assignmentCreateForm.assigned_agent_id).trim();
    const currentReceiver = safe(state.assignmentCreateForm.delivery_receiver_agent_id).trim();
    const currentExists = items.some((item) => safe(item && item.agent_id).trim() === current);
    const receiverExists = items.some((item) => safe(item && item.agent_id).trim() === currentReceiver);
    let html = '';
    if (!items.length) {
      html = "<option value=''>暂无可用角色</option>";
    } else {
      html = items
        .map((item) => {
          const agentId = safe(item && item.agent_id).trim();
          const agentName = safe(item && item.agent_name).trim();
          return "<option value='" + escapeHtml(agentId) + "'" +
            (agentId === current ? ' selected' : '') +
            '>' + escapeHtml(agentName || agentId) + '</option>';
        })
        .join('');
    }
    select.innerHTML = html;
    if (items.length && (!current || !currentExists)) {
      state.assignmentCreateForm.assigned_agent_id = safe(items[0].agent_id).trim();
      select.value = state.assignmentCreateForm.assigned_agent_id;
    } else if (!items.length) {
      state.assignmentCreateForm.assigned_agent_id = '';
    }
    if (receiverSelect) {
      receiverSelect.innerHTML = items.length
        ? ("<option value=''>请选择指定交付对象</option>" + items.map((item) => {
          const agentId = safe(item && item.agent_id).trim();
          const agentName = safe(item && item.agent_name).trim();
          return "<option value='" + escapeHtml(agentId) + "'" +
            (agentId === currentReceiver ? ' selected' : '') +
            '>' + escapeHtml(agentName || agentId) + '</option>';
        }).join(''))
        : "<option value=''>暂无可用角色</option>";
      if (currentReceiver && receiverExists) {
        receiverSelect.value = currentReceiver;
      } else {
        state.assignmentCreateForm.delivery_receiver_agent_id = '';
        receiverSelect.value = '';
      }
    }
  }

  function renderAssignmentUpstreamResults() {
    const resultNode = $('assignmentUpstreamResults');
    if (!resultNode) return;
    const catalog = assignmentNodeCatalog();
    const query = safe(state.assignmentCreateUpstreamSearch).trim().toLowerCase();
    const selectedIds = new Set(state.assignmentCreateSelectedUpstreamIds || []);
    const rows = catalog
      .filter((item) => !selectedIds.has(safe(item && item.node_id).trim()))
      .filter((item) => {
        if (!query) return true;
        const hay = (
          safe(item && item.node_name) + ' ' +
          safe(item && item.node_id)
        ).toLowerCase();
        return hay.includes(query);
      })
      .slice(0, 8);
    if (!rows.length) {
      resultNode.innerHTML = "<div class='hint'>暂无可添加的上游任务</div>";
      return;
    }
    resultNode.innerHTML = rows.map((item) => {
      const nodeId = safe(item && item.node_id).trim();
      const status = safe(item && item.status_text ? item.status_text : statusText(item && item.status)).trim() || '-';
      return (
        "<div class='assignment-search-item'>" +
        "<div>" +
        "<div class='assignment-search-item-title'>" + escapeHtml(safe(item && item.node_name)) + "</div>" +
        "<div class='assignment-search-item-meta'>" + escapeHtml(nodeId + ' · ' + status) + '</div>' +
        "</div>" +
        "<button class='alt' type='button' data-assignment-upstream-add='" + escapeHtml(nodeId) + "'>添加</button>" +
        '</div>'
      );
    }).join('');
  }

  function renderAssignmentSelectedUpstreams() {
    const node = $('assignmentSelectedUpstreams');
    if (!node) return;
    const catalog = assignmentNodeCatalog();
    const selectedIds = Array.isArray(state.assignmentCreateSelectedUpstreamIds)
      ? state.assignmentCreateSelectedUpstreamIds
      : [];
    if (!selectedIds.length) {
      node.innerHTML = "<div class='hint'>未选择上游任务</div>";
      return;
    }
    node.innerHTML = selectedIds.map((nodeId) => {
      const matched = catalog.find((item) => safe(item && item.node_id).trim() === safe(nodeId).trim()) || {};
      const label = safe(matched.node_name || nodeId).trim();
      return (
        "<span class='assignment-token'>" +
        "<span>" + escapeHtml(label) + '</span>' +
        "<button type='button' data-assignment-upstream-remove='" + escapeHtml(nodeId) + "'>×</button>" +
        '</span>'
      );
    }).join('');
  }

  function renderAssignmentPathPreview() {
    const pathPreview = $('assignmentPathPreview');
    const receiverField = $('assignmentDeliveryReceiverField');
    if (receiverField) {
      receiverField.style.display = safe(state.assignmentCreateForm.delivery_mode).trim().toLowerCase() === 'specified' ? 'flex' : 'none';
    }
    if (pathPreview) {
      pathPreview.innerHTML = assignmentCreatePreviewPaths().map((item) => escapeHtml(item)).join('<br/>');
    }
  }

  function renderAssignmentDrawer() {
    const mask = $('assignmentDrawerMask');
    if (mask) {
      mask.classList.toggle('hidden', !state.assignmentCreateOpen);
    }
    renderAssignmentAgentOptions();
    const nameInput = $('assignmentTaskNameInput');
    const goalInput = $('assignmentGoalInput');
    const artifactInput = $('assignmentArtifactInput');
    const agentSelect = $('assignmentAgentSelect');
    const prioritySelect = $('assignmentPrioritySelect');
    const deliveryModeSelect = $('assignmentDeliveryModeSelect');
    const receiverField = $('assignmentDeliveryReceiverField');
    const receiverSelect = $('assignmentDeliveryReceiverSelect');
    const searchInput = $('assignmentUpstreamSearch');
    if (nameInput) nameInput.value = safe(state.assignmentCreateForm.node_name);
    if (goalInput) goalInput.value = safe(state.assignmentCreateForm.node_goal);
    if (artifactInput) artifactInput.value = safe(state.assignmentCreateForm.expected_artifact);
    if (agentSelect) agentSelect.value = safe(state.assignmentCreateForm.assigned_agent_id);
    if (prioritySelect) prioritySelect.value = assignmentPriorityLabel(state.assignmentCreateForm.priority);
    if (deliveryModeSelect) deliveryModeSelect.value = safe(state.assignmentCreateForm.delivery_mode || 'none').trim() || 'none';
    if (receiverSelect) receiverSelect.value = safe(state.assignmentCreateForm.delivery_receiver_agent_id).trim();
    if (receiverField) {
      receiverField.style.display = safe(state.assignmentCreateForm.delivery_mode).trim().toLowerCase() === 'specified' ? 'flex' : 'none';
    }
    renderAssignmentPathPreview();
    if (searchInput) searchInput.value = safe(state.assignmentCreateUpstreamSearch);
    renderAssignmentUpstreamResults();
    renderAssignmentSelectedUpstreams();
    setAssignmentDrawerError(state.assignmentDrawerError || '');
  }

  function renderAssignmentCenter() {
    renderAssignmentWorkboard();
    renderAssignmentGraphSelector();
    renderAssignmentScheduler();
    renderAssignmentGraph();
    renderAssignmentDetail();
    renderAssignmentDrawer();
    renderGlobalRuntimeMetricLine();
    syncAssignmentPrimaryViewUi();
    setAssignmentError(state.assignmentError || '');
    setAssignmentDetailError(state.assignmentDetailError || '');
  }

  async function ensureAssignmentAgentPool(forceRefresh) {
    const force = !!forceRefresh;
    if (!force && Array.isArray(state.tcAgents) && state.tcAgents.length) {
      renderAssignmentAgentOptions();
      return state.tcAgents;
    }
    const data = await getJSON(withTestDataQuery('/api/training/agents'));
    state.tcAgents = Array.isArray(data.items) ? data.items : [];
    state.tcStats = data.stats && typeof data.stats === 'object' ? data.stats : state.tcStats;
    if (typeof syncTrainingCenterPlanAgentOptions === 'function') {
      syncTrainingCenterPlanAgentOptions();
    }
    renderAssignmentAgentOptions();
    return state.tcAgents;
  }

  const ASSIGNMENT_UI_SOURCE_WORKFLOW = 'workflow-ui';
  const ASSIGNMENT_UI_GLOBAL_GRAPH_REQUEST_ID = 'workflow-ui-global-graph-v1';
  const ASSIGNMENT_UI_GLOBAL_GRAPH_NAME = '任务中心全局主图';

  function isAssignmentUiGlobalGraph(item) {
    const row = item && typeof item === 'object' ? item : {};
    return !row.is_test_data &&
      safe(row.source_workflow).trim() === ASSIGNMENT_UI_SOURCE_WORKFLOW &&
      safe(row.external_request_id).trim() === ASSIGNMENT_UI_GLOBAL_GRAPH_REQUEST_ID;
  }

  function globalAssignmentGraph() {
    const items = Array.isArray(state.assignmentGraphs) ? state.assignmentGraphs : [];
    return items.find((item) => isAssignmentUiGlobalGraph(item)) || null;
  }

  function globalAssignmentTicketId() {
    const row = globalAssignmentGraph();
    return safe(row && row.ticket_id).trim();
  }

  function fallbackWorkflowUiGraph() {
    const items = Array.isArray(state.assignmentGraphs) ? state.assignmentGraphs : [];
    return items.find((item) => !item.is_test_data && safe(item && item.source_workflow).trim() === ASSIGNMENT_UI_SOURCE_WORKFLOW) || null;
  }

  function preferredAssignmentTicketId() {
    const row = globalAssignmentGraph() || fallbackWorkflowUiGraph();
    return safe(row && row.ticket_id).trim();
  }

  function assignmentDefaultCreatePayload() {
    return {
      graph_name: ASSIGNMENT_UI_GLOBAL_GRAPH_NAME,
      source_workflow: ASSIGNMENT_UI_SOURCE_WORKFLOW,
      summary: '任务中心手动创建（全局主图）',
      review_mode: 'none',
      external_request_id: ASSIGNMENT_UI_GLOBAL_GRAPH_REQUEST_ID,
    };
  }

  async function ensureAssignmentGraphExists() {
    if (!Array.isArray(state.assignmentGraphs) || !state.assignmentGraphs.length) {
      await refreshAssignmentGraphs({ preserveSelection: true });
    }
    const preferredTicketId = preferredAssignmentTicketId();
    if (preferredTicketId) {
      state.assignmentSelectedTicketId = preferredTicketId;
      return preferredTicketId;
    }
    const existing = selectedAssignmentTicketId();
    if (existing) return existing;
    const created = await postJSON('/api/assignments', assignmentDefaultCreatePayload());
    state.assignmentSelectedTicketId = safe(created.ticket_id).trim();
    state.assignmentActiveLoaded = 0;
    state.assignmentHistoryLoaded = 0;
    await refreshAssignmentGraphs({ preserveSelection: true });
    return selectedAssignmentTicketId();
  }

  async function ensureAssignmentPrototypeTestData() {
    return postJSON('/api/assignments/test-data/bootstrap', {
      operator: 'web-user',
    });
  }

  function assignmentGraphUrl(ticketId) {
    return withTestDataQuery('/api/assignments/' + encodeURIComponent(ticketId) +
      '/graph?active_loaded=' + encodeURIComponent(String(Number(state.assignmentActiveLoaded || 0))) +
      '&active_batch_size=' + encodeURIComponent(String(ASSIGNMENT_ACTIVE_BATCH)) +
      '&history_loaded=' + encodeURIComponent(String(Number(state.assignmentHistoryLoaded || 0))) +
      '&history_batch_size=' + encodeURIComponent(String(ASSIGNMENT_HISTORY_BATCH)));
  }

  function assignmentGraphsUrl() {
    // Task center now binds to the canonical global graph only.
    return withTestDataQuery(
      '/api/assignments?limit=1' +
      '&source_workflow=' + encodeURIComponent(ASSIGNMENT_UI_SOURCE_WORKFLOW) +
      '&external_request_id=' + encodeURIComponent(ASSIGNMENT_UI_GLOBAL_GRAPH_REQUEST_ID),
    );
  }

  function assignmentWorkboardDurationText(seconds) {
    const totalSeconds = Math.max(0, Number(seconds || 0));
    if (!Number.isFinite(totalSeconds) || totalSeconds <= 0) return '0s';
    if (typeof formatElapsedMs === 'function') {
      return formatElapsedMs(totalSeconds * 1000);
    }
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const secs = Math.floor(totalSeconds % 60);
    if (hours > 0) return String(hours) + 'h ' + String(minutes) + 'm';
    if (minutes > 0) return String(minutes) + 'm ' + String(secs) + 's';
    return String(secs) + 's';
  }

  function assignmentWorkboardGoalTone(status, progressPct) {
    const key = safe(status).trim().toLowerCase();
    if (key === 'running') {
      return Number(progressPct || 0) >= 100 ? 'done' : 'running';
    }
    if (key === 'stopped') return 'fail';
    return 'future';
  }

  function assignmentWorkboardGoalSnapshot() {
    const metrics = state.dashboardMetrics && typeof state.dashboardMetrics === 'object'
      ? state.dashboardMetrics
      : {};
    const goalHours = Math.max(1, Number(metrics.prod_runtime_goal_hours || 24));
    const status = safe(metrics.prod_runtime_status).trim().toLowerCase() || 'unknown';
    const startedAt = safe(metrics.prod_runtime_started_at).trim();
    const uptimeSeconds = Math.max(0, Number(metrics.prod_runtime_uptime_seconds || 0));
    const progressPct = Math.max(0, Math.min(100, Number(metrics.prod_runtime_goal_progress_pct || 0)));
    let title = '24h 目标待观察';
    let detail = '当前未拿到连续运行状态';
    if (status === 'running') {
      title = progressPct >= 100 ? '24h 连续运行已达成' : '24h 连续运行进行中';
      detail = '连续运行 ' + assignmentWorkboardDurationText(uptimeSeconds) + ' / ' + String(goalHours) + 'h';
      if (startedAt) {
        detail += ' · 启动于 ' + (typeof assignmentFormatBeijingTime === 'function' ? assignmentFormatBeijingTime(startedAt) : startedAt);
      }
    } else if (status === 'stopped') {
      title = '24h 连续运行已中断';
      detail = startedAt
        ? '最近一次启动于 ' + (typeof assignmentFormatBeijingTime === 'function' ? assignmentFormatBeijingTime(startedAt) : startedAt)
        : 'prod 当前未运行';
    }
    return {
      goalHours: goalHours,
      status: status,
      startedAt: startedAt,
      uptimeSeconds: uptimeSeconds,
      progressPct: progressPct,
      title: title,
      detail: detail,
      tone: assignmentWorkboardGoalTone(status, progressPct),
    };
  }

  function assignmentWorkboardRefreshIso(refreshAtMs, fallbackIso) {
    const localMs = Math.max(0, Number(refreshAtMs || 0));
    if (localMs > 0) {
      try {
        return new Date(localMs).toISOString();
      } catch (_) {
        // fall through to server timestamp
      }
    }
    return safe(fallbackIso).trim();
  }

  function assignmentWorkboardFreshnessSnapshot() {
    const localRefreshAtMs = Math.max(
      0,
      Number(state.assignmentGraphLastRefreshAtMs || 0),
      Number(state.dashboardLastRefreshAtMs || 0),
    );
    const serverFetchedAt = safe(state.dashboardLastFetchedAt).trim();
    const refreshIso = assignmentWorkboardRefreshIso(localRefreshAtMs, serverFetchedAt);
    const refreshMs = localRefreshAtMs > 0
      ? localRefreshAtMs
      : (refreshIso ? new Date(refreshIso).getTime() : NaN);
    const ageMs = Number.isFinite(refreshMs) && refreshMs > 0
      ? Math.max(0, Date.now() - refreshMs)
      : NaN;
    let tone = 'muted';
    let label = '刷新时间待确认';
    if (Number.isFinite(ageMs)) {
      if (ageMs <= 15000) {
        tone = 'success';
        label = '数据新鲜';
      } else if (ageMs <= 60000) {
        tone = 'muted';
        label = '数据稍旧';
      } else {
        tone = 'blocked';
        label = '数据已过期';
      }
    }
    const sourceLabel = Number(state.assignmentGraphLastRefreshAtMs || 0) >= Number(state.dashboardLastRefreshAtMs || 0)
      ? '任务图'
      : 'dashboard';
    let detail = '最近一次任务中心刷新时间还未建立。';
    if (refreshIso) {
      detail = '最近刷新 ' + assignmentFormatBeijingTime(refreshIso);
      if (Number.isFinite(ageMs)) {
        detail += ' · ' + formatElapsedMs(ageMs) + ' 前';
      }
      detail += ' · 来源 ' + sourceLabel;
    }
    return {
      tone: tone,
      label: label,
      detail: detail,
      ageMs: ageMs,
      refreshIso: refreshIso,
    };
  }

  function assignmentWorkboardConnectionSnapshot() {
    const mode = assignmentExecutionMode();
    const refreshModeText = assignmentExecutionRefreshModeText(mode);
    const pollIntervalMs = Math.max(
      250,
      Number(state.assignmentExecutionPollIntervalMs || assignmentExecutionSettingsPayload().poll_interval_ms || 450),
    );
    const streamConnected = !!state.assignmentExecutionEventSource && !!state.assignmentExecutionEventSourceConnected;
    if (streamConnected) {
      return {
        tone: 'running',
        label: '实时流已连接',
        detail: refreshModeText + ' 正在推送节点变化；若断线会回退到 ' + String(pollIntervalMs) + 'ms 兜底刷新。',
      };
    }
    if (safe(mode).trim().toLowerCase() === 'event_stream') {
      return {
        tone: 'blocked',
        label: '已回退短轮询',
        detail: '实时流当前未连通，任务中心暂用 ' + String(pollIntervalMs) + 'ms 轮询保活。',
      };
    }
    return {
      tone: 'muted',
      label: refreshModeText + ' 模式',
      detail: '当前没有事件流连接，任务中心按 ' + String(pollIntervalMs) + 'ms 轮询刷新。',
    };
  }

  function assignmentWorkboardGuidanceSnapshot(currentMainline, nextMainline, patrolNode, schedulePreview, workflowGroup) {
    const handoffNote = safe(workflowGroup && workflowGroup.workflowMainlineHandoffNote).trim();
    const currentStatus = safe(currentMainline && currentMainline.status).trim().toLowerCase();
    const patrolStatus = safe(patrolNode && patrolNode.status).trim().toLowerCase();
    const futureCount = (Array.isArray(schedulePreview) ? schedulePreview : []).filter((item) => {
      const nextTrigger = safe(item && (item.next_trigger_at || item.next_trigger_text)).trim();
      return !!nextTrigger && nextTrigger !== '停用中';
    }).length;
    if (currentMainline && currentStatus === 'running') {
      return {
        tone: 'running',
        label: nextMainline ? '继续等待当前主线' : '继续观察当前主线',
        detail: nextMainline
          ? '当前真正会消耗 token 的主线还在执行，下一棒已经排队，先不要抢着介入。'
          : '当前真正会消耗 token 的主线还在执行，优先等待收尾和下一次接棒。',
      };
    }
    if (nextMainline && patrolNode && patrolStatus === 'running') {
      return {
        tone: 'blocked',
        label: '保底巡检正在占槽',
        detail: handoffNote || '保底巡检仍在运行，真正的 [持续迭代] workflow 还在等待接棒。',
      };
    }
    if (nextMainline) {
      return {
        tone: 'muted',
        label: '等待运行槽释放',
        detail: handoffNote || '当前没有 running 主线，但下一棒已经 ready，先观察占槽任务是否正常收尾。',
      };
    }
    if (futureCount > 0) {
      return {
        tone: 'muted',
        label: '等待下一次定时触发',
        detail: '当前图内没有 ready 接棒，但至少还有 ' + String(futureCount) + ' 条 future 入口，不必急着人工补链。',
      };
    }
    return {
      tone: 'fail',
      label: '需要人工介入',
      detail: '当前同时缺少 running 主线、ready 接棒和 future 入口，需立即补链或重派发。',
    };
  }

  function assignmentWorkboardStatusCardHtml(title, value, detail, tone) {
    return (
      "<section class='assignment-workboard-status-card " + escapeHtml(safe(tone).trim() || 'muted') + "'>" +
      "<div class='assignment-workboard-status-k'>" + escapeHtml(title) + '</div>' +
      "<div class='assignment-workboard-status-v'>" + escapeHtml(value) + '</div>' +
      "<div class='assignment-workboard-status-note'>" + escapeHtml(detail) + '</div>' +
      '</section>'
    );
  }

  function assignmentIsWorkflowMainline(item) {
    const row = item && typeof item === 'object' ? item : {};
    if (row.is_workflow_mainline) return true;
    const agentId = safe(row.assigned_agent_id || row.agent_id).trim().toLowerCase();
    const expectedArtifact = safe(row.expected_artifact).trim().toLowerCase();
    const nodeName = safe(row.node_name).trim();
    return agentId === 'workflow' && (
      expectedArtifact === 'continuous-improvement-report.md' ||
      nodeName.indexOf('[持续迭代] workflow') === 0
    );
  }

  function assignmentIsWorkflowPatrol(item) {
    const row = item && typeof item === 'object' ? item : {};
    if (row.is_workflow_patrol) return true;
    const agentId = safe(row.assigned_agent_id || row.agent_id).trim().toLowerCase();
    const expectedArtifact = safe(row.expected_artifact).trim().toLowerCase();
    const nodeName = safe(row.node_name).trim();
    return agentId === 'workflow' && (
      expectedArtifact === 'workflow-pm-wake-summary' ||
      nodeName.indexOf('pm持续唤醒 - workflow 主线巡检') === 0
    );
  }

  function assignmentAnnotateWorkboardGroup(group) {
    const current = group && typeof group === 'object' ? group : {};
    const running = Array.isArray(current.running) ? current.running : [];
    const queued = Array.isArray(current.queued) ? current.queued : [];
    const runningMainline = running.find((item) => assignmentIsWorkflowMainline(item));
    const queuedMainline = queued.find((item) => assignmentIsWorkflowMainline(item));
    const patrolRunning = running.find((item) => assignmentIsWorkflowPatrol(item));
    current.workflowMainlineHandoffPending = !!queuedMainline && !runningMainline;
    current.workflowMainlineHandoffNote = current.workflowMainlineHandoffPending
      ? (patrolRunning
        ? '保底巡检仍在运行，真正的 [持续迭代] workflow 还在待执行。'
        : '真正的 [持续迭代] workflow 还在待执行。')
      : '';
    return current;
  }

  function assignmentWorkboardGroups() {
    const graphData = state.assignmentGraphData && typeof state.assignmentGraphData === 'object'
      ? state.assignmentGraphData
      : {};
    const rows = Array.isArray(graphData.nodes) ? graphData.nodes : [];
    if (!rows.length) {
      const metrics = state.dashboardMetrics && typeof state.dashboardMetrics === 'object'
        ? state.dashboardMetrics
        : {};
      const grouped = Array.isArray(metrics.assignment_workboard_agents)
        ? metrics.assignment_workboard_agents
        : [];
      return grouped.map((item) => assignmentAnnotateWorkboardGroup({
        key: safe(item && item.agent_id).trim() || safe(item && item.agent_name).trim(),
        agentId: safe(item && item.agent_id).trim(),
        agentName: safe(item && item.agent_name).trim() || safe(item && item.agent_id).trim() || '未指派',
        running: Array.isArray(item && item.running) ? item.running : [],
        queued: Array.isArray(item && item.queued) ? item.queued : [],
        failed: Array.isArray(item && item.failed) ? item.failed : [],
        blocked: Array.isArray(item && item.blocked) ? item.blocked : [],
        workflowMainlineHandoffPending: !!(item && item.workflow_mainline_handoff_pending),
        workflowMainlineHandoffNote: safe(item && item.workflow_mainline_handoff_note).trim(),
      }));
    }
    const map = new Map();
    rows.forEach((item) => {
      const row = item && typeof item === 'object' ? item : {};
      const status = safe(row.status).trim().toLowerCase();
      if (!['running', 'ready', 'pending', 'failed', 'blocked'].includes(status)) return;
      const agentId = safe(row.assigned_agent_id).trim();
      const agentName = safe(row.assigned_agent_name).trim() || agentId || '未指派';
      const key = agentId || agentName;
      if (!map.has(key)) {
        map.set(key, {
          key: key,
          agentId: agentId,
          agentName: agentName,
          running: [],
          queued: [],
          failed: [],
          blocked: [],
        });
      }
      const bucket = map.get(key);
      if (status === 'running') {
        bucket.running.push(row);
      } else if (status === 'failed') {
        bucket.failed.push(row);
      } else if (status === 'blocked') {
        bucket.blocked.push(row);
      } else {
        bucket.queued.push(row);
      }
    });
    return Array.from(map.values()).map((item) => assignmentAnnotateWorkboardGroup(item)).sort((left, right) => {
      const leftScore = left.running.length * 100 + left.queued.length * 10 + left.failed.length;
      const rightScore = right.running.length * 100 + right.queued.length * 10 + right.failed.length;
      if (leftScore !== rightScore) return rightScore - leftScore;
      return safe(left.agentName).localeCompare(safe(right.agentName), 'zh-CN');
    });
  }

  function assignmentWorkboardTaskButtons(items, toneClass) {
    const rows = Array.isArray(items) ? items.slice(0, 4) : [];
    if (!rows.length) {
      return "<div class='hint'>暂无</div>";
    }
    return rows.map((item) => {
      const nodeId = safe(item && item.node_id).trim();
      const nodeName = safe(item && (item.node_name || item.node_id)).trim() || '-';
      const priorityLabel = safe(item && (item.priority_label || item.priority)).trim() || '-';
      return (
        "<button class='alt running-task-item' type='button' data-assignment-workboard-node='" + escapeHtml(nodeId) + "'>" +
        "<div class='title'>" + escapeHtml(nodeName) + '</div>' +
        "<div class='sub'>" + escapeHtml(priorityLabel + ' · ' + toneClass) + '</div>' +
        '</button>'
      );
    }).join('');
  }

  function assignmentWorkboardNodeMetaText(item, fallbackStatus) {
    const row = item && typeof item === 'object' ? item : {};
    const parts = [];
    const priorityLabel = safe(row.priority_label || row.priority).trim();
    const statusText = safe(row.status_text).trim() || safe(fallbackStatus).trim();
    const agentName = safe(row.assigned_agent_name || row.agent_id).trim();
    if (priorityLabel) parts.push(priorityLabel);
    if (statusText) parts.push(statusText);
    if (agentName && !assignmentIsWorkflowMainline(row) && !assignmentIsWorkflowPatrol(row)) {
      parts.push(agentName);
    }
    return parts.join(' · ') || '-';
  }

  function assignmentWorkboardNodeTimingText(item) {
    const row = item && typeof item === 'object' ? item : {};
    const updatedAt = safe(row.updated_at).trim();
    const plannedTriggerAt = safe(row.planned_trigger_at).trim();
    if (updatedAt) {
      let detail = '最近更新 ' + assignmentFormatBeijingTime(updatedAt);
      const updatedMs = new Date(updatedAt).getTime();
      if (Number.isFinite(updatedMs) && updatedMs > 0) {
        detail += ' · ' + formatElapsedMs(Math.max(0, Date.now() - updatedMs)) + ' 前';
      }
      return detail;
    }
    if (plannedTriggerAt) {
      return '计划时间 ' + assignmentFormatBeijingTime(plannedTriggerAt);
    }
    return '';
  }

  function assignmentWorkboardNodeStageSnapshot(item) {
    const row = item && typeof item === 'object' ? item : {};
    const label = safe(row.latest_run_stage_label).trim();
    const detail = safe(row.latest_run_stage_detail).trim();
    const stageAt = safe(row.latest_run_stage_at || row.latest_run_event_at).trim();
    if (!label && !detail) return null;
    let timeText = '';
    if (stageAt) {
      timeText = '阶段时间 ' + assignmentFormatBeijingTime(stageAt);
      const stageMs = new Date(stageAt).getTime();
      if (Number.isFinite(stageMs) && stageMs > 0) {
        timeText += ' · ' + formatElapsedMs(Math.max(0, Date.now() - stageMs)) + ' 前';
      }
    }
    return {
      label: label || '当前阶段',
      detail: detail || '阶段摘要已建立，等待下一条进度更新。',
      timeText: timeText,
    };
  }

  function assignmentWorkboardFocusStageHtml(item) {
    const stage = assignmentWorkboardNodeStageSnapshot(item);
    if (!stage) return '';
    return (
      "<div class='assignment-workboard-focus-stage'>" +
      "<div class='assignment-workboard-focus-stage-label'>" + escapeHtml(stage.label) + '</div>' +
      "<div class='assignment-workboard-focus-stage-detail'>" + escapeHtml(stage.detail) + '</div>' +
      (stage.timeText
        ? "<div class='assignment-workboard-focus-stage-time'>" + escapeHtml(stage.timeText) + '</div>'
        : '') +
      '</div>'
    );
  }

  function assignmentWorkboardFocusCardHtml(item, options) {
    const row = item && typeof item === 'object' ? item : {};
    const opts = options && typeof options === 'object' ? options : {};
    const nodeId = safe(row.node_id).trim();
    const tone = safe(opts.tone).trim() || assignmentStatusTone(row.status) || 'future';
    const title = safe(row.node_name || row.node_id).trim() || safe(opts.emptyTitle).trim() || '暂无节点';
    const metaText = assignmentWorkboardNodeMetaText(row, opts.fallbackStatus);
    const timingText = assignmentWorkboardNodeTimingText(row);
    const noteText = safe(opts.note).trim() || safe(opts.emptyNote).trim();
    const innerHtml =
      "<div class='assignment-workboard-focus-eyebrow'>" + escapeHtml(safe(opts.eyebrow).trim() || '任务') + '</div>' +
      "<div class='assignment-workboard-focus-title'>" + escapeHtml(title) + '</div>' +
      "<div class='assignment-workboard-focus-meta'>" + escapeHtml(metaText) + '</div>' +
      (timingText ? "<div class='assignment-workboard-focus-time'>" + escapeHtml(timingText) + '</div>' : '') +
      assignmentWorkboardFocusStageHtml(row) +
      (noteText ? "<div class='assignment-workboard-focus-note'>" + escapeHtml(noteText) + '</div>' : '');
    if (!nodeId) {
      return "<div class='assignment-workboard-focus-card " + escapeHtml(tone) + " is-empty'>" + innerHtml + '</div>';
    }
    return (
      "<button class='assignment-workboard-focus-card " + escapeHtml(tone) + "' type='button' data-assignment-workboard-node='" +
      escapeHtml(nodeId) +
      "'>" +
      innerHtml +
      '</button>'
    );
  }

  function assignmentWorkboardGroupCardHtml(group) {
    const item = group && typeof group === 'object' ? group : {};
    const tone = item.running.length ? 'running' : (item.failed.length ? 'fail' : 'future');
    return (
      "<section class='assignment-workboard-group-card'>" +
      "<div class='assignment-workboard-group-head'>" +
      "<div>" +
      "<div class='assignment-workboard-group-title'>" + escapeHtml(safe(item.agentName).trim() || '未指派') + '</div>' +
      "<div class='assignment-workboard-group-meta'>" +
      escapeHtml('运行中 ' + item.running.length + ' · 待执行 ' + item.queued.length + ' · 失败 ' + item.failed.length) +
      '</div>' +
      '</div>' +
      "<span class='assignment-chip " + escapeHtml(tone) + "'>" + escapeHtml(tone === 'running' ? '活跃' : (tone === 'fail' ? '需处理' : '排队中')) + '</span>' +
      '</div>' +
      (safe(item.workflowMainlineHandoffNote).trim()
        ? "<div class='assignment-workboard-inline-note warn'>" + escapeHtml(item.workflowMainlineHandoffNote) + '</div>'
        : '') +
      (item.running.length
        ? "<div class='assignment-workboard-list-title'>正在执行</div><div class='running-task-list'>" + assignmentWorkboardTaskButtons(item.running, '运行中') + '</div>'
        : '') +
      (item.queued.length
        ? "<div class='assignment-workboard-list-title'>待执行</div><div class='running-task-list'>" + assignmentWorkboardTaskButtons(item.queued, '待执行') + '</div>'
        : '') +
      (item.failed.length
        ? "<div class='assignment-workboard-list-title'>失败池</div><div class='running-task-list'>" + assignmentWorkboardTaskButtons(item.failed, '失败') + '</div>'
        : '') +
      (item.blocked.length
        ? "<div class='assignment-workboard-inline-note'>阻塞 " + escapeHtml(String(item.blocked.length)) + ' 项</div>'
        : '') +
      '</section>'
    );
  }

  function assignmentWorkboardScheduleCardHtml(item) {
    const row = item && typeof item === 'object' ? item : {};
    const scheduleName = safe(row.schedule_name || row.schedule_id).trim() || '-';
    const statusText = safe(row.last_result_status_text || row.last_result_status).trim() || 'pending';
    const nextTrigger = safe(row.next_trigger_text || row.next_trigger_at).trim() || '-';
    const lastSummary = safe(row.last_result_summary).trim();
    return (
      "<div class='assignment-workboard-schedule-card'>" +
      "<div class='row between'>" +
      "<strong>" + escapeHtml(scheduleName) + "</strong>" +
      "<span class='assignment-chip muted'>" + escapeHtml(statusText) + '</span>' +
      '</div>' +
      "<div class='assignment-workboard-schedule-meta'>下次触发 · " + escapeHtml(nextTrigger) + '</div>' +
      (lastSummary
        ? "<div class='assignment-workboard-schedule-meta'>最近结果 · " + escapeHtml(lastSummary) + '</div>'
        : '') +
      '</div>'
    );
  }

  function renderAssignmentWorkboard() {
    const host = $('assignmentWorkboard');
    if (!host) return;
    const metrics = state.dashboardMetrics && typeof state.dashboardMetrics === 'object'
      ? state.dashboardMetrics
      : {};
    const goal = assignmentWorkboardGoalSnapshot();
    const groups = assignmentWorkboardGroups();
    const runningCount = groups.reduce((sum, item) => sum + item.running.length, 0);
    const queuedCount = groups.reduce((sum, item) => sum + item.queued.length, 0);
    const failedCount = groups.reduce((sum, item) => sum + item.failed.length, 0);
    const activeAgents = groups.filter((item) => item.running.length > 0 || item.queued.length > 0).length;
    const workflowGroup = groups.find((item) => safe(item.agentId || item.agentName).trim().toLowerCase() === 'workflow') || null;
    const currentMainline = workflowGroup
      ? (workflowGroup.running.find((item) => assignmentIsWorkflowMainline(item)) || workflowGroup.running[0] || null)
      : null;
    const nextMainline = workflowGroup
      ? (workflowGroup.queued.find((item) => assignmentIsWorkflowMainline(item)) || workflowGroup.queued[0] || null)
      : null;
    const patrolNode = workflowGroup
      ? (
        workflowGroup.running.find((item) => assignmentIsWorkflowPatrol(item)) ||
        workflowGroup.queued.find((item) => assignmentIsWorkflowPatrol(item)) ||
        null
      )
      : null;
    const helperGroups = groups.filter((item) => safe(item.agentId || item.agentName).trim().toLowerCase() !== 'workflow');
    const failurePool = groups
      .flatMap((item) => Array.isArray(item.failed) ? item.failed : [])
      .slice(0, 4);
    const schedulePreview = Array.isArray(metrics.schedule_workboard_preview) ? metrics.schedule_workboard_preview.slice(0, 4) : [];
    const freshness = assignmentWorkboardFreshnessSnapshot();
    const connection = assignmentWorkboardConnectionSnapshot();
    const headerHtml =
      "<div class='assignment-panel-head'>" +
      "<div><div class='card-title'>任务看板</div><div class='hint'>默认先看 workflow 主线、接棒和失败池，不必先钻进长图。</div></div>" +
      "<div class='assignment-head-actions'>" +
      "<span class='assignment-chip " + escapeHtml(goal.tone) + "'>" + escapeHtml(goal.title) + "</span>" +
      "<span class='assignment-chip muted'>" + escapeHtml(goal.detail) + "</span>" +
      '</div>' +
      '</div>';
    const summaryHtml =
      "<div class='assignment-workboard-body'>" +
      "<div class='assignment-workboard-summary-grid'>" +
      assignmentStatHtml('活跃小伙伴', escapeHtml(String(activeAgents))) +
      assignmentStatHtml('运行中任务', escapeHtml(String(runningCount))) +
      assignmentStatHtml('待执行任务', escapeHtml(String(queuedCount))) +
      assignmentStatHtml('失败任务', escapeHtml(String(failedCount))) +
      '</div>';
    if (!groups.length) {
      host.innerHTML = headerHtml + summaryHtml + "<div class='assignment-workboard-inline-note'>主图当前没有可展示的运行中或待执行任务。</div></div>";
      return;
    }
    const handoffNote = safe(workflowGroup && workflowGroup.workflowMainlineHandoffNote).trim();
    const focusHtml =
      "<section class='assignment-workboard-section'>" +
      "<div class='assignment-workboard-section-head'>" +
      "<div>" +
      "<div class='assignment-workboard-section-title'>主线焦点</div>" +
      "<div class='assignment-workboard-section-meta'>把当前主线、下一棒和保底巡检固定在同一屏里观察。</div>" +
      '</div>' +
      "<span class='assignment-chip muted'>workflow 主线</span>" +
      '</div>' +
      "<div class='assignment-workboard-focus-grid'>" +
      assignmentWorkboardFocusCardHtml(currentMainline, {
        eyebrow: '当前主线',
        fallbackStatus: currentMainline ? '运行中' : '待接棒',
        tone: currentMainline ? assignmentStatusTone(currentMainline.status) : 'future',
        emptyTitle: '当前没有 running 主线',
        note: currentMainline
          ? '当前真正会消耗 token 的连续迭代节点。'
          : '当前没有 running 主线，优先看右侧接棒和保底是否仍在。',
      }) +
      assignmentWorkboardFocusCardHtml(nextMainline, {
        eyebrow: '下一棒',
        fallbackStatus: nextMainline ? '待执行' : '未排队',
        tone: nextMainline ? assignmentStatusTone(nextMainline.status) : 'future',
        emptyTitle: '当前没有 ready 接棒',
        note: nextMainline
          ? (handoffNote || '下一棒已进图，等待 running 槽释放。')
          : '当前没有 ready 接棒节点，需结合右侧定时任务判断是否还保有 future 出口。',
      }) +
      assignmentWorkboardFocusCardHtml(patrolNode, {
        eyebrow: '保底巡检',
        fallbackStatus: patrolNode ? '保底入口' : '未命中',
        tone: patrolNode ? assignmentStatusTone(patrolNode.status) : 'future',
        emptyTitle: '当前图内没有保底巡检节点',
        note: patrolNode
          ? '保底巡检仍在图里，主线异常时会优先检查接力是否断链。'
          : '当前图里没有保底巡检节点，请同时看右侧 schedule 是否仍保留 future 入口。',
      }) +
      '</div>' +
      (handoffNote
        ? "<div class='assignment-workboard-inline-note warn'>" + escapeHtml(handoffNote) + '</div>'
        : '') +
      '</section>';
    const guidance = assignmentWorkboardGuidanceSnapshot(
      currentMainline,
      nextMainline,
      patrolNode,
      schedulePreview,
      workflowGroup,
    );
    const statusStripHtml =
      "<div class='assignment-workboard-status-strip'>" +
      assignmentWorkboardStatusCardHtml('数据新鲜度', freshness.label, freshness.detail, freshness.tone) +
      assignmentWorkboardStatusCardHtml('连接状态', connection.label, connection.detail, connection.tone) +
      assignmentWorkboardStatusCardHtml('当前建议', guidance.label, guidance.detail, guidance.tone) +
      '</div>';
    const groupsHtml =
      "<section class='assignment-workboard-section'>" +
      "<div class='assignment-workboard-section-head'>" +
      "<div>" +
      "<div class='assignment-workboard-section-title'>协作泳道</div>" +
      "<div class='assignment-workboard-section-meta'>固定显示当前 helper 的活跃任务和失败池，避免信息全堆到一条长列表里。</div>" +
      '</div>' +
      "<span class='assignment-chip muted'>helper " + escapeHtml(String(helperGroups.length)) + "</span>" +
      '</div>' +
      (
        helperGroups.length
          ? "<div class='assignment-workboard-group-grid'>" + helperGroups.map((group) => assignmentWorkboardGroupCardHtml(group)).join('') + '</div>'
          : "<div class='assignment-workboard-inline-note'>当前没有额外 helper 接棒，主线暂由 workflow 自己推进。</div>"
      ) +
      '</section>';
    const failureHtml =
      "<section class='assignment-workboard-section'>" +
      "<div class='assignment-workboard-section-head'>" +
      "<div>" +
      "<div class='assignment-workboard-section-title'>近期失败池</div>" +
      "<div class='assignment-workboard-section-meta'>先看 active 版本窗口内最靠前的失败节点，不把所有历史失败都摊平。</div>" +
      '</div>' +
      "<span class='assignment-chip fail'>失败 " + escapeHtml(String(failurePool.length)) + '</span>' +
      '</div>' +
      (
        failurePool.length
          ? "<div class='running-task-list'>" + assignmentWorkboardTaskButtons(failurePool, '失败') + '</div>'
          : "<div class='assignment-workboard-inline-note'>当前没有需要优先处理的失败节点。</div>"
      ) +
      '</section>';
    const scheduleHtml =
      "<section class='assignment-workboard-section'>" +
      "<div class='assignment-workboard-section-head'>" +
      "<div>" +
      "<div class='assignment-workboard-section-title'>定时入口</div>" +
      "<div class='assignment-workboard-section-meta'>主线与保底是否还有 future 出口，优先在这里判断。</div>" +
      '</div>' +
      "<span class='assignment-chip muted'>schedule " + escapeHtml(String(schedulePreview.length)) + '</span>' +
      '</div>' +
      (
        schedulePreview.length
          ? "<div class='assignment-workboard-schedule-list'>" + schedulePreview.map((item) => assignmentWorkboardScheduleCardHtml(item)).join('') + '</div>'
          : "<div class='assignment-workboard-inline-note'>最近未拿到定时任务预览。</div>"
      ) +
      '</section>';
    host.innerHTML =
      headerHtml +
      summaryHtml +
      statusStripHtml +
      "<div class='assignment-workboard-layout'>" +
      "<div class='assignment-workboard-stage'>" +
      focusHtml +
      groupsHtml +
      '</div>' +
      "<aside class='assignment-workboard-rail'>" +
      failureHtml +
      scheduleHtml +
      '</aside>' +
      '</div>' +
      '</div>';
  }

  function assignmentGraphOptionLabel(item) {
    const row = item && typeof item === 'object' ? item : {};
    const baseLabel = typeof assignmentGraphDisplayName === 'function'
      ? assignmentGraphDisplayName(row)
      : (safe(row.graph_name).trim() || safe(row.ticket_id).trim() || '未命名任务图');
    return row.is_test_data ? (baseLabel + ' · 测试') : baseLabel;
  }

  function isAssignmentGraphSelectorVisibleItem(item) {
    const row = item && typeof item === 'object' ? item : {};
    const sourceWorkflow = safe(row.source_workflow).trim().toLowerCase();
    return !!row.is_test_data || sourceWorkflow === ASSIGNMENT_UI_SOURCE_WORKFLOW;
  }

  function assignmentVisibleGraphs() {
    const items = Array.isArray(state.assignmentGraphs) ? state.assignmentGraphs : [];
    return items.filter((item) => isAssignmentGraphSelectorVisibleItem(item));
  }

  function renderAssignmentGraphSelector() {
    const select = $('assignmentGraphSelect');
    if (!select) return;
    select.disabled = true;
    select.hidden = true;
    select.setAttribute('aria-hidden', 'true');
    select.style.display = 'none';
  }

  function assignmentDelay(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, Math.max(0, Number(ms) || 0)));
  }

  function pickAssignmentDefaultNode(graphData) {
    const rows = Array.isArray(graphData && graphData.nodes) ? graphData.nodes : [];
    function assignmentDefaultNodeRank(item) {
      const row = item && typeof item === 'object' ? item : {};
      const status = safe(row.status).trim().toLowerCase();
      const isWorkflowMainline = !!row.is_workflow_mainline;
      if (isWorkflowMainline && status === 'running') return 0;
      if (isWorkflowMainline && status === 'ready') return 1;
      if (isWorkflowMainline && status === 'pending') return 2;
      if (isWorkflowMainline && status === 'blocked') return 3;
      if (status === 'running') return 4;
      if (status === 'ready') return 5;
      if (status === 'pending') return 6;
      if (status === 'blocked') return 7;
      if (isWorkflowMainline) return 8;
      if (status === 'failed' || status === 'succeeded') return 9;
      return 10;
    }
    const preferred = rows.slice().sort((left, right) => {
      const rankDiff = assignmentDefaultNodeRank(left) - assignmentDefaultNodeRank(right);
      if (rankDiff !== 0) return rankDiff;
      const fields = ['updated_at', 'completed_at', 'created_at', 'node_id'];
      for (let index = 0; index < fields.length; index += 1) {
        const field = fields[index];
        const leftValue = safe(left && left[field]).trim();
        const rightValue = safe(right && right[field]).trim();
        if (leftValue === rightValue) continue;
        return rightValue.localeCompare(leftValue, 'zh-CN');
      }
      return 0;
    })[0];
    return safe(preferred && preferred.node_id).trim();
  }

  async function refreshAssignmentDetail(nodeId, options) {
    const opts = options || {};
    const ticketId = selectedAssignmentTicketId();
    if (!ticketId) {
      state.assignmentDetail = null;
      state.assignmentSelectedNodeId = '';
      stopAssignmentExecutionRealtime();
      renderAssignmentDetail();
      return null;
    }
    const targetNodeId = safe(nodeId || state.assignmentSelectedNodeId).trim();
    const seq = Number(state.assignmentDetailRequestSeq || 0) + 1;
    state.assignmentDetailRequestSeq = seq;
    const url = withTestDataQuery('/api/assignments/' + encodeURIComponent(ticketId) +
      '/status-detail?node_id=' + encodeURIComponent(targetNodeId));
    const data = await getJSON(url);
    if (seq !== state.assignmentDetailRequestSeq) return null;
    state.assignmentDetail = data;
    state.assignmentSelectedNodeId = safe(data && data.selected_node && data.selected_node.node_id).trim();
    setAssignmentDetailError('');
    renderAssignmentDetail();
    if (!opts.skipGraphRender) {
      renderAssignmentGraph();
    }
    return data;
  }

  async function refreshAssignmentGraphData(options) {
    const opts = options || {};
    const ticketId = safe(opts.ticketId || state.assignmentSelectedTicketId).trim();
    const silent = !!opts.silent;
    const skipDetail = !!opts.skipDetail;
    if (!ticketId) {
      state.assignmentGraphData = null;
      state.assignmentGraphLastRefreshAtMs = 0;
      state.assignmentScheduler = null;
      state.assignmentActiveLoaded = 0;
      stopAssignmentExecutionRealtime();
      renderAssignmentCenter();
      return null;
    }
    const seq = Number(state.assignmentGraphRequestSeq || 0) + 1;
    state.assignmentGraphRequestSeq = seq;
    if (!silent) {
      state.assignmentLoading = true;
      renderAssignmentCenter();
    }
    try {
      const data = await getJSON(assignmentGraphUrl(ticketId));
      if (seq !== state.assignmentGraphRequestSeq) return null;
      state.assignmentGraphData = data;
      state.assignmentGraphLastRefreshAtMs = Date.now();
      state.assignmentScheduler = data.graph && data.graph.scheduler ? data.graph.scheduler : null;
      state.assignmentSelectedTicketId = ticketId;
      if (!safe(state.assignmentSelectedNodeId).trim()) {
        state.assignmentSelectedNodeId = pickAssignmentDefaultNode(data);
      } else {
        const exists = Array.isArray(data.nodes)
          ? data.nodes.some((item) => safe(item && item.node_id).trim() === safe(state.assignmentSelectedNodeId).trim())
          : false;
        if (!exists) {
          state.assignmentSelectedNodeId = pickAssignmentDefaultNode(data);
        }
      }
      setAssignmentError('');
      renderAssignmentCenter();
      if (!skipDetail) {
        await refreshAssignmentDetail(state.assignmentSelectedNodeId);
      }
      return data;
    } finally {
      state.assignmentLoading = false;
      renderAssignmentCenter();
    }
  }

  async function refreshAssignmentGraphs(options) {
    if (!state.agentSearchRootReady) {
      state.assignmentGraphs = [];
      state.assignmentGraphData = null;
      state.assignmentDetail = null;
      state.assignmentSelectedTicketId = '';
      state.assignmentSelectedNodeId = '';
      state.assignmentScheduler = null;
      state.assignmentActiveLoaded = 0;
      state.assignmentHistoryLoaded = 0;
      stopAssignmentExecutionRealtime();
      renderAssignmentCenter();
      return { items: [] };
    }
    const opts = options || {};
    const previous = safe(state.assignmentSelectedTicketId).trim();
    const data = await getJSON(assignmentGraphsUrl());
    state.assignmentGraphs = Array.isArray(data.items) ? data.items : [];
    const visibleGraphs = assignmentVisibleGraphs();
    const selectedExists = visibleGraphs.some((item) => safe(item && item.ticket_id).trim() === previous);
    const globalTicketId = globalAssignmentTicketId();
    const preferredTicketId = preferredAssignmentTicketId();
    const nextTicketId = selectedExists
      ? previous
      : (globalTicketId || preferredTicketId || (
        visibleGraphs.length
          ? safe(visibleGraphs[0].ticket_id).trim()
          : ''
      ));
    if (nextTicketId !== previous) {
      state.assignmentActiveLoaded = 0;
      state.assignmentHistoryLoaded = 0;
    }
    state.assignmentSelectedTicketId = nextTicketId;
    if (selectedAssignmentTicketId()) {
      return refreshAssignmentGraphData({ ticketId: selectedAssignmentTicketId() });
    }
    state.assignmentGraphData = null;
    state.assignmentDetail = null;
    state.assignmentSelectedNodeId = '';
    stopAssignmentExecutionRealtime();
    renderAssignmentCenter();
    return data;
  }

  async function dispatchAssignmentTicket(ticketId) {
    const tid = safe(ticketId || selectedAssignmentTicketId()).trim();
    if (!tid || !state.agentSearchRootReady) {
      return { dispatchResult: null, graphData: null };
    }
    const dispatchResult = await postJSON('/api/assignments/' + encodeURIComponent(tid) + '/dispatch-next', {
      operator: 'web-user',
    });
    const graphData = await refreshAssignmentGraphData({ ticketId: tid });
    return { dispatchResult: dispatchResult, graphData: graphData };
  }

  async function maybeDispatchAssignmentTicket(ticketId) {
    const result = await dispatchAssignmentTicket(ticketId);
    return result.graphData;
  }

  async function resumeAssignmentTicket(ticketId) {
    const tid = safe(ticketId || selectedAssignmentTicketId()).trim();
    if (!tid || !state.agentSearchRootReady) {
      return { resumeResult: null, graphData: null };
    }
    const resumeResult = await postJSON('/api/assignments/' + encodeURIComponent(tid) + '/resume', {
      operator: 'web-user',
    });
    const graphData = await refreshAssignmentGraphData({ ticketId: tid });
    return { resumeResult: resumeResult, graphData: graphData };
  }

  async function waitForAssignmentDispatch(ticketId, options) {
    const tid = safe(ticketId || selectedAssignmentTicketId()).trim();
    if (!tid || !state.agentSearchRootReady) return null;
    const opts = options && typeof options === 'object' ? options : {};
    const attempts = Math.max(1, Number(opts.attempts || 6));
    const intervalMs = Math.max(120, Number(opts.intervalMs || 300));
    for (let index = 0; index < attempts; index += 1) {
      await assignmentDelay(intervalMs);
      const data = await refreshAssignmentGraphData({ ticketId: tid });
      const nodes = Array.isArray(data && data.nodes) ? data.nodes : [];
      const runningNode = nodes.find((item) => safe(item && item.status).trim().toLowerCase() === 'running');
      if (runningNode) {
        return data;
      }
      const schedulerState = safe(data && data.graph && data.graph.scheduler_state).trim().toLowerCase();
      if (schedulerState === 'paused' || schedulerState === 'idle') {
        return data;
      }
    }
    return state.assignmentGraphData;
  }

  function assignmentResumeStatusMessage(graphData) {
    const data = graphData && typeof graphData === 'object' ? graphData : {};
    const nodes = Array.isArray(data && data.nodes) ? data.nodes : [];
    if (nodes.some((item) => safe(item && item.status).trim().toLowerCase() === 'running')) {
      return '任务调度已恢复并开始执行';
    }
    if (nodes.some((item) => safe(item && item.status).trim().toLowerCase() === 'ready')) {
      return '任务调度已恢复，任务仍在队列中';
    }
    return '任务调度已恢复';
  }

  function assignmentCreateStatusMessage(createdNodeId) {
    const nodeId = safe(createdNodeId).trim();
    const selected = selectedAssignmentNode();
    const current = nodeId && safe(selected.node_id).trim() === nodeId ? selected : {};
    const nodeStatus = safe(current.status).trim().toLowerCase();
    const upstreamNodes = Array.isArray(current.upstream_nodes) ? current.upstream_nodes : [];
    const schedulerState = safe(state.assignmentScheduler && state.assignmentScheduler.state).trim().toLowerCase();
    if (nodeStatus === 'running') return '任务已创建并开始执行';
    if (nodeStatus === 'ready') return '任务已创建并进入调度队列';
    if (nodeStatus === 'pending' && upstreamNodes.length) return '任务已创建，等待上游完成';
    if (nodeStatus === 'pending' && schedulerState === 'running') return '任务已创建，等待调度';
    if (nodeStatus === 'pending') return '任务已创建';
    if (nodeStatus === 'blocked') return '任务已创建，但被上游失败阻塞';
    if (schedulerState === 'paused' || schedulerState === 'pause_pending') return '任务已创建，当前调度已暂停';
    return '任务已创建';
  }

  function setAssignmentCreateOpen(nextOpen, options) {
    const opts = options && typeof options === 'object' ? options : {};
    const wasOpen = !!state.assignmentCreateOpen;
    state.assignmentCreateOpen = !!nextOpen;
    if (!state.assignmentCreateOpen) {
      if (opts.clearDraft) {
        resetAssignmentCreateForm({ clearDraft: true });
      } else if (wasOpen) {
        syncAssignmentCreateFormFromInputs();
        persistAssignmentCreateDraft();
      }
      setAssignmentDrawerError('');
    }
    if (state.assignmentCreateOpen) {
      restoreAssignmentCreateDraft();
      setAssignmentDrawerError('');
      ensureAssignmentAgentPool(false).catch((err) => {
        setAssignmentDrawerError(err.message || String(err));
      });
    }
    renderAssignmentDrawer();
  }

  function syncAssignmentCreateFormFromInputs() {
    state.assignmentCreateForm = {
      node_name: safe($('assignmentTaskNameInput') ? $('assignmentTaskNameInput').value : '').trim(),
      assigned_agent_id: safe($('assignmentAgentSelect') ? $('assignmentAgentSelect').value : '').trim(),
      priority: assignmentPriorityLabel($('assignmentPrioritySelect') ? $('assignmentPrioritySelect').value : 'P1'),
      node_goal: safe($('assignmentGoalInput') ? $('assignmentGoalInput').value : '').trim(),
      expected_artifact: safe($('assignmentArtifactInput') ? $('assignmentArtifactInput').value : '').trim(),
      delivery_mode: safe($('assignmentDeliveryModeSelect') ? $('assignmentDeliveryModeSelect').value : 'none').trim() || 'none',
      delivery_receiver_agent_id: safe($('assignmentDeliveryReceiverSelect') ? $('assignmentDeliveryReceiverSelect').value : '').trim(),
    };
    state.assignmentCreateUpstreamSearch = safe($('assignmentUpstreamSearch') ? $('assignmentUpstreamSearch').value : '').trim();
    persistAssignmentCreateDraft();
  }

  async function submitAssignmentCreate() {
    syncAssignmentCreateFormFromInputs();
    const form = state.assignmentCreateForm || defaultAssignmentCreateForm();
    if (!safe(form.node_name).trim()) throw new Error('任务名称必填');
    if (!safe(form.assigned_agent_id).trim()) throw new Error('执行 agent 必填');
    if (!safe(form.node_goal).trim()) throw new Error('确认任务目标必填');
    if (safe(form.delivery_mode).trim().toLowerCase() === 'specified' && !safe(form.delivery_receiver_agent_id).trim()) {
      throw new Error('指定交付对象时必须选择接收 agent');
    }
    const ticketId = await ensureAssignmentGraphExists();
    const payload = {
      node_name: form.node_name,
      assigned_agent_id: form.assigned_agent_id,
      priority: assignmentPriorityLabel(form.priority),
      node_goal: form.node_goal,
      expected_artifact: form.expected_artifact,
      delivery_mode: form.delivery_mode,
      delivery_receiver_agent_id: form.delivery_receiver_agent_id,
      upstream_node_ids: Array.isArray(state.assignmentCreateSelectedUpstreamIds)
        ? state.assignmentCreateSelectedUpstreamIds
        : [],
      operator: 'web-user',
    };
    const created = await postJSON('/api/assignments/' + encodeURIComponent(ticketId) + '/nodes', payload);
    const createdNodeId = safe(created && created.node && created.node.node_id).trim();
    if (createdNodeId) {
      state.assignmentSelectedNodeId = createdNodeId;
    }
    resetAssignmentCreateForm({ clearDraft: true });
    setAssignmentCreateOpen(false, { clearDraft: true });
    await refreshAssignmentGraphs({ preserveSelection: true });
    const schedulerState = safe(state.assignmentScheduler && state.assignmentScheduler.state).trim().toLowerCase();
    if (schedulerState === 'idle') {
      await resumeAssignmentTicket(ticketId);
    } else if (schedulerState === 'running') {
      await dispatchAssignmentTicket(ticketId);
    }
    setStatus(assignmentCreateStatusMessage(createdNodeId));
  }

  async function pauseAssignmentSchedulerAction() {
    const ticketId = selectedAssignmentTicketId();
    if (!ticketId) return;
    await postJSON('/api/assignments/' + encodeURIComponent(ticketId) + '/pause', {
      operator: 'web-user',
    });
    await refreshAssignmentGraphData({ ticketId: ticketId });
    setStatus('任务调度已暂停');
  }

  async function resumeAssignmentSchedulerAction() {
    const ticketId = selectedAssignmentTicketId();
    if (!ticketId) return;
    await resumeAssignmentTicket(ticketId);
    setStatus('任务调度恢复中');
    void waitForAssignmentDispatch(ticketId, { attempts: 8, intervalMs: 250 })
      .then((graphData) => {
        setStatus(assignmentResumeStatusMessage(graphData));
      })
      .catch(() => {
        setStatus('任务调度已恢复');
      });
  }

  async function clearAssignmentGraphAction() {
    const ticketId = selectedAssignmentTicketId();
    if (!ticketId) return;
    const ok = window.confirm(
      '将清空当前任务图中的全部活动任务与依赖边，并保留删除留痕。此操作不可撤销，确认继续？',
    );
    if (!ok) return;
    await postJSON('/api/assignments/' + encodeURIComponent(ticketId) + '/clear', {
      operator: 'web-user',
    });
    state.assignmentSelectedNodeId = '';
    await refreshAssignmentGraphData({ ticketId: ticketId });
    setStatus('当前任务图已清空');
  }

  async function loadMoreAssignmentHistory() {
    const graphData = state.assignmentGraphData && typeof state.assignmentGraphData === 'object'
      ? state.assignmentGraphData
      : {};
    const history = graphData.history && typeof graphData.history === 'object'
      ? graphData.history
      : {};
    if (!history.has_more) return;
    state.assignmentHistoryLoaded = Number(history.next_history_loaded || state.assignmentHistoryLoaded || 0);
    await refreshAssignmentGraphData({ ticketId: selectedAssignmentTicketId() });
  }

  async function loadMoreAssignmentTasks() {
    const graphData = state.assignmentGraphData && typeof state.assignmentGraphData === 'object'
      ? state.assignmentGraphData
      : {};
    const active = graphData.active && typeof graphData.active === 'object'
      ? graphData.active
      : {};
    if (!active.has_more) return;
    state.assignmentActiveLoaded = Number(active.next_active_loaded || state.assignmentActiveLoaded || 0);
    await refreshAssignmentGraphData({ ticketId: selectedAssignmentTicketId() });
  }
