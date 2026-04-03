    const session = currentSession();
    if (!session) return;
    const running = state.runningTasks[safe(session.session_id)];
    if (!running || !running.task_id) return;
    await postJSON('/api/tasks/' + encodeURIComponent(running.task_id) + '/interrupt', {});
    setStatus('已请求中断: ' + safe(running.task_id));
  }

  function selectedWorkflowIds() {
    return Object.keys(state.selectedWorkflowIds).filter((id) => !!state.selectedWorkflowIds[id]);
  }

  function workflowPlanCount(row) {
    const plan = row && Array.isArray(row.plan) ? row.plan : [];
    return plan.length;
  }

  function isTrainingQueueItem(row) {
    const status = safe(row && row.workflow_status).toLowerCase();
    if (['planned', 'selected', 'training', 'done'].includes(status)) return true;
    if (workflowPlanCount(row) > 0) return true;
    const trainingId = safe(row && row.training_id);
    const trainingStatus = safe(row && row.training_status).toLowerCase();
    return !!trainingId || ['running', 'done', 'pending', 'failed'].includes(trainingStatus);
  }

  function isRecordQueueItem(row) {
    if (!row) return false;
    const count = Number(row.work_record_count || 0);
    if (count <= 0) return false;
    return !isTrainingQueueItem(row);
  }

  function visibleWorkflows() {
    const rows = Array.isArray(state.workflows) ? state.workflows : [];
    if (state.queueMode === 'training') {
      return rows.filter((row) => isTrainingQueueItem(row));
    }
    return rows.filter((row) => isRecordQueueItem(row));
  }

  function updateQueueModeUI() {
    const isTraining = state.queueMode === 'training';
    $('queueModeRecordsBtn').classList.toggle('active', !isTraining);
    $('queueModeTrainingBtn').classList.toggle('active', isTraining);
    $('workflowQueueTitle').textContent = isTraining ? '训练任务队列' : '工作记录';
    $('batchAnalyzeBtn').style.display = isTraining ? 'none' : '';
    $('batchAnalystInput').style.display = isTraining ? 'none' : '';
  }

  function setWorkflowQueueMode(mode) {
    const next = safe(mode).toLowerCase() === 'training' ? 'training' : 'records';
    state.queueMode = next;
    if (next !== 'records') {
      state.selectedWorkflowIds = {};
    }
    updateQueueModeUI();
    renderWorkflowQueue();
    renderWorkflowMeta();
  }

  function selectedRecordWorkflowIds() {
    const selected = new Set(selectedWorkflowIds());
    return visibleWorkflows()
      .filter((row) => isWorkflowAnalysisSelectable(row))
      .map((row) => safe(row.workflow_id))
      .filter((id) => selected.has(id));
  }

  function workflowById(workflowId) {
    const id = safe(workflowId);
    return (state.workflows || []).find((row) => safe(row.workflow_id) === id) || null;
  }

  function normalizeWorkflowSelection() {
    const valid = new Set((state.workflows || []).map((row) => safe(row.workflow_id)));
    for (const id of Object.keys(state.selectedWorkflowIds)) {
      if (!valid.has(id)) {
        delete state.selectedWorkflowIds[id];
      }
    }
    if (state.queueMode !== 'records') {
      state.selectedWorkflowIds = {};
    } else {
      const recordValid = new Set(
        visibleWorkflows()
          .filter((row) => isWorkflowAnalysisSelectable(row))
          .map((row) => safe(row.workflow_id)),
      );
      for (const id of Object.keys(state.selectedWorkflowIds)) {
        if (!recordValid.has(id)) {
          delete state.selectedWorkflowIds[id];
        }
      }
    }
  }

  function updateBatchActionState() {
    const rootReady = !!state.agentSearchRootReady;
    const selected = selectedRecordWorkflowIds().length;
    const selectableTotal = visibleWorkflows().filter((row) => isWorkflowAnalysisSelectable(row)).length;
    const recordsMode = state.queueMode === 'records';
    const running = !!(state.batchRun && state.batchRun.running);
    const hasCurrentWorkflow = !!state.selectedWorkflowId;
    const hasAnalyst = !!selectedAnalyst();
    const currentRow = hasCurrentWorkflow ? workflowById(state.selectedWorkflowId) : null;
    const currentSelectable = !!(currentRow && isWorkflowAnalysisSelectable(currentRow));
    $('workflowSelectionToggleCheck').disabled = !rootReady || running || !recordsMode || selectableTotal === 0;
    $('batchAnalyzeBtn').disabled = !rootReady || running || !recordsMode || selected === 0 || !hasAnalyst;
    $('batchDeleteRecordsBtn').disabled = !rootReady || running || !recordsMode || selected === 0;
    $('assignBtn').disabled = !rootReady || running || !hasCurrentWorkflow || !recordsMode || !hasAnalyst || !currentSelectable;
    $('generatePlanBtn').disabled = !rootReady || running || !hasCurrentWorkflow || !recordsMode;
    $('executePlanBtn').disabled = !rootReady || running || !hasCurrentWorkflow || recordsMode;
    $('deleteWorkflowBtn').disabled = !rootReady || running || !hasCurrentWorkflow;
    $('batchAnalystInput').disabled = !rootReady || running;
    $('analystInput').disabled = !rootReady || running;
    $('batchProgressMeta').textContent = rootReady ? batchProgressText() : '功能已锁定，等待设置 agent路径';
  }

  function workflowSelectionState(total, selected) {
    if (total <= 0 || selected <= 0) return 'none';
    if (selected >= total) return 'all';
    return 'partial';
  }

  function renderWorkflowSelectionMeta() {
    const list = visibleWorkflows();
    const total = list.length;
    const selectableTotal = list.filter((row) => isWorkflowAnalysisSelectable(row)).length;
    const selected = selectedRecordWorkflowIds().length;
    const doneCount = list.filter((row) => safe(row.workflow_status).toLowerCase() === 'done').length;
    const mode = workflowSelectionState(selectableTotal, selected);
    const toggle = $('workflowSelectionToggleCheck');
    const recordsMode = state.queueMode === 'records';
    if (toggle) {
      if (!recordsMode) {
        toggle.checked = false;
        toggle.indeterminate = false;
        toggle.style.visibility = 'hidden';
      } else {
        toggle.style.visibility = 'visible';
        if (mode === 'all') {
          toggle.checked = true;
          toggle.indeterminate = false;
          toggle.title = '全部已选（取消勾选可清空）';
        } else if (mode === 'partial') {
          toggle.checked = false;
          toggle.indeterminate = true;
          toggle.title = '部分已选（勾选可全选）';
        } else {
          toggle.checked = false;
          toggle.indeterminate = false;
          toggle.title = '未选中（勾选可全选）';
        }
        toggle.setAttribute('aria-label', toggle.title);
      }
    }
    if (recordsMode) {
      const blocked = Math.max(0, total - selectableTotal);
      $('workflowSelectionMeta').textContent =
        '已选 ' + selected + '/' + selectableTotal + ' · 可勾选 ' + selectableTotal + ' · 禁用 ' + blocked;
    } else {
      $('workflowSelectionMeta').textContent = '训练任务 ' + total + ' · 已完成 ' + doneCount;
    }
    updateBatchActionState();
  }

  function renderWorkflowQueue() {
    const box = $('workflowList');
    box.innerHTML = '';
    const list = visibleWorkflows();
    const listIds = new Set(list.map((row) => safe(row.workflow_id)));
    if (state.selectedWorkflowId && !listIds.has(state.selectedWorkflowId)) {
      state.selectedWorkflowId = '';
    }
    const recordsMode = state.queueMode === 'records';
    for (const row of list) {
      const workflowId = safe(row.workflow_id);
      const selectable = recordsMode ? isWorkflowAnalysisSelectable(row) : true;
      const node = document.createElement('div');
      node.className =
        'session-item' +
        (workflowId === state.selectedWorkflowId ? ' active' : '') +
        (recordsMode && !selectable ? ' locked' : '');
      let checked = !!state.selectedWorkflowIds[workflowId];
      if (recordsMode && !selectable && checked) {
        delete state.selectedWorkflowIds[workflowId];
        checked = false;
      }
      const batchRunning = !!(state.batchRun && state.batchRun.running);
      const preview = short(
        safe(row.work_record_preview || row.latest_user_message || row.latest_assistant_message || ''),
        120,
      );
      const title =
        state.queueMode === 'training'
          ? short(safe(row.training_id || row.workflow_id), 34)
          : short(safe(row.session_id || row.workflow_id), 34);
      const firstLine =
        '分析流程=' +
        statusText(row.workflow_status) +
        ' · 分析任务=' +
        statusText(row.analysis_status) +
        ' · 训练=' +
        statusText(row.training_status || 'none');
      const analysisBadge = workflowAnalysisBadgeInfo(row);
      const secondLine =
        state.queueMode === 'training'
          ? '计划项=' +
            workflowPlanCount(row) +
            ' · 决策=' +
            statusText(row.decision || 'none') +
            ' · 记录=' +
            safe(row.work_record_count || 0)
          : '工作记录=' + safe(row.work_record_count || 0);
      const gateLine = recordsMode
        ? selectable
          ? '可勾选：含未分析消息 ' + safe(row.unanalyzed_message_count || 0) + ' 条'
          : '不可勾选：' + reasonText(row.analysis_block_reason || row.analysis_block_reason_code)
        : '';
      if (recordsMode) {
        node.innerHTML =
          "<div class='row'><input type='checkbox' class='workflow-check' data-workflow-id='" +
          workflowId +
          "'" +
          (checked ? ' checked' : '') +
          (batchRunning || !selectable ? ' disabled' : '') +
          "/><div class='title'>" +
          title +
          ' ' +
          analysisBadgeHtml(analysisBadge) +
          "</div></div><div class='sub'>" +
          firstLine +
          "</div><div class='sub'>" +
          secondLine +
          "</div><div class='sub'>" +
          safe(gateLine) +
          "</div><div class='sub'>" +
          safe(preview || '暂无工作记录摘要') +
          '</div>';
      } else {
        node.innerHTML =
          "<div class='title'>" +
          title +
          ' ' +
          analysisBadgeHtml(analysisBadge) +
          "</div><div class='sub'>" +
          firstLine +
          "</div><div class='sub'>" +
          secondLine +
          "</div><div class='sub'>" +
          safe(preview || '暂无工作记录摘要') +
          '</div>';
      }
      hydrateAnalysisBadges(node);
      const check = node.querySelector('.workflow-check');
      if (check) {
        check.addEventListener('click', (event) => {
          event.stopPropagation();
          if (!selectable) {
            check.checked = false;
            return;
          }
          const val = !!check.checked;
          if (val) {
            state.selectedWorkflowIds[workflowId] = true;
          } else {
            delete state.selectedWorkflowIds[workflowId];
          }
          renderWorkflowSelectionMeta();
        });
      }
      node.onclick = () => {
        selectWorkflow(workflowId).catch((err) => {
          setWorkflowResult(err.message || String(err));
        });
      };
      box.appendChild(node);
    }
    if (!list.length) {
      const empty = document.createElement('div');
      empty.className = 'hint';
      empty.textContent =
        state.queueMode === 'training'
          ? '暂无训练任务（先在工作记录中完成分析并生成任务）'
          : '暂无可分析的工作记录';
      box.appendChild(empty);
    }
    renderWorkflowSelectionMeta();
  }

  function renderWorkflowMeta() {
    const row = state.workflows.find((v) => safe(v.workflow_id) === state.selectedWorkflowId);
    const panel = $('workflowDialogue');
    if (!row) {
      $('workflowMeta').textContent = '请选择左侧工作记录或训练任务';
      panel.innerHTML = "<div class='hint'>暂无工作记录</div>";
      return;
    }
    const gateText = isWorkflowAnalysisSelectable(row)
      ? '可进入分析'
      : '不可勾选：' + reasonText(row.analysis_block_reason || row.analysis_block_reason_code);
    $('workflowMeta').textContent =
      '工作流=' +
      safe(row.workflow_id) +
      ' · 分析任务=' +
      safe(row.analysis_id) +
      ' · 分析师=' +
      safe(row.assigned_analyst || '未指派') +
      ' · 门禁=' +
      gateText +
      ' · 状态=' +
      statusText(row.workflow_status);
    const records = Array.isArray(row.work_records) ? row.work_records : [];
    if (!records.length) {
      panel.innerHTML = "<div class='hint'>暂无工作记录</div>";
      return;
    }
    panel.innerHTML = '';
    const lockedByPlan = Number(row.training_plan_item_count || 0) > 0;
    const foldHint = document.createElement('div');
    foldHint.className = 'hint';
    foldHint.textContent = '对话默认折叠，点击每条记录可展开详情。';
    panel.appendChild(foldHint);
    if (lockedByPlan) {
      const lockHint = document.createElement('div');
      lockHint.className = 'hint warn';
      lockHint.textContent =
        '当前会话已生成训练计划（' +
        safe(row.training_plan_item_count || 0) +
        ' 项），单条消息删除已禁用。';
      panel.appendChild(lockHint);
    }
    for (const rec of records) {
      const role = safe(rec.role);
      const roleText = role === 'user' ? '用户' : role === 'assistant' ? '助手' : role;
      const content = safe(rec.content).trim();
      if (!content) continue;
      const messageId = Number(rec.message_id || 0);
      const stateText = safe(rec.analysis_state || '');
      const reasonCode = safe(rec.analysis_reason || '');
      const runId = safe(rec.analysis_run_id || '');
      const updatedAt = safe(rec.analysis_updated_at || '');
      const preview = short(content.replace(/\s+/g, ' '), 56);
      const card = document.createElement('details');
      card.className = 'workflow-record';
      card.open = false;

      const head = document.createElement('summary');
      head.className = 'workflow-record-head';
      const roleNode = document.createElement('div');
      roleNode.className = 'workflow-record-role';
      roleNode.textContent = '[' + roleText + '] #' + safe(messageId);
      const previewNode = document.createElement('div');
      previewNode.className = 'workflow-record-preview';
      previewNode.textContent = preview;
      const stateNode = document.createElement('div');
      stateNode.className = 'workflow-record-state';
      const messageBadge = analysisBadgeInfo(stateText);
      stateNode.appendChild(createAnalysisBadgeNode(messageBadge));
      if (reasonCode) {
        const reasonNode = document.createElement('span');
        reasonNode.className = 'hint';
        reasonNode.textContent = ' ' + safe(reasonText(reasonCode));
        stateNode.appendChild(reasonNode);
      }
      head.appendChild(roleNode);
      head.appendChild(previewNode);
      head.appendChild(stateNode);

      const body = document.createElement('div');
      body.className = 'workflow-record-body';

      const contentNode = document.createElement('div');
      contentNode.className = 'workflow-record-content';
      contentNode.textContent = content;

      const meta = document.createElement('div');
      meta.className = 'workflow-record-meta';
      meta.textContent =
        '批次=' +
        (runId || 'none') +
        ' · 更新时间=' +
        (updatedAt || safe(rec.created_at || ''));

      const actions = document.createElement('div');
      actions.className = 'workflow-record-actions';
      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'alt workflow-delete-msg';
      delBtn.textContent = '删除此条';
      delBtn.setAttribute('data-session-id', safe(row.session_id));
      delBtn.setAttribute('data-message-id', safe(messageId));
      if (lockedByPlan || messageId <= 0) {
        delBtn.disabled = true;
        delBtn.title = reasonText('conversation_locked_by_training_plan');
      }
      actions.appendChild(delBtn);

      body.appendChild(contentNode);
      body.appendChild(meta);
      body.appendChild(actions);
      card.appendChild(head);
      card.appendChild(body);
      panel.appendChild(card);
    }
  }

  async function deleteSessionMessage(sessionId, messageId, buttonNode) {
    const sid = safe(sessionId).trim();
    const mid = Number(messageId || 0);
    if (!sid || mid <= 0) throw new Error('消息标识无效');
    const row = workflowById(state.selectedWorkflowId);
    if (row && Number(row.training_plan_item_count || 0) > 0) {
      throw new Error(reasonText('conversation_locked_by_training_plan'));
    }
    const ok = window.confirm('将删除消息 #' + mid + '，此操作不可撤销。确认继续？');
    if (!ok) return;
    if (buttonNode) buttonNode.disabled = true;
    try {
      const data = await postJSON(
        '/api/chat/sessions/' +
          encodeURIComponent(sid) +
          '/messages/' +
          encodeURIComponent(String(mid)) +
          '/delete',
        { operator: 'workflow-ui' },
      );
      setWorkflowResult(data);
      await refreshWorkflows();
      if (state.selectedWorkflowId && workflowById(state.selectedWorkflowId)) {
        await selectWorkflow(state.selectedWorkflowId);
      } else {
        renderWorkflowMeta();
      }
      await refreshDashboard();
      setStatus('消息已删除 #' + mid);
    } catch (err) {
      const code = safe(err && err.code);
      const payload = err && err.data ? err.data : { ok: false, error: err.message || String(err), code: code };
      setWorkflowResult(payload);
      if (code === 'conversation_locked_by_training_plan') {
        throw new Error(reasonText(code) + '（' + code + '）');
      }
      throw err;
    } finally {
      if (buttonNode) buttonNode.disabled = false;
    }
  }

  async function refreshWorkflows() {
    const data = await getJSON('/api/workflows/training/queue');
    state.workflows = Array.isArray(data.items) ? data.items : [];
    normalizeWorkflowSelection();
    if (
      state.selectedWorkflowId &&
      !state.workflows.find((it) => safe(it.workflow_id) === state.selectedWorkflowId)
    ) {
      state.selectedWorkflowId = '';
    }
    renderWorkflowQueue();
    renderWorkflowMeta();
  }

  async function selectWorkflow(workflowId) {
    state.selectedWorkflowId = workflowId;
    renderWorkflowQueue();
    renderWorkflowMeta();
    await loadWorkflowPlan(workflowId);
    await refreshWorkflowEvents(workflowId);
  }

  function renderWorkflowPlan(workflowId) {
