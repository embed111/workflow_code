  async function deliverSelectedAssignmentArtifact() {
    const selected = selectedAssignmentNode();
    const ticketId = selectedAssignmentTicketId();
    const nodeId = safe(selected.node_id).trim();
    if (!ticketId || !nodeId) return;
    await postJSON(
      '/api/assignments/' + encodeURIComponent(ticketId) + '/nodes/' + encodeURIComponent(nodeId) + '/deliver-artifact',
      {
        artifact_label: safe($('assignmentArtifactLabelInput') ? $('assignmentArtifactLabelInput').value : '').trim(),
        delivery_note: safe($('assignmentArtifactNoteInput') ? $('assignmentArtifactNoteInput').value : '').trim(),
        operator: 'web-user',
      },
    );
    await refreshAssignmentGraphData({ ticketId: ticketId });
    setStatus('产物已提交');
  }

  async function viewSelectedAssignmentArtifact(pathIndex) {
    const selected = selectedAssignmentNode();
    const ticketId = selectedAssignmentTicketId();
    const nodeId = safe(selected.node_id).trim();
    if (!ticketId || !nodeId) return;
    window.open(
      assignmentArtifactPreviewUrl(ticketId, nodeId, pathIndex),
      '_blank',
      'noopener',
    );
  }

  async function markSelectedAssignmentSuccess() {
    const selected = selectedAssignmentNode();
    const ticketId = selectedAssignmentTicketId();
    const nodeId = safe(selected.node_id).trim();
    const successReason = safe($('assignmentReceiptReason') ? $('assignmentReceiptReason').value : '').trim();
    const resultRef = safe($('assignmentReceiptRef') ? $('assignmentReceiptRef').value : '').trim();
    if (!ticketId || !nodeId) return;
    await postJSON(
      '/api/assignments/' + encodeURIComponent(ticketId) + '/nodes/' + encodeURIComponent(nodeId) + '/mark-success',
      {
        success_reason: successReason,
        result_ref: resultRef,
        operator: 'web-user',
      },
    );
    await refreshAssignmentGraphData({ ticketId: ticketId });
    await maybeDispatchAssignmentTicket(ticketId);
    setStatus('任务已标记成功');
  }

  async function markSelectedAssignmentFailed() {
    const selected = selectedAssignmentNode();
    const ticketId = selectedAssignmentTicketId();
    const nodeId = safe(selected.node_id).trim();
    const failureReason = safe($('assignmentReceiptReason') ? $('assignmentReceiptReason').value : '').trim();
    if (!ticketId || !nodeId) return;
    await postJSON(
      '/api/assignments/' + encodeURIComponent(ticketId) + '/nodes/' + encodeURIComponent(nodeId) + '/mark-failed',
      {
        failure_reason: failureReason,
        operator: 'web-user',
      },
    );
    await refreshAssignmentGraphData({ ticketId: ticketId });
    setStatus('任务已标记失败');
  }

  async function rerunSelectedAssignmentNode() {
    const selected = selectedAssignmentNode();
    const ticketId = selectedAssignmentTicketId();
    const nodeId = safe(selected.node_id).trim();
    if (!ticketId || !nodeId) return;
    await postJSON(
      '/api/assignments/' + encodeURIComponent(ticketId) + '/nodes/' + encodeURIComponent(nodeId) + '/rerun',
      {
        operator: 'web-user',
      },
    );
    await refreshAssignmentGraphData({ ticketId: ticketId });
    await maybeDispatchAssignmentTicket(ticketId);
    setStatus('失败任务已重跑');
  }

  async function overrideSelectedAssignmentNode() {
    const selected = selectedAssignmentNode();
    const ticketId = selectedAssignmentTicketId();
    const nodeId = safe(selected.node_id).trim();
    const targetStatus = safe($('assignmentOverrideStatus') ? $('assignmentOverrideStatus').value : '').trim();
    const reason = safe($('assignmentOverrideReason') ? $('assignmentOverrideReason').value : '').trim();
    if (!ticketId || !nodeId) return;
    await postJSON(
      '/api/assignments/' + encodeURIComponent(ticketId) + '/nodes/' + encodeURIComponent(nodeId) + '/override-status',
      {
        target_status: targetStatus,
        reason: reason,
        operator: 'web-user',
      },
    );
    await refreshAssignmentGraphData({ ticketId: ticketId });
    await maybeDispatchAssignmentTicket(ticketId);
    setStatus('执行状态已人工修改');
  }

  async function deleteSelectedAssignmentNode() {
    const selected = selectedAssignmentNode();
    const ticketId = selectedAssignmentTicketId();
    const nodeId = safe(selected.node_id).trim();
    const nodeName = safe(selected.node_name || selected.node_id).trim();
    if (!ticketId || !nodeId) return;
    const ok = window.confirm(
      '将删除任务“' + nodeName + '”。若它位于依赖链中间，系统会自动桥接原有上下游并保留删除留痕。此操作不可撤销，确认继续？',
    );
    if (!ok) return;
    const data = await deleteJSON(
      '/api/assignments/' + encodeURIComponent(ticketId) + '/nodes/' + encodeURIComponent(nodeId),
      { operator: 'web-user' },
    );
    const schedulerState = safe(data && data.graph_overview && data.graph_overview.scheduler_state).trim().toLowerCase();
    state.assignmentSelectedNodeId = '';
    if (schedulerState === 'running') {
      const dispatchResult = await maybeDispatchAssignmentTicket(ticketId);
      if (!dispatchResult) {
        await refreshAssignmentGraphData({ ticketId: ticketId });
      }
    } else {
      await refreshAssignmentGraphData({ ticketId: ticketId });
    }
    setStatus('任务已删除');
  }

  function createAssignmentStrategyRegistry(strategies, fallbackKey) {
    const entries = strategies && typeof strategies === 'object' ? strategies : {};
    const fallback = safe(fallbackKey).trim();
    return {
      resolve(key) {
        const lookup = safe(key).trim();
        return entries[lookup] || (fallback ? entries[fallback] : null) || null;
      },
    };
  }

  function createAssignmentProbeOutput() {
    return {
      ts: new Date().toISOString(),
      case: assignmentProbeCase(),
      pass: false,
      error: '',
      active_tab: '',
      show_test_data: !!state.showTestData,
      ticket_id: '',
      graph_name: '',
      graph_is_test_data: false,
      scheduler_state: '',
      scheduler_chip_text: '',
      scheduler_chip_title: '',
      total_nodes: 0,
      status_counts: {},
      rendered_node_count: 0,
      running_circle_count: 0,
      selected_node_id: '',
      selected_node_name: '',
      status_line: '',
      header_note: '',
      graph_meta: '',
      detail_meta: '',
      empty_visible: false,
      pause_disabled: true,
      resume_disabled: true,
      clear_disabled: true,
      execution_card_visible: false,
      latest_run_id: '',
      latest_run_status: '',
      latest_run_event_count: 0,
      prompt_visible: false,
      stdout_visible: false,
      stderr_visible: false,
      result_visible: false,
      settings_provider: '',
      settings_codex_path: '',
      settings_command_template_len: 0,
      settings_global_concurrency: 0,
      settings_meta: '',
      detail_section_key: '',
      detail_section_open: false,
      detail_section_summary_visible: false,
      detail_section_body_visible: false,
      detail_section_body_overlaps: false,
      detail_section_summary_height: 0,
      detail_section_body_height: 0,
      drawer_open: false,
      draft_cache_present: false,
      draft_node_name: '',
      draft_goal: '',
      draft_priority: '',
      draft_upstream_search: '',
    };
  }

  function assignmentProbeWait(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  function assignmentProbeDelayMs() {
    return Math.max(0, Number(queryParam('assignment_probe_delay_ms') || '720'));
  }

  function syncAssignmentProbeTicketSelection() {
    const requestedTicketId = safe(queryParam('assignment_probe_ticket')).trim();
    if (requestedTicketId) {
      state.assignmentSelectedTicketId = requestedTicketId;
    }
  }

  async function prepareAssignmentSettingsProbe() {
    switchTab('settings');
    await refreshAssignmentExecutionSettings();
  }

  async function prepareAssignmentTaskCenterProbe() {
    switchTab('task-center');
    await refreshAssignmentGraphs({ preserveSelection: true });
    const requestedNodeId = safe(queryParam('assignment_probe_node')).trim();
    if (requestedNodeId && selectedAssignmentTicketId()) {
      state.assignmentSelectedNodeId = requestedNodeId;
      await refreshAssignmentDetail(requestedNodeId);
    }
  }

  async function prepareAssignmentDraftPersistProbe(output) {
    const expectedName = '缓存保留验证任务';
    const expectedGoal = '关闭抽屉后再次打开，之前编辑内容应自动回填。';
    const expectedPriority = 'P2';
    const expectedSearch = 'cache-check';
    output.draft_node_name = expectedName;
    output.draft_goal = expectedGoal;
    output.draft_priority = expectedPriority;
    output.draft_upstream_search = expectedSearch;
    clearAssignmentCreateDraft();
    resetAssignmentCreateForm({ clearDraft: true });
    state.assignmentCreateDraftLoaded = false;
    switchTab('task-center');
    await ensureAssignmentAgentPool(false);
    setAssignmentCreateOpen(true);
    await assignmentProbeWait(80);
    const nameInput = $('assignmentTaskNameInput');
    if (nameInput) {
      nameInput.value = expectedName;
      nameInput.dispatchEvent(new Event('input', { bubbles: true }));
    }
    const goalInput = $('assignmentGoalInput');
    if (goalInput) {
      goalInput.value = expectedGoal;
      goalInput.dispatchEvent(new Event('input', { bubbles: true }));
    }
    const prioritySelect = $('assignmentPrioritySelect');
    if (prioritySelect) {
      prioritySelect.value = expectedPriority;
      prioritySelect.dispatchEvent(new Event('change', { bubbles: true }));
    }
    const upstreamSearch = $('assignmentUpstreamSearch');
    if (upstreamSearch) {
      upstreamSearch.value = expectedSearch;
      upstreamSearch.dispatchEvent(new Event('input', { bubbles: true }));
    }
    await assignmentProbeWait(80);
    setAssignmentCreateOpen(false);
    await assignmentProbeWait(80);
    resetAssignmentCreateForm({ clearDraft: false });
    state.assignmentCreateDraftLoaded = false;
    setAssignmentCreateOpen(true);
  }

  async function prepareAssignmentCreateSubmitProbe(output) {
    const expectedName = '提交创建验证任务';
    const expectedGoal = '验证提交创建后应立即选中新节点，并从空闲图进入调度。';
    clearAssignmentCreateDraft();
    resetAssignmentCreateForm({ clearDraft: true });
    state.assignmentCreateDraftLoaded = false;
    state.assignmentSelectedNodeId = '';
    switchTab('task-center');
    await refreshAssignmentGraphs({ preserveSelection: true });
    await ensureAssignmentAgentPool(false);
    setAssignmentCreateOpen(true);
    await assignmentProbeWait(80);
    if ($('assignmentTaskNameInput')) {
      $('assignmentTaskNameInput').value = expectedName;
    }
    if ($('assignmentGoalInput')) {
      $('assignmentGoalInput').value = expectedGoal;
    }
    if ($('assignmentPrioritySelect')) {
      $('assignmentPrioritySelect').value = 'P0';
    }
    syncAssignmentCreateFormFromInputs();
    await submitAssignmentCreate();
  }

  async function probeAssignmentDetailSection(output) {
    const sectionKey = safe(queryParam('assignment_probe_section')).trim() || 'execution-chain';
    const selectedNodeId = safe((assignmentDetailPayload().selected_node || {}).node_id || state.assignmentSelectedNodeId).trim();
    const stateKey = selectedNodeId && sectionKey ? selectedNodeId + '::' + sectionKey : '';
    const section = Array.from(document.querySelectorAll('#assignmentDetailBody details[data-assignment-detail-key]')).find(
      (item) => safe(item.getAttribute('data-assignment-detail-key')).trim() === stateKey,
    );
    output.detail_section_key = sectionKey;
    if (!section) return;
    const nextOpen = output.case === 'detail_expanded';
    section.open = nextOpen;
    state.assignmentDetailSectionOpen[stateKey] = nextOpen;
    await assignmentProbeWait(80);
    const summary = section.querySelector('summary');
    const body = section.querySelector('.assignment-detail-section-body');
    const summaryRect = summary ? summary.getBoundingClientRect() : null;
    const bodyRect = body ? body.getBoundingClientRect() : null;
    output.detail_section_open = !!section.open;
    output.detail_section_summary_visible = !!(summary && summary.getClientRects().length);
    output.detail_section_body_visible = !!(body && body.getClientRects().length);
    output.detail_section_body_overlaps = !!(
      summaryRect &&
      bodyRect &&
      output.detail_section_body_visible &&
      bodyRect.top < summaryRect.bottom - 1
    );
    output.detail_section_summary_height = Number(summaryRect ? summaryRect.height : 0);
    output.detail_section_body_height = Number(bodyRect ? bodyRect.height : 0);
  }

  function collectAssignmentSettingsProbe(output) {
    output.settings_provider = safe($('assignmentExecutionProviderSelect') ? $('assignmentExecutionProviderSelect').value : '').trim();
    output.settings_codex_path = safe($('assignmentCodexCommandPathInput') ? $('assignmentCodexCommandPathInput').value : '').trim();
    output.settings_command_template_len = safe($('assignmentCommandTemplateInput') ? $('assignmentCommandTemplateInput').value : '').trim().length;
    output.settings_global_concurrency = Number(
      safe($('assignmentExecutionConcurrencyInput') ? $('assignmentExecutionConcurrencyInput').value : '').trim() || '0',
    );
    output.settings_meta = safe($('assignmentExecutionMeta') ? $('assignmentExecutionMeta').textContent : '').trim();
  }

  function collectAssignmentTaskCenterProbe(output) {
    const overview = selectedAssignmentGraphOverview() || {};
    const metrics = assignmentMetricsSummary();
    const selected = selectedAssignmentNode();
    const detail = assignmentDetailPayload();
    const chain = detail.execution_chain && typeof detail.execution_chain === 'object'
      ? detail.execution_chain
      : {};
    const latestRun = assignmentExecutionLatestRun(chain);
    const emptyState = $('assignmentEmptyState');
    output.show_test_data = !!state.showTestData;
    output.ticket_id = selectedAssignmentTicketId();
    output.graph_name = safe(overview.graph_name).trim();
    output.graph_is_test_data = !!overview.is_test_data;
    output.scheduler_state = safe(overview.scheduler_state).trim().toLowerCase();
    output.scheduler_chip_text = safe($('assignmentSchedulerStateChip') ? $('assignmentSchedulerStateChip').textContent : '').trim();
    output.scheduler_chip_title = safe($('assignmentSchedulerStateChip') ? $('assignmentSchedulerStateChip').getAttribute('title') : '').trim();
    output.total_nodes = Number(metrics.total_nodes || 0);
    output.status_counts = metrics.status_counts && typeof metrics.status_counts === 'object'
      ? metrics.status_counts
      : {};
    output.rendered_node_count = document.querySelectorAll('#assignmentGraphSvg [data-node-id]').length;
    output.running_circle_count = document.querySelectorAll('#assignmentGraphSvg .assignment-node-circle.running').length;
    output.selected_node_id = safe(selected.node_id).trim();
    output.selected_node_name = safe(selected.node_name).trim();
    output.status_line = safe($('statusLine') ? $('statusLine').textContent : '').trim();
    output.header_note = safe($('assignmentHeaderNote') ? $('assignmentHeaderNote').textContent : '').trim();
    output.graph_meta = safe($('assignmentGraphMeta') ? $('assignmentGraphMeta').textContent : '').trim();
    output.detail_meta = safe($('assignmentDetailMeta') ? $('assignmentDetailMeta').textContent : '').trim();
    output.empty_visible = !!(emptyState && !emptyState.classList.contains('hidden'));
    output.pause_disabled = !!($('assignmentPauseBtn') && $('assignmentPauseBtn').disabled);
    output.resume_disabled = !!($('assignmentResumeBtn') && $('assignmentResumeBtn').disabled);
    output.clear_disabled = !!($('assignmentClearBtn') && $('assignmentClearBtn').disabled);
    output.execution_card_visible = document.querySelectorAll('#assignmentDetailBody .assignment-run-details').length > 0;
    output.latest_run_id = safe(latestRun.run_id).trim();
    output.latest_run_status = safe(latestRun.status).trim().toLowerCase();
    output.latest_run_event_count = Number(latestRun.event_count || 0);
    output.prompt_visible = safe(latestRun.prompt_text).trim().length > 0;
    output.stdout_visible = safe(latestRun.stdout_text).trim().length > 0;
    output.stderr_visible = safe(latestRun.stderr_text).trim().length > 0;
    output.result_visible = safe(latestRun.result_text).trim().length > 0;
  }

  function assignmentSettingsProbePass(output) {
    return output.active_tab === 'settings' &&
      output.settings_provider === 'codex' &&
      !!output.settings_codex_path &&
      output.settings_command_template_len > 0 &&
      output.settings_global_concurrency >= 1;
  }

  function assignmentDefaultTaskCenterProbePass(output) {
    return output.active_tab === 'task-center' &&
      !!output.ticket_id &&
      output.graph_is_test_data &&
      output.total_nodes >= 20 &&
      output.rendered_node_count >= 12 &&
      output.running_circle_count >= 1 &&
      !!output.selected_node_id &&
      output.header_note.includes('测试数据');
  }

  function assignmentHiddenProbePass(output) {
    return output.active_tab === 'task-center' &&
      !output.ticket_id &&
      output.empty_visible &&
      output.rendered_node_count === 0 &&
      output.pause_disabled &&
      output.resume_disabled &&
      output.clear_disabled;
  }

  function assignmentRunningDetailProbePass(output) {
    return output.active_tab === 'task-center' &&
      !!output.ticket_id &&
      !!output.latest_run_id &&
      (output.latest_run_status === 'starting' || output.latest_run_status === 'running') &&
      output.execution_card_visible &&
      output.prompt_visible &&
      output.latest_run_event_count >= 1;
  }

  function assignmentFailedDetailProbePass(output) {
    return output.active_tab === 'task-center' &&
      !!output.ticket_id &&
      !!output.latest_run_id &&
      output.latest_run_status === 'failed' &&
      output.execution_card_visible &&
      output.prompt_visible &&
      (output.stdout_visible || output.stderr_visible || output.result_visible);
  }

  function assignmentSuccessDetailProbePass(output) {
    return output.active_tab === 'task-center' &&
      !!output.ticket_id &&
      !!output.latest_run_id &&
      output.latest_run_status === 'succeeded' &&
      output.execution_card_visible &&
      output.prompt_visible &&
      output.result_visible;
  }

  function assignmentSchedulerIdleProbePass(output) {
    return output.active_tab === 'task-center' &&
      !!output.ticket_id &&
      output.scheduler_state === 'running' &&
      output.running_circle_count === 0 &&
      output.scheduler_chip_text === '空闲' &&
      output.scheduler_chip_title.includes('当前无运行中任务');
  }

  function assignmentDetailCollapsedProbePass(output) {
    return output.active_tab === 'task-center' &&
      !!output.ticket_id &&
      !!output.selected_node_id &&
      !!output.detail_section_key &&
      !output.detail_section_open &&
      output.detail_section_summary_visible &&
      !output.detail_section_body_visible;
  }

  function assignmentDetailExpandedProbePass(output) {
    return output.active_tab === 'task-center' &&
      !!output.ticket_id &&
      !!output.selected_node_id &&
      !!output.detail_section_key &&
      output.detail_section_open &&
      output.detail_section_summary_visible &&
      output.detail_section_body_visible &&
      !output.detail_section_body_overlaps &&
      output.detail_section_body_height > 24;
  }

  function collectAssignmentDraftPersistProbe(output) {
    output.drawer_open = !!state.assignmentCreateOpen;
    try {
      output.draft_cache_present = !!safe(localStorage.getItem(assignmentCreateDraftCacheKey)).trim();
    } catch (_) {
      output.draft_cache_present = false;
    }
    output.draft_node_name = safe($('assignmentTaskNameInput') ? $('assignmentTaskNameInput').value : '');
    output.draft_goal = safe($('assignmentGoalInput') ? $('assignmentGoalInput').value : '');
    output.draft_priority = assignmentPriorityLabel(
      $('assignmentPrioritySelect') ? $('assignmentPrioritySelect').value : 'P1',
    );
    output.draft_upstream_search = safe($('assignmentUpstreamSearch') ? $('assignmentUpstreamSearch').value : '');
  }

  function assignmentDraftPersistProbePass(output) {
    return output.active_tab === 'task-center' &&
      output.drawer_open &&
      output.draft_cache_present &&
      output.draft_node_name === '缓存保留验证任务' &&
      output.draft_goal === '关闭抽屉后再次打开，之前编辑内容应自动回填。' &&
      output.draft_priority === 'P2' &&
      output.draft_upstream_search === 'cache-check';
  }

  function assignmentCreateSubmitProbePass(output) {
    return output.active_tab === 'task-center' &&
      !!output.ticket_id &&
      output.total_nodes === 1 &&
      !!output.selected_node_id &&
      output.selected_node_name === '提交创建验证任务' &&
      output.scheduler_state === 'running' &&
      output.status_line.includes('任务已创建');
  }

  function createAssignmentTaskCenterProbeStrategy(evaluate, options) {
    const opts = options && typeof options === 'object' ? options : {};
    return {
      prepare: prepareAssignmentTaskCenterProbe,
      afterWait: opts.probeDetailSection ? probeAssignmentDetailSection : null,
      collect: collectAssignmentTaskCenterProbe,
      evaluate: evaluate,
    };
  }

  const ASSIGNMENT_PROBE_STRATEGY_REGISTRY = createAssignmentStrategyRegistry(
    {
      settings: {
        prepare: prepareAssignmentSettingsProbe,
        collect: collectAssignmentSettingsProbe,
        evaluate: assignmentSettingsProbePass,
      },
      hidden: createAssignmentTaskCenterProbeStrategy(assignmentHiddenProbePass),
      running_detail: createAssignmentTaskCenterProbeStrategy(assignmentRunningDetailProbePass),
      failed_detail: createAssignmentTaskCenterProbeStrategy(assignmentFailedDetailProbePass),
      success_detail: createAssignmentTaskCenterProbeStrategy(assignmentSuccessDetailProbePass),
      scheduler_idle_display: createAssignmentTaskCenterProbeStrategy(assignmentSchedulerIdleProbePass),
      detail_collapsed: createAssignmentTaskCenterProbeStrategy(assignmentDetailCollapsedProbePass, { probeDetailSection: true }),
      detail_expanded: createAssignmentTaskCenterProbeStrategy(assignmentDetailExpandedProbePass, { probeDetailSection: true }),
      draft_persist: {
        prepare: prepareAssignmentDraftPersistProbe,
        collect: collectAssignmentDraftPersistProbe,
        evaluate: assignmentDraftPersistProbePass,
      },
      create_submit: {
        prepare: prepareAssignmentCreateSubmitProbe,
        collect: collectAssignmentTaskCenterProbe,
        evaluate: assignmentCreateSubmitProbePass,
      },
      default: createAssignmentTaskCenterProbeStrategy(assignmentDefaultTaskCenterProbePass),
    },
    'default',
  );

  const ASSIGNMENT_DETAIL_ACTION_STRATEGY_REGISTRY = createAssignmentStrategyRegistry({
    assignmentMarkSuccessBtn: {
      buttonId: 'assignmentMarkSuccessBtn',
      execute: markSelectedAssignmentSuccess,
    },
    assignmentMarkFailedBtn: {
      buttonId: 'assignmentMarkFailedBtn',
      execute: markSelectedAssignmentFailed,
    },
    assignmentDeliverBtn: {
      buttonId: 'assignmentDeliverBtn',
      execute: deliverSelectedAssignmentArtifact,
    },
    assignmentViewArtifactBtn: {
      buttonId: 'assignmentViewArtifactBtn',
      execute: viewSelectedAssignmentArtifact,
    },
    assignmentRerunBtn: {
      buttonId: 'assignmentRerunBtn',
      execute: rerunSelectedAssignmentNode,
    },
    assignmentOverrideBtn: {
      buttonId: 'assignmentOverrideBtn',
      execute: overrideSelectedAssignmentNode,
    },
    assignmentDeleteBtn: {
      buttonId: 'assignmentDeleteBtn',
      execute: deleteSelectedAssignmentNode,
    },
  });

  async function runAssignmentCenterProbe() {
    const output = createAssignmentProbeOutput();
    try {
      const strategy = ASSIGNMENT_PROBE_STRATEGY_REGISTRY.resolve(output.case);
      syncAssignmentProbeTicketSelection();
      if (strategy && typeof strategy.prepare === 'function') {
        await strategy.prepare(output);
      }
      const delayMs = assignmentProbeDelayMs();
      if (delayMs > 0) {
        await assignmentProbeWait(delayMs);
      }
      if (strategy && typeof strategy.afterWait === 'function') {
        await strategy.afterWait(output);
      }
      const activeTab = document.querySelector('.tab.active');
      output.active_tab = safe(activeTab && activeTab.getAttribute('data-tab')).trim();
      if (strategy && typeof strategy.collect === 'function') {
        strategy.collect(output);
      }
      if (strategy && typeof strategy.evaluate === 'function') {
        output.pass = !!strategy.evaluate(output);
      }
    } catch (err) {
      output.error = safe(err && err.message ? err.message : err);
    }
    const node = ensureAssignmentCenterProbeOutputNode();
    node.textContent = JSON.stringify(output);
    node.setAttribute('data-pass', output.pass ? '1' : '0');
  }

  function bindAssignmentCenterEvents() {
    const graphCanvas = $('assignmentGraphCanvas');
    if (graphCanvas) {
      graphCanvas.addEventListener('click', (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;
        const group = target.closest('[data-node-id]');
        if (!group) return;
        const nodeId = safe(group.getAttribute('data-node-id')).trim();
        if (!nodeId) return;
        state.assignmentSelectedNodeId = nodeId;
        refreshAssignmentDetail(nodeId).catch((err) => {
          setAssignmentDetailError(err.message || String(err));
        });
      });
    }

    const detailBody = $('assignmentDetailBody');
    if (detailBody) {
      detailBody.addEventListener('click', (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;
        const actionNode = target.closest('[id]');
        const id = safe(actionNode && actionNode.id).trim();
        const strategy = ASSIGNMENT_DETAIL_ACTION_STRATEGY_REGISTRY.resolve(id);
        if (!strategy) return;
        const run = async (work) => {
          try {
            await work();
            setAssignmentDetailError('');
          } catch (err) {
            setAssignmentDetailError(err.message || String(err));
          }
        };
        run(() => withButtonLock(strategy.buttonId || id, strategy.execute));
      });
    }

    const drawerMask = $('assignmentDrawerMask');
    if (drawerMask) {
      drawerMask.addEventListener('click', (event) => {
        if (event.target === drawerMask) {
          setAssignmentCreateOpen(false);
        }
      });
    }

    const resultNode = $('assignmentUpstreamResults');
    if (resultNode) {
      resultNode.addEventListener('click', (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;
        const button = target.closest('[data-assignment-upstream-add]');
        if (!button) return;
        const nodeId = safe(button.getAttribute('data-assignment-upstream-add')).trim();
        if (!nodeId) return;
        if (!Array.isArray(state.assignmentCreateSelectedUpstreamIds)) {
          state.assignmentCreateSelectedUpstreamIds = [];
        }
        if (!state.assignmentCreateSelectedUpstreamIds.includes(nodeId)) {
          state.assignmentCreateSelectedUpstreamIds.push(nodeId);
        }
        persistAssignmentCreateDraft();
        renderAssignmentDrawer();
      });
    }

    const selectedNode = $('assignmentSelectedUpstreams');
    if (selectedNode) {
      selectedNode.addEventListener('click', (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;
        const button = target.closest('[data-assignment-upstream-remove]');
        if (!button) return;
        const nodeId = safe(button.getAttribute('data-assignment-upstream-remove')).trim();
        state.assignmentCreateSelectedUpstreamIds = (state.assignmentCreateSelectedUpstreamIds || [])
          .filter((item) => safe(item).trim() !== nodeId);
        persistAssignmentCreateDraft();
        renderAssignmentDrawer();
      });
    }

    if ($('assignmentCreateBtn')) {
      $('assignmentCreateBtn').onclick = async () => {
        try {
          setAssignmentDrawerError('');
          await ensureAssignmentAgentPool(false);
          setAssignmentCreateOpen(true);
        } catch (err) {
          setAssignmentError(err.message || String(err));
        }
      };
    }
    if ($('assignmentRefreshBtn')) {
      $('assignmentRefreshBtn').onclick = async () => {
        try {
          await withButtonLock('assignmentRefreshBtn', async () => {
            await refreshAssignmentGraphs({ preserveSelection: true });
          });
        } catch (err) {
          setAssignmentError(err.message || String(err));
        }
      };
    }
    if ($('assignmentGraphSelect')) {
      $('assignmentGraphSelect').onchange = async () => {
        try {
          const ticketId = safe($('assignmentGraphSelect').value).trim();
          if (!ticketId || ticketId === selectedAssignmentTicketId()) return;
          state.assignmentSelectedTicketId = ticketId;
          state.assignmentSelectedNodeId = '';
          state.assignmentActiveLoaded = 0;
          state.assignmentHistoryLoaded = 0;
          await refreshAssignmentGraphData({ ticketId: ticketId });
        } catch (err) {
          setAssignmentError(err.message || String(err));
        }
      };
    }
    if ($('assignmentLoadHistoryBtn')) {
      $('assignmentLoadHistoryBtn').onclick = async () => {
        try {
          await withButtonLock('assignmentLoadHistoryBtn', async () => {
            await loadMoreAssignmentHistory();
          });
        } catch (err) {
          setAssignmentError(err.message || String(err));
        }
      };
    }
    if ($('assignmentLoadMoreTasksBtn')) {
      $('assignmentLoadMoreTasksBtn').onclick = async () => {
        try {
          await withButtonLock('assignmentLoadMoreTasksBtn', async () => {
            await loadMoreAssignmentTasks();
          });
        } catch (err) {
          setAssignmentError(err.message || String(err));
        }
      };
    }
    if ($('assignmentPauseBtn')) {
      $('assignmentPauseBtn').onclick = async () => {
        try {
          await withButtonLock('assignmentPauseBtn', pauseAssignmentSchedulerAction);
        } catch (err) {
          setAssignmentError(err.message || String(err));
        }
      };
    }
    if ($('assignmentResumeBtn')) {
      $('assignmentResumeBtn').onclick = async () => {
        try {
          await withButtonLock('assignmentResumeBtn', resumeAssignmentSchedulerAction);
        } catch (err) {
          setAssignmentError(err.message || String(err));
        }
      };
    }
    if ($('assignmentClearBtn')) {
      $('assignmentClearBtn').onclick = async () => {
        try {
          await withButtonLock('assignmentClearBtn', clearAssignmentGraphAction);
        } catch (err) {
          setAssignmentError(err.message || String(err));
        }
      };
    }
    if ($('assignmentDrawerCloseBtn')) {
      $('assignmentDrawerCloseBtn').onclick = () => setAssignmentCreateOpen(false);
    }
    if ($('assignmentDrawerCancelBtn')) {
      $('assignmentDrawerCancelBtn').onclick = () => setAssignmentCreateOpen(false);
    }
    if ($('assignmentDrawerSubmitBtn')) {
      $('assignmentDrawerSubmitBtn').onclick = async () => {
        try {
          await withButtonLock('assignmentDrawerSubmitBtn', submitAssignmentCreate);
        } catch (err) {
          setAssignmentDrawerError(err.message || String(err));
        }
      };
    }
    if ($('assignmentClearUpstreamSearchBtn')) {
      $('assignmentClearUpstreamSearchBtn').onclick = () => {
        state.assignmentCreateUpstreamSearch = '';
        if ($('assignmentUpstreamSearch')) $('assignmentUpstreamSearch').value = '';
        persistAssignmentCreateDraft();
        renderAssignmentDrawer();
      };
    }
    if ($('assignmentUpstreamSearch')) {
      $('assignmentUpstreamSearch').addEventListener('input', () => {
        state.assignmentCreateUpstreamSearch = safe($('assignmentUpstreamSearch').value).trim();
        persistAssignmentCreateDraft();
        renderAssignmentUpstreamResults();
      });
    }
    if ($('assignmentTaskNameInput')) {
      $('assignmentTaskNameInput').addEventListener('input', () => {
        state.assignmentCreateForm.node_name = safe($('assignmentTaskNameInput').value);
        persistAssignmentCreateDraft();
        renderAssignmentPathPreview();
      });
    }
    if ($('assignmentGoalInput')) {
      $('assignmentGoalInput').addEventListener('input', () => {
        state.assignmentCreateForm.node_goal = safe($('assignmentGoalInput').value);
        persistAssignmentCreateDraft();
      });
    }
    if ($('assignmentArtifactInput')) {
      $('assignmentArtifactInput').addEventListener('input', () => {
        state.assignmentCreateForm.expected_artifact = safe($('assignmentArtifactInput').value);
        persistAssignmentCreateDraft();
        renderAssignmentPathPreview();
      });
    }
    if ($('assignmentAgentSelect')) {
      $('assignmentAgentSelect').addEventListener('change', () => {
        state.assignmentCreateForm.assigned_agent_id = safe($('assignmentAgentSelect').value).trim();
        persistAssignmentCreateDraft();
        renderAssignmentPathPreview();
      });
    }
    if ($('assignmentPrioritySelect')) {
      $('assignmentPrioritySelect').addEventListener('change', () => {
        state.assignmentCreateForm.priority = assignmentPriorityLabel($('assignmentPrioritySelect').value);
        persistAssignmentCreateDraft();
      });
    }
    if ($('assignmentDeliveryModeSelect')) {
      $('assignmentDeliveryModeSelect').addEventListener('change', () => {
        state.assignmentCreateForm.delivery_mode = safe($('assignmentDeliveryModeSelect').value).trim() || 'none';
        if (safe(state.assignmentCreateForm.delivery_mode).trim().toLowerCase() !== 'specified') {
          state.assignmentCreateForm.delivery_receiver_agent_id = '';
        }
        persistAssignmentCreateDraft();
        renderAssignmentPathPreview();
      });
    }
    if ($('assignmentDeliveryReceiverSelect')) {
      $('assignmentDeliveryReceiverSelect').addEventListener('change', () => {
        state.assignmentCreateForm.delivery_receiver_agent_id = safe($('assignmentDeliveryReceiverSelect').value).trim();
        persistAssignmentCreateDraft();
        renderAssignmentPathPreview();
      });
    }
  }
