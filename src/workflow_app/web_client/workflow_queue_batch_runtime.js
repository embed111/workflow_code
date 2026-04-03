    const box = $('planBox');
    box.innerHTML = '';
    const items = state.workflowPlans[workflowId] || [];
    for (const item of items) {
      const row = document.createElement('div');
      row.className = 'plan-item';
      row.innerHTML =
        "<input type='checkbox' class='plan-check' data-item-id='" +
        safe(item.item_id) +
        "'" +
        (item.selected ? ' checked' : '') +
        '/>' +
        "<label><div class='title'>" +
        safe(item.title) +
        "</div><div class='hint'>" +
        safe(item.description) +
        '</div></label>';
      box.appendChild(row);
    }
    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'hint';
      empty.textContent = '请先生成训练任务';
      box.appendChild(empty);
    }
  }

  async function loadWorkflowPlan(workflowId) {
    if (!workflowId) return;
    const data = await getJSON(
      '/api/workflows/training/' + encodeURIComponent(workflowId) + '/plan',
    );
    state.workflowPlans[workflowId] = Array.isArray(data.plan) ? data.plan : [];
    renderWorkflowPlan(workflowId);
  }

  function renderWorkflowEvents(workflowId) {
    const box = $('workflowEvents');
    box.innerHTML = '';
    const wid = safe(workflowId);
    const rows = state.workflowEvents[wid] || [];
    if (!rows.length) {
      const empty = document.createElement('div');
      empty.className = 'hint';
      empty.textContent = '暂无过程事件';
      box.appendChild(empty);
      return;
    }
    const latest = rows[rows.length - 1] || {};
    const latestInfo = eventToneInfo(latest.status);
    const summary = document.createElement('div');
    summary.className = 'event-summary-card ' + safe(latestInfo.className);
    const currentStage = stageText(latest.stage, latest.payload || {});
    const latestEvent = currentStage + ' · ' + statusText(latest.status);
    const summaryTop = document.createElement('div');
    summaryTop.className = 'event-summary-top';
    const chip = document.createElement('span');
    chip.className = 'event-status-chip ' + safe(latestInfo.className);
    appendIconLabel(chip, latestInfo.label, latestInfo.icon, {
      spinning: !!latestInfo.spinning,
      labelClassName: 'event-chip-label',
    });
    const updated = document.createElement('span');
    updated.className = 'hint';
    updated.textContent = '最近更新时间 ' + safe(formatDateTime(latest.created_at));
    summaryTop.appendChild(chip);
    summaryTop.appendChild(updated);
    summary.appendChild(summaryTop);

    const grid = document.createElement('div');
    grid.className = 'event-summary-grid';
    const cells = [
      { k: '当前阶段', v: currentStage },
      { k: '最近关键事件', v: latestEvent },
      { k: '当前结果', v: latestInfo.label },
    ];
    for (const cell of cells) {
      const cellNode = document.createElement('div');
      const keyNode = document.createElement('div');
      keyNode.className = 'k';
      keyNode.textContent = safe(cell.k);
      const valNode = document.createElement('div');
      valNode.className = 'v';
      valNode.textContent = safe(cell.v);
      cellNode.appendChild(keyNode);
      cellNode.appendChild(valNode);
      grid.appendChild(cellNode);
    }
    summary.appendChild(grid);
    box.appendChild(summary);

    const guide = document.createElement('div');
    guide.className = 'event-help-panel';
    const guideTitle = document.createElement('div');
    guideTitle.className = 'event-help-title';
    guideTitle.textContent = '阶段说明与状态图例';
    guide.appendChild(guideTitle);
    const guideText = document.createElement('div');
    guideText.className = 'event-help-text';
    guideText.textContent =
      '当前阶段=' +
      currentStage +
      '。' +
      nextStepHint(latest.stage, latest.status);
    guide.appendChild(guideText);
    const legendRow = document.createElement('div');
    legendRow.className = 'event-legend-row';
    const legendItems = [
      { label: '成功', icon: 'success', tone: 'tone-success' },
      { label: '进行中', icon: 'running', tone: 'tone-running', spinning: true },
      { label: '失败', icon: 'failed', tone: 'tone-failed' },
    ];
    for (const info of legendItems) {
      const chip = document.createElement('span');
      chip.className = 'event-legend-chip ' + safe(info.tone);
      appendIconLabel(chip, info.label, info.icon, {
        spinning: !!info.spinning,
        labelClassName: 'event-chip-label',
      });
      legendRow.appendChild(chip);
    }
    guide.appendChild(legendRow);
    box.appendChild(guide);

    const detail = document.createElement('details');
    detail.className = 'event-detail';
    detail.open = !!state.workflowEventDetailOpen[wid];
    detail.addEventListener('toggle', () => {
      state.workflowEventDetailOpen[wid] = detail.open;
    });
    const detailSummary = document.createElement('summary');
    detailSummary.textContent = '展开时间线详情（' + safe(rows.length) + ' 条）';
    detail.appendChild(detailSummary);
    const timeline = document.createElement('div');
    timeline.className = 'event-timeline';
    for (const row of rows) {
      const info = eventToneInfo(row.status);
      const item = document.createElement('div');
      item.className = 'event-item ' + safe(info.className);

      const head = document.createElement('div');
      head.className = 'event-item-head';
      const icon = document.createElement('span');
      icon.className = 'event-icon';
      icon.appendChild(createStatusIcon(info.icon, { spinning: !!info.spinning }));
      const title = document.createElement('span');
      title.className = 'event-title';
      title.textContent = safe(stageText(row.stage, row.payload || {}));
      const time = document.createElement('span');
      time.className = 'event-time';
      time.textContent = safe(formatDateTime(row.created_at));
      head.appendChild(icon);
      head.appendChild(title);
      head.appendChild(time);
      item.appendChild(head);

      const sub = document.createElement('div');
      sub.className = 'event-item-sub';
      sub.textContent = safe(statusText(row.status));
      item.appendChild(sub);

      const debug = document.createElement('details');
      debug.className = 'event-debug';
      const debugKey = workflowEventDebugKey(wid, row.event_id);
      debug.open = !!state.workflowEventDebugOpen[debugKey];
      debug.addEventListener('toggle', () => {
        state.workflowEventDebugOpen[debugKey] = debug.open;
      });
      const debugSummary = document.createElement('summary');
      debugSummary.textContent = '调试数据（原始 payload）';
      const pre = document.createElement('pre');
      pre.className = 'trace-pre';
      pre.textContent = formatJsonLines(row.payload || {});
      debug.appendChild(debugSummary);
      debug.appendChild(pre);
      item.appendChild(debug);

      timeline.appendChild(item);
    }
    detail.appendChild(timeline);
    box.appendChild(detail);
  }

  async function refreshWorkflowEvents(workflowId) {
    if (!workflowId) return;
    const data = await getJSON(
      '/api/workflows/training/' + encodeURIComponent(workflowId) + '/events?since_id=0',
    );
    state.workflowEvents[workflowId] = Array.isArray(data.events) ? data.events : [];
    renderWorkflowEvents(workflowId);
  }

  function startWorkflowPoller() {
    if (state.workflowPoller) return;
    state.workflowPoller = window.setInterval(() => {
      if (!state.selectedWorkflowId || state.workflowPollBusy) return;
      state.workflowPollBusy = true;
      refreshWorkflows()
        .then(() => {
          if (!state.selectedWorkflowId) return null;
          return refreshWorkflowEvents(state.selectedWorkflowId);
        })
        .catch(() => {})
        .finally(() => {
          state.workflowPollBusy = false;
        });
    }, 1200);
  }

  async function assignAnalyst() {
    if (!state.selectedWorkflowId) throw new Error('请先选择工作记录');
    const analyst = selectedAnalyst();
    if (!analyst) throw new Error('分析师名称不能为空');
    $('analystInput').value = analyst;
    $('batchAnalystInput').value = analyst;
    const data = await postJSON('/api/workflows/training/assign', {
      workflow_id: state.selectedWorkflowId,
      analyst: analyst,
    });
    setWorkflowResult(data);
    await refreshWorkflows();
    await refreshWorkflowEvents(state.selectedWorkflowId);
    setStatus('已指派分析师: ' + analyst);
  }

  async function generateWorkflowPlan() {
    if (!state.selectedWorkflowId) throw new Error('请先选择工作记录');
    const workflowId = state.selectedWorkflowId;
    const data = await postJSON('/api/workflows/training/plan', {
      workflow_id: workflowId,
    });
    state.workflowPlans[workflowId] = Array.isArray(data.plan) ? data.plan : [];
    renderWorkflowPlan(workflowId);
    setWorkflowResult(data);
    await refreshWorkflows();
    setWorkflowQueueMode('training');
    if (workflowById(workflowId)) {
      await selectWorkflow(workflowId);
    } else {
      const first = visibleWorkflows()[0];
      if (first) {
        await selectWorkflow(safe(first.workflow_id));
      } else {
        renderWorkflowEvents('');
      }
    }
    setStatus('训练任务已生成');
  }

  async function executeWorkflowPlan() {
    if (!state.selectedWorkflowId) throw new Error('请先选择训练任务');
    const selectedItems = [];
    document.querySelectorAll('.plan-check').forEach((node) => {
      if (node.checked) {
        selectedItems.push(node.getAttribute('data-item-id'));
      }
    });
    const data = await postJSON('/api/workflows/training/execute', {
      workflow_id: state.selectedWorkflowId,
      selected_items: selectedItems,
      max_retries: 3,
    });
    setWorkflowResult(data);
    await refreshWorkflows();
    await refreshWorkflowEvents(state.selectedWorkflowId);
    setStatus('训练任务执行完成');
  }

  function ensureBatchRecordIds(idsOverride) {
    const ids = Array.isArray(idsOverride) ? idsOverride.map((v) => safe(v)).filter(Boolean) : selectedRecordWorkflowIds();
    if (!ids.length) {
      throw new Error('请先勾选至少一条工作记录');
    }
    const valid = new Set(
      visibleWorkflows()
        .filter((row) => isWorkflowAnalysisSelectable(row))
        .map((row) => safe(row.workflow_id)),
    );
    const filtered = ids.filter((id) => valid.has(id));
    if (!filtered.length) {
      throw new Error('所选条目不可进入分析（可能已全部分析完成），请先刷新');
    }
    return filtered;
  }

  function confirmBatchAction(label, ids, extraLines) {
    const lines = [
      '即将执行批量操作：' + label,
      '影响条目数：' + ids.length,
      '此操作会按顺序逐条执行并保留成功/失败明细。',
    ];
    for (const item of extraLines || []) {
      if (!safe(item)) continue;
      lines.push(safe(item));
    }
    return window.confirm(lines.join('\n'));
  }

  function startBatchRun(action, ids) {
    state.batchRun = {
      running: true,
      action: action,
      total: ids.length,
      done: 0,
      success: 0,
      failed: 0,
      skipped: 0,
      results: [],
      started_at: new Date().toISOString(),
      finished_at: '',
    };
    updateBatchActionState();
  }

  function finishBatchRun() {
    state.batchRun.running = false;
    state.batchRun.finished_at = new Date().toISOString();
    state.lastBatchReport = {
      ...state.batchRun,
    };
    state.lastFailedWorkflowIds = state.batchRun.results
      .filter((row) => safe(row.status) === 'failed')
      .map((row) => safe(row.workflow_id))
      .filter(Boolean);
    updateBatchActionState();
  }

  async function runBatchOperation(action, ids, worker, options) {
    if (state.batchRun.running) {
      throw new Error('已有批量任务在执行，请稍后');
    }
    const runIds = ensureBatchRecordIds(ids);
    const concurrency = Math.max(1, Math.min(3, Number((options || {}).concurrency || 2)));
    startBatchRun(action, runIds);
    let cursor = 0;

    async function runWorker() {
      while (true) {
        if (cursor >= runIds.length) break;
        const idx = cursor;
        cursor += 1;
        const workflowId = runIds[idx];
        let result;
        try {
          const data = await worker(workflowId, idx);
          result = {
            workflow_id: workflowId,
            status: safe((data || {}).status || 'success'),
            data: data || {},
          };
        } catch (err) {
          result = {
            workflow_id: workflowId,
            status: 'failed',
            error: err.message || String(err),
          };
        }
        state.batchRun.results.push(result);
        state.batchRun.done += 1;
        if (result.status === 'success') {
          state.batchRun.success += 1;
        } else if (result.status === 'skipped') {
          state.batchRun.skipped += 1;
        } else {
          state.batchRun.failed += 1;
        }
        $('batchProgressMeta').textContent = batchProgressText();
      }
    }

    const workers = [];
    for (let i = 0; i < concurrency; i += 1) {
      workers.push(runWorker());
    }
    await Promise.all(workers);
    finishBatchRun();

    const report = state.lastBatchReport || {};
    setWorkflowResult(report);
    setStatus(
      '批量' +
        action +
        '完成: 成功=' +
        safe(report.success || 0) +
        '，失败=' +
        safe(report.failed || 0) +
        '，跳过=' +
        safe(report.skipped || 0),
    );
    return report;
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, Math.max(0, Number(ms) || 0)));
  }

  async function waitWorkflowAnalysisDone(workflowId, timeoutMs) {
    const deadline = Date.now() + Math.max(2000, Number(timeoutMs) || 20000);
    const doneStates = new Set(['analyzed', 'planned', 'selected', 'training', 'done', 'failed']);
    while (Date.now() <= deadline) {
      const data = await getJSON('/api/workflows/training/queue');
      const rows = Array.isArray(data.items) ? data.items : [];
      const row = rows.find((item) => safe(item.workflow_id) === workflowId);
      if (row) {
        const status = safe(row.workflow_status).toLowerCase();
        if (doneStates.has(status)) return row;
      }
      await sleep(450);
    }
    throw new Error('analysis_timeout');
  }

  function selectAllWorkflows() {
    for (const row of visibleWorkflows()) {
      if (!isWorkflowAnalysisSelectable(row)) continue;
      const id = safe(row.workflow_id);
      if (!id) continue;
      state.selectedWorkflowIds[id] = true;
    }
    renderWorkflowQueue();
  }

  function clearWorkflowSelection() {
    state.selectedWorkflowIds = {};
    renderWorkflowQueue();
  }

  function toggleWorkflowSelectionState() {
    if (state.queueMode !== 'records') return;
    const selectableTotal = visibleWorkflows().filter((row) => isWorkflowAnalysisSelectable(row)).length;
    if (!selectableTotal) return;
    const selected = selectedRecordWorkflowIds().length;
    if (selected >= selectableTotal) {
      clearWorkflowSelection();
      return;
    }
    selectAllWorkflows();
  }

  async function batchAnalyzeRecords(idsOverride) {
    let analyst = selectedAnalyst();
    if (!analyst) throw new Error('请先填写分析师名称');
    $('batchAnalystInput').value = analyst;
    $('analystInput').value = analyst;
    const ids = ensureBatchRecordIds(idsOverride);
    if (
      !confirmBatchAction('顺序分析并生成训练任务', ids, [
        '分析师：' + analyst,
        '执行策略：按勾选顺序串行处理',
      ])
    ) {
      return;
    }
    await runBatchOperation(
      '分析并生成训练任务',
      ids,
      async (workflowId, idx) => {
        await postJSON('/api/workflows/training/assign', {
          workflow_id: workflowId,
          analyst: analyst,
        });
        await waitWorkflowAnalysisDone(workflowId, 30000);
        const planData = await postJSON('/api/workflows/training/plan', {
          workflow_id: workflowId,
        });
        state.workflowPlans[workflowId] = Array.isArray(planData.plan) ? planData.plan : [];
        return {
          status: 'success',
          order: idx + 1,
          plan_count: state.workflowPlans[workflowId].length,
        };
      },
      { concurrency: 1 },
    );
    await refreshWorkflows();
    setWorkflowQueueMode('training');
    if (state.selectedWorkflowId) {
      await refreshWorkflowEvents(state.selectedWorkflowId);
    } else {
      const first = visibleWorkflows()[0];
      if (first) {
        await selectWorkflow(safe(first.workflow_id));
      }
    }
    setStatus('已完成顺序分析并生成训练任务');
  }

  async function batchDeleteRecords(idsOverride) {
    const ids = ensureBatchRecordIds(idsOverride);
    const idToSession = {};
    for (const id of ids) {
      const row = workflowById(id);
      idToSession[id] = safe(row && row.session_id).trim();
    }
    if (
      !confirmBatchAction('删除工作记录', ids, [
        '删除范围：对应会话的工作记录、分析/训练关联、任务日志',
        '注意：该操作不可撤销',
      ])
    ) {
      return;
    }
    await runBatchOperation(
      '删除记录',
      ids,
      async (workflowId) => {
        const sessionId = safe(idToSession[workflowId]).trim();
        if (!sessionId) {
          return { status: 'failed', reason: 'session_missing' };
        }
        await postJSON('/api/chat/sessions/' + encodeURIComponent(sessionId) + '/delete', {
          delete_artifacts: true,
        });
        return { status: 'success', session_id: sessionId };
      },
      { concurrency: 1 },
    );
    state.selectedWorkflowId = '';
    state.selectedWorkflowIds = {};
    await refreshSessions();
    await refreshWorkflows();
    await refreshDashboard();
    setStatus('批量删除工作记录完成');
  }

  async function deleteCurrentSession() {
    const session = currentSession();
    if (!session) throw new Error('当前没有可删除会话');
    const sessionId = safe(session.session_id);
    if (state.runningTasks[sessionId]) {
      throw new Error('当前会话有运行中的任务，不能删除');
    }
    const ok = window.confirm(
      '将删除当前会话全部记录（消息、事件、任务、训练关联）。此操作不可撤销，是否继续？',
    );
    if (!ok) return;
    const data = await postJSON(
      '/api/chat/sessions/' + encodeURIComponent(sessionId) + '/delete',
      { delete_artifacts: true },
    );
    delete state.runningTasks[sessionId];
    delete state.sessionTaskRuns[sessionId];
    delete state.sessionsById[sessionId];
    state.sessionOrder = state.sessionOrder.filter((sid) => sid !== sessionId);
    if (state.selectedSessionId === sessionId) {
      state.selectedSessionId = state.sessionOrder.length ? state.sessionOrder[0] : '';
    }
    renderSessionList();
    if (state.selectedSessionId) {
      await loadSessionMessages(state.selectedSessionId);
    } else {
      renderFeed();
    }
    await refreshWorkflows();
    await refreshDashboard();
    setStatus('会话已删除: ' + sessionId);
    setWorkflowResult(data);
  }

  async function deleteSelectedWorkflow() {
    if (!state.selectedWorkflowId) throw new Error('请先选择记录或训练任务');
    const workflowId = state.selectedWorkflowId;
    const row = workflowById(workflowId);
    if (!row) throw new Error('所选条目已不存在，请先刷新');
    if (state.queueMode === 'records') {
      const sessionId = safe(row.session_id).trim();
      if (!sessionId) throw new Error('当前工作记录缺少 session_id，无法删除');
      const ok = window.confirm(
        '将删除该工作记录对应会话的全部记录（消息、事件、分析/训练关联、任务日志）。此操作不可撤销，是否继续？',
      );
      if (!ok) return;
      const data = await postJSON(
        '/api/chat/sessions/' + encodeURIComponent(sessionId) + '/delete',
        { delete_artifacts: true },
      );
      state.selectedWorkflowId = '';
      state.selectedWorkflowIds = {};
      await refreshSessions();
      await refreshWorkflows();
      renderWorkflowPlan('');
      renderWorkflowEvents('');
      await refreshDashboard();
      setStatus('工作记录已删除: ' + sessionId);
      setWorkflowResult(data);
      return;
    }
    const ok = window.confirm(
      '将删除该训练任务并重置对应分析为待处理状态。此操作不可撤销，是否继续？',
    );
    if (!ok) return;
    const data = await postJSON(
      '/api/workflows/training/' + encodeURIComponent(workflowId) + '/delete',
      { delete_artifacts: true },
    );
    state.selectedWorkflowId = '';
    delete state.workflowPlans[workflowId];
    delete state.workflowEvents[workflowId];
    delete state.workflowEventDetailOpen[workflowId];
    for (const key of Object.keys(state.workflowEventDebugOpen)) {
      if (key.startsWith(workflowId + ':')) {
        delete state.workflowEventDebugOpen[key];
      }
    }
    await refreshWorkflows();
    renderWorkflowPlan('');
    renderWorkflowEvents('');
    await refreshDashboard();
    setStatus('训练任务已删除: ' + workflowId);
    setWorkflowResult(data);
  }

  async function cleanupHistory() {
    const mode = safe($('cleanupMode').value).trim() || 'closed_sessions';
    const deleteArtifacts = !!$('cleanupArtifacts').checked;
    const deleteLogs = !!$('cleanupLogs').checked;
    let maxAgeHours = Number($('cleanupTestDataHours').value || 168);
    if (!Number.isFinite(maxAgeHours) || maxAgeHours < 1) {
      maxAgeHours = 168;
    }
    const modeText =
      mode === 'all'
        ? '清空全部历史记录'
        : mode === 'test_data'
          ? '仅清理测试数据（保留最近 ' + Math.floor(maxAgeHours) + ' 小时）'
          : '仅清理已关闭会话';
    const ok = window.confirm(
      '即将执行[' +
        modeText +
        ']。\n这会删除数据库记录' +
        (deleteArtifacts ? '及关联产物文件' : '') +
        (deleteLogs ? '，并清空运行日志目录' : '') +
        '。\n确认继续？',
    );
    if (!ok) return;
    const data = await postJSON('/api/admin/history/cleanup', {
      mode: mode,
      delete_artifacts: deleteArtifacts,
      delete_log_files: deleteLogs,
      max_age_hours: Math.floor(maxAgeHours),
    });
    clearFrontendSessions();
    clearWorkflowPanel();
    await refreshAgents(true);
    await refreshSessions();
    await refreshWorkflows();
    await refreshDashboard();
    setStatus('历史清理完成: ' + modeText);
    setWorkflowResult(data);
  }

  function clearFrontendSessions() {
    state.sessionsById = {};
    state.sessionOrder = [];
    state.selectedSessionId = '';
    state.runningTasks = {};
    state.sessionTaskRuns = {};
    state.taskTraceCache = {};
    state.taskTraceExpanded = {};
    state.taskTraceDetailsOpen = {};
    state.agentPolicyAnalysisByName = {};
    state.agentPolicyAnalysisInitialized = false;
    state.sessionPolicyGateState = 'idle_unselected';
    state.sessionPolicyGateReason = '请先选择角色';
    state.sessionPolicyCacheLine = '';
    state.feedRenderedSessionId = '';
    resetPolicyAnalyzeProgress();
    if (state.poller) {
      clearInterval(state.poller);
      state.poller = 0;
    }
    localStorage.removeItem(sessionCacheKey);
    renderSessionList();
    renderFeed();
    applyGateState();
  }

  function clearWorkflowPanel() {
    state.workflows = [];
    state.queueMode = 'records';
    state.selectedWorkflowId = '';
    state.workflowPlans = {};
    state.workflowEvents = {};
    state.workflowEventDetailOpen = {};
    state.workflowEventDebugOpen = {};
    state.workflowPollBusy = false;
    state.selectedWorkflowIds = {};
    state.batchRun = {
      running: false,
      action: '',
      total: 0,
      done: 0,
      success: 0,
      failed: 0,
      skipped: 0,
      results: [],
      started_at: '',
      finished_at: '',
    };
    state.lastBatchReport = null;
    state.lastFailedWorkflowIds = [];
    refreshAnalystOptions('');
    updateQueueModeUI();
    renderWorkflowQueue();
    renderWorkflowMeta();
    renderWorkflowPlan('');
    renderWorkflowEvents('');
  }

  function injectLayoutProbeStressContent() {
    const longHash = 'a'.repeat(220);
    const longPath = 'C:/work/agents/' + 'very-long-segment-'.repeat(18) + 'AGENTS.md';
    const longToken = 'LONG_TOKEN_'.repeat(90);
    const cards = Array.from(document.querySelectorAll('#agentMeta .agent-policy-card-body'));
    if (cards[0]) cards[0].textContent = '角色\n' + longToken + '\n' + longHash;
    if (cards[1]) cards[1].textContent = '职责\n' + longPath + '\n' + longToken;
    if (cards[2]) cards[2].textContent = '目标\n' + longToken + '\n' + longPath + '\n' + longHash;
    const meta = document.querySelector('#agentMeta .agent-meta-line');
    if (meta) meta.textContent = '哈希=' + longHash + ' 路径=' + longPath;
    Array.from(document.querySelectorAll('#agentMeta .agent-policy-pre')).forEach((node, idx) => {
      node.textContent = '证据' + String(idx + 1) + '\n' + longPath + '\n' + longHash + '\n' + longToken;
    });
    Array.from(document.querySelectorAll('#agentMeta .agent-clarity-v')).forEach((node, idx) => {
      node.textContent = '解释' + String(idx + 1) + ': ' + longPath + ' ' + longHash + ' ' + longToken;
    });
    const host = $('agentMeta');
    if (host) host.scrollLeft = 0;
  }

  async function runLayoutProbe() {
    const output = {
      ts: new Date().toISOString(),
      tab: layoutProbeTab(),
      error: '',
      pass: false,
      innerWidth: 0,
      scrollWidth: 0,
      bodyScrollWidth: 0,
    };
    try {
      const shouldExpandMeta = queryParam('layout_probe_expand') === '1';
      if (!selectedAgent()) {
        const first = (state.agents || []).find((item) => safe(item.agent_name).trim());
        if (first) {
          $('agentSelect').value = safe(first.agent_name);
          state.agentMetaPanelOpen = false;
          state.agentMetaDetailsOpen = false;
          state.agentMetaClarityOpen = false;
          startPolicyAnalysisForSelection();
        }
      }
      if (queryParam('layout_probe_stress') === '1') {
        injectLayoutProbeStressContent();
      }
      const targetTab = layoutProbeTab();
      switchTab(targetTab);
      if (targetTab === 'training') {
        if (!state.selectedWorkflowId) {
          const first = visibleWorkflows()[0];
          if (first) {
            await selectWorkflow(safe(first.workflow_id));
          }
        } else {
          await refreshWorkflowEvents(state.selectedWorkflowId);
        }
      }
      if (targetTab === 'training-center') {
        await refreshTrainingCenterAgents();
        await refreshTrainingCenterQueue();
      }
      await new Promise((resolve) => window.setTimeout(resolve, 140));
      if (shouldExpandMeta) {
        const summary = document.querySelector('#agentMeta details > summary');
        if (summary instanceof HTMLElement) {
          summary.click();
          await new Promise((resolve) => window.setTimeout(resolve, 120));
          const host = $('agentMeta');
          if (host) {
            host.scrollTop = host.scrollHeight;
            host.scrollLeft = 0;
          }
        }
      }
      const root = document.documentElement;
      const body = document.body;
      output.innerWidth = Number(window.innerWidth || 0);
      output.scrollWidth = Number((root && root.scrollWidth) || 0);
      output.bodyScrollWidth = Number((body && body.scrollWidth) || 0);
      output.pass = output.scrollWidth <= output.innerWidth;
    } catch (err) {
      output.error = safe(err && err.message ? err.message : err);
    }
    let probeNode = $('layoutProbeOutput');
    if (!probeNode) {
      probeNode = document.createElement('pre');
      probeNode.id = 'layoutProbeOutput';
      probeNode.style.display = 'none';
      document.body.appendChild(probeNode);
    }
    probeNode.textContent = JSON.stringify(output);
    probeNode.setAttribute('data-pass', output.pass ? '1' : '0');
  }
